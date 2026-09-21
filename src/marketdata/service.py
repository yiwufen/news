"""行情服务门面：组合 quotes/klines/universe，并以单例暴露给 MCP 层。

单例是必要的：熔断状态、TTL 缓存、httpx 连接池都要跨请求共享。
universe 同步采用懒加载——首次调用发现主数据缺失/过期时后台触发
（不阻塞当前请求），锁防止并发重复同步。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path

from src.marketdata.models import Instrument
from src.marketdata.providers.base import ListProvider, ProviderError
from src.marketdata.providers.eastmoney import EastMoneyProvider
from src.marketdata.providers.sina import SinaListProvider
from src.marketdata.providers.tencent import TencentProvider
from src.marketdata.quotes import (
    AllSourcesUnavailable,
    MarketDataSettings,
    QuoteOutcome,
    QuoteService,
    pick_suggest_result,
    suggest_query_for,
)
from src.marketdata.klines import KlineService
from src.marketdata.store import MarketStore
from src.marketdata.universe import (
    lookup_instruments,
    sync_universe,
    universe_is_stale,
)

logger = logging.getLogger(__name__)

DEFAULT_MARKET_DB = str(
    Path(__file__).resolve().parent.parent.parent / "data" / "market.db"
)


def _settings_from_env() -> MarketDataSettings:
    def _f(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name, "") or default)
        except ValueError:
            return default

    def _i(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, "") or default)
        except ValueError:
            return default

    return MarketDataSettings(
        quote_ttl_open=_f("MARKETDATA_QUOTE_TTL_OPEN", 10.0),
        quote_ttl_closed=_f("MARKETDATA_QUOTE_TTL_CLOSED", 600.0),
        breaker_threshold=_i("MARKETDATA_BREAKER_THRESHOLD", 3),
        breaker_cooldown=_f("MARKETDATA_BREAKER_COOLDOWN", 60.0),
    )


class MarketDataService:
    def __init__(
        self,
        store: MarketStore,
        eastmoney: EastMoneyProvider,
        tencent: TencentProvider,
        list_provider: ListProvider | None = None,
        settings: MarketDataSettings | None = None,
    ) -> None:
        self._store = store
        self._eastmoney = eastmoney
        # 主数据源与行情源分域（clist 限流连坐事故的整改）：默认新浪
        self._list_provider = list_provider or SinaListProvider()
        settings = settings or _settings_from_env()
        self.quotes = QuoteService(
            store,
            [eastmoney, tencent],
            settings,
            suggest_provider=eastmoney,
        )
        # 日K主源东财，备源腾讯（ifzq fqkline，见 providers/tencent.py）
        self.klines = KlineService(store, [eastmoney, tencent], settings)
        self._universe_lock = asyncio.Lock()
        self._sync_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # universe 懒同步
    # ------------------------------------------------------------------

    async def _sync_universe_locked(self) -> None:
        async with self._universe_lock:
            stale = await asyncio.to_thread(universe_is_stale, self._store)
            if not stale:
                return
            try:
                await sync_universe(self._store, self._list_provider)
            except Exception as exc:
                # fire-and-forget 任务：任何同步失败都不允许以未捕获异常
                # 结束（否则主数据可能被清到一半）。同步失败不阻塞查询
                # 链路：解析层还有 suggest 兜底；此处只记日志等下次触发。
                logger.warning("universe sync failed, will retry: %s", exc)

    def _ensure_universe(self) -> None:
        """主数据过期时后台同步（fire-and-forget，不阻塞当前请求）。"""
        if self._sync_task is not None and not self._sync_task.done():
            return
        self._sync_task = asyncio.get_running_loop().create_task(
            self._sync_universe_locked()
        )

    # ------------------------------------------------------------------
    # 工具门面方法
    # ------------------------------------------------------------------

    async def search_stocks(
        self, query: str, limit: int = 10
    ) -> dict[str, object]:
        self._ensure_universe()
        local = await asyncio.to_thread(
            lookup_instruments, self._store, query
        )
        candidates = {i.secid: i for i in local}

        # 本地无命中（universe 尚未就绪或冷门标的）时 suggest 在线补
        note = None
        if not candidates:
            note = "local universe miss; results from online search"
            try:
                online = await self._eastmoney.fetch_suggest(query)
            except ProviderError as exc:
                return {
                    "candidates": [],
                    "note": f"local universe empty and online search failed: {exc}",
                }
            for inst in online:
                candidates.setdefault(inst.secid, inst)

        items = list(candidates.values())[:limit]
        return {
            "candidates": [
                {
                    "secid": i.secid,
                    "symbol": i.symbol,
                    "name": i.name,
                    "market": i.market,
                    "asset_type": i.asset_type,
                }
                for i in items
            ],
            **({"note": note} if note else {}),
        }

    async def get_quotes(self, symbols: list[str]) -> QuoteOutcome:
        self._ensure_universe()
        return await self.quotes.get_quotes(symbols)

    async def resolve_one(self, symbol: str) -> Instrument | dict[str, object]:
        """get_stock_history 用的单符号解析：返回 Instrument 或 error dict。"""
        candidates = await asyncio.to_thread(
            lookup_instruments, self._store, symbol
        )
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            try:
                online = await self._eastmoney.fetch_suggest(
                    suggest_query_for(symbol)
                )
            except ProviderError:
                online = []
            picked = pick_suggest_result(symbol, online)
            if isinstance(picked, Instrument):
                await asyncio.to_thread(self._store.upsert_instrument, picked)
                return picked
            if isinstance(picked, list):
                return _ambiguous_error(symbol, picked[:5])
            return {"error": f"Unknown symbol: {symbol!r}"}
        return _ambiguous_error(symbol, candidates[:5])

    async def get_history(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> dict[str, object]:
        self._ensure_universe()
        resolved = await self.resolve_one(symbol)
        if isinstance(resolved, dict):
            return resolved
        return await self.klines.get_history(
            resolved.secid, start=start, end=end, limit=limit
        )


def _ambiguous_error(
    symbol: str, candidates: list[Instrument]
) -> dict[str, object]:
    return {
        "error": (
            f"Ambiguous symbol: {symbol!r}. Call search_stocks first and "
            "pass the exact symbol/secid."
        ),
        "candidates": [
            {
                "secid": i.secid,
                "symbol": i.symbol,
                "name": i.name,
                "market": i.market,
                "asset_type": i.asset_type,
            }
            for i in candidates
        ],
    }


# ---------------------------------------------------------------------------
# 进程级单例
# ---------------------------------------------------------------------------

_singleton: MarketDataService | None = None
_singleton_lock = threading.Lock()


def get_service(db_path: str | None = None) -> MarketDataService:
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                store = MarketStore(db_path or DEFAULT_MARKET_DB)
                _singleton = MarketDataService(
                    store,
                    eastmoney=EastMoneyProvider(),
                    tencent=TencentProvider(),
                )
    return _singleton


def reset_service_singleton() -> None:
    """测试专用：清空单例。"""
    global _singleton
    with _singleton_lock:
        _singleton = None


__all__ = [
    "AllSourcesUnavailable",
    "MarketDataService",
    "get_service",
    "reset_service_singleton",
    "DEFAULT_MARKET_DB",
]
