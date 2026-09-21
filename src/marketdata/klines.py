"""历史日K服务：按需拉取落库、增量合并、除权检测重拉。

落库的是前复权（fqt=1）序列。前复权价格在分红除权后整段变化，因此
每次增量补拉时先比对重叠日期的收盘价：对不上说明发生除权（或上游
修正数据），删除该 secid 全部本地日K、以新拉序列重建。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.marketdata.models import KlineBar
from src.marketdata.quotes import cn_market_open, hk_market_open

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
    def __init__(self, store: MarketStore, provider: HistoryProvider) -> None:
        self._store = store
        self._provider = provider

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

        local_max = await asyncio.to_thread(self._store.max_kline_date, secid)
        if local_max is None:
            bars = await self._provider.fetch_klines(
                secid, lmt=FULL_HISTORY_LMT
            )
            action = await asyncio.to_thread(
                self._store.insert_klines, bars
            )
            logger.info(
                "kline full fetch %s: %d bars inserted", secid, action
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
            new_bars = await self._provider.fetch_klines(secid, lmt=lmt)
            rebuild = await asyncio.to_thread(
                _needs_rebuild, self._store, secid, new_bars
            )
            if rebuild:
                full = await self._provider.fetch_klines(
                    secid, lmt=FULL_HISTORY_LMT
                )
                await asyncio.to_thread(self._store.replace_klines, secid, full)
                action = "replaced"
            else:
                await asyncio.to_thread(self._store.insert_klines, new_bars)
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
        return {
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

def _needs_rebuild(
    store: MarketStore, secid: str, new_bars: list[KlineBar]
) -> bool:
    """除权检测（同步，由上层下放线程）。

    比对本地最近几根与新拉序列中重叠日期的收盘价；存在重叠且收盘价
    不一致，说明发生了除权或上游修正，需要整段重建。
    """
    if not new_bars:
        return False
    tail = store.tail_klines(secid, _OVERLAP_CHECK_BARS)
    local_close = {b.trade_date: b.close for b in tail}
    overlap_dates = local_close.keys() & {b.trade_date for b in new_bars}
    new_close = {b.trade_date: b.close for b in new_bars}
    mismatched = [d for d in overlap_dates if local_close[d] != new_close[d]]
    if overlap_dates and mismatched:
        logger.warning(
            "kline corporate-action detected for %s on %s; rebuilding series",
            secid,
            min(mismatched),
        )
        return True
    return False
