from __future__ import annotations

from src.skills.service import run_skill_query


def _base_raw_result(*, intent: str, source: str = "knowledge_base") -> dict:
    return {
        "request_id": "req-1",
        "query": {
            "intent": intent,
            "entities": ["Xiaomi Group"],
            "time_range": {
                "start": "2026-03-01",
                "end": "2026-04-05",
            },
            "filters": {
                "event_types": ["policy_sanction"],
                "risk_levels": None,
                "sources": None,
                "min_credibility": 0.5,
                "categories": None,
            },
            "original_query": "Show Xiaomi updates",
            "confidence": 0.9,
        },
        "source": source,
        "retrieval": {
            "retrieval_mode": "hybrid",
            "bm25_count": 2,
            "vector_count": 2,
            "graph_used": source == "knowledge_base",
        },
        "graph": {
            "enabled": True,
            "used": source == "knowledge_base",
            "nodes": [
                {"id": "ent-xiaomi", "type": "Entity", "name": "Xiaomi Group"},
                {"id": "clu-new", "type": "EventCluster", "name": "Newer Xiaomi cluster"},
                {"id": "ent-partner", "type": "Entity", "name": "Partner Co"},
            ],
            "edges": [
                {"source": "ent-xiaomi", "target": "clu-new", "type": "INVOLVED_IN"},
                {"source": "ent-partner", "target": "clu-new", "type": "INVOLVED_IN"},
            ],
            "paths": [
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
            "summary": {
                "start_entities": [{"entity_id": "ent-xiaomi", "name": "Xiaomi Group"}],
                "event_cluster_count": 1,
                "expanded_entity_count": 1,
                "expanded": source == "knowledge_base",
            },
        },
        "knowledge_units": [
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
        ],
        "entities": [
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
        ],
        "event_clusters": [
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
        ],
        "timeline_data": {},
        "total_count": 7,
        "verification": {"passed": True, "retry_count": 0, "issues": []},
        "errors": [],
    }


def test_run_skill_query_maps_supported_entity_overview(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="ENTITY_OVERVIEW")
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
    assert result["payload"]["related_entities"] == [raw_result["entities"][1]]


def test_run_skill_query_rejects_unsupported_intents(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="COMPARATIVE_ANALYSIS")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Unsupported query")

    assert result["ok"] is False
    assert result["skill_type"] is None
    assert result["payload"] is None
    assert result["errors"] == ["unsupported_intent:COMPARATIVE_ANALYSIS"]


def test_run_skill_query_sets_capabilities_for_direct_articles(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="EVENT_ANALYSIS", source="direct_articles")
    raw_result["retrieval"]["graph_used"] = True
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Analyze Xiaomi events", articles=[{"doc_id": "doc-1"}])

    assert result["skill_type"] == "event_analysis"
    assert result["capabilities"] == {
        "graph_supported": False,
        "graph_used": False,
        "timeline_supported": False,
    }


def test_run_skill_query_keeps_ok_true_for_non_blocking_graph_errors(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="ENTITY_OVERVIEW")
    raw_result["errors"] = ["[graph] neo4j unavailable"]
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi overview")

    assert result["ok"] is True
    assert result["errors"] == ["[graph] neo4j unavailable"]


def test_run_skill_query_marks_blocking_errors_as_failed_contract(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="ENTITY_OVERVIEW")
    raw_result["errors"] = ["search backend unavailable"]
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi overview")

    assert result["ok"] is False
    assert result["errors"] == ["search backend unavailable"]


def test_run_skill_query_builds_cluster_first_timeline_oldest_first(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="ENTITY_TIMELINE")
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
    raw_result = _base_raw_result(intent="ENTITY_TIMELINE")
    raw_result["retrieval"]["graph_used"] = True
    raw_result["event_clusters"].append(
        {
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
    raw_result = _base_raw_result(intent="EVENT_ANALYSIS")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Analyze Xiaomi events")

    evidence = result["payload"]["supporting_evidence"][0]
    assert evidence["ku_id"] == "ku-cluster-new"
    assert evidence["source"] == {"doc_id": "doc-1", "source_name": "test-source", "url": None}
    assert evidence["evidence"] == [{"text": "Xiaomi Group received a penalty."}]
    assert evidence["confidence"] == 0.95
    assert evidence["conflict_status"] == "possible"


def test_run_skill_query_maps_relationship_query_to_relationship_payload(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="RELATIONSHIP_QUERY")
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
    assert result["payload"]["related_entities"] == [raw_result["entities"][1]]
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
    assert result["payload"]["graph"] == raw_result["graph"]


def test_run_skill_query_keeps_relationship_contract_on_non_blocking_graph_errors(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="RELATIONSHIP_QUERY")
    raw_result["errors"] = ["[graph] neo4j unavailable"]
    raw_result["graph"]["used"] = False
    raw_result["graph"]["nodes"] = []
    raw_result["graph"]["edges"] = []
    raw_result["graph"]["paths"] = []
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi relationships")

    assert result["ok"] is True
    assert result["skill_type"] == "relationship_query"
    assert result["payload"]["relationship_paths"] == []
    assert result["errors"] == ["[graph] neo4j unavailable"]


def test_run_skill_query_returns_empty_relationship_matches_without_graph_paths(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="RELATIONSHIP_QUERY")
    raw_result["graph"]["paths"] = []
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi relationships")

    assert result["ok"] is True
    assert result["skill_type"] == "relationship_query"
    assert result["payload"]["relationship_paths"] == []
    assert result["payload"]["related_entities"] == []
    assert result["payload"]["related_event_clusters"] == []


def test_run_skill_query_returns_stable_failed_relationship_contract_for_direct_articles(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="RELATIONSHIP_QUERY", source="direct_articles")
    raw_result["retrieval"]["graph_used"] = False
    raw_result["graph"] = {
        "enabled": True,
        "used": False,
        "nodes": [],
        "edges": [],
        "paths": [],
        "summary": {},
    }
    raw_result["verification"] = {"passed": False, "retry_count": 0, "issues": []}
    raw_result["errors"] = ["关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入"]
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Show Xiaomi relationships", articles=[{"doc_id": "doc-1"}])

    assert result["ok"] is False
    assert result["skill_type"] == "relationship_query"
    assert result["source"] == "direct_articles"
    assert result["payload"]["related_entities"] == []
    assert result["payload"]["related_event_clusters"] == []
    assert result["payload"]["relationship_paths"] == []
    assert result["payload"]["graph"] == raw_result["graph"]
    assert len(result["payload"]["supporting_evidence"]) == 3
    assert result["errors"] == ["关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入"]
