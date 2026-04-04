"""
Knowledge retrieval entrypoint for `run_pipeline`.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from src.intent import IntentClassifier
from src.intent.models import IntentType, StructuredQuery
from src.retrieval.knowledge_search import KnowledgeSearchRequest, KnowledgeSearcher


def _resolve_retrieval_mode(
    searcher: KnowledgeSearcher,
    *,
    has_direct_articles: bool,
) -> Literal["hybrid", "bm25_only"]:
    if has_direct_articles:
        return "hybrid"

    embedding_client = getattr(searcher, "embedding_client", None)
    is_configured = getattr(embedding_client, "is_configured", None)
    if callable(is_configured) and not is_configured():
        return "bm25_only"
    return "hybrid"


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


def _build_compatibility_output(
    structured_query: StructuredQuery,
    result: dict,
    source: str,
    graph_enabled: bool,
) -> dict:
    events = _build_timeline_events(result)
    request_id = str(uuid4())[:8]
    target_entity = structured_query.entities[0] if structured_query.entities else None
    graph_edges = []
    if graph_enabled:
        graph_edges = [
            {
                "entity_id": entity["entity_id"],
                "cluster_id": unit["cluster_id"],
                "ku_id": unit["ku_id"],
            }
            for unit in result["knowledge_units"]
            for entity in unit["entities"]
            if entity.get("entity_id") and unit.get("cluster_id")
        ]
    base_output = {
        "request_id": request_id,
        "query": structured_query.to_dict(),
        "source": source,
        "retrieval": result["retrieval"],
        "graph": {
            "enabled": graph_enabled,
            "edges": graph_edges,
        },
        "knowledge_units": result["knowledge_units"],
        "entities": result["entities"],
        "event_clusters": result["event_clusters"],
        "total_count": result["total_count"],
        "report": {},
        "risk_assessment": {},
        "timeline_data": {},
        "comparison_report": {},
        "event_impact": {},
        "verification": {
            "passed": True,
            "retry_count": 0,
            "issues": [],
        },
        "particles_count": len(result["knowledge_units"]),
        "errors": [],
        "stage_durations": {},
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
        base_output["report"] = {
            "entities": structured_query.entities,
            "relationships": base_output["graph"]["edges"],
            "total_relationships": len(base_output["graph"]["edges"]),
        }
        return base_output

    if structured_query.intent == IntentType.COMPARATIVE_ANALYSIS:
        comparison = {
            "entities": structured_query.entities,
            "entity_event_counts": {
                entity: sum(
                    1
                    for unit in result["knowledge_units"]
                    if entity.lower()
                    in " ".join(
                        ref["mention"] for ref in unit["entities"]
                    ).lower()
                )
                for entity in structured_query.entities
            },
            "summary": "",
        }
        if len(structured_query.entities) >= 2:
            entity_a = structured_query.entities[0]
            entity_b = structured_query.entities[1]
            count_a = comparison["entity_event_counts"][entity_a]
            count_b = comparison["entity_event_counts"][entity_b]
            if count_a > count_b:
                comparison["summary"] = f"{entity_a} has more matched events than {entity_b}"
            elif count_b > count_a:
                comparison["summary"] = f"{entity_b} has more matched events than {entity_a}"
            else:
                comparison["summary"] = f"{entity_a} and {entity_b} have the same matched event count"
        base_output["comparison_report"] = comparison
        return base_output

    if structured_query.intent == IntentType.EVENT_IMPACT:
        base_output["event_impact"] = {
            "key_events": events[:10],
            "impact_scope": {
                "entities": [entity["canonical_name"] for entity in result["entities"]],
                "event_clusters": [cluster["cluster_id"] for cluster in result["event_clusters"]],
            },
            "affected_entities": [entity["canonical_name"] for entity in result["entities"]],
        }
        return base_output

    summaries = [event["description"] for event in events[:5]]
    base_output["report"] = {
        "target_entity": target_entity,
        "summary": summaries,
        "evidence_count": len(result["knowledge_units"]),
        "entity_count": len(result["entities"]),
        "cluster_count": len(result["event_clusters"]),
    }
    base_output["risk_assessment"] = {
        "target_entity": target_entity,
        "risk_level": "MEDIUM" if result["knowledge_units"] else "LOW",
        "risk_score": min(1.0, len(result["knowledge_units"]) / 10),
    }
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
        retrieval_mode=_resolve_retrieval_mode(
            searcher,
            has_direct_articles=bool(articles),
        ),
    )

    if articles:
        result = searcher.search_articles(articles, request)
        source = "direct_articles"
    else:
        result = searcher.search(request)
        source = "knowledge_base"

    return _build_compatibility_output(
        structured_query=structured_query,
        result=result.to_dict(),
        source=source,
        graph_enabled=graph_enabled,
    )
