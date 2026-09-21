"""KlineService 测试：按需全量拉取、本地命中、增量合并、除权重拉、
多源 failover、降级契约、limit 截断。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from src.marketdata.models import KlineBar
from src.marketdata.providers.base import HistoryProvider, ProviderError
from src.marketdata.klines import KlineService, _needs_rebuild
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


class FailingHistory(HistoryProvider):
    """恒定失败的 fake 日K源。"""

    def __init__(self, name: str = "failing") -> None:
        self.name = name
        self.calls = 0

    async def fetch_klines(
        self, secid: str, lmt: int, end: str = "20500101"
    ) -> list[KlineBar]:
        self.calls += 1
        raise ProviderError(self.name, "boom")


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
        svc = KlineService(store, [provider])
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
        svc = KlineService(store, [provider])
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
        svc = KlineService(store, [provider])
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
        svc = KlineService(store, [provider])

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
        svc = KlineService(store, [provider])

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
        svc = KlineService(store, [provider])
        asyncio.run(svc.get_history("1.600519"))
        # 盘中场景：即使本地已有今日K线也要刷新
        assert len(provider.calls) == 1

    def test_intraday_price_change_no_rebuild_storm(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """盘中最新一根 close 变化是正常现象：只覆盖更新，不触发全量重拉。

        修复前的行为：_needs_rebuild 把"今日 close 变了"误判为除权，
        盘中每次调用都退化为 增量+全量 双请求 + 整表重建。
        """
        monkeypatch.setattr(
            "src.marketdata.klines._beijing_today", lambda: "2026-09-18"
        )
        monkeypatch.setattr(
            "src.marketdata.klines._market_open_for", lambda secid: True
        )
        store.insert_klines(_bars("1.600519", _DATES))
        # 上游同序列，仅最新一根（今天）close 不同（盘中价格移动）
        moved = _bars("1.600519", _DATES)
        moved[-1] = replace(moved[-1], close=moved[-1].close + 5.0)
        provider = FakeHistory(moved)
        svc = KlineService(store, [provider])

        for _ in range(2):
            asyncio.run(svc.get_history("1.600519"))
        result = asyncio.run(svc.get_history("1.600519"))

        # 每次只有一次小 lmt 增量，绝不出现 6500 全量
        assert provider.calls == [30, 30, 30]
        assert 6500 not in provider.calls
        # 今日 close 已被覆盖为新值
        bars = cast(list[dict[str, Any]], result["bars"])
        assert bars[-1]["close"] == pytest.approx(109.0)

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
        svc = KlineService(store, [provider])
        result = asyncio.run(svc.get_history("1.600519"))
        assert result["count"] == 5
        assert provider.calls == []


class TestFailoverAndDegradation:
    def test_failover_to_backup(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_time(monkeypatch, "2026-09-18")
        primary = FailingHistory("p")
        backup = FakeHistory(_bars("1.600519", _DATES))
        svc = KlineService(store, [primary, backup])

        result = asyncio.run(svc.get_history("1.600519"))
        assert result["count"] == 5
        assert primary.calls == 2  # 首次 + 快速重试后切源
        assert backup.calls == [6500]  # 备源一次全量拉取成功

    def test_all_fail_no_local_returns_error(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_time(monkeypatch, "2026-09-18")
        svc = KlineService(
            store, [FailingHistory("p"), FailingHistory("b")]
        )
        result = asyncio.run(svc.get_history("1.600519"))
        assert isinstance(result, dict)
        error = cast(str, result["error"])
        assert "所有日K源不可用" in error
        assert "boom" in error

    def test_all_fail_local_data_returns_degraded(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """源全挂但本地有缓存：显式 degraded 返回，不静默冒充新数据。"""
        _freeze_time(monkeypatch, "2026-09-25")  # 本地到 09-18，有缺口
        store.insert_klines(_bars("1.600519", _DATES))
        svc = KlineService(
            store, [FailingHistory("p"), FailingHistory("b")]
        )
        result = asyncio.run(svc.get_history("1.600519"))
        assert result["count"] == 5
        assert result["degraded"] is True
        assert "degraded_note" in result

    def test_upstream_empty_returns_error(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """源正常但无该标的数据（如未知 secid）→ 结构化 error 而非源失败。"""
        _freeze_time(monkeypatch, "2026-09-18")
        provider = FakeHistory(_bars("0.000001", _DATES))  # 只有别的 secid
        svc = KlineService(store, [provider])
        result = asyncio.run(svc.get_history("1.600519"))
        assert isinstance(result, dict)
        assert "上游无" in cast(str, result["error"])

    def test_rebuild_skipped_when_full_fetch_short(
        self, store: MarketStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """除权重拉时备源序列短于本地（截断）→ 不替换、不混排，给 warning。"""
        _freeze_time(monkeypatch, "2026-09-25")
        local_dates = [f"2026-09-{d:02d}" for d in range(7, 15)]  # 8 根
        store.insert_klines(_bars("1.600519", local_dates))
        # 备源只有最近 5 根且整段偏移（除权）
        provider = FakeHistory(
            _bars("1.600519", local_dates[-5:], close_base=90.0)
        )
        svc = KlineService(store, [provider])

        result = asyncio.run(svc.get_history("1.600519"))
        assert result["warning"]
        assert result["count"] == 8  # 本地序列原样保留
        local = store.select_klines("1.600519")
        assert local[0].close == pytest.approx(100.0)


class TestNeedsRebuildLogic:
    def test_no_overlap_no_rebuild(self, store: MarketStore) -> None:
        """增量区间与本地无重叠（本地数据较新）时不得触发重建。"""
        store.insert_klines(_bars("1.600519", _DATES[:3]))
        new = _bars("1.600519", _DATES[3:])  # 无重叠日期
        assert _needs_rebuild(store, "1.600519", new) is False

    def test_overlap_price_change_triggers_rebuild(
        self, store: MarketStore
    ) -> None:
        store.insert_klines(_bars("1.600519", _DATES[:3]))
        shifted = _bars("1.600519", _DATES[:4], close_base=99.0)  # 重叠+偏移
        assert _needs_rebuild(store, "1.600519", shifted) is True

    def test_overlap_same_price_no_rebuild(self, store: MarketStore) -> None:
        store.insert_klines(_bars("1.600519", _DATES[:3]))
        same = _bars("1.600519", _DATES[:4])  # 重叠且价格一致
        assert _needs_rebuild(store, "1.600519", same) is False

    def test_mismatch_only_on_newest_bar_no_rebuild(
        self, store: MarketStore
    ) -> None:
        """仅本地最新一根不一致（盘中未收盘/收盘修正）→ upsert 覆盖即可。"""
        store.insert_klines(_bars("1.600519", _DATES[:3]))
        moved = _bars("1.600519", _DATES[:3])
        moved[-1] = replace(moved[-1], close=moved[-1].close + 5.0)
        assert _needs_rebuild(store, "1.600519", moved) is False
