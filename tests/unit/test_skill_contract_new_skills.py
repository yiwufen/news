from __future__ import annotations

from src.skills.service import run_skill_query


def _base_raw_result(*, intent: str) -> dict:
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
        "source": "knowledge_base",
        "retrieval": {
            "retrieval_mode": "hybrid",
            "bm25_count": 2,
            "vector_count": 2,
            "graph_used": True,
        },
        "graph": {
            "enabled": True,
            "used": True,
            "nodes": [],
            "edges": [],
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
            "summary": {},
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
        ],
        "entities": [
            {
                "entity_id": "ent-xiaomi",
                "entity_type": "Company",
                "canonical_name": "Xiaomi Group",
                "aliases": [],
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
                "conflict_reasons": [],
                "updated_at": "2026-04-03T09:00:00+00:00",
            },
        ],
        "timeline_data": {},
        "total_count": 6,
        "verification": {"passed": True, "retry_count": 0, "issues": []},
        "errors": [],
    }


def test_run_skill_query_maps_risk_assessment_to_risk_payload(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="RISK_ASSESSMENT")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Assess Xiaomi risk")

    assert result["ok"] is True
    assert result["skill_type"] == "risk_assessment"
    assert result["payload"]["target_entity"] == "Xiaomi Group"
    assert result["payload"]["target_entity_id"] == "ent-xiaomi"
    assert result["payload"]["total_risk_score"] == 0.8
    assert result["payload"]["risk_level"] == "CRITICAL"
    assert len(result["payload"]["risk_factors"]) == 2
    assert result["payload"]["risk_factors"][0]["factor_type"] == "POLICY_SANCTION"
    assert result["payload"]["risk_paths"][0]["source_entity_id"] == "ent-partner"


def test_run_skill_query_builds_guarantee_analysis_from_mainline_clusters(monkeypatch) -> None:
    raw_result = _base_raw_result(intent="GUARANTEE_ANALYSIS")
    raw_result["query"]["entities"] = ["A Holdings"]
    raw_result["entities"] = [
        {
            "entity_id": "ent-a",
            "entity_type": "Company",
            "canonical_name": "A Holdings",
            "aliases": [],
            "identifiers": {},
            "description": None,
            "tags": [],
            "source_ku_ids": ["ku-ab"],
            "created_at": "2026-04-01T09:00:00+00:00",
            "updated_at": "2026-04-01T09:00:00+00:00",
        },
        {
            "entity_id": "ent-b",
            "entity_type": "Company",
            "canonical_name": "B Holdings",
            "aliases": [],
            "identifiers": {},
            "description": None,
            "tags": [],
            "source_ku_ids": ["ku-bc"],
            "created_at": "2026-04-01T09:00:00+00:00",
            "updated_at": "2026-04-01T09:00:00+00:00",
        },
        {
            "entity_id": "ent-c",
            "entity_type": "Company",
            "canonical_name": "C Holdings",
            "aliases": [],
            "identifiers": {},
            "description": None,
            "tags": [],
            "source_ku_ids": ["ku-ca"],
            "created_at": "2026-04-01T09:00:00+00:00",
            "updated_at": "2026-04-01T09:00:00+00:00",
        },
    ]
    raw_result["knowledge_units"] = [
        {
            "ku_id": "ku-ab",
            "unit_kind": "event",
            "unit_type": "guarantee",
            "summary": "A guarantees B",
            "entities": [
                {"entity_id": "ent-a", "mention": "A Holdings"},
                {"entity_id": "ent-b", "mention": "B Holdings"},
            ],
            "source": {"doc_id": "doc-ab", "source_name": "test-source", "url": None},
            "evidence": [{"text": "A Holdings provides guarantee for B Holdings."}],
            "time": {
                "event_time": "2026-04-02T09:00:00+00:00",
                "published_at": "2026-04-02T09:00:00+00:00",
                "extracted_at": "2026-04-02T09:05:00+00:00",
            },
            "confidence": 0.9,
            "tags": [],
            "relation_hints": [],
            "cluster_id": "clu-ab",
            "conflict_status": "none",
            "status": "active",
        },
        {
            "ku_id": "ku-bc",
            "unit_kind": "event",
            "unit_type": "guarantee",
            "summary": "B guarantees C",
            "entities": [
                {"entity_id": "ent-b", "mention": "B Holdings"},
                {"entity_id": "ent-c", "mention": "C Holdings"},
            ],
            "source": {"doc_id": "doc-bc", "source_name": "test-source", "url": None},
            "evidence": [{"text": "B Holdings provides guarantee for C Holdings."}],
            "time": {
                "event_time": "2026-04-03T09:00:00+00:00",
                "published_at": "2026-04-03T09:00:00+00:00",
                "extracted_at": "2026-04-03T09:05:00+00:00",
            },
            "confidence": 0.9,
            "tags": [],
            "relation_hints": [],
            "cluster_id": "clu-bc",
            "conflict_status": "none",
            "status": "active",
        },
        {
            "ku_id": "ku-ca",
            "unit_kind": "event",
            "unit_type": "guarantee",
            "summary": "C guarantees A",
            "entities": [
                {"entity_id": "ent-c", "mention": "C Holdings"},
                {"entity_id": "ent-a", "mention": "A Holdings"},
            ],
            "source": {"doc_id": "doc-ca", "source_name": "test-source", "url": None},
            "evidence": [{"text": "C Holdings provides guarantee for A Holdings."}],
            "time": {
                "event_time": "2026-04-04T09:00:00+00:00",
                "published_at": "2026-04-04T09:00:00+00:00",
                "extracted_at": "2026-04-04T09:05:00+00:00",
            },
            "confidence": 0.9,
            "tags": [],
            "relation_hints": [],
            "cluster_id": "clu-ca",
            "conflict_status": "none",
            "status": "active",
        },
    ]
    raw_result["event_clusters"] = [
        {
            "cluster_id": "clu-ab",
            "cluster_type": "guarantee",
            "title": "A guarantees B",
            "summary": "A guarantees B",
            "entity_ids": ["ent-a", "ent-b"],
            "primary_entity_id": "ent-a",
            "time_anchor": "2026-04-02T09:00:00+00:00",
            "time_range": {"start": "2026-04-02T09:00:00+00:00", "end": "2026-04-02T10:00:00+00:00"},
            "member_ku_ids": ["ku-ab"],
            "source_doc_ids": ["doc-ab"],
            "conflict_status": "none",
            "cluster_confidence": 0.9,
            "representative_ku_id": "ku-ab",
            "member_count": 1,
            "source_count": 1,
            "summary_variants": [],
            "event_time_variants": [],
            "conflict_reasons": [],
            "updated_at": "2026-04-02T10:00:00+00:00",
        },
        {
            "cluster_id": "clu-bc",
            "cluster_type": "guarantee",
            "title": "B guarantees C",
            "summary": "B guarantees C",
            "entity_ids": ["ent-b", "ent-c"],
            "primary_entity_id": "ent-b",
            "time_anchor": "2026-04-03T09:00:00+00:00",
            "time_range": {"start": "2026-04-03T09:00:00+00:00", "end": "2026-04-03T10:00:00+00:00"},
            "member_ku_ids": ["ku-bc"],
            "source_doc_ids": ["doc-bc"],
            "conflict_status": "none",
            "cluster_confidence": 0.9,
            "representative_ku_id": "ku-bc",
            "member_count": 1,
            "source_count": 1,
            "summary_variants": [],
            "event_time_variants": [],
            "conflict_reasons": [],
            "updated_at": "2026-04-03T10:00:00+00:00",
        },
        {
            "cluster_id": "clu-ca",
            "cluster_type": "guarantee",
            "title": "C guarantees A",
            "summary": "C guarantees A",
            "entity_ids": ["ent-c", "ent-a"],
            "primary_entity_id": "ent-c",
            "time_anchor": "2026-04-04T09:00:00+00:00",
            "time_range": {"start": "2026-04-04T09:00:00+00:00", "end": "2026-04-04T10:00:00+00:00"},
            "member_ku_ids": ["ku-ca"],
            "source_doc_ids": ["doc-ca"],
            "conflict_status": "none",
            "cluster_confidence": 0.9,
            "representative_ku_id": "ku-ca",
            "member_count": 1,
            "source_count": 1,
            "summary_variants": [],
            "event_time_variants": [],
            "conflict_reasons": [],
            "updated_at": "2026-04-04T10:00:00+00:00",
        },
    ]
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Analyze A Holdings guarantee network")

    assert result["ok"] is True
    assert result["skill_type"] == "guarantee_analysis"
    assert len(result["payload"]["guarantee_edges"]) == 3
    assert result["payload"]["guarantee_edges"][0]["source_name"] == "A Holdings"
    pattern_types = {pattern["pattern_type"] for pattern in result["payload"]["detected_patterns"]}
    assert "circular_guarantee" in pattern_types
