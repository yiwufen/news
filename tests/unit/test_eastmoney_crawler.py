"""Tests for EastMoney crawler time conversion."""

from __future__ import annotations

from collectors.eastmoney_crawler import _cst_showtime_to_utc


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
