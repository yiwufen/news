"""Unit tests for time_normalization module."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.time_normalization import (
    TimeNormalizationContext,
    TimeNormalizer,
    TimeNormalizationResult,
)


@pytest.fixture
def normalizer() -> TimeNormalizer:
    return TimeNormalizer()


@pytest.fixture
def context() -> TimeNormalizationContext:
    return TimeNormalizationContext(
        published_at=datetime(2026, 4, 5, 10, 30, 0, tzinfo=UTC),
        extracted_at=datetime(2026, 4, 5, 12, 0, 0, tzinfo=UTC),
        document_title="Test document",
    )


class TestNormalizeIsoDatetime:
    """Tests for ISO datetime normalization."""

    def test_normalize_iso_datetime_with_z_suffix(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2026-04-03T14:30:00Z", context)

        assert result.normalized_time is not None
        assert result.normalized_time.year == 2026
        assert result.normalized_time.month == 4
        assert result.normalized_time.day == 3
        assert result.resolution_type == "absolute"
        assert result.confidence == 0.95

    def test_normalize_iso_datetime_with_timezone(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2026-04-03T14:30:00+08:00", context)

        assert result.normalized_time is not None
        assert result.resolution_type == "absolute"

    def test_normalize_iso_date_only(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2026-04-03", context)

        assert result.normalized_time is not None
        assert result.normalized_time.date() == date(2026, 4, 3)
        assert result.resolution_type == "absolute"


class TestNormalizeRelativeTime:
    """Tests for relative time normalization."""

    def test_normalize_yesterday(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("昨天", context)

        assert result.normalized_time is not None
        assert result.normalized_time.date() == date(2026, 4, 4)
        assert result.resolution_type == "relative"
        assert result.original_expression == "昨天"
        assert result.confidence >= 0.85

    def test_normalize_today(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("今天", context)

        assert result.normalized_time is not None
        assert result.normalized_time.date() == date(2026, 4, 5)
        assert result.resolution_type == "relative"

    def test_normalize_two_days_ago(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2天前", context)

        assert result.normalized_time is not None
        assert result.normalized_time.date() == date(2026, 4, 3)

    def test_normalize_three_days_ago(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("3天前", context)

        assert result.normalized_time is not None
        assert result.normalized_time.date() == date(2026, 4, 2)

    def test_normalize_last_week_monday(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        # 2026-04-05 is Saturday
        # This week: 2026-03-30 (Mon) to 2026-04-05 (Sun)
        # Last week: 2026-03-23 (Mon) to 2026-03-29 (Sun)
        result = normalizer.normalize_event_time("上周一", context)

        assert result.normalized_time is not None
        # Last Monday is 2026-03-23
        assert result.normalized_time.date() == date(2026, 3, 23)

    def test_normalize_last_week_friday(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        # 2026-04-05 is Saturday
        result = normalizer.normalize_event_time("上周五", context)

        assert result.normalized_time is not None
        # Last Friday before 2026-04-05 is 2026-03-27 (not 2026-04-03, which is this week)
        assert result.normalized_time.date() == date(2026, 3, 27)

    def test_normalize_this_week_monday(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        # 2026-04-05 is Saturday
        result = normalizer.normalize_event_time("本周一", context)

        assert result.normalized_time is not None
        # Monday of the week containing 2026-04-05 is 2026-03-30
        assert result.normalized_time.date() == date(2026, 3, 30)

    def test_normalize_last_month(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("上个月", context)

        assert result.normalized_time is not None
        # One month before April 2026 is March 2026
        assert result.normalized_time.month == 3

    def test_normalize_last_year(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("去年", context)

        assert result.normalized_time is not None
        assert result.normalized_time.year == 2025

    def test_normalize_past_one_week(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("过去一周", context)

        assert result.normalized_time is not None
        expected_date = date(2026, 3, 29)  # 7 days before 2026-04-05
        assert result.normalized_time.date() == expected_date


class TestNormalizeFuzzyTime:
    """Tests for fuzzy time normalization."""

    def test_normalize_recent_days(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("近日", context)

        assert result.normalized_time is not None
        assert result.resolution_type == "fuzzy"
        assert result.confidence == 0.6
        assert result.time_range_hint is not None
        # Should return a range around the published date
        start, end = result.time_range_hint
        assert end == date(2026, 4, 5)
        assert start == date(2026, 3, 29)  # 7 days before

    def test_normalize_recent_week(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("近期", context)

        assert result.normalized_time is not None
        assert result.resolution_type == "fuzzy"
        assert result.time_range_hint is not None

    def test_normalize_year_start(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("今年初", context)

        assert result.normalized_time is not None
        assert result.resolution_type == "fuzzy"
        assert result.normalized_time.month == 1
        assert result.normalized_time.day == 1


class TestUnresolvedTime:
    """Tests for unresolved time expressions."""

    def test_normalize_none_returns_unresolved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time(None, context)

        assert result.normalized_time is None
        assert result.resolution_type == "unresolved"
        assert result.confidence == 0.0

    def test_normalize_unrecognized_returns_unresolved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("某个时间", context)

        assert result.normalized_time is None
        assert result.resolution_type == "unresolved"
        assert result.confidence == 0.0


class TestAlreadyDatetime:
    """Tests for already-normalized datetime values."""

    def test_normalize_datetime_returns_absolute(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        dt = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        result = normalizer.normalize_event_time(dt, context)

        assert result.normalized_time == dt
        assert result.resolution_type == "absolute"
        assert result.confidence == 1.0
