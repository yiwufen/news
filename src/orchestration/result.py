"""Typed output model for the retrieval pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.graph.knowledge_retrieval import GraphRetrievalResult
from src.schemas.query import StructuredQuery

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
    hops: int = 1  # Entity-to-Entity hop count used in graph retrieval


@dataclass
class PipelineResult:
    """Typed output of the retrieval pipeline.

    Replaces the untyped dict previously returned by ``run_pipeline``.
    Consumers access typed fields directly.
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
        """Serialized graph data."""
        if self.graph_result is not None:
            return self.graph_result.to_graph_dict(enabled=self.graph.graph_enabled)
        return GraphRetrievalResult.empty(start_entities=[]).to_graph_dict(
            enabled=self.graph.graph_enabled,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "request_id": self.request_id,
            "query": self.query.to_dict(),
            "source": self.source,
            "knowledge_units": self.knowledge_units,
            "entities": self.entities,
            "event_clusters": self.event_clusters,
            "total_count": self.total_count,
            "retrieval": {
                "retrieval_mode": self.retrieval.retrieval_mode,
                "bm25_count": self.retrieval.bm25_count,
                "applied_filters": self.retrieval.applied_filters,
                "hit_scores": self.retrieval.hit_scores,
            },
            "graph": {
                "graph_enabled": self.graph.graph_enabled,
                "graph_used": self.graph.graph_used,
                "candidate_count": self.graph.candidate_count,
                "expanded_cluster_count": self.graph.expanded_cluster_count,
                "expanded_entity_count": self.graph.expanded_entity_count,
                "hit_reasons": self.graph.hit_reasons,
                "hops": self.graph.hops,
            },
            "graph_data": self.graph_dict,
            "errors": self.errors,
        }
