"""QuoteService 稳定性机制测试：failover、熔断、TTL 缓存、stale 降级。

用可切换失败的 fake provider 驱动，不打真实上游。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import pytest

from typing import cast

from src.marketdata.models import Instrument, Quote
from src.marketdata.providers.base import (
    ProviderError,
    QuoteProvider,
    SearchProvider,
)
from src.marketdata.quotes import (
    AllSourcesUnavailable,
    CircuitBreaker,
    MarketDataSettings,
    QuoteService,
    cn_market_open,
    hk_market_open,
)
from src.marketdata.store import MarketStore

_CST = timezone(timedelta(hours=8))


def make_quote(secid: str) -> Quote:
    market, symbol = secid.split(".", 1)
    return Quote(
        secid=secid,
        symbol=symbol,
        name=f"test-{symbol}",
        price=100.0,
        change=1.0,
        change_pct=1.0,
        open=99.0,
        high=101.0,
        low=98.0,
        pre_close=99.0,
        volume=1000.0,
        amount=100000.0,
        market_time=datetime(2026, 9, 21, 10, 0, tzinfo=_CST),
        source="fake",
    )


class FlippableProvider(QuoteProvider):
    """可运行时切换成功/失败的 fake 源，统计调用次数。"""

    def __init__(self, name: str, drop: Sequence[str] = ()) -> None:
        self.name = name
        self.calls = 0
        self.fail = False
        self._drop = set(drop)

    async def fetch_quotes(self, secids: list[str]) -> dict[str, Quote]:
        self.calls += 1
        if self.fail:
            raise ProviderError(self.name, "boom")
        return {s: make_quote(s) for s in secids if s not in self._drop}


class FakeSuggest(SearchProvider):
    name = "fake_suggest"

    def __init__(self, results: list[Instrument]) -> None:
        self._results = results
        self.calls = 0

    async def fetch_suggest(self, query: str) -> list[Instrument]:
        self.calls += 1
        return self._results

    async def fetch_instruments(self, fs: str) -> list[Instrument]:
        return []


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


def _service(
    store: MarketStore,
    primary: FlippableProvider,
    backup: FlippableProvider,
    settings: MarketDataSettings | None = None,
    suggest: FakeSuggest | None = None,
) -> QuoteService:
    return QuoteService(
        store,
        [primary, backup],
        settings or MarketDataSettings(
            quote_ttl_open=0.0, quote_ttl_closed=0.0  # 测试默认禁用 TTL
        ),
        suggest_provider=suggest,
    )


class TestCircuitBreaker:
    def test_opens_at_threshold_and_recovers(self) -> None:
        cb = CircuitBreaker(threshold=2, cooldown=0.05)
        assert cb.available()
        cb.record_failure()
        assert cb.available()  # 未达阈值
        cb.record_failure()
        assert not cb.available()  # 进入冷却
        time.sleep(0.06)
        assert cb.available()  # 冷却期满半开

    def test_success_resets_counter(self) -> None:
        cb = CircuitBreaker(threshold=2, cooldown=60.0)
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert cb.available()  # 成功清零，未连续达阈值


class TestMarketHours:
    def test_cn_hours(self) -> None:
        monday = datetime(2026, 9, 21, tzinfo=_CST)  # 周一
        assert cn_market_open(monday.replace(hour=10, minute=0))
        assert not cn_market_open(monday.replace(hour=12, minute=0))  # 午休
        assert cn_market_open(monday.replace(hour=14, minute=0))
        assert not cn_market_open(monday.replace(hour=15, minute=1))
        saturday = datetime(2026, 9, 26, 10, 0, tzinfo=_CST)
        assert not cn_market_open(saturday)

    def test_hk_hours(self) -> None:
        monday = datetime(2026, 9, 21, tzinfo=_CST)
        assert hk_market_open(monday.replace(hour=11, minute=30))  # 上午盘
        assert not hk_market_open(monday.replace(hour=12, minute=30))  # 午休
        assert not cn_market_open(monday.replace(hour=12, minute=30))
        assert hk_market_open(monday.replace(hour=15, minute=30))  # 下午盘
        assert not hk_market_open(monday.replace(hour=16, minute=1))


class TestQuoteServiceFailover:
    def test_primary_success_backup_untouched(self, store: MarketStore) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        svc = _service(store, primary, backup)
        outcome = asyncio.run(svc.get_quotes(["600519"]))
        assert outcome.quotes[0]["secid"] == "1.600519"
        assert primary.calls == 1
        assert backup.calls == 0
        # 成功响应落快照
        snaps = store.get_snapshots(["1.600519"])
        assert "1.600519" in snaps

    def test_failover_to_backup(self, store: MarketStore) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        primary.fail = True
        svc = _service(store, primary, backup)
        outcome = asyncio.run(svc.get_quotes(["600519"]))
        assert outcome.quotes[0]["source"] == "fake"
        assert primary.calls == 2  # 首次 + 快速重试
        assert backup.calls == 1

    def test_all_fail_no_snapshot_raises(self, store: MarketStore) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        primary.fail = backup.fail = True
        svc = _service(store, primary, backup)
        with pytest.raises(AllSourcesUnavailable):
            asyncio.run(svc.get_quotes(["600519"]))

    def test_all_fail_returns_stale_snapshot(
        self, store: MarketStore
    ) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        svc = _service(store, primary, backup)
        asyncio.run(svc.get_quotes(["600519"]))  # 先成功一次，落快照

        primary.fail = backup.fail = True
        outcome = asyncio.run(svc.get_quotes(["600519"]))
        assert outcome.degraded is True
        assert outcome.quotes[0]["stale"] is True
        assert "as_of" in outcome.quotes[0]

    def test_breaker_skips_source_after_threshold(
        self, store: MarketStore
    ) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        primary.fail = backup.fail = True
        settings = MarketDataSettings(
            quote_ttl_open=0.0,
            quote_ttl_closed=0.0,
            breaker_threshold=2,
            retries_per_source=0,  # 每轮只打一次，简化计数
        )
        svc = _service(store, primary, backup, settings=settings)

        for _ in range(2):
            with pytest.raises(AllSourcesUnavailable):
                asyncio.run(svc.get_quotes(["600519"]))

        assert primary.calls == 2
        assert backup.calls == 2
        # 两源均已熔断：第三次调用不再打上游
        with pytest.raises(AllSourcesUnavailable) as exc_info:
            asyncio.run(svc.get_quotes(["600519"]))
        assert "circuit open" in str(exc_info.value)
        assert primary.calls == 2


class TestQuoteServiceResolution:
    def test_ambiguous_symbol_goes_unresolved(
        self, store: MarketStore
    ) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        svc = _service(store, primary, backup)
        outcome = asyncio.run(svc.get_quotes(["000001"]))
        assert outcome.quotes == []
        assert outcome.unresolved[0]["reason"] == "ambiguous"
        candidates = cast(list[dict[str, object]], outcome.unresolved[0]["candidates"])
        assert len(candidates) == 2
        assert primary.calls == 0  # 解析失败不打上游

    def test_suggest_fallback_resolves_and_persists(
        self, store: MarketStore
    ) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        suggest = FakeSuggest(
            [Instrument("116.00700", "00700", 116, "腾讯控股", "TXKG", "stock")]
        )
        svc = _service(store, primary, backup, suggest=suggest)

        outcome = asyncio.run(svc.get_quotes(["腾讯控股"]))
        assert outcome.quotes[0]["secid"] == "116.00700"
        assert suggest.calls == 1
        # 兜底结果回写主数据：第二次解析走本地
        outcome2 = asyncio.run(svc.get_quotes(["腾讯控股"]))
        assert suggest.calls == 1

    def test_suggest_prefers_exact_name_match(
        self, store: MarketStore
    ) -> None:
        """多候选中恰有一条名称精确匹配（如港股 vs 其 ADR）时直接解析。"""
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        suggest = FakeSuggest(
            [
                Instrument("116.00700", "00700", 116, "腾讯控股", "TXKG", "stock"),
                Instrument("153.TCTZF", "TCTZF", 153, "腾讯控股ADR", None, "stock"),
            ]
        )
        svc = _service(store, primary, backup, suggest=suggest)
        outcome = asyncio.run(svc.get_quotes(["腾讯控股"]))
        assert outcome.quotes[0]["secid"] == "116.00700"
        assert outcome.unresolved == []

    def test_suggest_fallback_disabled_reports_not_found(
        self, store: MarketStore
    ) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        svc = _service(store, primary, backup)
        outcome = asyncio.run(svc.get_quotes(["不存在的标的"]))
        assert outcome.unresolved[0]["reason"] == "not_found"

    def test_provider_missing_secid_exposed_as_no_data(
        self, store: MarketStore
    ) -> None:
        # 两源都缺个别 secid（退市/未覆盖）→ 其余正常返回，缺项显式
        # no_data，不静默跳过
        hstech = Instrument("100.HSTECH", "HSTECH", 100, "恒生科技指数", "HSTECH", "index")
        store.upsert_instrument(hstech)
        primary = FlippableProvider("p", drop=["100.HSTECH"])
        backup = FlippableProvider("b", drop=["100.HSTECH"])
        svc = _service(store, primary, backup)
        outcome = asyncio.run(svc.get_quotes(["600519", "HSTECH"]))
        assert [q["secid"] for q in outcome.quotes] == ["1.600519"]
        assert outcome.unresolved[0]["reason"] == "no_data"

    def test_partial_coverage_next_source_fills_gap(
        self, store: MarketStore
    ) -> None:
        """主源缺个别 secid（响应正常）不算失败，下一源补缺。"""
        store.upsert_instrument(
            Instrument("100.HSTECH", "HSTECH", 100, "恒生科技指数", "HSTECH", "index")
        )
        primary = FlippableProvider("p", drop=["100.HSTECH"])
        backup = FlippableProvider("b")
        svc = _service(store, primary, backup)
        outcome = asyncio.run(svc.get_quotes(["HSTECH"]))
        assert [q["secid"] for q in outcome.quotes] == ["100.HSTECH"]
        assert outcome.quotes[0]["source"] == "fake"
        # 两源都被调用：主源部分成功，备源补缺
        assert primary.calls == 1 and backup.calls == 1

    def test_output_preserves_input_order(self, store: MarketStore) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        svc = _service(store, primary, backup)
        outcome = asyncio.run(
            svc.get_quotes(["600519", "上证指数", "600519"])
        )
        assert [q["secid"] for q in outcome.quotes] == [
            "1.600519",
            "1.000001",
            "1.600519",
        ]


class TestTtlCache:
    def test_cache_hit_within_ttl(self, store: MarketStore) -> None:
        primary, backup = FlippableProvider("p"), FlippableProvider("b")
        settings = MarketDataSettings(
            quote_ttl_open=60.0, quote_ttl_closed=60.0
        )
        svc = _service(store, primary, backup, settings=settings)
        asyncio.run(svc.get_quotes(["600519"]))
        outcome = asyncio.run(svc.get_quotes(["600519"]))
        assert outcome.quotes[0]["stale"] is False
        assert primary.calls == 1  # 第二次命中缓存
