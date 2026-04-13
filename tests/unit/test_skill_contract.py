from __future__ import annotations

from datetime import date

from src.graph.knowledge_retrieval import GraphRetrievalResult
from src.intent.models import IntentType, QueryFilters, StructuredQuery, TimeRange
from src.orchestration.result import GraphMeta, PipelineResult, PipelineSource, RetrievalMeta
from src.skills.service import run_skill_query


_KNOWLEDGE_UNITS = [
    {
        "ku_id": "ku-cluster-new",
        "unit_kind": "event",
        "unit_type": "policy_sanction",
        "summary": "Xiaomi receives a regulatory penalty",
        "entities": [{"entity_id": "ent-xiaomi", "mention": "Xiaomi Group"}],
        "source": {"doc_id": "doc-1", "source_name": "test-source", "url": None},
        "evidence": [{"text": "Xiaomi Group received a penalty."}],
        "time": {
            "event_time": "2026-04-02T09:00:00+00:00",
            "published_at": "2026-04-02T09:00:00+00:00",
            "extracted_at": "2026-04-02T09:05:00+00:00",
        },
        "confidence": 0.95,
        "tags": [],
        "relation_hints": [],
        "cluster_id": "clu-new",
        "conflict_status": "possible",
        "status": "active",
    },
    {
        "ku_id": "ku-cluster-old",
        "unit_kind": "event",
        "unit_type": "policy_sanction",
        "summary": "Xiaomi starts remediation",
        "entities": [{"entity_id": "ent-xiaomi", "mention": "Xiaomi Group"}],
        "source": {"doc_id": "doc-2", "source_name": "test-source", "url": None},
        "evidence": [{"text": "Xiaomi started remediation."}],
        "time": {
            "event_time": "2026-03-15T09:00:00+00:00",
            "published_at": "2026-03-15T09:00:00+00:00",
            "extracted_at": "2026-03-15T09:05:00+00:00",
        },
        "confidence": 0.8,
        "tags": [],
        "relation_hints": [],
        "cluster_id": "clu-old",
        "conflict_status": "none",
        "status": "active",
    },
    {
        "ku_id": "ku-standalone",
        "unit_kind": "fact",
        "unit_type": "progress_update",
        "summary": "Xiaomi published a standalone update",
        "entities": [{"entity_id": "ent-xiaomi", "mention": "Xiaomi Group"}],
        "source": {"doc_id": "doc-3", "source_name": "test-source", "url": None},
        "evidence": [{"text": "Standalone progress update."}],
        "time": {
            "event_time": "2026-03-20T09:00:00+00:00",
            "published_at": "2026-03-20T09:00:00+00:00",
            "extracted_at": "2026-03-20T09:05:00+00:00",
        },
        "confidence": 0.7,
        "tags": [],
        "relation_hints": [],
        "cluster_id": None,
        "conflict_status": "none",
        "status": "active",
    },
]

_ENTITIES = [
    {
        "entity_id": "ent-xiaomi",
        "entity_type": "Company",
        "canonical_name": "Xiaomi Group",
        "aliases": ["小米集团"],
        "identifiers": {},
        "description": None,
        "tags": [],
        "source_ku_ids": ["ku-cluster-new"],
        "created_at": "2026-04-02T09:00:00+00:00",
        "updated_at": "2026-04-02T09:00:00+00:00",
    },
    {
        "entity_id": "ent-partner",
        "entity_type": "Organization",
        "canonical_name": "Partner Co",
        "aliases": [],
        "identifiers": {},
        "description": None,
        "tags": [],
        "source_ku_ids": ["ku-cluster-new"],
        "created_at": "2026-04-02T09:00:00+00:00",
        "updated_at": "2026-04-02T09:00:00+00:00",
    },
]

_EVENT_CLUSTERS = [
    {
        "cluster_id": "clu-old",
        "cluster_type": "policy_sanction",
        "title": "Older Xiaomi cluster",
        "summary": "Older Xiaomi cluster",
        "entity_ids": ["ent-xiaomi"],
        "primary_entity_id": "ent-xiaomi",
        "time_anchor": "2026-03-15T09:00:00+00:00",
        "time_range": {
            "start": "2026-03-15T09:00:00+00:00",
            "end": "2026-03-16T09:00:00+00:00",
        },
        "member_ku_ids": ["ku-cluster-old"],
        "source_doc_ids": ["doc-2"],
        "conflict_status": "none",
        "cluster_confidence": 0.8,
        "representative_ku_id": "ku-cluster-old",
        "member_count": 1,
        "source_count": 1,
        "summary_variants": [],
        "event_time_variants": [],
        "conflict_reasons": [],
        "updated_at": "2026-03-16T09:00:00+00:00",
    },
    {
        "cluster_id": "clu-new",
        "cluster_type": "policy_sanction",
        "title": "Newer Xiaomi cluster",
        "summary": "Newer Xiaomi cluster",
        "entity_ids": ["ent-xiaomi", "ent-partner"],
        "primary_entity_id": "ent-xiaomi",
        "time_anchor": "2026-04-02T09:00:00+00:00",
        "time_range": {
            "start": "2026-04-02T09:00:00+00:00",
            "end": "2026-04-03T09:00:00+00:00",
        },
        "member_ku_ids": ["ku-cluster-new"],
        "source_doc_ids": ["doc-1"],
        "conflict_status": "possible",
        "cluster_confidence": 0.95,
        "representative_ku_id": "ku-cluster-new",
        "member_count": 1,
        "source_count": 1,
        "summary_variants": [],
        "event_time_variants": [],
        "conflict_reasons": ["multiple_event_time_values"],
        "updated_at": "2026-04-03T09:00:00+00:00",
    },
]


def _make_pipeline_result(
    *,
    intent: str,
    source: PipelineSource = "knowledge_base",
    knowledge_units: list[dict] | None = None,
    entities: list[dict] | None = None,
    event_clusters: list[dict] | None = None,
    graph_used: bool | None = None,
    graph_result: GraphRetrievalResult | None = None,
    errors: list[str] | None = None,
    total_count: int = 7,
) -> PipelineResult:
    """Build a PipelineResult for monkeypatching run_pipeline in tests."""
    effective_graph_used = graph_used if graph_used is not None else (source == "knowledge_base")

    default_graph_result = GraphRetrievalResult(
        used=effective_graph_used,
        nodes=[
            {"id": "ent-xiaomi", "type": "Entity", "name": "Xiaomi Group"},
            {"id": "clu-new", "type": "EventCluster", "name": "Newer Xiaomi cluster"},
            {"id": "ent-partner", "type": "Entity", "name": "Partner Co"},
        ],
        edges=[
            {"source": "ent-xiaomi", "target": "clu-new", "type": "INVOLVED_IN"},
            {"source": "ent-partner", "target": "clu-new", "type": "INVOLVED_IN"},
        ],
        paths=[
            {
                "path_type": "Entity->EventCluster->Entity",
                "start_entity_id": "ent-xiaomi",
                "start_entity_name": "Xiaomi Group",
                "cluster_id": "clu-new",
                "cluster_title": "Newer Xiaomi cluster",
                "cluster_type": "policy_sanction",
                "neighbor_entity_id": "ent-partner",
                "neighbor_entity_name": "Partner Co",
                "member_ku_ids": ["ku-cluster-new"],
            }
        ],
        summary={
            "start_entities": [{"entity_id": "ent-xiaomi", "name": "Xiaomi Group"}],
            "event_cluster_count": 1,
            "expanded_entity_count": 1,
            "expanded": source == "knowledge_base",
        },
    )

    return PipelineResult(
        request_id="req-1",
        query=StructuredQuery(
            intent=IntentType(intent),
            entities=["Xiaomi Group"],
            time_range=TimeRange(
                start=date(2026, 3, 1),
                end=date(2026, 4, 5),
            ),
            filters=QueryFilters(event_types=["policy_sanction"]),
            original_query="Show Xiaomi updates",
            confidence=0.9,
        ),
        source=source,
        knowledge_units=knowledge_units if knowledge_units is not None else list(_KNOWLEDGE_UNITS),
        entities=entities if entities is not None else list(_ENTITIES),
        event_clusters=event_clusters if event_clusters is not None else list(_EVENT_CLUSTERS),
        total_count=total_count,
        retrieval=RetrievalMeta(
            retrieval_mode="bm25",
            bm25_count=2,
        ),
        graph=GraphMeta(
            graph_enabled=True,
            graph_used=effective_graph_used,
        ),
        graph_result=graph_result if graph_result is not None else default_graph_result,
        errors=errors if errors is not None else [],
    )


def test_run_skill_query_maps_supported_entity_overview(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="ENTITY_OVERVIEW")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi overview")

    assert result["contract_version"] == "v1"
    assert result["ok"] is True
    assert result["skill_type"] == "entity_overview"
    assert result["source"] == "knowledge_base"
    assert result["summary"] == {
        "knowledge_unit_count": 3,
        "entity_count": 2,
        "event_cluster_count": 2,
        "total_count": 7,
    }
    assert result["capabilities"] == {
        "graph_supported": True,
        "graph_used": True,
        "timeline_supported": False,
    }
    assert result["payload"]["target_entity"] == "Xiaomi Group"
    assert result["payload"]["recent_event_clusters"][0]["cluster_id"] == "clu-new"
    assert result["payload"]["related_entities"] == [raw_result.entities[1]]


def test_run_skill_query_honors_skill_type_override(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="ENTITY_OVERVIEW")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(
        raw_query="Assess Xiaomi risk",
        skill_type_override="risk_assessment",
    )

    assert result["skill_type"] == "risk_assessment"
    assert result["query"]["intent"] == "RISK_ASSESSMENT"
    assert "risk_level" in result["payload"]


def test_run_skill_query_rejects_unsupported_intents(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="COMPARATIVE_ANALYSIS")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Unsupported query")

    assert result["ok"] is False
    assert result["skill_type"] is None
    assert result["payload"] is None
    assert result["errors"] == ["unsupported_intent:COMPARATIVE_ANALYSIS"]


def test_run_skill_query_sets_capabilities_for_direct_articles(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="EVENT_ANALYSIS",
        source="direct_articles",
        graph_used=True,
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Analyze Xiaomi events", articles=[{"doc_id": "doc-1"}])

    assert result["skill_type"] == "event_analysis"
    assert result["capabilities"] == {
        "graph_supported": False,
        "graph_used": False,
        "timeline_supported": False,
    }


def test_run_skill_query_keeps_ok_true_for_non_blocking_graph_errors(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="ENTITY_OVERVIEW",
        errors=["[graph] neo4j unavailable"],
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi overview")

    assert result["ok"] is True
    assert result["errors"] == ["[graph] neo4j unavailable"]


def test_run_skill_query_marks_blocking_errors_as_failed_contract(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="ENTITY_OVERVIEW",
        errors=["search backend unavailable"],
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi overview")

    assert result["ok"] is False
    assert result["errors"] == ["search backend unavailable"]


def test_run_skill_query_builds_cluster_first_timeline_oldest_first(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="ENTITY_TIMELINE")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi timeline")

    assert result["skill_type"] == "entity_timeline"
    events = result["payload"]["timeline_events"]
    assert [event["event_id"] for event in events] == [
        "clu-old",
        "ku-standalone",
        "clu-new",
    ]
    assert events[0]["event_source"] == "event_cluster"
    assert events[1]["event_source"] == "knowledge_unit"
    assert events[2]["representative_ku_id"] == "ku-cluster-new"


def test_run_skill_query_includes_graph_only_clusters_in_timeline(monkeypatch) -> None:
    extra_cluster = {
        "cluster_id": "clu-graph",
        "cluster_type": "policy_sanction",
        "title": "Graph-only Xiaomi cluster",
        "summary": "Graph-only Xiaomi cluster",
        "entity_ids": ["ent-xiaomi"],
        "primary_entity_id": "ent-xiaomi",
        "time_anchor": "2026-04-04T09:00:00+00:00",
        "time_range": {
            "start": "2026-04-04T09:00:00+00:00",
            "end": "2026-04-04T12:00:00+00:00",
        },
        "member_ku_ids": ["ku-graph-only"],
        "source_doc_ids": ["doc-4"],
        "conflict_status": "none",
        "cluster_confidence": 0.88,
        "representative_ku_id": "ku-graph-only",
        "member_count": 1,
        "source_count": 1,
        "summary_variants": [],
        "event_time_variants": [],
        "conflict_reasons": [],
        "updated_at": "2026-04-04T12:00:00+00:00",
    }
    raw_result = _make_pipeline_result(
        intent="ENTITY_TIMELINE",
        event_clusters=[*_EVENT_CLUSTERS, extra_cluster],
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi timeline")

    events = result["payload"]["timeline_events"]
    assert [event["event_id"] for event in events] == [
        "clu-old",
        "ku-standalone",
        "clu-new",
        "clu-graph",
    ]
    assert events[-1]["event_source"] == "event_cluster"
    assert events[-1]["representative_ku_id"] == "ku-graph-only"


def test_run_skill_query_preserves_traceable_supporting_evidence(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="EVENT_ANALYSIS")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Analyze Xiaomi events")

    evidence = result["payload"]["supporting_evidence"][0]
    assert evidence["ku_id"] == "ku-cluster-new"
    assert evidence["source"] == {"doc_id": "doc-1", "source_name": "test-source", "url": None}
    assert evidence["evidence"] == [{"text": "Xiaomi Group received a penalty."}]
    assert evidence["confidence"] == 0.95
    assert evidence["conflict_status"] == "possible"


def test_run_skill_query_maps_relationship_query_to_relationship_payload(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="RELATIONSHIP_QUERY")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi relationships")

    assert result["contract_version"] == "v1"
    assert result["ok"] is True
    assert result["skill_type"] == "relationship_query"
    assert result["capabilities"] == {
        "graph_supported": True,
        "graph_used": True,
        "timeline_supported": False,
    }
    assert result["payload"]["target_entity"] == "Xiaomi Group"
    assert result["payload"]["related_entities"] == [raw_result.entities[1]]
    assert [cluster["cluster_id"] for cluster in result["payload"]["related_event_clusters"]] == ["clu-new"]
    assert result["payload"]["relationship_paths"] == [
        {
            "path_type": "Entity->EventCluster->Entity",
            "start_entity_id": "ent-xiaomi",
            "start_entity_name": "Xiaomi Group",
            "cluster_id": "clu-new",
            "cluster_title": "Newer Xiaomi cluster",
            "cluster_type": "policy_sanction",
            "neighbor_entity_id": "ent-partner",
            "neighbor_entity_name": "Partner Co",
            "member_ku_ids": ["ku-cluster-new"],
        }
    ]
    assert result["payload"]["graph"] == raw_result.graph_result.to_graph_dict(enabled=True)  # type: ignore[union-attr]


def test_run_skill_query_keeps_relationship_contract_on_non_blocking_graph_errors(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="RELATIONSHIP_QUERY",
        graph_used=False,
        graph_result=GraphRetrievalResult(
            used=False,
            nodes=[],
            edges=[],
            paths=[],
        ),
        errors=["[graph] neo4j unavailable"],
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi relationships")

    assert result["ok"] is True
    assert result["skill_type"] == "relationship_query"
    assert result["payload"]["relationship_paths"] == []
    assert result["errors"] == ["[graph] neo4j unavailable"]


def test_run_skill_query_returns_empty_relationship_matches_without_graph_paths(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="RELATIONSHIP_QUERY",
        graph_result=GraphRetrievalResult(
            used=True,
            nodes=[
                {"id": "ent-xiaomi", "type": "Entity", "name": "Xiaomi Group"},
                {"id": "clu-new", "type": "EventCluster", "name": "Newer Xiaomi cluster"},
                {"id": "ent-partner", "type": "Entity", "name": "Partner Co"},
            ],
            edges=[
                {"source": "ent-xiaomi", "target": "clu-new", "type": "INVOLVED_IN"},
                {"source": "ent-partner", "target": "clu-new", "type": "INVOLVED_IN"},
            ],
            paths=[],
        ),
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi relationships")

    assert result["ok"] is True
    assert result["skill_type"] == "relationship_query"
    assert result["payload"]["relationship_paths"] == []
    assert result["payload"]["related_entities"] == []
    assert result["payload"]["related_event_clusters"] == []


def test_run_skill_query_returns_stable_failed_relationship_contract_for_direct_articles(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="RELATIONSHIP_QUERY",
        source="direct_articles",
        graph_used=False,
        graph_result=GraphRetrievalResult(
            used=False,
            nodes=[],
            edges=[],
            paths=[],
        ),
        errors=["关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入"],
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi relationships", articles=[{"doc_id": "doc-1"}])

    assert result["ok"] is False
    assert result["skill_type"] == "relationship_query"
    assert result["source"] == "direct_articles"
    assert result["payload"]["related_entities"] == []
    assert result["payload"]["related_event_clusters"] == []
    assert result["payload"]["relationship_paths"] == []
    assert result["payload"]["graph"] == raw_result.graph_result.to_graph_dict(enabled=True)  # type: ignore[union-attr]
    assert len(result["payload"]["supporting_evidence"]) == 3
    assert result["errors"] == ["关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入"]
