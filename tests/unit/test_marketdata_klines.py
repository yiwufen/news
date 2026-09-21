"""KlineService 测试：按需全量拉取、本地命中、增量合并、除权重拉、limit 截断。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from src.marketdata.models import KlineBar
from src.marketdata.providers.base import HistoryProvider
from src.marketdata.klines import KlineService
from src.marketdata.store import MarketStore


def _bars(secid: str, dates: list[str], close_base: float = 100.0) -> list[KlineBar]:
    return [
        KlineBar(
            secid=secid,
            trade_date=d,
            open=close_base + i,
            high=close_base + i + 1,
            low=close_base + i - 1,
            close=close_base + i,
            volume=1000.0 + i,
            amount=100000.0 + i,
        )
        for i, d in enumerate(dates)
    ]


class FakeHistory(HistoryProvider):
    """按 lmt 返回最近 N 根的 fake 日K源，统计调用。"""

    def __init__(self, all_bars: list[KlineBar]) -> None:
        self.name = "fake_history"
        self._all = sorted(all_bars, key=lambda b: b.trade_date)
        self.calls: list[int] = []  # 每次 fetch 的 lmt

    async def fetch_klines(
        self, secid: str, lmt: int, end: str = "20500101"
    ) -> list[KlineBar]:
        self.calls.append(lmt)
        bars = [b for b in self._all if b.secid == secid]
        return bars[-lmt:]


@pytest.fixture()
def store(tmp_path: Path) -> MarketStore:
    return MarketStore(tmp_path / "market.db")


_DATES = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]


def _freeze_time(monkeypatch: pytest.MonkeyPatch, today: str) -> None:
    """固定 klines 模块的“今天”与盘中判定，避免测试依赖真实时钟。"""
    monkeypatch.setattr("src.marketdata.klines._beijing_today", lambda: today)
    monkeypatch.setattr(
        "src.marketdata.klines._market_open_for", lambda secid: False
    )


class TestGetHistory:
    def test_first_call_fetches_full_and_persists(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_time(monkeypatch, "2026-09-18")
        provider = FakeHistory(_bars("1.600519", _DATES))
        svc = KlineService(store, provider)
        result = asyncio.run(svc.get_history("1.600519"))
        assert result["count"] == 5
        assert result["first_date"] == "2026-09-14"
        assert result["adjust"] == "qfq"
        assert provider.calls == [6500]
        assert store.max_kline_date("1.600519") == "2026-09-18"

    def test_second_call_hits_local_cache(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_time(monkeypatch, "2026-09-18")
        provider = FakeHistory(_bars("1.600519", _DATES))
        svc = KlineService(store, provider)
        asyncio.run(svc.get_history("1.600519"))
        # 本地已覆盖到 effective_end（今天），不再打上游
        result = asyncio.run(svc.get_history("1.600519"))
        assert result["count"] == 5
        assert provider.calls == [6500]

    def test_date_range_filter_and_limit(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_time(monkeypatch, "2026-09-18")
        provider = FakeHistory(_bars("1.600519", _DATES))
        svc = KlineService(store, provider)
        asyncio.run(svc.get_history("1.600519"))
        result = asyncio.run(
            svc.get_history("1.600519", start="2026-09-16", limit=2)
        )
        bars = cast(list[dict[str, Any]], result["bars"])
        assert [b["date"] for b in bars] == [
            "2026-09-17",
            "2026-09-18",
        ]
        assert result["first_date"] == "2026-09-17"

    def test_incremental_merge_on_gap(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 本地先落 3 根；上游有 5 根（尾部多 2 根）→ 增量合并
        _freeze_time(monkeypatch, "2026-09-18")
        provider = FakeHistory(_bars("1.600519", _DATES))
        store.insert_klines(_bars("1.600519", _DATES[:3]))
        svc = KlineService(store, provider)

        future = "2099-01-01"
        result = asyncio.run(svc.get_history("1.600519", end=future))
        assert result["count"] == 5
        # 增量路径：小 lmt 拉取而非 6500 全量
        assert provider.calls and provider.calls[0] < 100
        assert provider.calls[0] > 5

    def test_corporate_action_rebuilds_series(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 本地 3 根（close 100/101/102）；上游同日期价格整体偏移（模拟除权）
        _freeze_time(monkeypatch, "2026-09-18")
        corporate_action_bars = _bars("1.600519", _DATES, close_base=90.0)
        provider = FakeHistory(corporate_action_bars)
        store.insert_klines(_bars("1.600519", _DATES[:3]))
        svc = KlineService(store, provider)

        future = "2099-01-01"
        asyncio.run(svc.get_history("1.600519", end=future))

        # 重叠日期 close 不一致 → 触发全量重拉并整段替换
        assert 6500 in provider.calls
        local = store.select_klines("1.600519")
        assert local[0].close == pytest.approx(90.0)  # 已是新序列

    def test_intraday_refresh_when_local_has_today(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """本地 max == 今天且盘中 → 仍刷新当日未收盘数据（不视为已覆盖）。"""
        monkeypatch.setattr(
            "src.marketdata.klines._beijing_today", lambda: "2026-09-18"
        )
        monkeypatch.setattr(
            "src.marketdata.klines._market_open_for", lambda secid: True
        )
        provider = FakeHistory(_bars("1.600519", _DATES))
        store.insert_klines(_bars("1.600519", _DATES))  # 本地已含“今天”
        svc = KlineService(store, provider)
        asyncio.run(svc.get_history("1.600519"))
        # 盘中场景：即使本地已有今日K线也要刷新
        assert len(provider.calls) == 1

    def test_after_hours_no_refresh_when_local_has_today(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """收盘后本地已含今日K线 → 纯本地返回，不打上游。"""
        monkeypatch.setattr(
            "src.marketdata.klines._beijing_today", lambda: "2026-09-18"
        )
        monkeypatch.setattr(
            "src.marketdata.klines._market_open_for", lambda secid: False
        )
        provider = FakeHistory(_bars("1.600519", _DATES))
        store.insert_klines(_bars("1.600519", _DATES))
        svc = KlineService(store, provider)
        result = asyncio.run(svc.get_history("1.600519"))
        assert result["count"] == 5
        assert provider.calls == []


class TestNeedsRebuildLogic:
    def test_no_overlap_no_rebuild(self, store: MarketStore) -> None:
        """增量区间与本地无重叠（本地数据较新）时不得触发重建。"""
        from src.marketdata.klines import _needs_rebuild

        store.insert_klines(_bars("1.600519", _DATES[:3]))
        new = _bars("1.600519", _DATES[3:])  # 无重叠日期
        assert _needs_rebuild(store, "1.600519", new) is False

    def test_overlap_price_change_triggers_rebuild(
        self, store: MarketStore
    ) -> None:
        from src.marketdata.klines import _needs_rebuild

        store.insert_klines(_bars("1.600519", _DATES[:3]))
        shifted = _bars("1.600519", _DATES[:4], close_base=99.0)  # 重叠+偏移
        assert _needs_rebuild(store, "1.600519", shifted) is True

    def test_overlap_same_price_no_rebuild(self, store: MarketStore) -> None:
        from src.marketdata.klines import _needs_rebuild

        store.insert_klines(_bars("1.600519", _DATES[:3]))
        same = _bars("1.600519", _DATES[:4])  # 重叠且价格一致
        assert _needs_rebuild(store, "1.600519", same) is False
