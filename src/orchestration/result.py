"""Typed output model for the retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.graph.knowledge_retrieval import GraphRetrievalResult
from src.intent.models import StructuredQuery

PipelineSource = Literal["knowledge_base", "direct_articles"]


@dataclass
class RetrievalMeta:
    """Metadata about the retrieval process."""

    retrieval_mode: str  # "bm25"
    bm25_count: int
    applied_filters: dict[str, object] = field(default_factory=dict)
    hit_scores: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass
class GraphMeta:
    """Metadata about graph enhancement."""

    graph_enabled: bool = False
    graph_used: bool = False
    candidate_count: int = 0
    expanded_cluster_count: int = 0
    expanded_entity_count: int = 0
    hit_reasons: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Typed output of the retrieval pipeline.

    Replaces the untyped dict previously returned by ``run_pipeline``.
    Skills consume this directly via typed field access.
    """

    request_id: str
    query: StructuredQuery
    source: PipelineSource
    knowledge_units: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    event_clusters: list[dict[str, Any]]
    total_count: int
    retrieval: RetrievalMeta
    graph: GraphMeta
    graph_result: GraphRetrievalResult | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def graph_dict(self) -> dict[str, Any]:
        """Serialized graph data for skill payload builders."""
        if self.graph_result is not None:
            return self.graph_result.to_graph_dict(enabled=self.graph.graph_enabled)
        return GraphRetrievalResult.empty(start_entities=[]).to_graph_dict(
            enabled=self.graph.graph_enabled,
        )
