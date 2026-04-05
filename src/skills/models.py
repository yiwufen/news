"""
Typed models for the skill-facing retrieval contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


ContractVersion = Literal["v1"]
SkillType = Literal["entity_overview", "entity_timeline", "event_analysis"]
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
    payload: EntityOverviewPayload | EntityTimelinePayload | EventAnalysisPayload | None = None
    verification: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
