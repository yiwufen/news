"""
Knowledge retrieval entrypoint for ``run_pipeline``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from src.entities import EntityRepository
from src.graph import GraphRetrievalResult, KnowledgeGraphRetriever
from src.intent import IntentClassifier
from src.intent.models import StructuredQuery
from src.orchestration.result import GraphMeta, PipelineResult, RetrievalMeta
from src.retrieval.knowledge_search import KnowledgeSearchRequest, KnowledgeSearcher


@dataclass
class _GraphEnhancement:
    """Internal container for graph enhancement results."""

    graph_result: GraphRetrievalResult
    entities: list[dict[str, Any]]
    event_clusters: list[dict[str, Any]]
    errors: list[str]


def _enhance_with_graph(
    *,
    structured_query: StructuredQuery,
    source: str,
    db_path: str = "data/news.db",
) -> _GraphEnhancement:
    """Run graph expansion from query entities.

    The graph always expands from the entities named in the query.
    Intent-specific filtering (e.g. focus-cluster selection for
    EVENT_IMPACT_ANALYSIS) is the responsibility of the Skills layer.
    """
    if source != "knowledge_base":
        return _GraphEnhancement(
            graph_result=GraphRetrievalResult.empty(start_entities=[]),
            entities=[],
            event_clusters=[],
            errors=[],
        )

    entity_repo = EntityRepository(db_path)
    start_entities = entity_repo.find_by_names(structured_query.entities)
    if not start_entities:
        return _GraphEnhancement(
            graph_result=GraphRetrievalResult.empty(start_entities=[]),
            entities=[],
            event_clusters=[],
            errors=[],
        )

    retriever = KnowledgeGraphRetriever(db_path=db_path)
    graph_result = retriever.search(structured_query, start_entities=start_entities)
    return _GraphEnhancement(
        graph_result=graph_result,
        entities=[entity.model_dump(mode="json") for entity in graph_result.expanded_entities],
        event_clusters=[cluster.model_dump(mode="json") for cluster in graph_result.expanded_clusters],
        errors=[f"[graph] {error}" for error in graph_result.errors],
    )


def _merge_by_id(
    items_a: list[dict[str, Any]],
    items_b: list[dict[str, Any]],
    key: str,
) -> list[dict[str, Any]]:
    """Deduplicate items from two lists by a key field."""
    merged: dict[str, dict[str, Any]] = {}
    for item in items_a:
        item_id = item.get(key)
        if item_id:
            merged[item_id] = item
    for item in items_b:
        item_id = item.get(key)
        if item_id:
            merged[item_id] = item
    return list(merged.values())


def run_pipeline(
    raw_query: str = "",
    articles: list[dict] | None = None,
    graph_enabled: bool = True,
    structured_query: StructuredQuery | None = None,
) -> PipelineResult:
    """Run the knowledge retrieval pipeline over normalized evidence.

    The supported mainline reads from the persisted knowledge base. Passing
    ``articles`` is an ad-hoc/debug path that performs temporary online
    extraction and in-memory retrieval; it does not participate in graph
    enhancement and should not replace offline ingestion through
    ``run_continuous``.

    ``graph_enabled=False`` is reserved for tests, debugging, and local
    operational triage. Product code should treat graph retrieval as enabled by
    default and fail-open on graph read errors.

    When *structured_query* is provided, the internal LLM intent-parsing
    step is skipped entirely.  This is the recommended call path for
    programmatic / agent consumers that already know the intent, entities,
    and time constraints.
    """
    if not raw_query and not articles and structured_query is None:
        raise ValueError("missing query input")

    if structured_query is None:
        classifier = IntentClassifier()
        structured_query = classifier.parse(raw_query or "")

    searcher = KnowledgeSearcher()
    request = KnowledgeSearchRequest(
        structured_query=structured_query,
        top_k=20,
    )

    if articles:
        search_result = searcher.search_articles(articles, request)
        source: str = "direct_articles"
    else:
        search_result = searcher.search(request)
        source = "knowledge_base"

    serialized: dict[str, Any] = search_result.to_dict()

    graph_enhancement: _GraphEnhancement | None = None
    if graph_enabled:
        graph_enhancement = _enhance_with_graph(
            structured_query=structured_query,
            source=source,
        )

    graph_ent = graph_enhancement.entities if graph_enhancement else []
    graph_clu = graph_enhancement.event_clusters if graph_enhancement else []
    merged_entities = _merge_by_id(serialized["entities"], graph_ent, "entity_id")
    merged_clusters = _merge_by_id(serialized["event_clusters"], graph_clu, "cluster_id")

    if graph_enhancement is not None and graph_enabled:
        graph_meta = GraphMeta(
            graph_enabled=True,
            graph_used=graph_enhancement.graph_result.used,
            candidate_count=graph_enhancement.graph_result.candidate_count,
            expanded_cluster_count=graph_enhancement.graph_result.expanded_cluster_count,
            expanded_entity_count=graph_enhancement.graph_result.expanded_entity_count,
            hit_reasons=graph_enhancement.graph_result.hit_reasons,
        )
    else:
        graph_meta = GraphMeta(graph_enabled=graph_enabled)

    errors = list(graph_enhancement.errors) if graph_enhancement else []
    if source == "direct_articles" and structured_query.intent.value == "RELATIONSHIP_QUERY":
        errors.append("关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入")

    return PipelineResult(
        request_id=str(uuid4())[:8],
        query=structured_query,
        source=source,  # type: ignore[arg-type]
        knowledge_units=serialized["knowledge_units"],
        entities=merged_entities,
        event_clusters=merged_clusters,
        total_count=search_result.total_count,
        retrieval=RetrievalMeta(
            retrieval_mode="bm25",
            bm25_count=search_result.bm25_count,
            applied_filters=search_result.applied_filters,
            hit_scores=search_result.hit_scores,
        ),
        graph=graph_meta,
        graph_result=graph_enhancement.graph_result if graph_enhancement else None,
        errors=errors,
    )
