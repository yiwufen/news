"""MarketDataService 门面与 MCP 行情工具校验测试。

MCP 工具校验沿用 test_mcp_server_validation.py 的模式：直接调用注册
工具的 fn，校验失败的分支不得触达真实数据源（get_service 打桩）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from src.marketdata.models import Instrument
from src.marketdata.providers.base import ListProvider, SearchProvider
from src.marketdata.providers.eastmoney import EastMoneyProvider
from src.marketdata.providers.tencent import TencentProvider
from src.marketdata.service import MarketDataService, reset_service_singleton
from src.marketdata.store import MarketStore


class StubEastMoney:
    """打桩的东财源：suggest/klines 可控。"""

    name = "eastmoney"

    def __init__(self, suggest: list[Instrument] | None = None) -> None:
        self._suggest = suggest or []
        self.suggest_calls = 0
        self.kline_calls = 0

    async def fetch_suggest(self, query: str) -> list[Instrument]:
        self.suggest_calls += 1
        return self._suggest

    async def fetch_klines(
        self, secid: str, lmt: int, end: str = "20500101"
    ) -> list[Any]:
        self.kline_calls += 1
        return []

    async def fetch_quotes(self, secids: list[str]) -> dict[str, Any]:
        return {}


class StubTencent:
    name = "tencent"

    async def fetch_quotes(self, secids: list[str]) -> dict[str, Any]:
        return {}


@pytest.fixture()
def store(tmp_path: Path) -> MarketStore:
    s = MarketStore(tmp_path / "market.db")
    s.replace_instruments(
        [
            Instrument("1.600519", "600519", 1, "贵州茅台", "GZMT", "stock"),
            Instrument("0.000001", "000001", 0, "平安银行", "PAYH", "stock"),
            Instrument("1.000001", "000001", 1, "上证指数", "SZZS", "index"),
        ]
    )
    return s


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_service_singleton()
    yield
    reset_service_singleton()


class TestMarketDataService:
    def _service(
        self, store: MarketStore, stub: StubEastMoney | None = None
    ) -> MarketDataService:
        return MarketDataService(
            store,
            eastmoney=cast(EastMoneyProvider, stub or StubEastMoney()),
            tencent=cast(TencentProvider, StubTencent()),
        )

    def test_search_stocks_local_hit(self, store: MarketStore) -> None:
        stub = StubEastMoney()
        svc = self._service(store, stub)
        result = asyncio.run(svc.search_stocks("茅台"))
        candidates = cast(list[dict[str, object]], result["candidates"])
        assert candidates[0]["secid"] == "1.600519"
        assert "note" not in result
        assert stub.suggest_calls == 0

    def test_search_stocks_online_fallback(self, store: MarketStore) -> None:
        stub = StubEastMoney(
            suggest=[
                Instrument("116.00700", "00700", 116, "腾讯控股", "TXKG", "stock")
            ]
        )
        svc = self._service(store, stub)
        result = asyncio.run(svc.search_stocks("腾讯控股"))
        candidates = cast(list[dict[str, object]], result["candidates"])
        assert candidates[0]["secid"] == "116.00700"
        note = cast(str, result["note"])
        assert "online" in note
        assert stub.suggest_calls == 1

    def test_resolve_one_ambiguous(self, store: MarketStore) -> None:
        svc = self._service(store)
        result = asyncio.run(svc.resolve_one("000001"))
        assert isinstance(result, dict)
        assert "error" in result and "candidates" in result
        candidates = cast(list[dict[str, object]], result["candidates"])
        assert len(candidates) == 2

    def test_resolve_one_suggest_single_hit_persists(
        self, store: MarketStore
    ) -> None:
        stub = StubEastMoney(
            suggest=[
                Instrument("116.00700", "00700", 116, "腾讯控股", "TXKG", "stock")
            ]
        )
        svc = self._service(store, stub)
        result = asyncio.run(svc.resolve_one("腾讯控股"))
        assert isinstance(result, Instrument)
        # 回写主数据：第二次本地命中，suggest 不再被打
        asyncio.run(svc.resolve_one("腾讯控股"))
        assert stub.suggest_calls == 1
        assert store.get_instrument("116.00700") is not None


# ---------------------------------------------------------------------------
# MCP 工具校验（不触达真实数据源）
# ---------------------------------------------------------------------------


@pytest.fixture()
def tools():
    from src.mcp_server import create_server

    server = create_server()
    manager = server._tool_manager
    return {
        name: manager.get_tool(name)
        for name in ("search_stocks", "get_stock_quotes", "get_stock_history")
    }


def _call(tool, **kwargs):
    return asyncio.run(tool.fn(**kwargs))


class TestSearchStocksValidation:
    def test_empty_query(self, tools) -> None:
        assert "error" in _call(tools["search_stocks"], query="  ")

    def test_limit_out_of_range(self, tools) -> None:
        assert "error" in _call(tools["search_stocks"], query="茅台", limit=0)
        assert "error" in _call(tools["search_stocks"], query="茅台", limit=51)


class TestGetStockQuotesValidation:
    def test_empty_symbols(self, tools) -> None:
        assert "error" in _call(tools["get_stock_quotes"], symbols=[])

    def test_too_many_symbols(self, tools) -> None:
        symbols = [str(600000 + i) for i in range(51)]
        assert "error" in _call(tools["get_stock_quotes"], symbols=symbols)


class TestGetStockHistoryValidation:
    def test_unsupported_adjust(self, tools) -> None:
        assert "error" in _call(
            tools["get_stock_history"], symbol="600519", adjust="hfq"
        )

    def test_limit_out_of_range(self, tools) -> None:
        assert "error" in _call(
            tools["get_stock_history"], symbol="600519", limit=501
        )

    def test_bad_date_format(self, tools) -> None:
        assert "error" in _call(
            tools["get_stock_history"], symbol="600519", start_date="2026/01/01"
        )
        assert "error" in _call(
            tools["get_stock_history"], symbol="600519", end_date="not-a-date"
        )
