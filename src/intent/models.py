"""Core data models for intent parsing and structured retrieval queries."""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


class IntentType(Enum):
    """High-level intent categories for retrieval requests."""

    ENTITY_TIMELINE = "ENTITY_TIMELINE"
    ENTITY_OVERVIEW = "ENTITY_OVERVIEW"
    RELATIONSHIP_QUERY = "RELATIONSHIP_QUERY"
    COMPARATIVE_ANALYSIS = "COMPARATIVE_ANALYSIS"
    EVENT_ANALYSIS = "EVENT_ANALYSIS"
    RISK_ASSESSMENT = "RISK_ASSESSMENT"
    GUARANTEE_ANALYSIS = "GUARANTEE_ANALYSIS"
    TOPIC_RESEARCH = "TOPIC_RESEARCH"
    EVENT_IMPACT_ANALYSIS = "EVENT_IMPACT_ANALYSIS"


@dataclass
class TimeRange:
    """Date boundaries extracted from the user's query."""

    start: date
    end: date

    def to_dict(self) -> dict[str, str]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }

    def __str__(self) -> str:
        return f"{self.start.isoformat()} ~ {self.end.isoformat()}"


@dataclass
class QueryFilters:
    """Structured metadata filters for retrieval."""

    event_types: list[str] | None = None
    risk_levels: list[str] | None = None
    sources: list[str] | None = None
    min_credibility: float = 0.5
    categories: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_types": self.event_types,
            "risk_levels": self.risk_levels,
            "sources": self.sources,
            "min_credibility": self.min_credibility,
            "categories": self.categories,
        }


@dataclass
class StructuredQuery:
    """Normalized query object produced by the intent layer."""

    intent: IntentType
    entities: list[str]
    time_range: TimeRange | None
    filters: QueryFilters
    original_query: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent.value,
            "entities": self.entities,
            "time_range": self.time_range.to_dict() if self.time_range else None,
            "filters": self.filters.to_dict(),
            "original_query": self.original_query,
            "confidence": self.confidence,
        }

    def get_target_entity(self) -> str | None:
        return self.entities[0] if self.entities else None
