"""历史日K服务：按需拉取落库、多源 failover、增量合并、除权检测重拉。

落库的是前复权（fqt=1）序列。前复权价格在分红除权后整段变化，因此
每次增量补拉时先比对重叠日期的收盘价：**早于本地最新一根**的日期对不上
说明发生除权（或上游修正数据），删除该 secid 全部本地日K、以新拉序列
重建；仅本地最新一根对不上（盘中未收盘价变动、收盘后修正）只做覆盖
更新，不触发重建。

除权重拉要求全量序列；主源（东财）不可用时备源（腾讯）单次仅约 800
根，若不足以覆盖现有本地序列则放弃重建并返回 warning，而不是把长短
不一、复权基准不同的两段序列拼在一起。

所有源失败时：本地有数据返回 ``degraded: true`` 的缓存结果，本地无
数据返回结构化 ``error``（与行情侧 stale 契约一致，不静默降级）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.marketdata.models import KlineBar
from src.marketdata.providers.base import ProviderError
from src.marketdata.quotes import (
    RETRY_BACKOFF_SECONDS,
    CircuitBreaker,
    MarketDataSettings,
    cn_market_open,
    hk_market_open,
)

if TYPE_CHECKING:
    from src.marketdata.providers.base import HistoryProvider
    from src.marketdata.store import MarketStore

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# 东财单次 kline 拉取上限（实测贵州茅台全史 6009 根可一次取回）
FULL_HISTORY_LMT = 6500
_OVERLAP_CHECK_BARS = 2


def _beijing_today() -> str:
    return datetime.now(_CST).date().isoformat()


def _market_open_for(secid: str) -> bool:
    market = secid.split(".", 1)[0]
    now = datetime.now(_CST)
    if market in ("1", "0"):
        return cn_market_open(now)
    return hk_market_open(now)


class KlineService:
    def __init__(
        self,
        store: MarketStore,
        providers: list[HistoryProvider],
        settings: MarketDataSettings | None = None,
    ) -> None:
        self._store = store
        self._providers = providers
        self._settings = settings or MarketDataSettings()
        self._breakers = {
            p.name: CircuitBreaker(
                self._settings.breaker_threshold,
                self._settings.breaker_cooldown,
            )
            for p in providers
        }

    # ------------------------------------------------------------------
    # failover 拉取
    # ------------------------------------------------------------------

    async def _fetch_klines(
        self, secid: str, lmt: int
    ) -> tuple[list[KlineBar] | None, list[str]]:
        """沿 failover 链拉取。

        返回 ``(bars, errors)``：bars 为 None 表示所有源都失败（errors
        非空）；空列表表示源正常但上游无该标的数据。成功立即返回，
        不再尝试后续源。
        """
        errors: list[str] = []
        for provider in self._providers:
            breaker = self._breakers[provider.name]
            if not breaker.available():
                errors.append(f"[{provider.name}] circuit open, skipped")
                continue
            fetched: list[KlineBar] | None = None
            for attempt in range(self._settings.retries_per_source + 1):
                try:
                    fetched = await provider.fetch_klines(secid, lmt=lmt)
                    break
                except ProviderError as exc:
                    errors.append(str(exc))
                    if attempt < self._settings.retries_per_source:
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS)
            if fetched is None:
                breaker.record_failure()
                continue
            breaker.record_success()
            return fetched, errors
        return None, errors

    # ------------------------------------------------------------------
    # 查询入口
    # ------------------------------------------------------------------

    async def get_history(
        self,
        secid: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> dict[str, object]:
        """返回区间日K（升序、最多 limit 根），必要时先补拉落库。"""
        today = _beijing_today()
        effective_end = min(end, today) if end else today
        degraded = False
        warning: str | None = None

        local_max = await asyncio.to_thread(self._store.max_kline_date, secid)
        if local_max is None:
            bars, errors = await self._fetch_klines(secid, FULL_HISTORY_LMT)
            if bars is None:
                return {
                    "error": (
                        "所有日K源不可用，且本地无缓存；请稍后重试。"
                        f"详情: {'; '.join(errors) or 'no provider attempted'}"
                    )
                }
            if not bars:
                return {"error": f"上游无 {secid} 的日K数据"}
            inserted = await asyncio.to_thread(self._store.insert_klines, bars)
            logger.info(
                "kline full fetch %s: %d bars inserted", secid, inserted
            )
        elif local_max < effective_end or (
            local_max == today and _market_open_for(secid)
        ):
            # 缺口增量；或当日盘中快照需要刷新（收盘价未定）
            days = max(
                (datetime.fromisoformat(effective_end)
                 - datetime.fromisoformat(local_max)).days,
                0,
            )
            lmt = min(int(days * 1.6) + 30, FULL_HISTORY_LMT)
            new_bars, errors = await self._fetch_klines(secid, lmt)
            if new_bars is None:
                # 增量失败但有本地数据：显式降级，不静默返回旧数据
                degraded = True
                logger.warning(
                    "kline incremental fetch failed for %s: %s",
                    secid,
                    "; ".join(errors),
                )
            else:
                rebuild = await asyncio.to_thread(
                    _needs_rebuild, self._store, secid, new_bars
                )
                if rebuild:
                    full, _full_errors = await self._fetch_klines(
                        secid, FULL_HISTORY_LMT
                    )
                    local_count = await asyncio.to_thread(
                        self._store.count_klines, secid
                    )
                    if full is not None and len(full) >= local_count:
                        await asyncio.to_thread(
                            self._store.replace_klines, secid, full
                        )
                        action = "replaced"
                    else:
                        # 全量重拉失败或备源覆盖不足：保留旧序列并提示，
                        # 不把新旧复权基准的序列混排
                        action = "rebuild-skipped"
                        warning = (
                            "检测到除权，但全量重拉失败或备源覆盖不足，"
                            "本地序列可能未复权"
                        )
                else:
                    await asyncio.to_thread(
                        self._store.upsert_klines, new_bars
                    )
                    action = "merged"
                logger.info(
                    "kline incremental fetch %s: %d bars %s",
                    secid,
                    len(new_bars),
                    action,
                )

        bars = await asyncio.to_thread(
            self._store.select_klines, secid, start, effective_end
        )
        bars = bars[-limit:]
        result: dict[str, object] = {
            "secid": secid,
            "adjust": "qfq",
            "count": len(bars),
            "first_date": bars[0].trade_date if bars else None,
            "last_date": bars[-1].trade_date if bars else None,
            "bars": [
                {
                    "date": b.trade_date,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "amount": b.amount,
                }
                for b in bars
            ],
        }
        if degraded:
            result["degraded"] = True
            result["degraded_note"] = (
                "日K上游源当前不可用，返回本地缓存（可能过期）"
            )
        if warning:
            result["warning"] = warning
        return result


def _needs_rebuild(
    store: MarketStore, secid: str, new_bars: list[KlineBar]
) -> bool:
    """除权检测（同步，由上层下放线程）。

    比对本地最近几根与新拉序列重叠日期的收盘价：**早于本地最新一根**
    的日期不一致说明前复权序列整段漂移（除权/上游修正），需要整段重建；
    仅最新一根不一致是盘中未收盘或收盘修正，由 upsert 覆盖，不算重建。
    """
    if not new_bars:
        return False
    tail = store.tail_klines(secid, _OVERLAP_CHECK_BARS)
    if not tail:
        return False
    newest_local = tail[-1].trade_date
    local_close = {b.trade_date: b.close for b in tail}
    new_close = {b.trade_date: b.close for b in new_bars}
    overlap_older = (local_close.keys() & new_close.keys()) - {newest_local}
    mismatched = [d for d in overlap_older if local_close[d] != new_close[d]]
    if mismatched:
        logger.warning(
            "kline corporate-action detected for %s on %s; rebuilding series",
            secid,
            min(mismatched),
        )
        return True
    return False
