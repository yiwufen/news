"""
Conflict detection service for multi-source KnowledgeUnit analysis.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Literal

from src.knowledge_base import KnowledgeUnit


class ConflictType(Enum):
    """Types of conflicts between KnowledgeUnits."""

    TIME_MISMATCH = "time_mismatch"
    AMOUNT_MISMATCH = "amount_mismatch"
    PARTICIPANT_MISMATCH = "participant_mismatch"
    LOCATION_MISMATCH = "location_mismatch"
    STATUS_MISMATCH = "status_mismatch"


SeverityLevel = Literal["low", "medium", "high"]


@dataclass
class ConflictDetail:
    """Details of a detected conflict."""

    conflict_type: ConflictType
    field_name: str
    values: list[str]
    sources: list[str]
    severity: SeverityLevel
    description: str | None = None


@dataclass
class ConflictReport:
    """Complete conflict analysis report."""

    has_conflicts: bool
    conflict_details: list[ConflictDetail] = field(default_factory=list)
    overall_severity: SeverityLevel = "low"


# Pre-compiled amount extraction patterns (specific patterns first to avoid overlap)
_AMOUNT_PATTERNS = [
    # USD patterns (specific first)
    (re.compile(r"(\d+(?:\.\d+)?)\s*万亿美元"), "USD", 1_000_000_000_000),
    (re.compile(r"(\d+(?:\.\d+)?)\s*亿美元"), "USD", 100_000_000),
    (re.compile(r"(\d+(?:\.\d+)?)\s*万美元"), "USD", 10_000),
    # HKD patterns
    (re.compile(r"(\d+(?:\.\d+)?)\s*亿港元"), "HKD", 100_000_000),
    (re.compile(r"(\d+(?:\.\d+)?)\s*万港元"), "HKD", 10_000),
    # CNY patterns (after specific currency patterns)
    (re.compile(r"(\d+(?:\.\d+)?)\s*亿元"), "CNY", 100_000_000),
    (re.compile(r"(\d+(?:\.\d+)?)\s*万元"), "CNY", 10_000),
    (re.compile(r"(\d+(?:\.\d+)?)\s*千元"), "CNY", 1_000),
    # Percentage
    (re.compile(r"(\d+(?:\.\d+)?)\s*%"), "PERCENT", 1),
]


def _extract_amounts(text: str) -> list[tuple[float, str, float]]:
    """
    Extract monetary amounts from text.

    Returns list of (value, currency, normalized_value) tuples.
    """
    amounts: list[tuple[float, str, float]] = []

    for pattern, currency, multiplier in _AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            value = float(match.group(1))
            normalized = value * multiplier
            amounts.append((value, currency, normalized))

    return amounts


class ConflictDetector:
    """Detects conflicts between multiple KnowledgeUnits."""

    # Thresholds for conflict detection
    AMOUNT_DIFF_THRESHOLD = 0.1  # 10% difference triggers conflict
    TIME_DIFF_THRESHOLD_DAYS = 1  # 1 day difference triggers conflict

    def detect_conflicts(
        self,
        units: list[KnowledgeUnit],
    ) -> ConflictReport:
        """
        Detect all types of conflicts in a list of KnowledgeUnits.

        Args:
            units: List of KnowledgeUnits to analyze for conflicts.

        Returns:
            ConflictReport with all detected conflicts.
        """
        if len(units) < 2:
            return ConflictReport(has_conflicts=False)

        details: list[ConflictDetail] = []

        # Detect time conflicts
        time_conflicts = self._detect_time_conflicts(units)
        details.extend(time_conflicts)

        # Detect amount conflicts
        amount_conflicts = self._detect_amount_conflicts(units)
        details.extend(amount_conflicts)

        # Detect participant conflicts
        participant_conflicts = self._detect_participant_conflicts(units)
        details.extend(participant_conflicts)

        # Determine overall severity
        severity = self._compute_overall_severity(details)

        return ConflictReport(
            has_conflicts=len(details) > 0,
            conflict_details=details,
            overall_severity=severity,
        )

    def _detect_time_conflicts(
        self,
        units: list[KnowledgeUnit],
    ) -> list[ConflictDetail]:
        """Detect conflicts in event times."""
        # Only explicit event_time values can disagree; published_at is not event evidence.
        time_groups: dict[date, list[KnowledgeUnit]] = {}

        for unit in units:
            if unit.time.event_time is None:
                continue

            unit_date = unit.time.event_time.date()
            if unit_date not in time_groups:
                time_groups[unit_date] = []
            time_groups[unit_date].append(unit)

        if len(time_groups) <= 1:
            return []

        dates = sorted(time_groups.keys())
        all_dates = [d.isoformat() for d in dates]

        sources = [
            unit.ku_id
            for grouped_units in time_groups.values()
            for unit in grouped_units
        ]
        max_diff = (dates[-1] - dates[0]).days

        return [
            ConflictDetail(
                conflict_type=ConflictType.TIME_MISMATCH,
                field_name="event_time",
                values=all_dates,
                sources=sources,
                severity="medium" if max_diff <= 3 else "high",
                description=f"Event time varies by {max_diff} days across sources",
            )
        ]

    def _detect_amount_conflicts(
        self,
        units: list[KnowledgeUnit],
    ) -> list[ConflictDetail]:
        """Detect conflicts in monetary amounts."""
        amounts_by_unit: dict[str, list[tuple[float, str, float]]] = {}

        for unit in units:
            text_parts = [unit.summary]
            text_parts.extend(e.text for e in unit.evidence)
            text = " ".join(text_parts)

            amounts = _extract_amounts(text)
            if amounts:
                amounts_by_unit[unit.ku_id] = amounts

        if len(amounts_by_unit) < 2:
            return []

        # Collect normalized amounts (value, currency, normalized_value)
        normalized_amounts: list[tuple[str, float, str]] = []
        for ku_id, amounts in amounts_by_unit.items():
            for value, currency, normalized in amounts:
                normalized_amounts.append((ku_id, normalized, currency))

        # Check for conflicts (different sources report different amounts)
        conflicts: list[ConflictDetail] = []
        checked_pairs: set[tuple[str, str]] = set()

        for i, (ku_id_1, val_1, cur_1) in enumerate(normalized_amounts):
            for ku_id_2, val_2, cur_2 in normalized_amounts[i + 1 :]:
                if ku_id_1 == ku_id_2:
                    continue

                sorted_pair = sorted([ku_id_1, ku_id_2])
                pair_key = (sorted_pair[0], sorted_pair[1])
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)

                if cur_1 != cur_2:
                    continue

                if val_1 < 1 or val_2 < 1:
                    continue

                max_val = max(val_1, val_2)
                diff_ratio = abs(val_1 - val_2) / max_val

                if diff_ratio > self.AMOUNT_DIFF_THRESHOLD:
                    conflicts.append(
                        ConflictDetail(
                            conflict_type=ConflictType.AMOUNT_MISMATCH,
                            field_name="amount",
                            values=[f"{val_1:.2f}", f"{val_2:.2f}"],
                            sources=[ku_id_1, ku_id_2],
                            severity="medium",
                            description=f"Amount differs by {diff_ratio * 100:.1f}%",
                        )
                    )

        return conflicts

    def _detect_participant_conflicts(
        self,
        units: list[KnowledgeUnit],
    ) -> list[ConflictDetail]:
        """Detect conflicts in participant entities."""
        if len(units) < 2:
            return []

        # Collect all entity mentions by unit
        entities_by_unit: dict[str, set[str]] = {}
        for unit in units:
            entities = {e.mention for e in unit.entities if e.mention}
            if entities:
                entities_by_unit[unit.ku_id] = entities

        if len(entities_by_unit) < 2:
            return []

        all_entities = set().union(*entities_by_unit.values())
        common_entities = set.intersection(*entities_by_unit.values())
        if common_entities == all_entities:
            return []

        unique_entities: dict[str, list[str]] = {}
        for ku_id, entities in entities_by_unit.items():
            unique = entities - common_entities
            if unique:
                unique_entities[ku_id] = sorted(unique)

        # One-sided additive mentions are incomplete coverage, not contradictory evidence.
        if len(unique_entities) <= 1:
            return []

        return [
            ConflictDetail(
                conflict_type=ConflictType.PARTICIPANT_MISMATCH,
                field_name="entities",
                values=[
                    f"{ku_id}: {', '.join(entities)}"
                    for ku_id, entities in unique_entities.items()
                ],
                sources=list(unique_entities.keys()),
                severity="low",
                description="Different sources mention different participants",
            )
        ]

    def _compute_overall_severity(
        self,
        details: list[ConflictDetail],
    ) -> SeverityLevel:
        """Compute overall severity from conflict details."""
        if not details:
            return "low"

        severities = [d.severity for d in details]

        if "high" in severities:
            return "high"
        if "medium" in severities:
            return "medium"
        return "low"
