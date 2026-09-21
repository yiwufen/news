"""腾讯行情源（备源）。

仅实现实时 quote（qt.gtimg.cn），GBK 编码、A/H 字段位置不同
（2026-09-21 盘中实测确认）。单位对齐东财口径：A股 volume=手、
港股 volume=股；amount 统一为元/港元（腾讯 A股返回万元，×10000）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.marketdata.models import Quote
from src.marketdata.providers.base import ProviderError, QuoteProvider

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


class TencentProvider(QuoteProvider):
    """腾讯实时行情备源。"""

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
