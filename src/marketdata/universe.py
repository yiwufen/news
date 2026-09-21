"""股票主数据（universe）：全量列表落库与本地符号解析。

设计要点（见 docs/design-issues/marketdata-mcp-design.md）：
- 主数据同步是懒加载：超过 24h 由服务层触发重拉，无后台定时任务；
- 名称/代码/拼音解析一律走本地 instruments 表，不打上游；
- suggest 在线搜索仅作冷门标的兜底，命中后回写落库。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.marketdata.models import Instrument
from src.marketdata.providers.sina import NODE_CN_STOCKS
from src.marketdata.store import UNIVERSE_SYNC_KEY

if TYPE_CHECKING:
    from src.marketdata.providers.base import ListProvider
    from src.marketdata.store import MarketStore

logger = logging.getLogger(__name__)

# 常用指数硬编码（决策点 2）：clist 不含指数，secid 来自东财体系。
DEFAULT_INDICES: list[Instrument] = [
    Instrument("1.000001", "000001", 1, "上证指数", "SZZS", "index"),
    Instrument("0.399001", "399001", 0, "深证成指", "SZZC", "index"),
    Instrument("0.399006", "399006", 0, "创业板指", "CYBZ", "index"),
    Instrument("100.HSI", "HSI", 100, "恒生指数", "HSZS", "index"),
    Instrument("100.HSTECH", "HSTECH", 100, "恒生科技指数", "HSTECH", "index"),
]

UNIVERSE_TTL = timedelta(hours=24)

_SUFFIX_MARKET = {".SH": 1, ".SZ": 0, ".HK": 116}
_PREFIX_MARKET = {"SH": 1, "SZ": 0, "HK": 116}


def universe_is_stale(store: MarketStore) -> bool:
    """主数据缺失或超过 TTL 时需要重同步。"""
    last = store.get_meta(UNIVERSE_SYNC_KEY)
    if last is None:
        return True
    try:
        synced = datetime.fromisoformat(last)
    except ValueError:
        return True
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - synced > UNIVERSE_TTL


async def sync_universe(
    store: MarketStore, provider: ListProvider
) -> int:
    """同步主数据：A股全量（新浪源）+ 硬编码指数，全量替换。

    港股不落全量：2026-09-21 实测东财 clist 翻页触发域名级封禁（连坐
    行情接口），且无其他已验证的港股全量源；港股解析走 suggest 在线
    兜底 + 回写累积（热门标的会自然沉淀进本地）。
    """
    items: dict[str, Instrument] = {}
    for inst in await provider.fetch_instruments(NODE_CN_STOCKS):
        items[inst.secid] = inst
    for inst in DEFAULT_INDICES:
        items[inst.secid] = inst

    count = await asyncio.to_thread(
        store.replace_instruments, list(items.values())
    )
    logger.info("universe synced: %d instruments", count)
    return count


def _suffixed_to_secid(query: str) -> str | None:
    """``600519.SH`` / ``SH600519`` / ``00700.HK`` 等带市场标识的形式。"""
    upper = query.upper()
    for suffix, market in _SUFFIX_MARKET.items():
        if upper.endswith(suffix):
            symbol = upper[: -len(suffix)]
            if symbol.isdigit():
                return f"{market}.{symbol}"
    for prefix, market in _PREFIX_MARKET.items():
        if upper.startswith(prefix) and upper[len(prefix) :].isdigit():
            return f"{market}.{upper[len(prefix) :]}"
    return None


def lookup_instruments(store: MarketStore, query: str) -> list[Instrument]:
    """本地解析 query，返回按确定性排序的候选（同步函数，上层下放线程）。

    解析顺序：secid 精确 > 带市场后缀 > 纯数字代码 > 拼音前缀 > 名称。
    代码命中多条（如 000001 = 平安银行 + 上证指数）时全部返回，由调用方
    决定是否歧义。
    """
    q = query.strip()
    if not q:
        return []

    # secid 精确（"1.600519"）
    if "." in q and q.split(".", 1)[0].isdigit():
        inst = store.get_instrument(q)
        if inst is not None:
            return [inst]

    # 带市场标识（"600519.SH" / "sh600519"）
    secid = _suffixed_to_secid(q)
    if secid is not None:
        inst = store.get_instrument(secid)
        if inst is not None:
            return [inst]

    # 纯数字代码（"600519" / "00700"）
    if q.isdigit():
        return store.find_by_symbol(q)

    # 纯 ASCII 字母：拼音前缀（"GZMT"）或指数英文代码（"HSTECH"）
    if q.isascii() and q.isalpha():
        return store.find_by_pinyin_prefix(q.upper())

    # 中文名（精确优先，包含兜底）
    return store.find_by_name(q)
