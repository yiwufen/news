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
]

_ENTITIES = [
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
        "conflict_reasons": [],
        "updated_at": "2026-04-03T09:00:00+00:00",
    },
]

_GRAPH_PATHS = [
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


def _make_pipeline_result(
    *,
    intent: str,
    source: PipelineSource = "knowledge_base",
    knowledge_units: list[dict] | None = None,
    entities: list[dict] | None = None,
    event_clusters: list[dict] | None = None,
    query_entities: list[str] | None = None,
    query_filters: QueryFilters | None = None,
    graph_result: GraphRetrievalResult | None = None,
    graph_used: bool = True,
    total_count: int = 6,
) -> PipelineResult:
    """Build a PipelineResult for monkeypatching run_pipeline in tests."""
    effective_filters = query_filters or QueryFilters(event_types=["policy_sanction"])

    default_graph_result = GraphRetrievalResult(
        used=graph_used,
        nodes=[
            {"id": "ent-xiaomi", "type": "Entity", "name": "Xiaomi Group"},
            {"id": "clu-new", "type": "EventCluster", "name": "Newer Xiaomi cluster"},
            {"id": "ent-partner", "type": "Entity", "name": "Partner Co"},
        ],
        edges=[
            {"source": "ent-xiaomi", "target": "clu-new", "type": "INVOLVED_IN"},
            {"source": "ent-partner", "target": "clu-new", "type": "INVOLVED_IN"},
        ],
        paths=list(_GRAPH_PATHS),
        summary={},
    )

    return PipelineResult(
        request_id="req-1",
        query=StructuredQuery(
            intent=IntentType(intent),
            entities=query_entities or ["Xiaomi Group"],
            time_range=TimeRange(
                start=date(2026, 3, 1),
                end=date(2026, 4, 5),
            ),
            filters=effective_filters,
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
            graph_used=graph_used,
        ),
        graph_result=graph_result if graph_result is not None else default_graph_result,
        errors=[],
    )


def test_run_skill_query_maps_risk_assessment_to_risk_payload(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="RISK_ASSESSMENT")
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
    guarantee_entities = [
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
    guarantee_units = [
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
    guarantee_clusters = [
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
    raw_result = _make_pipeline_result(
        intent="GUARANTEE_ANALYSIS",
        query_entities=["A Holdings"],
        entities=guarantee_entities,
        knowledge_units=guarantee_units,
        event_clusters=guarantee_clusters,
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="Analyze A Holdings guarantee network")

    assert result["ok"] is True
    assert result["skill_type"] == "guarantee_analysis"
    assert len(result["payload"]["guarantee_edges"]) == 3
    assert result["payload"]["guarantee_edges"][0]["source_name"] == "A Holdings"
    pattern_types = {pattern["pattern_type"] for pattern in result["payload"]["detected_patterns"]}
    assert "circular_guarantee" in pattern_types


def test_run_skill_query_maps_topic_research_to_topic_payload(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="TOPIC_RESEARCH",
        query_filters=QueryFilters(event_types=["policy_sanction"], categories=["新能源", "光伏"]),
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="分析新能源行业的发展趋势")

    assert result["ok"] is True
    assert result["skill_type"] == "topic_research"
    assert result["payload"]["topic_keywords"] == ["新能源", "光伏"]
    assert len(result["payload"]["related_event_clusters"]) == 2
    assert len(result["payload"]["trend_timeline"]) >= 1
    assert result["payload"]["event_type_distribution"]["policy_sanction"] == 2
    assert len(result["payload"]["key_milestones"]) >= 1


def test_run_skill_query_maps_event_impact_analysis_to_impact_payload(monkeypatch) -> None:
    raw_result = _make_pipeline_result(intent="EVENT_IMPACT_ANALYSIS")
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="分析小米集团事件的影响")

    assert result["ok"] is True
    assert result["skill_type"] == "event_impact_analysis"
    assert result["payload"]["focus_event_cluster_id"] == "clu-new"
    assert result["payload"]["focus_event_type"] == "policy_sanction"
    assert len(result["payload"]["directly_affected_entities"]) == 2
    assert result["payload"]["directly_affected_entities"][0]["impact_level"] == "CRITICAL"
    assert result["payload"]["directly_affected_entities"][0]["entity_id"] == "ent-xiaomi"
    # impact_paths may be empty if neighbor entities are in the focus cluster
    assert result["payload"]["total_affected_entities"] >= 2
    assert "focus_event" in result["payload"]["impact_summary"]


def test_run_skill_query_event_impact_analysis_empty_clusters(monkeypatch) -> None:
    raw_result = _make_pipeline_result(
        intent="EVENT_IMPACT_ANALYSIS",
        event_clusters=[],
        knowledge_units=[],
        entities=[],
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="分析事件影响")

    assert result["ok"] is True
    assert result["skill_type"] == "event_impact_analysis"
    assert result["payload"]["focus_event_cluster_id"] is None
    assert result["payload"]["directly_affected_entities"] == []
    assert result["payload"]["indirectly_affected_entities"] == []


def test_run_skill_query_event_impact_analysis_with_indirect_impact(monkeypatch) -> None:
    """Test event impact analysis with indirect impact paths."""
    extra_entity = {
        "entity_id": "ent-supplier",
        "entity_type": "Company",
        "canonical_name": "Supplier Co",
        "aliases": [],
        "identifiers": {},
        "description": None,
        "tags": [],
        "source_ku_ids": ["ku-supplier"],
        "created_at": "2026-04-02T09:00:00+00:00",
        "updated_at": "2026-04-02T09:00:00+00:00",
    }
    extra_path = {
        "path_type": "Entity->EventCluster->Entity",
        "start_entity_id": "ent-xiaomi",
        "start_entity_name": "Xiaomi Group",
        "cluster_id": "clu-supplier",
        "cluster_title": "Supplier relationship",
        "cluster_type": "supply_chain",
        "neighbor_entity_id": "ent-supplier",
        "neighbor_entity_name": "Supplier Co",
        "member_ku_ids": ["ku-supplier"],
    }
    raw_result = _make_pipeline_result(
        intent="EVENT_IMPACT_ANALYSIS",
        entities=[*_ENTITIES, extra_entity],
        graph_result=GraphRetrievalResult(
            used=True,
            nodes=[
                {"id": "ent-xiaomi", "type": "Entity", "name": "Xiaomi Group"},
                {"id": "clu-new", "type": "EventCluster", "name": "Newer Xiaomi cluster"},
                {"id": "ent-partner", "type": "Entity", "name": "Partner Co"},
                {"id": "clu-supplier", "type": "EventCluster", "name": "Supplier relationship"},
                {"id": "ent-supplier", "type": "Entity", "name": "Supplier Co"},
            ],
            edges=[
                {"source": "ent-xiaomi", "target": "clu-new", "type": "INVOLVED_IN"},
                {"source": "ent-partner", "target": "clu-new", "type": "INVOLVED_IN"},
                {"source": "ent-xiaomi", "target": "clu-supplier", "type": "INVOLVED_IN"},
                {"source": "ent-supplier", "target": "clu-supplier", "type": "INVOLVED_IN"},
            ],
            paths=[*_GRAPH_PATHS, extra_path],
            summary={},
        ),
    )
    monkeypatch.setattr("src.skills.service.run_pipeline", lambda **_: raw_result)

    result = run_skill_query(raw_query="分析小米集团事件的影响")

    assert result["ok"] is True
    assert result["skill_type"] == "event_impact_analysis"
    assert result["payload"]["focus_event_cluster_id"] == "clu-new"
    # Direct affected: ent-xiaomi, ent-partner
    assert len(result["payload"]["directly_affected_entities"]) == 2
    # Indirect affected: ent-supplier
    assert len(result["payload"]["indirectly_affected_entities"]) == 1
    assert result["payload"]["indirectly_affected_entities"][0]["entity_id"] == "ent-supplier"
    assert result["payload"]["indirectly_affected_entities"][0]["impact_level"] == "MEDIUM"
    # Impact path from xiaomi to supplier
    assert len(result["payload"]["impact_paths"]) >= 1
    assert result["payload"]["total_affected_entities"] == 3
