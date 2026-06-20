"""
Knowledge retrieval entrypoint for ``run_pipeline``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from src.entities import EntityRepository
from src.graph import GraphRetrievalResult, KnowledgeGraphRetriever
from src.paths import DEFAULT_DB_PATH
from src.schemas.query import IntentType, StructuredQuery
from src.orchestration.result import GraphMeta, PipelineResult, RetrievalMeta
from src.retrieval.knowledge_search import KnowledgeSearchRequest, KnowledgeSearcher
from src.retrieval.serve_singletons import (
    get_entity_repository,
    get_graph_retriever,
    get_searcher,
    is_serve_mode,
)


def _resolve_searcher(db_path: str) -> KnowledgeSearcher:
    """Shared singleton in serve mode; fresh instance otherwise."""
    if is_serve_mode():
        return get_searcher(db_path)
    return KnowledgeSearcher(db_path)


def _resolve_entity_repo(db_path: str) -> EntityRepository:
    """Shared singleton in serve mode; fresh instance otherwise."""
    if is_serve_mode():
        return get_entity_repository(db_path)
    return EntityRepository(db_path)


def _resolve_graph_retriever(db_path: str) -> KnowledgeGraphRetriever:
    """Shared singleton in serve mode; fresh instance otherwise."""
    if is_serve_mode():
        return get_graph_retriever(db_path)
    return KnowledgeGraphRetriever(db_path=db_path)


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
    db_path: str = DEFAULT_DB_PATH,
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

    entity_repo = _resolve_entity_repo(db_path)
    start_entities = entity_repo.find_by_names(structured_query.entities)
    if not start_entities:
        return _GraphEnhancement(
            graph_result=GraphRetrievalResult.empty(start_entities=[]),
            entities=[],
            event_clusters=[],
            errors=[],
        )

    retriever = _resolve_graph_retriever(db_path)

    # Handle A-B relationship path queries
    if (
        structured_query.target_entity
        and structured_query.intent == IntentType.RELATIONSHIP_QUERY
        and len(start_entities) == 1
    ):
        target_entities = entity_repo.find_by_names([structured_query.target_entity])
        if not target_entities:
            return _GraphEnhancement(
                graph_result=GraphRetrievalResult.empty(start_entities=start_entities),
                entities=[],
                event_clusters=[],
                errors=[f"[graph] target entity '{structured_query.target_entity}' not found"],
            )
        graph_result = retriever.search_relationship_path(
            entity_a=start_entities[0],
            entity_b=target_entities[0],
            max_hops=structured_query.hops,
        )
    else:
        graph_result = retriever.search(
            structured_query,
            start_entities=start_entities,
            summary_only=True,
        )
    return _GraphEnhancement(
        graph_result=graph_result,
        entities=[],
        event_clusters=[],
        errors=[f"[graph] {error}" for error in graph_result.errors],
    )


def expand_graph_detail(
    *,
    cluster_ids: list[str],
    db_path: str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Expand specific clusters into full graph detail (Tier-2).

    Called by the ``graph-expand`` CLI subcommand.
    """
    retriever = _resolve_graph_retriever(db_path)
    result = retriever.expand_clusters(cluster_ids)
    return result.to_graph_dict(enabled=True)


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
    articles: list[dict] | None = None,
    graph_enabled: bool = True,
    structured_query: StructuredQuery | None = None,
    top_k: int = 20,
    hops: int | None = None,
    db_path: str = DEFAULT_DB_PATH,
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

    *structured_query* is required.  Programmatic callers (CLI, agents)
    construct it directly; natural-language intent parsing is no longer
    embedded in the pipeline.
    """
    if structured_query is None:
        raise ValueError("structured_query is required (LLM intent parsing has been removed)")

    effective_query = structured_query
    if hops is not None:
        effective_query = replace(structured_query, hops=hops)

    searcher = _resolve_searcher(db_path)

    request = KnowledgeSearchRequest(
        structured_query=effective_query,
        top_k=top_k,
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
            structured_query=effective_query,
            source=source,
            db_path=db_path,
        )

    graph_ent = graph_enhancement.entities if graph_enhancement else []
    graph_clu = graph_enhancement.event_clusters if graph_enhancement else []
    merged_entities = _merge_by_id(serialized["entities"], graph_ent, "entity_id")
    merged_clusters = _merge_by_id(serialized["event_clusters"], graph_clu, "cluster_id")

    if graph_enhancement is not None and graph_enabled:
        gr = graph_enhancement.graph_result
        summary = gr.summary
        graph_meta = GraphMeta(
            graph_enabled=True,
            graph_used=gr.used,
            candidate_count=gr.candidate_count,
            expanded_cluster_count=summary.get("event_cluster_count", 0),
            expanded_entity_count=summary.get("expanded_entity_count", 0),
            hit_reasons=gr.hit_reasons,
            hops=effective_query.hops,
        )
    else:
        graph_meta = GraphMeta(graph_enabled=graph_enabled, hops=effective_query.hops)

    errors = list(graph_enhancement.errors) if graph_enhancement else []
    warnings: list[dict[str, str]] = []
    if source == "direct_articles" and effective_query.intent == IntentType.RELATIONSHIP_QUERY:
        errors.append("关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入")

    # Detect graph-dependent intents that degraded silently.
    if (
        graph_enhancement is not None
        and graph_enhancement.graph_result.used is False
        and effective_query.intent == IntentType.RELATIONSHIP_QUERY
    ):
        errors.append(
            "关系查询需要图谱服务，当前不可用，返回的结果为降级的文本搜索而非关系路径"
        )

    # Structured warnings for empty results
    if search_result.total_count == 0 and effective_query.entities:
        # Reuse the searcher's entity repo rather than constructing a new one.
        matched = searcher.entities.find_by_names(effective_query.entities)
        if not matched:
            entity_names = ", ".join(effective_query.entities)
            warnings.append({
                "code": "ENTITY_NOT_FOUND",
                "message": f"未找到实体'{entity_names}'，已降级为文本搜索",
            })
        if search_result.total_count == 0:
            warnings.append({
                "code": "NO_RESULTS",
                "message": "查询未返回任何结果",
            })

    return PipelineResult(
        request_id=str(uuid4())[:8],
        query=effective_query,
        source=source,  # type: ignore[arg-type]
        knowledge_units=serialized["knowledge_units"],
        entities=merged_entities,
        event_clusters=merged_clusters,
        total_count=search_result.total_count,
        retrieval=RetrievalMeta(
            retrieval_mode=search_result.retrieval_path,
            bm25_count=search_result.bm25_count,
            applied_filters=search_result.applied_filters,
            hit_scores=search_result.hit_scores,
        ),
        graph=graph_meta,
        graph_result=graph_enhancement.graph_result if graph_enhancement else None,
        errors=errors,
        warnings=warnings,
    )
