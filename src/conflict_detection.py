"""
Conflict detection service for multi-source KnowledgeUnit analysis.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Literal

from anthropic import Anthropic
from anthropic.types import ToolUseBlock

from src.knowledge_base import KnowledgeUnit


class ConflictType(Enum):
    """Types of conflicts between KnowledgeUnits."""

    TIME_MISMATCH = "time_mismatch"
    AMOUNT_MISMATCH = "amount_mismatch"
    PARTICIPANT_MISMATCH = "participant_mismatch"

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


# ---------------------------------------------------------------------------
# LLM-based semantic conflict detection
# ---------------------------------------------------------------------------

_CONTRADICTION_SYSTEM_PROMPT = """\
你是一个金融信息矛盾检测器。给定多条来自不同来源的新闻描述，判断它们是否存在事实矛盾。

准确性优先：宁漏勿误报。仅当两条描述对同一事实给出了不可调和的矛盾陈述时才标记为矛盾。

## 不是矛盾的情况

- 一条描述比另一条更详细（补充性信息）
- 不同指标：如一条说"营收425亿"，另一条说"利润382亿"
- 不同时间节点的数据：如一条说"Q1营收"，另一条说"全年营收"
- 单方面的信息增补：一条提到了另一条没提到的参与者

## 是矛盾的情况（正例）

- A: "腾讯以425亿元收购搜狗" vs B: "搜狗以425亿元收购腾讯" → factual（方向相反）
- A: "该政策利好科技板块" vs B: "该政策对科技板块构成利空" → sentiment（立场相反）
- A: "交易金额425亿元" vs B: "交易金额382亿元"（同一交易） → numerical（数值不同）

## 输出要求

- 每条矛盾独立记录，description 字段引用原文具体语句
- 无矛盾时返回空列表
"""

_CONTRADICTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "flag_contradictions",
    "description": "检测多条知识描述之间的事实矛盾",
    "input_schema": {
        "type": "object",
        "properties": {
            "contradictions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "conflict_type": {
                            "type": "string",
                            "enum": ["factual", "numerical", "temporal", "sentiment"],
                            "description": "矛盾类型",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "严重程度",
                        },
                        "description": {
                            "type": "string",
                            "description": "矛盾描述，引用原文中的具体语句",
                        },
                    },
                    "required": ["conflict_type", "severity", "description"],
                },
            },
        },
        "required": ["contradictions"],
    },
}


def _build_contradiction_prompt(
    representative: KnowledgeUnit,
    other_units: list[KnowledgeUnit],
) -> str:
    parts: list[str] = []

    parts.append("## 参考描述（代表来源）")
    parts.append(f"摘要: {representative.summary}")
    if representative.evidence:
        evidence_text = "；".join(e.text for e in representative.evidence[:3])
        parts.append(f"原文: {evidence_text}")
    parts.append(f"来源: {representative.source.doc_id}")
    parts.append("")

    parts.append("## 待比较描述")
    for i, unit in enumerate(other_units, 1):
        parts.append(f"### 描述 {i}（来源: {unit.source.doc_id}）")
        parts.append(f"摘要: {unit.summary}")
        if unit.evidence:
            evidence_text = "；".join(e.text for e in unit.evidence[:3])
            parts.append(f"原文: {evidence_text}")
        parts.append("")

    return "\n".join(parts)


class LLMConflictDetector:
    """LLM-based semantic conflict detection for multi-source clusters."""

    def __init__(self) -> None:
        self._client: Anthropic | None = None
        self._model: str | None = None

    def _get_client(self) -> tuple[Anthropic, str]:
        if self._client is None or self._model is None:
            from src.llm.client import create_offline_llm_client

            self._client, self._model = create_offline_llm_client()
        return self._client, self._model

    def detect_semantic_conflicts(
        self,
        representative: KnowledgeUnit,
        units: list[KnowledgeUnit],
    ) -> list[dict[str, Any]]:
        """Detect semantic contradictions between representative and other units."""
        other_units = [u for u in units if u.ku_id != representative.ku_id]
        if not other_units:
            return []

        client, model = self._get_client()
        prompt = _build_contradiction_prompt(representative, other_units)

        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=_CONTRADICTION_SYSTEM_PROMPT,
            tools=[_CONTRADICTION_TOOL_SCHEMA],  # type: ignore[arg-type]
            tool_choice={"type": "tool", "name": "flag_contradictions"},
            messages=[{"role": "user", "content": prompt}],
        )

        return _parse_contradiction_response(response)


def _parse_contradiction_response(response: Any) -> list[dict[str, Any]]:
    for block in getattr(response, "content", []) or []:
        if not isinstance(block, ToolUseBlock) or block.name != "flag_contradictions":
            continue
        payload = block.input
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            continue
        contradictions = payload.get("contradictions")
        if not isinstance(contradictions, list):
            continue
        return [
            {
                "type": f"semantic_{c['conflict_type']}",
                "field": "summary",
                "severity": c["severity"],
                "description": c["description"],
            }
            for c in contradictions
            if isinstance(c, dict)
            and c.get("conflict_type")
            and c.get("severity")
        ]
    return []
