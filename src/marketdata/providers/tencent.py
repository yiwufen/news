"""腾讯行情源（备源）：实时 quote（qt.gtimg.cn）+ 日K备份（ifzq.gtimg.cn）。

quote：GBK 编码、A/H 字段位置不同（2026-09-21 盘中实测确认）。
单位对齐东财口径：A股 volume=手、港股 volume=股；amount 统一为
元/港元（腾讯 A股返回万元，×10000）。

kline（2026-09-21 实测）：A股/指数走 fqkline、港股走 hkfqkline 端点，
行格式 ``[日期,开,收,高,低,量,(可选dict)]``——注意收盘在高位前；
**无成交额字段，amount 置 0**；单次行数上限约 800（900+ 截断/空）；
请求 n 根可能返回 n+1 根，解析层按 lmt 截尾归一。端点只支持
"最近 N 根"，忽略 ``end`` 参数（调用方也未使用）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.marketdata.models import KlineBar, Quote
from src.marketdata.providers.base import (
    HistoryProvider,
    ProviderError,
    QuoteProvider,
)

_CST = timezone(timedelta(hours=8))

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://gu.qq.com/",
}


def secid_to_tencent(secid: str) -> str | None:
    """东财 secid -> 腾讯代码。100/116 港股体系共用 hk 前缀。"""
    try:
        market_str, symbol = secid.split(".", 1)
    except ValueError:
        return None
    match market_str:
        case "1":
            return f"sh{symbol}"
        case "0":
            return f"sz{symbol}"
        case "116" | "100":
            return f"hk{symbol}"
    return None


def _num(s: str) -> float | None:
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_a_share_time(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=_CST)
    except ValueError:
        return None


def _parse_hk_time(s: str) -> datetime | None:
    try:
        return datetime.strptime(s, "%Y/%m/%d %H:%M:%S").replace(tzinfo=_CST)
    except ValueError:
        return None


def parse_tencent_quotes(
    body: str, wanted: dict[str, str]
) -> dict[str, Quote]:
    """解析 qt.gtimg.cn 响应。

    ``wanted`` 为 secid -> 腾讯代码映射（由调用方按请求 secids 构建），
    解析出的行按腾讯代码反查回 secid；不在 wanted 中的行忽略。
    schema 不符时抛 ValueError。
    """
    code_to_secid = {v: k for k, v in wanted.items()}
    quotes: dict[str, Quote] = {}

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("v_") or '="' not in line:
            continue
        head, _, value = line.partition('="')
        code = head[2:]  # v_sh600519 -> sh600519
        fields = value.rstrip('";').split("~")
        secid = code_to_secid.get(code)
        if secid is None or len(fields) < 38:
            continue

        is_hk = code.startswith("hk")
        market_time = (
            _parse_hk_time(fields[30])
            if is_hk
            else _parse_a_share_time(fields[30])
        )
        if market_time is None:
            raise ValueError(f"tencent time field malformed: {fields[30]!r}")

        amount = _num(fields[37])
        quotes[secid] = Quote(
            secid=secid,
            symbol=secid.split(".", 1)[1],
            name=fields[1],
            price=_num(fields[3]),
            change=_num(fields[31]),
            change_pct=_num(fields[32]),
            open=_num(fields[5]),
            high=_num(fields[33]),
            low=_num(fields[34]),
            pre_close=_num(fields[4]),
            volume=_num(fields[36]),
            amount=amount * 10000 if (amount is not None and not is_hk) else amount,
            market_time=market_time,
            source="tencent",
        )
    if not quotes:
        raise ValueError("tencent payload has no parsable rows")
    return quotes


# ifzq 单次行数上限：实测 n=800 正常返回、900+ 截断到 641 或返回空
_TX_KLINE_MAX = 800


def parse_tencent_klines(
    payload: dict[str, Any], secid: str, lmt: int
) -> list[KlineBar]:
    """解析 ifzq fqkline / hkfqkline 响应为升序日K（最多 lmt 根）。

    键优先 ``qfqday``（前复权），指数无复权概念时上游用 ``day``；
    行尾部可能带除权信息 dict（忽略）；无成交额字段，amount=0。
    schema 不符时抛 ValueError。
    """
    code = secid_to_tencent(secid)
    if code is None:
        raise ValueError(f"unmappable secid: {secid}")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get(code), dict):
        raise ValueError("tencent kline data missing")
    node: dict[str, Any] = data[code]
    rows = node.get("qfqday", node.get("day"))
    if not isinstance(rows, list):
        raise ValueError("tencent kline rows missing")

    bars: list[KlineBar] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            raise ValueError(f"tencent kline row malformed: {row!r}")
        try:
            bars.append(
                KlineBar(
                    secid=secid,
                    trade_date=str(row[0]),
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=float(row[5]),
                    amount=0.0,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"tencent kline row malformed: {row!r}") from exc
    return bars[-lmt:]


class TencentProvider(QuoteProvider, HistoryProvider):
    """腾讯实时行情备源 + 日K备份源。"""

    name = "tencent"

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
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

    async def fetch_quotes(self, secids: list[str]) -> dict[str, Quote]:
        wanted: dict[str, str] = {}
        for secid in secids:
            code = secid_to_tencent(secid)
            if code is not None:
                wanted[secid] = code
        if not wanted:
            raise ProviderError(self.name, f"no mappable secids in {secids}")

        url = f"https://qt.gtimg.cn/q={','.join(wanted.values())}"
        try:
            resp = await self._get_client().get(url)
            resp.raise_for_status()
            body = resp.content.decode("gbk", errors="replace")
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"http error: {exc}") from exc
        try:
            return parse_tencent_quotes(body, wanted)
        except ValueError as exc:
            raise ProviderError(self.name, f"schema: {exc}") from exc

    async def fetch_klines(
        self, secid: str, lmt: int, end: str = "20500101"
    ) -> list[KlineBar]:
        """拉取最近日K（前复权），最多 ``_TX_KLINE_MAX`` 根。``end`` 忽略。"""
        code = secid_to_tencent(secid)
        if code is None:
            raise ProviderError(self.name, f"unmappable secid: {secid}")
        market = secid.split(".", 1)[0]
        endpoint = (
            "https://ifzq.gtimg.cn/appstock/app/fqkline/get"  # A股/沪深指数
            if market in ("0", "1")
            else "https://ifzq.gtimg.cn/appstock/app/hkfqkline/get"  # 港股/港股指数
        )
        n = min(lmt, _TX_KLINE_MAX)
        try:
            resp = await self._get_client().get(
                endpoint, params={"param": f"{code},day,,,{n},qfq"}
            )
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"http error: {exc}") from exc
        except ValueError as exc:
            raise ProviderError(self.name, f"non-json body: {exc}") from exc
        try:
            return parse_tencent_klines(payload, secid, lmt)
        except ValueError as exc:
            raise ProviderError(self.name, f"schema: {exc}") from exc
