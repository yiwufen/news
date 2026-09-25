"""新浪股票列表源（主数据专用，与东财行情域分域隔离）。

背景（2026-09-21 实测事故）：东财 clist 连续翻页会触发域名级封禁，
连坐同域的实时行情接口 push2。主数据同步因此改走新浪列表接口，
即使新浪限流也不影响行情链路。

接口（历史悠久的经典接口）：
- 列表: Market_Center.getHQNodeData?page&num&node=hs_a（num 上限 100）
- 总数: Market_Center.getHQNodeStockCount?node=hs_a

翻页策略：页间隔控频 + 断点续传（页级失败长退避后从当前页继续），
与「整体失败重拉」相比不会浪费已拉页数，也不会因单页抖动前功尽弃。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from src.marketdata.models import Instrument
from src.marketdata.providers.base import ListProvider, ProviderError

logger = logging.getLogger(__name__)

_BASE = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/"
    "json_v2.php/Market_Center.getHQNodeData"
)
_COUNT_URL = (
    "https://vip.stock.finance.sina.com.cn/quotes_service/api/"
    "json_v2.php/Market_Center.getHQNodeStockCount"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn",
    "Accept": "application/json, text/plain, */*",
}

# A股沪深列表节点（含 bj 前缀的北交所行，解析层过滤）
NODE_CN_STOCKS = "hs_a"

_PAGE_SIZE = 100  # 新浪 num 服务端上限
_PAGE_DELAY = 0.4
_PAGE_RETRY_DELAYS = (1.0, 5.0, 15.0, 30.0)  # 断点续传退避预算
_REQUEST_TIMEOUT = 8.0

# 新浪 symbol 前缀 -> 东财市场号；bj（北交所）一期不覆盖，过滤
_PREFIX_MARKET = {"sh": 1, "sz": 0}


def parse_sina_list_rows(rows: list[dict[str, Any]]) -> list[Instrument]:
    """解析单页列表行。symbol 形如 'sh600519'；无法映射的前缀（bj）跳过。"""
    items: list[Instrument] = []
    for row in rows:
        symbol_raw = row.get("symbol")
        code = row.get("code")
        name = row.get("name")
        if not isinstance(symbol_raw, str) or not isinstance(code, str):
            raise ValueError("sina list row missing symbol/code")
        prefix = symbol_raw[:2].lower()
        market = _PREFIX_MARKET.get(prefix)
        if market is None:
            continue
        items.append(
            Instrument(
                secid=f"{market}.{code}",
                symbol=code,
                market=market,
                name=str(name or code),
                pinyin=None,
                asset_type="stock",
            )
        )
    return items


class SinaListProvider(ListProvider):
    """新浪全量股票列表（仅主数据同步使用）。"""

    name = "sina_list"

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = _REQUEST_TIMEOUT,
    ) -> None:
        self._transport = transport
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers=_HEADERS,
                transport=self._transport,
            )
        return self._client

    async def _get_json(self, url: str, params: dict[str, str]) -> Any:
        try:
            resp = await self._get_client().get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"http error: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(self.name, f"non-json body: {exc}") from exc

    async def _fetch_count(self, node: str) -> int:
        raw = await self._get_json(_COUNT_URL, {"node": node})
        try:
            return int(str(raw))
        except (TypeError, ValueError) as exc:
            raise ProviderError(self.name, f"count malformed: {raw!r}") from exc

    async def _fetch_page(self, node: str, page: int) -> list[dict[str, Any]]:
        """返回单页原始行（终止判断基于原始行数）。"""
        raw = await self._get_json(
            _BASE,
            {
                "page": str(page),
                "num": str(_PAGE_SIZE),
                "sort": "symbol",
                "asc": "1",
                "node": node,
                "symbol": "",
                "_s_r_a": "page",
            },
        )
        if not isinstance(raw, list):
            raise ProviderError(self.name, f"list page {page} not a JSON array")
        return raw

    async def fetch_instruments(self, node: str) -> list[Instrument]:
        """分页拉全量；页级失败按断点续传退避重试。

        注意终止条件基于原始行数：sort=symbol 升序时 bj（北交所）前缀
        排最前，前几页可能整页被解析层过滤，不能用过滤后数量判断尾页。
        """
        total = await self._fetch_count(node)
        all_items: list[Instrument] = []
        page = 1
        retry = 0
        while True:
            try:
                rows = await self._fetch_page(node, page)
            except ProviderError as exc:
                if retry >= len(_PAGE_RETRY_DELAYS):
                    raise
                delay = _PAGE_RETRY_DELAYS[retry]
                retry += 1
                logger.warning(
                    "sina list page %d failed (%s); resume in %.0fs "
                    "(attempt %d/%d)",
                    page,
                    exc,
                    delay,
                    retry,
                    len(_PAGE_RETRY_DELAYS),
                )
                await asyncio.sleep(delay)
                continue  # 断点续传：从失败页继续
            if not rows:
                break  # 真正的尾页
            try:
                all_items.extend(parse_sina_list_rows(rows))
            except ValueError as exc:
                raise ProviderError(self.name, f"schema: {exc}") from exc
            page += 1
            retry = 0
            await asyncio.sleep(_PAGE_DELAY)
        logger.info(
            "sina list %s done: %d items (declared total %d)",
            node,
            len(all_items),
            total,
        )
        return all_items
