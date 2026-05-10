"""Intent-aware scoring profiles for retrieval ranking."""

from __future__ import annotations

from dataclasses import dataclass

from src.schemas.query import IntentType


@dataclass(frozen=True)
class ScoringProfile:
    """Weights for _score_final_hit, varying by intent."""

    entity_bonus: float = 10.0
    dense_weight: float = 8.0
    event_type_bonus: float = 3.0
    bm25_weight: float = 0.5
    bm25_cap: float = 3.0
    recency_scale: float = 1.0
    risk_type_bonus: float = 0.0
    causal_chain_bonus: float = 0.0
    recency_boost_days: int = 0


RISK_UNIT_TYPES = frozenset({
    "debt_default", "equity_pledge", "legal_proceeding",
    "regulatory_action", "sanction", "risk_warning",
    "restructuring", "executive_change",
})

INTENT_PROFILES: dict[IntentType, ScoringProfile] = {
    IntentType.ENTITY_OVERVIEW: ScoringProfile(),
    IntentType.RISK_ASSESSMENT: ScoringProfile(
        entity_bonus=8.0,
        dense_weight=6.0,
        event_type_bonus=5.0,
        bm25_weight=0.7,
        bm25_cap=4.0,
        risk_type_bonus=5.0,
    ),
    IntentType.EVENT_IMPACT_ANALYSIS: ScoringProfile(
        entity_bonus=7.0,
        dense_weight=6.0,
        event_type_bonus=4.0,
        bm25_weight=0.6,
        bm25_cap=3.5,
        causal_chain_bonus=4.0,
        recency_boost_days=30,
    ),
    IntentType.TOPIC_RESEARCH: ScoringProfile(
        entity_bonus=6.0,
        dense_weight=8.0,
        event_type_bonus=2.0,
        bm25_weight=0.8,
        bm25_cap=4.0,
    ),
    IntentType.EVENT_ANALYSIS: ScoringProfile(
        entity_bonus=8.0,
        dense_weight=7.0,
        event_type_bonus=5.0,
        bm25_weight=0.6,
        bm25_cap=3.5,
    ),
    IntentType.GUARANTEE_ANALYSIS: ScoringProfile(
        entity_bonus=10.0,
        dense_weight=6.0,
        event_type_bonus=4.0,
    ),
    IntentType.RELATIONSHIP_QUERY: ScoringProfile(
        entity_bonus=10.0,
        dense_weight=7.0,
        event_type_bonus=3.0,
    ),
    # COMPARATIVE_ANALYSIS and ENTITY_TIMELINE use dedicated strategies
    # in KnowledgeSearcher; they have their own scoring logic.
}
