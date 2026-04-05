"""
Time normalization service for KnowledgeUnit event_time standardization.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from dateutil.relativedelta import relativedelta

from src.knowledge_base import TimeResolutionType

# Chinese weekday mapping
_WEEKDAY_MAP = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}

# Relative time patterns: (pattern, delta_or_handler)
_RELATIVE_TIME_PATTERNS: list[tuple[str, relativedelta | str | Callable[..., relativedelta]]] = [
    # Absolute relative days
    (r"今天", relativedelta(days=0)),
    (r"今日", relativedelta(days=0)),
    (r"昨天", relativedelta(days=1)),
    (r"昨日", relativedelta(days=1)),
    (r"前天", relativedelta(days=2)),
    (r"大前天", relativedelta(days=3)),
    # Numeric relative days
    (r"(\d+)天前", lambda m: relativedelta(days=int(m.group(1)))),
    (r"(\d+)日前", lambda m: relativedelta(days=int(m.group(1)))),
    # Weeks
    (r"上周([一二三四五六日天])", "last_weekday"),
    (r"本周([一二三四五六日天])", "this_weekday"),
    (r"这周([一二三四五六日天])", "this_weekday"),
    # Months
    (r"上个月", relativedelta(months=1)),
    (r"上月", relativedelta(months=1)),
    (r"上个月初", "last_month_start"),
    (r"上个月末", "last_month_end"),
    # Years
    (r"去年", relativedelta(years=1)),
    (r"去年初", "last_year_start"),
    (r"去年末", "last_year_end"),
    # Extended relative periods (from intent classifier)
    (r"过去一年|最近一年", relativedelta(years=1)),
    (r"过去三个月|最近三个月", relativedelta(months=3)),
    (r"过去半年|最近半年", relativedelta(months=6)),
    (r"过去一个月|最近一个月", relativedelta(months=1)),
    (r"过去一周|最近一周", relativedelta(weeks=1)),
]

# Fuzzy time patterns: (pattern, fuzzy_type)
_FUZZY_TIME_PATTERNS: list[tuple[str, str]] = [
    (r"近日|近期|最近", "recent_week"),
    (r"日前", "recent_days"),
    (r"日前左右", "recent_days"),
    (r"前不久", "recent_days"),
    (r"近期内", "recent_week"),
    (r"近期", "recent_week"),
    (r"本月初", "month_start"),
    (r"本月中", "month_mid"),
    (r"本月末|本月月底", "month_end"),
    (r"本季度初", "quarter_start"),
    (r"本季度末", "quarter_end"),
    (r"今年初|年初", "year_start"),
    (r"今年末|年末|年底", "year_end"),
]


@dataclass
class TimeNormalizationContext:
    """Context for time normalization."""

    published_at: datetime
    extracted_at: datetime
    document_title: str | None = None


@dataclass
class TimeNormalizationResult:
    """Result of time normalization."""

    normalized_time: datetime | None
    original_expression: str | None
    resolution_type: TimeResolutionType
    confidence: float
    time_range_hint: tuple[date, date] | None = None


class TimeNormalizer:
    """Normalizes event_time expressions to absolute datetime values."""

    def __init__(self) -> None:
        self._compiled_relative = [
            (re.compile(p), d) for p, d in _RELATIVE_TIME_PATTERNS
        ]
        self._compiled_fuzzy = [
            (re.compile(p), t) for p, t in _FUZZY_TIME_PATTERNS
        ]

    def normalize_event_time(
        self,
        raw_time: datetime | str | None,
        context: TimeNormalizationContext,
    ) -> TimeNormalizationResult:
        """
        Normalize a raw event_time value to an absolute datetime.

        Args:
            raw_time: The raw event_time value from LLM extraction.
                      Can be a datetime, ISO string, or Chinese expression.
            context: Context including published_at for relative time calculation.

        Returns:
            TimeNormalizationResult with normalized time and metadata.
        """
        if raw_time is None:
            return TimeNormalizationResult(
                normalized_time=None,
                original_expression=None,
                resolution_type="unresolved",
                confidence=0.0,
            )

        # Already a datetime - check if it's reasonable
        if isinstance(raw_time, datetime):
            return TimeNormalizationResult(
                normalized_time=raw_time,
                original_expression=None,
                resolution_type="absolute",
                confidence=1.0,
            )

        # Try to parse as ISO datetime first
        if isinstance(raw_time, str):
            # Check for ISO format
            iso_time = self._try_parse_iso(raw_time)
            if iso_time is not None:
                return TimeNormalizationResult(
                    normalized_time=iso_time,
                    original_expression=raw_time,
                    resolution_type="absolute",
                    confidence=0.95,
                )

            # Try relative time patterns
            relative_result = self._try_parse_relative(raw_time, context)
            if relative_result is not None:
                return relative_result

            # Try fuzzy time patterns
            fuzzy_result = self._try_parse_fuzzy(raw_time, context)
            if fuzzy_result is not None:
                return fuzzy_result

        # Unable to parse
        return TimeNormalizationResult(
            normalized_time=None,
            original_expression=str(raw_time) if raw_time else None,
            resolution_type="unresolved",
            confidence=0.0,
        )

    def _try_parse_iso(self, value: str) -> datetime | None:
        """Try to parse an ISO format datetime string."""
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

    def _try_parse_relative(
        self,
        expression: str,
        context: TimeNormalizationContext,
    ) -> TimeNormalizationResult | None:
        """Try to parse a relative time expression."""
        ref_date = context.published_at.date()
        expression_lower = expression.strip().lower()

        for pattern, delta_or_handler in self._compiled_relative:
            match = pattern.search(expression_lower)
            if not match:
                continue

            normalized_time: datetime | None = None
            confidence = 0.9

            if isinstance(delta_or_handler, relativedelta):
                # Simple relative delta
                target_date = ref_date - delta_or_handler
                normalized_time = datetime.combine(
                    target_date, datetime.min.time(), tzinfo=UTC
                )
            elif isinstance(delta_or_handler, str):
                # Special handler
                normalized_time = self._handle_special_relative(
                    delta_or_handler, match, ref_date
                )
                if delta_or_handler in ("last_weekday", "this_weekday"):
                    confidence = 0.85
            elif callable(delta_or_handler):
                # Lambda handler
                delta = delta_or_handler(match)
                if isinstance(delta, relativedelta):
                    target_date = ref_date - delta
                    normalized_time = datetime.combine(
                        target_date, datetime.min.time(), tzinfo=UTC
                    )

            if normalized_time is not None:
                return TimeNormalizationResult(
                    normalized_time=normalized_time,
                    original_expression=expression,
                    resolution_type="relative",
                    confidence=confidence,
                )

        return None

    def _handle_special_relative(
        self,
        handler_type: str,
        match: re.Match,
        ref_date: date,
    ) -> datetime | None:
        """Handle special relative time patterns."""
        if handler_type == "last_weekday":
            weekday_char = match.group(1)
            target_weekday = _WEEKDAY_MAP.get(weekday_char)
            if target_weekday is None:
                return None
            return self._get_last_weekday(ref_date, target_weekday)

        if handler_type == "this_weekday":
            weekday_char = match.group(1)
            target_weekday = _WEEKDAY_MAP.get(weekday_char)
            if target_weekday is None:
                return None
            return self._get_this_weekday(ref_date, target_weekday)

        if handler_type == "last_month_start":
            last_month = ref_date - relativedelta(months=1)
            target = date(last_month.year, last_month.month, 1)
            return datetime.combine(target, datetime.min.time(), tzinfo=UTC)

        if handler_type == "last_month_end":
            last_month = ref_date - relativedelta(months=1)
            # Last day of last month
            first_of_this_month = date(ref_date.year, ref_date.month, 1)
            target = first_of_this_month - timedelta(days=1)
            return datetime.combine(target, datetime.min.time(), tzinfo=UTC)

        if handler_type == "last_year_start":
            target = date(ref_date.year - 1, 1, 1)
            return datetime.combine(target, datetime.min.time(), tzinfo=UTC)

        if handler_type == "last_year_end":
            target = date(ref_date.year - 1, 12, 31)
            return datetime.combine(target, datetime.min.time(), tzinfo=UTC)

        return None

    def _get_last_weekday(self, ref_date: date, target_weekday: int) -> datetime:
        """Get the date of a specific weekday in the previous week."""
        current_weekday = ref_date.weekday()
        # Find Monday of current week
        days_since_monday = current_weekday
        this_monday = ref_date - timedelta(days=days_since_monday)
        # Previous week's Monday
        last_monday = this_monday - timedelta(days=7)
        # Target weekday in previous week
        target_date = last_monday + timedelta(days=target_weekday)
        return datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)

    def _get_this_weekday(self, ref_date: date, target_weekday: int) -> datetime:
        """Get the date of a specific weekday in the current week (Monday-based week start)."""
        current_weekday = ref_date.weekday()
        # Calculate days to the target weekday from the start of this week (Monday)
        days_from_monday = target_weekday
        current_days_from_monday = current_weekday
        days_diff = days_from_monday - current_days_from_monday
        target_date = ref_date + timedelta(days=days_diff)
        return datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)

    def _try_parse_fuzzy(
        self,
        expression: str,
        context: TimeNormalizationContext,
    ) -> TimeNormalizationResult | None:
        """Try to parse a fuzzy time expression and return a range estimate."""
        ref_date = context.published_at.date()
        expression_lower = expression.strip().lower()

        for pattern, fuzzy_type in self._compiled_fuzzy:
            if not pattern.search(expression_lower):
                continue

            time_range = self._get_fuzzy_time_range(fuzzy_type, ref_date)
            if time_range is None:
                continue

            # Use the start of the range as the normalized time
            normalized_time = datetime.combine(
                time_range[0], datetime.min.time(), tzinfo=UTC
            )

            return TimeNormalizationResult(
                normalized_time=normalized_time,
                original_expression=expression,
                resolution_type="fuzzy",
                confidence=0.6,
                time_range_hint=time_range,
            )

        return None

    def _get_fuzzy_time_range(
        self,
        fuzzy_type: str,
        ref_date: date,
    ) -> tuple[date, date] | None:
        """Get a time range estimate for a fuzzy time expression."""
        if fuzzy_type == "recent_week":
            return (ref_date - timedelta(days=7), ref_date)

        if fuzzy_type == "recent_days":
            return (ref_date - timedelta(days=3), ref_date)

        if fuzzy_type == "month_start":
            return (date(ref_date.year, ref_date.month, 1), ref_date)

        if fuzzy_type == "month_mid":
            mid = date(ref_date.year, ref_date.month, 15)
            return (mid - timedelta(days=5), mid + timedelta(days=5))

        if fuzzy_type == "month_end":
            # Last day of month
            if ref_date.month == 12:
                next_month = date(ref_date.year + 1, 1, 1)
            else:
                next_month = date(ref_date.year, ref_date.month + 1, 1)
            last_day = next_month - timedelta(days=1)
            return (last_day - timedelta(days=5), last_day)

        if fuzzy_type == "quarter_start":
            quarter_month = ((ref_date.month - 1) // 3) * 3 + 1
            return (date(ref_date.year, quarter_month, 1), ref_date)

        if fuzzy_type == "quarter_end":
            quarter_month = ((ref_date.month - 1) // 3) * 3 + 3
            if quarter_month == 12:
                next_quarter = date(ref_date.year + 1, 1, 1)
            else:
                next_quarter = date(ref_date.year, quarter_month + 1, 1)
            last_day = next_quarter - timedelta(days=1)
            return (last_day - timedelta(days=7), last_day)

        if fuzzy_type == "year_start":
            return (date(ref_date.year, 1, 1), date(ref_date.year, 1, 31))

        if fuzzy_type == "year_end":
            return (date(ref_date.year, 12, 1), date(ref_date.year, 12, 31))

        return None
