"""
Typed models for the skill-facing retrieval contract.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


ContractVersion = Literal["v1"]
SkillType = Literal[
    "entity_overview",
    "entity_timeline",
    "event_analysis",
    "relationship_query",
    "risk_assessment",
    "guarantee_analysis",
    "topic_research",
    "event_impact_analysis",
]
SkillSource = Literal["knowledge_base", "direct_articles"]
TimelineEventSource = Literal["event_cluster", "knowledge_unit"]


class SupportingEvidence(BaseModel):
    """Normalized evidence item exposed to skills."""

    ku_id: str
    unit_kind: str
    unit_type: str
    summary: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    source: dict[str, Any]
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float
    conflict_status: str
    cluster_id: str | None = None


class TimelineEvent(BaseModel):
    """Timeline event normalized for skill consumption."""

    event_id: str
    event_source: TimelineEventSource
    event_type: str
    title: str
    summary: str
    date: str | None = None
    time_range: dict[str, Any] | None = None
    cluster_id: str | None = None
    representative_ku_id: str | None = None
    member_ku_ids: list[str] = Field(default_factory=list)
    source_doc_ids: list[str] = Field(default_factory=list)


class EntityOverviewPayload(BaseModel):
    """Payload for the entity overview skill."""

    target_entity: str | None = None
    recent_event_clusters: list[dict[str, Any]] = Field(default_factory=list)
    related_entities: list[dict[str, Any]] = Field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)


class EntityTimelinePayload(BaseModel):
    """Payload for the entity timeline skill."""

    target_entity: str | None = None
    time_range: dict[str, Any] | None = None
    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)


class EventAnalysisPayload(BaseModel):
    """Payload for the event analysis skill."""

    focus_event_types: list[str] = Field(default_factory=list)
    event_clusters: list[dict[str, Any]] = Field(default_factory=list)
    involved_entities: list[dict[str, Any]] = Field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)


class RelationshipPath(BaseModel):
    """Normalized graph relationship path exposed to skills."""

    path_type: str
    start_entity_id: str | None = None
    start_entity_name: str | None = None
    cluster_id: str | None = None
    cluster_title: str | None = None
    cluster_type: str | None = None
    neighbor_entity_id: str | None = None
    neighbor_entity_name: str | None = None
    member_ku_ids: list[str] = Field(default_factory=list)


class RelationshipGraph(BaseModel):
    """Graph result preserved for relationship-oriented consumers."""

    enabled: bool = False
    used: bool = False
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    paths: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class RelationshipQueryPayload(BaseModel):
    """Payload for the relationship query skill."""

    target_entity: str | None = None
    related_entities: list[dict[str, Any]] = Field(default_factory=list)
    related_event_clusters: list[dict[str, Any]] = Field(default_factory=list)
    relationship_paths: list[RelationshipPath] = Field(default_factory=list)
    graph: RelationshipGraph = Field(default_factory=RelationshipGraph)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)


class RiskFactorPayload(BaseModel):
    """Risk factor exposed in skill payload."""

    factor_id: str
    factor_type: str
    factor_score: float
    description: str
    source_doc_ids: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)


class RiskPathPayload(BaseModel):
    """Risk传导路径 exposed in skill payload."""

    source_entity_id: str
    source_entity_name: str
    source_risk_score: float
    path_weight: float
    time_decay: float
    cluster_id: str | None = None
    relation_chain: list[str] = Field(default_factory=list)
    event_date: str | None = None


class RiskAssessmentPayload(BaseModel):
    """Payload for the risk assessment skill."""

    target_entity: str | None = None
    target_entity_id: str | None = None
    total_risk_score: float = 0.0
    risk_level: str = "LOW"
    risk_factors: list[RiskFactorPayload] = Field(default_factory=list)
    risk_paths: list[RiskPathPayload] = Field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)
    source_doc_ids: list[str] = Field(default_factory=list)


class GuaranteePatternPayload(BaseModel):
    """Detected guarantee pattern exposed in skill payload."""

    pattern_type: str
    risk_level: str
    entities: list[dict[str, Any]] = Field(default_factory=list)
    description: str
    source_doc_ids: list[str] = Field(default_factory=list)


class GuaranteeAnalysisPayload(BaseModel):
    """Payload for the guarantee pattern detection skill."""

    target_entity: str | None = None
    guarantee_edges: list[dict[str, Any]] = Field(default_factory=list)
    detected_patterns: list[GuaranteePatternPayload] = Field(default_factory=list)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)


class TrendMilestone(BaseModel):
    """Trend milestone for topic research skill."""

    date: str
    event_type: str
    title: str
    summary: str
    cluster_id: str
    importance_score: float = 0.5
    entity_count: int = 0
    source_count: int = 0


class TopicTrend(BaseModel):
    """Topic trend data for topic research skill."""

    period: str
    event_count: int = 0
    entity_count: int = 0
    dominant_event_types: list[str] = Field(default_factory=list)


class TopicResearchPayload(BaseModel):
    """Payload for the topic research skill."""

    topic_keywords: list[str] = Field(default_factory=list)
    time_range: dict[str, Any] | None = None
    related_event_clusters: list[dict[str, Any]] = Field(default_factory=list)
    related_entities: list[dict[str, Any]] = Field(default_factory=list)
    trend_timeline: list[TopicTrend] = Field(default_factory=list)
    key_milestones: list[TrendMilestone] = Field(default_factory=list)
    event_type_distribution: dict[str, int] = Field(default_factory=dict)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)


class ImpactLevel(str, Enum):
    """Impact level for affected entities."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class AffectedEntity(BaseModel):
    """Affected entity for event impact analysis skill."""

    entity_id: str
    entity_name: str
    entity_type: str | None = None
    impact_level: ImpactLevel = ImpactLevel.UNKNOWN
    impact_description: str | None = None
    involvement_role: str | None = None
    related_cluster_ids: list[str] = Field(default_factory=list)


class ImpactPath(BaseModel):
    """Impact transmission path for event impact analysis skill."""

    path_id: str
    path_type: str
    source_entity_id: str
    source_entity_name: str
    target_entity_id: str
    target_entity_name: str
    intermediate_entities: list[dict[str, Any]] = Field(default_factory=list)
    bridge_cluster_ids: list[str] = Field(default_factory=list)
    path_weight: float = 0.5
    hops: int = 1


class EventImpactAnalysisPayload(BaseModel):
    """Payload for the event impact analysis skill."""

    focus_event_cluster_id: str | None = None
    focus_event_type: str | None = None
    focus_event_title: str | None = None
    directly_affected_entities: list[AffectedEntity] = Field(default_factory=list)
    indirectly_affected_entities: list[AffectedEntity] = Field(default_factory=list)
    impact_paths: list[ImpactPath] = Field(default_factory=list)
    impact_network: dict[str, Any] = Field(default_factory=dict)
    total_affected_entities: int = 0
    impact_summary: dict[str, Any] = Field(default_factory=dict)
    supporting_evidence: list[SupportingEvidence] = Field(default_factory=list)


class SkillSummary(BaseModel):
    """Common aggregate counts for the contract."""

    knowledge_unit_count: int = 0
    entity_count: int = 0
    event_cluster_count: int = 0
    total_count: int = 0


class SkillCapabilities(BaseModel):
    """Capability flags exposed to skill callers."""

    graph_supported: bool
    graph_used: bool
    timeline_supported: bool


class SkillContract(BaseModel):
    """Top-level response envelope for skill-facing retrieval."""

    contract_version: ContractVersion = "v1"
    ok: bool
    skill_type: SkillType | None = None
    source: SkillSource | None = None
    query: dict[str, Any] = Field(default_factory=dict)
    summary: SkillSummary = Field(default_factory=SkillSummary)
    capabilities: SkillCapabilities = Field(
        default_factory=lambda: SkillCapabilities(
            graph_supported=False,
            graph_used=False,
            timeline_supported=False,
        )
    )
    payload: (
        EntityOverviewPayload
        | EntityTimelinePayload
        | EventAnalysisPayload
        | RelationshipQueryPayload
        | RiskAssessmentPayload
        | GuaranteeAnalysisPayload
        | TopicResearchPayload
        | EventImpactAnalysisPayload
        | None
    ) = None
    verification: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
