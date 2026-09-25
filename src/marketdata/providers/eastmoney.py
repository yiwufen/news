"""东方财富行情源（主源）。

接口均为 quote.eastmoney.com 网页自用 AJAX 接口，无官方 SLA；
响应 schema 校验 fail-fast（形状不对按源失败处理，不吐脏数据）。

字段映射（2026-09-21 盘中实测确认）：
- ulist: f2 现价 f3 涨跌幅% f5 成交量(A股:手/港股:股) f6 成交额
         f12 代码 f13 市场 f14 名称 f15 最高 f16 最低 f17 今开
         f18 昨收 f124 行情时间戳(unix 秒)；停牌时数值字段为 "-"
- kline: 每行 "日期,开,收,高,低,量,额,..."
- suggest: QuotationCodeTable.Data[].QuoteID 即 secid
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.marketdata.models import Instrument, KlineBar, Quote
from src.marketdata.providers.base import (
    HistoryProvider,
    ProviderError,
    QuoteProvider,
    SearchProvider,
)

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}

_QUOTE_FIELDS = "f2,f3,f5,f6,f12,f13,f14,f15,f16,f17,f18,f124"

_REQUEST_TIMEOUT = 5.0


def _num(v: object) -> float | None:
    """东财 fltt=2 下数值字段；停牌/缺失时为 '-' 或异常类型。"""
    if isinstance(v, (int, float)):
        return float(v)
    return None


def parse_quote_payload(payload: dict[str, Any]) -> dict[str, Quote]:
    """解析 ulist.np 响应为 secid -> Quote。schema 不符时抛 ValueError。"""
    if payload.get("rc") != 0:
        raise ValueError(f"eastmoney rc={payload.get('rc')}")
    diff = (payload.get("data") or {}).get("diff")
    if not isinstance(diff, list):
        raise ValueError("eastmoney diff missing")

    quotes: dict[str, Quote] = {}
    for item in diff:
        symbol = item.get("f12")
        market = item.get("f13")
        name = item.get("f14")
        ts = item.get("f124")
        if not isinstance(symbol, str) or not isinstance(market, int):
            raise ValueError("eastmoney quote item missing f12/f13")
        if not isinstance(name, str) or not isinstance(ts, int):
            raise ValueError("eastmoney quote item missing f14/f124")
        price = _num(item.get("f2"))
        pre_close = _num(item.get("f18"))
        change = (
            round(price - pre_close, 4)
            if price is not None and pre_close is not None
            else None
        )
        secid = f"{market}.{symbol}"
        quotes[secid] = Quote(
            secid=secid,
            symbol=symbol,
            name=name,
            price=price,
            change=change,
            change_pct=_num(item.get("f3")),
            open=_num(item.get("f17")),
            high=_num(item.get("f15")),
            low=_num(item.get("f16")),
            pre_close=pre_close,
            volume=_num(item.get("f5")),
            amount=_num(item.get("f6")),
            market_time=datetime.fromtimestamp(ts, tz=_CST),
            source="eastmoney",
        )
    return quotes


def parse_kline_payload(payload: dict[str, Any]) -> list[KlineBar]:
    """解析 push2his kline 响应（升序）。schema 不符时抛 ValueError。"""
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("eastmoney kline data missing")
    secid = f"{data.get('market')}.{data.get('code')}"
    klines = data.get("klines")
    if not isinstance(klines, list):
        raise ValueError("eastmoney klines missing")

    bars: list[KlineBar] = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 7:
            raise ValueError(f"eastmoney kline row malformed: {line!r}")
        try:
            bars.append(
                KlineBar(
                    secid=secid,
                    trade_date=parts[0],
                    open=float(parts[1]),
                    close=float(parts[2]),
                    high=float(parts[3]),
                    low=float(parts[4]),
                    volume=float(parts[5]),
                    amount=float(parts[6]),
                )
            )
        except ValueError as exc:
            raise ValueError(f"eastmoney kline row malformed: {line!r}") from exc
    return bars


# suggest 只保留这些类别（Classify 实测值）；OTCBB 粉单、Fund 等干扰项丢弃
_SUGGEST_ALLOWED_CLASSIFY = {"AStock": "stock", "HK": "stock", "Index": "index"}


def parse_suggest_payload(payload: dict[str, Any]) -> list[Instrument]:
    """解析 searchapi suggest 响应为候选 Instrument（pinyin 一并带出）。"""
    table = payload.get("QuotationCodeTable")
    if not isinstance(table, dict):
        raise ValueError("eastmoney suggest table missing")
    items = table.get("Data")
    if items is None:  # 无命中时上游返回 null 而非空数组（实测）
        return []
    if not isinstance(items, list):
        raise ValueError("eastmoney suggest Data malformed")

    result: list[Instrument] = []
    for it in items:
        asset_type = _SUGGEST_ALLOWED_CLASSIFY.get(str(it.get("Classify")))
        secid = it.get("QuoteID")
        code = it.get("Code")
        if asset_type is None or not isinstance(secid, str) or not isinstance(code, str):
            continue
        try:
            market = int(secid.split(".")[0])
        except (TypeError, ValueError):
            continue
        result.append(
            Instrument(
                secid=secid,
                symbol=code,
                market=market,
                name=str(it.get("Name") or code),
                pinyin=str(it["PinYin"]) if it.get("PinYin") else None,
                asset_type=asset_type,
            )
        )
    return result


class EastMoneyProvider(QuoteProvider, HistoryProvider, SearchProvider):
    """东财 quote / kline / suggest 适配（主数据列表已移新浪源）。"""

    name = "eastmoney"

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

    async def fetch_quotes(self, secids: list[str]) -> dict[str, Quote]:
        payload = await self._get_json(
            "https://push2.eastmoney.com/api/qt/ulist.np/get",
            {
                "secids": ",".join(secids),
                "fields": _QUOTE_FIELDS,
                "fltt": "2",
                "invt": "2",
            },
        )
        try:
            return parse_quote_payload(payload)
        except ValueError as exc:
            raise ProviderError(self.name, f"schema: {exc}") from exc

    async def fetch_klines(
        self, secid: str, lmt: int, end: str = "20500101"
    ) -> list[KlineBar]:
        payload = await self._get_json(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            {
                "secid": secid,
                "klt": "101",
                "fqt": "1",  # 前复权
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
                "end": end,
                "lmt": str(lmt),
            },
        )
        try:
            bars = parse_kline_payload(payload)
        except ValueError as exc:
            raise ProviderError(self.name, f"schema: {exc}") from exc
        if bars and bars[0].secid != secid:
            raise ProviderError(
                self.name,
                f"kline secid mismatch: asked {secid} got {bars[0].secid}",
            )
        return bars

    async def fetch_suggest(self, query: str) -> list[Instrument]:
        payload = await self._get_json(
            "https://searchapi.eastmoney.com/api/suggest/get",
            {
                "input": query,
                "type": "14",
                # 东财网页搜索的公开固定 token（非鉴权凭据）
                "token": "D43BF722C8E33BDC906FB84D85E326E8",
                "count": "10",
            },
        )
        try:
            return parse_suggest_payload(payload)
        except ValueError as exc:
            raise ProviderError(self.name, f"schema: {exc}") from exc
