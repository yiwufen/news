from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginationParams(BaseModel):
    page: int = 1
    page_size: int = 20


class PaginatedResponse(BaseModel, Generic[T]):
    total: int
    items: list[T]
    page: int
    page_size: int


class HealthResponse(BaseModel):
    status: str
    db_connected: bool
    neo4j_connected: bool | None = None
    version: str = "0.1.0"


class EntitySummary(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str | None = None
    updated_at: str


class KUSummary(BaseModel):
    ku_id: str
    unit_kind: str
    unit_type: str
    summary: str
    published_at: str
    conflict_status: str
    status: str


class ClusterSummary(BaseModel):
    cluster_id: str
    cluster_type: str
    title: str
    member_count: int
    source_count: int
    conflict_status: str
    updated_at: str


class ArticleSummary(BaseModel):
    id: int
    doc_id: str
    title: str
    publish_time: str
    source_name: str
    category: str
    credibility_tier: int


class ProcessingLogEntry(BaseModel):
    doc_id: str
    status: str
    knowledge_units_count: int
    entities_count: int
    clusters_count: int
    error_message: str | None = None
    updated_at: str


class ProcessingSummary(BaseModel):
    total_processed: int
    total_failed: int
    total_pending: int
    last_processed_at: str | None = None


class PipelineServiceStatus(BaseModel):
    running: bool
    pid: int | None = None
    started_at: str | None = None
    command: list[str] | None = None


class PipelineStatus(BaseModel):
    fetch: PipelineServiceStatus
    offline: PipelineServiceStatus


class DashboardStats(BaseModel):
    entities: dict[str, Any]
    knowledge_units: dict[str, Any]
    event_clusters: dict[str, Any]
    articles: dict[str, Any]
    processing: ProcessingSummary
    pipeline: PipelineStatus | None = None
