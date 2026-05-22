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
    """Tests for ISO datetime validation."""

    def test_normalize_iso_datetime_with_z_suffix(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2026-04-03T14:30:00Z", context)

        assert result.normalized_time is not None
        assert result.normalized_time.year == 2026
        assert result.normalized_time.month == 4
        assert result.normalized_time.day == 3
        assert result.resolution_type == "explicit"
        assert result.validation_error is None

    def test_normalize_iso_datetime_with_timezone(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2026-04-03T14:30:00+08:00", context)

        assert result.normalized_time is not None
        assert result.resolution_type == "explicit"

    def test_normalize_iso_date_only(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2026-04-03", context)

        assert result.normalized_time is not None
        assert result.normalized_time.date() == date(2026, 4, 3)
        assert result.resolution_type == "explicit"


class TestTimeValidation:
    """Tests for LLM-produced time validation."""

    def test_future_time_flagged(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("2030-01-01T00:00:00Z", context)

        assert result.normalized_time is not None
        assert result.normalized_time.year == 2030
        assert result.validation_error == "event_time is in the future"

    def test_implausibly_old_time_flagged(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        # context.published_at is 2026-04-05, 3+ years before is before 2023-04-05
        result = normalizer.normalize_event_time("2020-01-01T00:00:00Z", context)

        assert result.normalized_time is not None
        assert result.validation_error is not None
        assert "before published_at" in result.validation_error

    def test_non_iso_string_returns_unresolved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("昨天", context)

        assert result.normalized_time is None
        assert result.resolution_type == "unresolved"
        assert result.validation_error is not None
        assert "non-ISO" in result.validation_error

    def test_resolution_type_preserved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time(
            "2026-04-03T00:00:00Z", context, resolution_type="contextual"
        )

        assert result.normalized_time is not None
        assert result.resolution_type == "contextual"

    def test_time_grain_preserved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time(
            "2026-01-01T00:00:00Z", context, time_grain="quarter"
        )

        assert result.normalized_time is not None
        assert result.time_grain == "quarter"

    def test_empty_string_returns_unresolved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("", context)

        assert result.normalized_time is None
        assert result.resolution_type == "unresolved"

    def test_whitespace_string_returns_unresolved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("  ", context)

        assert result.normalized_time is None
        assert result.resolution_type == "unresolved"


class TestUnresolvedTime:
    """Tests for unresolved time expressions."""

    def test_normalize_none_returns_unresolved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time(None, context)

        assert result.normalized_time is None
        assert result.resolution_type == "unresolved"
        assert result.validation_error is None

    def test_unrecognized_string_returns_unresolved(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        result = normalizer.normalize_event_time("某个时间", context)

        assert result.normalized_time is None
        assert result.resolution_type == "unresolved"
        assert result.validation_error is not None


class TestAlreadyDatetime:
    """Tests for already-normalized datetime values."""

    def test_normalize_datetime_returns_explicit(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        dt = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        result = normalizer.normalize_event_time(dt, context)

        assert result.normalized_time == dt
        assert result.resolution_type == "explicit"
        assert result.validation_error is None

    def test_naive_datetime_gets_utc(
        self, normalizer: TimeNormalizer, context: TimeNormalizationContext
    ) -> None:
        dt = datetime(2026, 3, 15, 10, 0, 0)
        result = normalizer.normalize_event_time(dt, context)

        assert result.normalized_time is not None
        assert result.normalized_time.tzinfo == UTC


class TestLegacyResolutionTypeCompat:
    """Tests that old TimeResolutionType values map correctly."""

    @pytest.mark.parametrize("legacy,expected", [
        ("absolute", "explicit"),
        ("relative", "contextual"),
        ("fuzzy", "contextual"),
        ("explicit", "explicit"),
        ("contextual", "contextual"),
        ("unresolved", "unresolved"),
    ])
    def test_legacy_resolution_mapped(self, legacy: str, expected: str) -> None:
        from src.knowledge_base import TimeRef

        tr = TimeRef.model_validate({
            "published_at": "2026-04-05T00:00:00Z",
            "extracted_at": "2026-04-05T00:00:00Z",
            "event_time_resolution": legacy,
        })
        assert tr.event_time_resolution == expected
