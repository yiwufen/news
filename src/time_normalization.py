"""
Time normalization service for KnowledgeUnit event_time validation.

The LLM resolves time expressions to ISO 8601 during extraction.
This module validates the result: checks format, plausibility, and timezone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from src.knowledge_base import TimeGrain, TimeResolutionType


@dataclass
class TimeNormalizationContext:
    """Context for time validation."""

    published_at: datetime
    extracted_at: datetime
    document_title: str | None = None


@dataclass
class TimeNormalizationResult:
    """Result of time validation."""

    normalized_time: datetime | None
    resolution_type: TimeResolutionType
    time_grain: TimeGrain
    validation_error: str | None = None


class TimeNormalizer:
    """Validates event_time values produced by the LLM.

    The LLM is instructed to resolve Chinese time expressions to
    ISO 8601 absolute datetimes using published_at as reference.
    This class validates the LLM's output: correct format, plausible
    dates, and proper timezone.
    """

    def normalize_event_time(
        self,
        raw_time: datetime | str | None,
        context: TimeNormalizationContext,
        *,
        resolution_type: TimeResolutionType | None = None,
        time_grain: TimeGrain = "day",
    ) -> TimeNormalizationResult:
        """Validate an event_time value produced by the LLM."""
        if raw_time is None:
            return TimeNormalizationResult(
                normalized_time=None,
                resolution_type="unresolved",
                time_grain="day",
            )

        if isinstance(raw_time, datetime):
            return self._validate_datetime(
                raw_time, context, resolution_type, time_grain
            )

        if isinstance(raw_time, str):
            parsed = self._try_parse_iso(raw_time)
            if parsed is not None:
                return self._validate_datetime(
                    parsed, context, resolution_type, time_grain
                )

            return TimeNormalizationResult(
                normalized_time=None,
                resolution_type="unresolved",
                time_grain="day",
                validation_error=f"LLM returned non-ISO time: {raw_time[:50]}",
            )

        return TimeNormalizationResult(
            normalized_time=None,
            resolution_type="unresolved",
            time_grain="day",
        )

    # News events are rarely reported >3 years after occurrence
    _MAX_PAST_DAYS = 365 * 3

    def _validate_datetime(
        self,
        dt: datetime,
        context: TimeNormalizationContext,
        resolution_type: TimeResolutionType | None,
        time_grain: TimeGrain,
    ) -> TimeNormalizationResult:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        resolution = resolution_type or "explicit"

        # event_time should not be far in the future
        if dt > context.extracted_at + timedelta(days=1):
            return TimeNormalizationResult(
                normalized_time=dt,
                resolution_type=resolution,
                time_grain=time_grain,
                validation_error="event_time is in the future",
            )

        # event_time should not be implausibly far before published_at
        if dt < context.published_at - timedelta(days=self._MAX_PAST_DAYS):
            return TimeNormalizationResult(
                normalized_time=dt,
                resolution_type=resolution,
                time_grain=time_grain,
                validation_error=f"event_time is more than {self._MAX_PAST_DAYS} days before published_at",
            )

        return TimeNormalizationResult(
            normalized_time=dt,
            resolution_type=resolution,
            time_grain=time_grain,
        )

    @staticmethod
    def _try_parse_iso(value: str) -> datetime | None:
        value = value.strip()
        if not value:
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except ValueError:
            return None
