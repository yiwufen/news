"""Tests for EastMoney crawler time conversion."""

from __future__ import annotations

from pathlib import Path

import pytest

from collectors.eastmoney_crawler import EastMoneyCrawler, _cst_showtime_to_utc


class TestCstShowtimeToUtc:
    """EastMoney showTime is Beijing time (CST = UTC+8); storage must be UTC."""

    def test_full_datetime_converted_to_utc(self) -> None:
        # 16:17:11 CST == 08:17:11 UTC (8 hour offset)
        result = _cst_showtime_to_utc("2026-06-22 16:17:11")
        assert result == "2026-06-22T08:17:11+00:00"

    def test_date_only_rolls_back_a_day(self) -> None:
        # 2026-06-22 00:00 CST == 2026-06-21T16:00 UTC (previous day in UTC)
        result = _cst_showtime_to_utc("2026-06-22")
        assert result == "2026-06-21T16:00:00+00:00"

    def test_midnight_cst_is_previous_evening_utc(self) -> None:
        result = _cst_showtime_to_utc("2026-06-22 00:00:00")
        assert result == "2026-06-21T16:00:00+00:00"

    def test_empty_string_returned_as_is(self) -> None:
        # Unparseable input falls through unchanged so downstream can handle it.
        assert _cst_showtime_to_utc("") == ""

    def test_whitespace_only_returned_as_is(self) -> None:
        assert _cst_showtime_to_utc("   ") == "   "

    def test_unparseable_returned_as_is(self) -> None:
        result = _cst_showtime_to_utc("not a date")
        assert result == "not a date"


class TestInferCategory:
    """_infer_category 关键词路由与兜底分类（纯行情快讯不再误标 MARKET_VOLATILITY）。"""

    @pytest.fixture()
    def crawler(self, tmp_path: Path) -> EastMoneyCrawler:
        # 数据库落在 pytest 管理的临时目录，避免污染仓库
        return EastMoneyCrawler(db_path=str(tmp_path / "news.db"))

    def test_unmatched_market_snapshot_falls_back_to_general(self, crawler: EastMoneyCrawler) -> None:
        # 纯行情状态描述（无归因、无事件实质词）此前被兜底误标为 MARKET_VOLATILITY
        result = crawler._infer_category(  # pyright: ignore[reportPrivateUsage]
            "减速器概念短线拉升，巨轮智能、光洋股份涨停"
        )
        assert result == "GENERAL"

    def test_keyword_match_still_wins_over_fallback(self, crawler: EastMoneyCrawler) -> None:
        # 命中关键词仍优先于兜底，不受兜底改动影响
        result = crawler._infer_category("美国将某公司列入实体清单")  # pyright: ignore[reportPrivateUsage]
        assert result == "POLICY_SANCTION"
