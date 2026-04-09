"""
Knowledge retrieval entrypoint for `run_pipeline`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import uuid4

from src.entities import EntityRepository
from src.graph import GraphRetrievalResult, KnowledgeGraphRetriever
from src.intent import IntentClassifier
from src.intent.models import IntentType, StructuredQuery
from src.retrieval.knowledge_search import KnowledgeSearchRequest, KnowledgeSearcher


@dataclass
class PipelineGraphEnhancement:
    graph_result: GraphRetrievalResult
    entities: list[dict]
    event_clusters: list[dict]
    errors: list[str]


def _parse_cluster_anchor(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(text[:10]), datetime.min.time())
            except ValueError:
                return None
    return None


def _cluster_sort_anchor(cluster: dict[str, object]) -> datetime:
    time_range = cluster.get("time_range")
    if not isinstance(time_range, dict):
        time_range = {}
    for candidate in (
        cluster.get("time_anchor"),
        time_range.get("end"),
        time_range.get("start"),
    ):
        parsed = _parse_cluster_anchor(candidate)
        if parsed is not None:
            return parsed
    return datetime.min


def _select_focus_cluster_for_impact(
    clusters: list[dict[str, object]],
    start_entity_ids: set[str],
) -> dict[str, object] | None:
    if not clusters:
        return None

    sorted_clusters = sorted(
        clusters,
        key=lambda cluster: (_cluster_sort_anchor(cluster), str(cluster.get("cluster_id", ""))),
        reverse=True,
    )
    for cluster in sorted_clusters:
        entity_ids = cluster.get("entity_ids", [])
        if not isinstance(entity_ids, list):
            continue
        if any(isinstance(entity_id, str) and entity_id in start_entity_ids for entity_id in entity_ids):
            return cluster
    return sorted_clusters[0]


def _resolve_graph_start_entities(
    *,
    structured_query: StructuredQuery,
    result: dict[str, object],
    entity_repo: EntityRepository,
) -> list:
    start_entities = entity_repo.find_by_names(structured_query.entities)
    if not start_entities:
        return []
    if structured_query.intent != IntentType.EVENT_IMPACT_ANALYSIS:
        return start_entities

    raw_clusters = result.get("event_clusters", [])
    if not isinstance(raw_clusters, list):
        return start_entities

    focus_cluster = _select_focus_cluster_for_impact(
        [cluster for cluster in raw_clusters if isinstance(cluster, dict)],
        {entity.entity_id for entity in start_entities},
    )
    if focus_cluster is None:
        return start_entities

    raw_entity_ids = focus_cluster.get("entity_ids", [])
    if not isinstance(raw_entity_ids, list):
        return start_entities
    focus_entity_ids = [
        entity_id
        for entity_id in raw_entity_ids
        if isinstance(entity_id, str) and entity_id
    ]
    focus_entities = entity_repo.get_by_ids(focus_entity_ids)
    return focus_entities or start_entities


def _build_timeline_events(result: dict) -> list[dict]:
    events: list[dict] = []
    for unit in result["knowledge_units"]:
        anchor = unit["time"]["event_time"] or unit["time"]["published_at"]
        events.append(
            {
                "date": anchor,
                "event_type": unit["unit_type"],
                "description": unit["summary"],
                "source_ids": [unit["source"]["doc_id"]],
                "particle_id": unit["ku_id"],
                "cluster_id": unit.get("cluster_id"),
            }
        )
    events.sort(key=lambda item: item["date"], reverse=True)
    return events


def _merge_by_id(
    items_a: list[dict],
    items_b: list[dict],
    key: str,
) -> list[dict]:
    """Deduplicate items from two lists by a key field."""
    merged: dict[str, dict] = {}
    for item in items_a + items_b:
        item_id = item.get(key)
        if not item_id:
            continue
        merged[item_id] = item
    return list(merged.values())


def _enhance_with_graph(
    *,
    structured_query: StructuredQuery,
    result: dict[str, object],
    source: str,
    db_path: str = "data/news.db",
) -> PipelineGraphEnhancement:
    if source != "knowledge_base":
        return PipelineGraphEnhancement(
            graph_result=GraphRetrievalResult.empty(start_entities=[]),
            entities=[],
            event_clusters=[],
            errors=[],
        )

    entity_repo = EntityRepository(db_path)
    start_entities = _resolve_graph_start_entities(
        structured_query=structured_query,
        result=result,
        entity_repo=entity_repo,
    )
    if not start_entities:
        return PipelineGraphEnhancement(
            graph_result=GraphRetrievalResult.empty(start_entities=[]),
            entities=[],
            event_clusters=[],
            errors=[],
        )

    retriever = KnowledgeGraphRetriever(db_path=db_path)
    graph_result = retriever.search(structured_query, start_entities=start_entities)
    return PipelineGraphEnhancement(
        graph_result=graph_result,
        entities=[entity.model_dump(mode="json") for entity in graph_result.expanded_entities],
        event_clusters=[cluster.model_dump(mode="json") for cluster in graph_result.expanded_clusters],
        errors=[f"[graph] {error}" for error in graph_result.errors],
    )


def _build_pipeline_output(
    structured_query: StructuredQuery,
    result: dict,
    source: str,
    graph_enabled: bool,
    graph_enhancement: PipelineGraphEnhancement | None = None,
) -> dict:
    relationship_query_requires_graph_source = (
        structured_query.intent == IntentType.RELATIONSHIP_QUERY and source != "knowledge_base"
    )
    graph_enhancement = graph_enhancement or PipelineGraphEnhancement(
        graph_result=GraphRetrievalResult.empty(start_entities=[]),
        entities=[],
        event_clusters=[],
        errors=[],
    )
    merged_entities = _merge_by_id(result["entities"], graph_enhancement.entities, "entity_id")
    merged_clusters = _merge_by_id(result["event_clusters"], graph_enhancement.event_clusters, "cluster_id")
    if graph_enabled:
        graph_dict = graph_enhancement.graph_result.to_graph_dict(enabled=True)
    else:
        graph_dict = GraphRetrievalResult.empty(start_entities=[]).to_graph_dict(enabled=False)
    events = _build_timeline_events(result)
    request_id = str(uuid4())[:8]
    target_entity = structured_query.entities[0] if structured_query.entities else None
    base_output = {
        "request_id": request_id,
        "query": structured_query.to_dict(),
        "source": source,
        "retrieval": {
            **result["retrieval"],
            "graph_used": graph_enabled and graph_enhancement.graph_result.used,
            "graph_candidate_count": graph_enhancement.graph_result.candidate_count if graph_enabled else 0,
            "graph_expanded_cluster_count": graph_enhancement.graph_result.expanded_cluster_count if graph_enabled else 0,
            "graph_expanded_entity_count": graph_enhancement.graph_result.expanded_entity_count if graph_enabled else 0,
            "graph_hit_reasons": graph_enhancement.graph_result.hit_reasons if graph_enabled else {},
        },
        "graph": graph_dict,
        "knowledge_units": result["knowledge_units"],
        "entities": merged_entities,
        "event_clusters": merged_clusters,
        "total_count": result["total_count"],
        "timeline_data": {},
        "verification": {
            "passed": not relationship_query_requires_graph_source,
            "retry_count": 0,
            "issues": [],
        },
        "errors": (
            ["关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入"]
            if relationship_query_requires_graph_source
            else []
        )
        + list(graph_enhancement.errors),
    }

    if structured_query.intent == IntentType.ENTITY_TIMELINE:
        base_output["timeline_data"] = {
            "timeline": {
                "entity": target_entity,
                "events": events,
                "total_events": len(events),
                "time_range": {
                    "start": events[-1]["date"] if events else None,
                    "end": events[0]["date"] if events else None,
                },
            },
            "entity": target_entity,
            "event_count": len(events),
        }
        return base_output

    if structured_query.intent == IntentType.RELATIONSHIP_QUERY:
        if relationship_query_requires_graph_source:
            return base_output
        if not graph_enabled:
            return {
                **base_output,
                "errors": ["关系查询需要图谱支持，请启用 graph_enabled"],
                "verification": {
                    "passed": False,
                    "retry_count": 0,
                    "issues": [],
                },
            }
        return base_output

    if structured_query.intent == IntentType.COMPARATIVE_ANALYSIS:
        return base_output

    if structured_query.intent == IntentType.EVENT_ANALYSIS:
        return base_output

    return base_output


def run_pipeline(
    raw_query: str = "",
    articles: list[dict] | None = None,
    graph_enabled: bool = True,
) -> dict:
    """Run the knowledge retrieval pipeline over normalized evidence."""
    if not raw_query and not articles:
        return {"error": "missing query input"}

    classifier = IntentClassifier()
    structured_query = classifier.parse(raw_query or "")
    searcher = KnowledgeSearcher()
    request = KnowledgeSearchRequest(
        structured_query=structured_query,
        top_k=20,
    )

    if articles:
        result = searcher.search_articles(articles, request)
        source = "direct_articles"
    else:
        result = searcher.search(request)
        source = "knowledge_base"
    result_dict = result.to_dict()

    graph_enhancement: PipelineGraphEnhancement | None = None
    if graph_enabled:
        graph_enhancement = _enhance_with_graph(
            structured_query=structured_query,
            result=result_dict,
            source=source,
        )

    return _build_pipeline_output(
        structured_query=structured_query,
        result=result_dict,
        source=source,
        graph_enabled=graph_enabled,
        graph_enhancement=graph_enhancement,
    )
