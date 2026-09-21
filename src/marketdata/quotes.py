"""实时行情服务：多源 failover + 熔断冷却 + TTL 缓存 + 显式 stale 降级。

稳定性语义（设计文档第五节）：
- failover 链按序尝试；超时/5xx 同源快速重试 1 次后立即切源；
- 某源连续失败达到阈值进入冷却，冷却期内直接跳过（半开恢复）；
- 相同 secid 盘中 TTL 10s、收盘后 10min 命中内存缓存直接返回；
- 所有源失败时返回本地快照并显式标 ``stale``；无快照才抛
  :class:`AllSourcesUnavailable`（fail-fast，禁止静默降级）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.marketdata.models import Instrument, Quote
from src.marketdata.providers.base import ProviderError
from src.marketdata.universe import lookup_instruments

if TYPE_CHECKING:
    from src.marketdata.providers.base import QuoteProvider, SearchProvider
    from src.marketdata.store import MarketStore

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class AllSourcesUnavailable(Exception):
    """failover 链上所有源都失败，且本地无任何快照可降级。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors) or "no provider attempted")
        self.errors = errors


@dataclass
class MarketDataSettings:
    quote_ttl_open: float = 10.0  # 盘中缓存秒
    quote_ttl_closed: float = 600.0  # 收盘后缓存秒
    breaker_threshold: int = 3  # 连续失败多少次进入冷却
    breaker_cooldown: float = 60.0  # 冷却秒
    retries_per_source: int = 1  # 同源快速重试次数（不含首次）


class CircuitBreaker:
    """连续失败计数熔断：达到阈值进入冷却，冷却期满半开恢复。"""

    def __init__(self, threshold: int, cooldown: float) -> None:
        self._threshold = threshold
        self._cooldown = cooldown
        self._failures = 0
        self._open_until = 0.0

    def available(self) -> bool:
        return time.monotonic() >= self._open_until

    def record_success(self) -> None:
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = time.monotonic() + self._cooldown
            self._failures = 0
            logger.warning(
                "provider circuit opened for %.0fs", self._cooldown
            )


def cn_market_open(now: datetime) -> bool:
    """A股交易时段。仅按星期与钟点判断；节假日误判只影响 TTL 长短，无害。"""
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (570 <= minutes <= 690) or (780 <= minutes <= 900)  # 9:30-11:30 / 13:00-15:00


def hk_market_open(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (570 <= minutes <= 720) or (780 <= minutes <= 960)  # 9:30-12:00 / 13:00-16:00


def quote_ttl_seconds(secid: str, settings: MarketDataSettings) -> float:
    market = secid.split(".", 1)[0]
    now = datetime.now(_CST)
    if market in ("1", "0") and cn_market_open(now):
        return settings.quote_ttl_open
    if market in ("116", "100") and hk_market_open(now):
        return settings.quote_ttl_open
    return settings.quote_ttl_closed


@dataclass
class QuoteOutcome:
    """get_stock_quotes 的输出契约。"""

    quotes: list[dict[str, object]] = field(default_factory=list)
    unresolved: list[dict[str, object]] = field(default_factory=list)
    degraded: bool = False  # 有任何一条来自 stale 快照即为 True


class QuoteService:
    def __init__(
        self,
        store: MarketStore,
        providers: list[QuoteProvider],
        settings: MarketDataSettings | None = None,
        suggest_provider: SearchProvider | None = None,
    ) -> None:
        self._store = store
        self._providers = providers
        self._settings = settings or MarketDataSettings()
        self._suggest = suggest_provider
        self._breakers = {
            p.name: CircuitBreaker(
                self._settings.breaker_threshold,
                self._settings.breaker_cooldown,
            )
            for p in providers
        }
        self._cache: dict[str, tuple[Quote, float]] = {}

    # ------------------------------------------------------------------
    # 解析
    # ------------------------------------------------------------------

    async def _resolve(self, symbols: list[str]) -> tuple[dict[str, Instrument], list[dict[str, object]]]:
        """本地解析 + suggest 在线兜底（0 候选且兜底可用时）。"""
        resolved: dict[str, Instrument] = {}
        unresolved: list[dict[str, object]] = []

        miss: list[str] = []
        for sym in symbols:
            candidates = await asyncio.to_thread(
                lookup_instruments, self._store, sym
            )
            if len(candidates) == 1:
                resolved[sym] = candidates[0]
            elif not candidates:
                miss.append(sym)
            else:
                unresolved.append(
                    {
                        "symbol": sym,
                        "reason": "ambiguous",
                        "candidates": [_inst_dict(i) for i in candidates[:5]],
                    }
                )

        # 本地 0 候选的走 suggest 兜底；兜底不可用/失败则如实报 unresolved
        for sym in miss:
            online = await self._suggest_lookup(sym)
            if online is None:
                unresolved.append(
                    {"symbol": sym, "reason": "not_found", "candidates": []}
                )
            elif isinstance(online, Instrument):
                resolved[sym] = online
                await asyncio.to_thread(self._store.upsert_instrument, online)
            else:  # 多候选，歧义
                unresolved.append(
                    {
                        "symbol": sym,
                        "reason": "ambiguous",
                        "candidates": [_inst_dict(i) for i in online[:5]],
                    }
                )
        return resolved, unresolved

    async def _suggest_lookup(
        self, symbol: str
    ) -> Instrument | list[Instrument] | None:
        if self._suggest is None:
            return None
        try:
            results = await self._suggest.fetch_suggest(symbol)
        except ProviderError as exc:
            logger.warning("suggest fallback failed for %r: %s", symbol, exc)
            return None
        # 港股等未落库标的常出现多候选（ADR/关联标的）；名称精确匹配
        # 的候选优先，等价于"公司全名直接命中"而非模糊联想
        exact = [r for r in results if r.name == symbol]
        pool = exact if exact else results
        return pool[0] if len(pool) == 1 else pool

    # ------------------------------------------------------------------
    # 行情获取
    # ------------------------------------------------------------------

    async def get_quotes(self, symbols: list[str]) -> QuoteOutcome:
        resolved, unresolved = await self._resolve(symbols)

        # 保持输入顺序输出；同 secid 可能被多个 symbol 命中，只拉一次
        secid_of: dict[str, str] = {
            sym: inst.secid for sym, inst in resolved.items()
        }
        outcome = QuoteOutcome(unresolved=unresolved)
        fresh_by_secid: dict[str, dict[str, object]] = {}

        needed: list[str] = []
        for secid in dict.fromkeys(secid_of.values()):  # 去重且保序
            cached = self._cache.get(secid)
            if cached is not None and cached[1] > time.monotonic():
                fresh_by_secid[secid] = _quote_dict(cached[0], stale=False)
            else:
                needed.append(secid)

        if needed:
            fetched, degraded = await self._fetch_with_failover(needed)
            fresh_by_secid.update(fetched)
            outcome.degraded = outcome.degraded or degraded

        for sym in symbols:
            secid = secid_of.get(sym)
            if secid is None:
                continue  # 解析失败的已在 unresolved 中
            if secid in fresh_by_secid:
                outcome.quotes.append(fresh_by_secid[secid])
            else:
                # 上游未返回该 secid 且本地无快照：显式暴露，不静默跳过
                outcome.unresolved.append(
                    {"symbol": sym, "reason": "no_data", "candidates": []}
                )
        return outcome

    async def _fetch_with_failover(
        self, secids: list[str]
    ) -> tuple[dict[str, dict[str, object]], bool]:
        """沿 failover 链拉取；部分覆盖时下一源只补缺失项。

        主源响应正常但缺个别 secid（如东财不覆盖某指数）不算源失败，
        不触发熔断，但缺失项会继续走下一源补拉；全部源失败时显式降级
        到本地快照。
        """
        errors: list[str] = []
        result: dict[str, Quote] = {}
        pending = list(secids)

        for provider in self._providers:
            if not pending:
                break
            breaker = self._breakers[provider.name]
            if not breaker.available():
                errors.append(f"[{provider.name}] circuit open, skipped")
                continue

            fetched: dict[str, Quote] = {}
            for _ in range(self._settings.retries_per_source + 1):
                try:
                    fetched = await provider.fetch_quotes(pending)
                    break
                except ProviderError as exc:
                    errors.append(str(exc))
                    continue

            if fetched:
                breaker.record_success()
                result.update(fetched)
                pending = [s for s in pending if s not in fetched]
            else:
                breaker.record_failure()

        if result:
            self._write_cache(result)
            await asyncio.to_thread(
                self._store.upsert_snapshots, list(result.values())
            )
            return _quotes_to_dicts(result, stale=False), False

        # 全部源失败：显式 stale 降级（有快照才有得降）
        snapshots = await asyncio.to_thread(
            self._store.get_snapshots, secids
        )
        if snapshots:
            logger.warning(
                "all quote sources failed, returning %d stale snapshots: %s",
                len(snapshots),
                "; ".join(errors),
            )
            return snapshots, True
        raise AllSourcesUnavailable(errors)

    def _write_cache(self, quotes: dict[str, Quote]) -> None:
        now = time.monotonic()
        for secid, quote in quotes.items():
            ttl = quote_ttl_seconds(secid, self._settings)
            self._cache[secid] = (quote, now + ttl)


def _inst_dict(inst: Instrument) -> dict[str, object]:
    return {
        "secid": inst.secid,
        "symbol": inst.symbol,
        "name": inst.name,
        "market": inst.market,
        "asset_type": inst.asset_type,
    }


def _quote_dict(quote: Quote, stale: bool) -> dict[str, object]:
    d = quote.to_dict()
    d["stale"] = stale
    if stale:
        d["as_of"] = d["market_time"]
    return d


def _quotes_to_dicts(
    quotes: dict[str, Quote], stale: bool
) -> dict[str, dict[str, object]]:
    return {secid: _quote_dict(q, stale) for secid, q in quotes.items()}
