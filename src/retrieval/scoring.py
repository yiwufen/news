"""Intent-aware scoring profiles for retrieval ranking.

Risk / guarantee / event-impact intents were removed. The corresponding
hardcoded ``RISK_UNIT_TYPES`` vocabulary and ``risk_type_bonus`` /
``causal_chain_bonus`` bonus paths were deleted because the type-vocabulary
mapping did not match real relevance (e.g. a risk query's relevant KUs were
mostly ``stock_price_change``, which never hit the old risk vocabulary).

To retrieve risk / guarantee / impact content now, callers pass
``event_types`` filters, which constrain the candidate pool at recall time
rather than nudging scores after the fact.
"""

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


INTENT_PROFILES: dict[IntentType, ScoringProfile] = {
    IntentType.ENTITY_OVERVIEW: ScoringProfile(),
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
    IntentType.RELATIONSHIP_QUERY: ScoringProfile(
        entity_bonus=10.0,
        dense_weight=7.0,
        event_type_bonus=3.0,
    ),
    # COMPARATIVE_ANALYSIS and ENTITY_TIMELINE use dedicated strategies
    # in KnowledgeSearcher; they have their own scoring logic.
}
