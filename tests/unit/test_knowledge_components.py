"""
Knowledge pipeline component tests.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from anthropic.types import ToolUseBlock

from src.entities import Entity, EntityRepository, EntityResolver
from src.event_merging import (
    EventCluster,
    EventClusterRepository,
    EventMerger,
    build_event_cluster_snapshot,
)
from src.graph.knowledge_retrieval import KnowledgeGraphRetriever
from src.schemas.query import IntentType, QueryFilters, StructuredQuery, TimeRange
from src.knowledge_base import (
    EntityRef,
    EvidenceSpan,
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocument,
    RelationHint,
    SourceRef,
    TimeRef,
    adapt_article_to_raw_document,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.knowledge_graph_sync import KnowledgeGraphSync
from src.retrieval.knowledge_search import KnowledgeSearchRequest, KnowledgeSearcher
from src.time_normalization import TimeNormalizationResult


def build_unit(
    *,
    mention: str = "Xiaomi Group",
    unit_type: str = "investment",
    summary: str = "Xiaomi Group announced an investment update",
    doc_id: str = "doc-1",
    published_at: datetime | None = None,
) -> KnowledgeUnit:
    published_at = published_at or datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    return KnowledgeUnit(
        unit_kind="event",
        unit_type=unit_type,
        summary=summary,
        entities=[EntityRef(mention=mention)],
        source=SourceRef(doc_id=doc_id, source_name="test-source"),
        evidence=[EvidenceSpan(text="Xiaomi Group announced an investment update today.")],
        time=TimeRef(
            event_time=published_at,
            published_at=published_at,
            extracted_at=published_at + timedelta(minutes=5),
        ),
        confidence=0.86,
    )


def test_adapt_article_to_raw_document_maps_fields() -> None:
    article = {
        "doc_id": "doc-1",
        "title": "Xiaomi launches a new phone",
        "content": "Xiaomi launched a new phone today.",
        "publish_time": "2026-04-01T09:00:00+00:00",
        "source_name": "test-source",
        "source_type": "news",
        "created_at": "2026-04-01T09:05:00+00:00",
    }

    doc = adapt_article_to_raw_document(article)

    assert doc.doc_id == "doc-1"
    assert doc.title == "Xiaomi launches a new phone"
    assert doc.source_name == "test-source"
    assert doc.published_at.isoformat() == "2026-04-01T09:00:00+00:00"
    assert doc.ingested_at.isoformat() == "2026-04-01T09:05:00+00:00"
    assert doc.language == "zh"
    assert doc.raw_metadata == {}


def test_knowledge_unit_requires_evidence() -> None:
    published_at = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    with pytest.raises(ValueError):
        KnowledgeUnit(
            unit_kind="event",
            unit_type="investment",
            summary="Xiaomi Group announced an investment update",
            entities=[EntityRef(mention="Xiaomi Group")],
            source=SourceRef(doc_id="doc-1", source_name="test-source"),
            evidence=[],
            time=TimeRef(
                event_time=published_at,
                published_at=published_at,
                extracted_at=published_at,
            ),
        )


def test_knowledge_unit_generates_stable_id_for_same_statement() -> None:
    unit_a = build_unit()
    unit_b = build_unit()
    unit_c = build_unit(summary="Xiaomi Group announced a different update")

    assert unit_a.ku_id == unit_b.ku_id
    assert unit_c.ku_id != unit_a.ku_id


def test_knowledge_extractor_requires_llm_when_fallback_removed() -> None:
    extractor = KnowledgeExtractor(enable_llm=False)
    document = RawDocument(
        doc_id="doc-1",
        source_type="news",
        title="Xiaomi launches a new phone",
        content="Xiaomi launched a new phone today.",
        source_name="test-source",
        published_at=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 4, 1, 9, 5, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="heuristic extraction has been removed"):
        extractor.extract(document)


def test_knowledge_extractor_normalizes_relative_event_time_before_validation() -> None:
    extractor = KnowledgeExtractor(enable_llm=True)
    extractor_any = cast(Any, extractor)
    extractor_any._time_normalizer = SimpleNamespace(
        normalize_event_time=lambda raw_time, context, **kw: TimeNormalizationResult(
            normalized_time=datetime(2026, 4, 4, 0, 0, tzinfo=UTC),
            resolution_type="contextual",
            time_grain="day",
        )
    )
    extractor_any.client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_: SimpleNamespace(
                content=[
                    ToolUseBlock(
                        id="toolu_test",
                        type="tool_use",
                        name="extract_knowledge_units",
                        input={
                            "knowledge_units": [
                                {
                                    "unit_kind": "event",
                                    "unit_type": "product_launch",
                                    "summary": "Xiaomi scheduled a product launch",
                                    "entities": [{"mention": "Xiaomi Group"}],
                                    "source": {
                                        "doc_id": "doc-1",
                                        "source_name": "test-source",
                                    },
                                    "evidence": [{"text": "Xiaomi will launch the product tomorrow."}],
                                    "time": {
                                        "event_time": "2026-04-04T00:00:00Z",
                                        "published_at": "2026-04-05T09:00:00+00:00",
                                        "extracted_at": "2026-04-05T09:05:00+00:00",
                                        "event_time_resolution": "contextual",
                                        "time_grain": "day",
                                    },
                                    "confidence": 0.8,
                                }
                            ]
                        },
                    )
                ]
            )
        )
    )
    extractor_any.model = "test-model"
    document = RawDocument(
        doc_id="doc-1",
        source_type="news",
        title="Xiaomi launches a new phone",
        content="Xiaomi launched a new phone yesterday.",
        source_name="test-source",
        published_at=datetime(2026, 4, 5, 9, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 4, 5, 9, 5, tzinfo=UTC),
    )

    units = extractor.extract(document)

    assert len(units) == 1
    assert units[0].time.event_time == datetime(2026, 4, 4, 0, 0, tzinfo=UTC)
    assert units[0].time.event_time_resolution == "contextual"
    assert units[0].time.time_grain == "day"


def test_knowledge_extractor_falls_back_to_published_at_for_future_event_time() -> None:
    """A future event_time (forecast target year) must fall back to published_at.

    The LLM extracted ``2030-01-01`` as event_time for a prediction statement.
    ``TimeNormalizer`` hard-clamps it to None; ``KnowledgeExtractor`` then
    resets event_time to the document's published_at so the KU keeps a valid
    temporal anchor.
    """
    extractor = KnowledgeExtractor(enable_llm=True)
    extractor_any = cast(Any, extractor)
    # Real TimeNormalizer — we want the actual clamp behavior to be exercised.
    extractor_any.client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_: SimpleNamespace(
                content=[
                    ToolUseBlock(
                        id="toolu_test",
                        type="tool_use",
                        name="extract_knowledge_units",
                        input={
                            "knowledge_units": [
                                {
                                    "unit_kind": "event",
                                    "unit_type": "market_analysis",
                                    "summary": "美银预计到2030年半导体市场规模达2万亿美元",
                                    "entities": [{"mention": "美银"}],
                                    "source": {
                                        "doc_id": "doc-future",
                                        "source_name": "test-source",
                                    },
                                    "evidence": [{"text": "美银预计到2030年半导体市场规模达2万亿美元。"}],
                                    "time": {
                                        "event_time": "2030-12-31T00:00:00Z",
                                        "published_at": "2026-04-05T09:00:00+00:00",
                                        "extracted_at": "2026-04-05T09:05:00+00:00",
                                        "event_time_resolution": "explicit",
                                        "time_grain": "year",
                                    },
                                    "confidence": 0.8,
                                }
                            ]
                        },
                    )
                ]
            )
        )
    )
    extractor_any.model = "test-model"
    document = RawDocument(
        doc_id="doc-future",
        source_type="news",
        title="半导体市场预测",
        content="美银预计到2030年半导体市场规模达2万亿美元。",
        source_name="test-source",
        published_at=datetime(2026, 4, 5, 9, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 4, 5, 9, 5, tzinfo=UTC),
    )

    units = extractor.extract(document)

    assert len(units) == 1
    # event_time was reset to published_at (not the forecast target year).
    assert units[0].time.event_time == datetime(2026, 4, 5, 9, 0, tzinfo=UTC)
    assert units[0].time.event_time_resolution == "contextual"
    # time_grain is preserved from the original extraction.
    assert units[0].time.time_grain == "year"


def test_knowledge_extractor_overwrites_system_time_fields_from_llm() -> None:
    """published_at and extracted_at must come from the pipeline, not the LLM.

    The LLM historically hallucinated these (e.g. extracted_at=2025-01-18 for a
    2026-06 article), which broke TimeNormalizer's future-check baseline.
    The extractor must overwrite them unconditionally with system-owned values.
    """
    extractor = KnowledgeExtractor(enable_llm=True)
    extractor_any = cast(Any, extractor)
    extractor_any.client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_: SimpleNamespace(
                content=[
                    ToolUseBlock(
                        id="toolu_test",
                        type="tool_use",
                        name="extract_knowledge_units",
                        input={
                            "knowledge_units": [
                                {
                                    "unit_kind": "event",
                                    "unit_type": "product_launch",
                                    "summary": "Xiaomi launched a product",
                                    "entities": [{"mention": "Xiaomi Group"}],
                                    "source": {
                                        "doc_id": "doc-systime",
                                        "source_name": "test-source",
                                    },
                                    "evidence": [{"text": "Xiaomi launched a product."}],
                                    "time": {
                                        "event_time": "2026-04-05T09:00:00Z",
                                        # LLM hallucinates these — must be overwritten:
                                        "published_at": "2099-01-01T00:00:00Z",
                                        "extracted_at": "2025-01-18T00:00:00Z",
                                    },
                                    "confidence": 0.8,
                                }
                            ]
                        },
                    )
                ]
            )
        )
    )
    extractor_any.model = "test-model"
    document = RawDocument(
        doc_id="doc-systime",
        source_type="news",
        title="Xiaomi launch",
        content="Xiaomi launched a product.",
        source_name="test-source",
        published_at=datetime(2026, 4, 5, 9, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 4, 5, 9, 5, tzinfo=UTC),
    )

    units = extractor.extract(document)

    assert len(units) == 1
    # System-owned values overwrite LLM hallucinations.
    assert units[0].time.published_at == datetime(2026, 4, 5, 9, 0, tzinfo=UTC)
    # extracted_at is the pipeline run time (now), NOT 2025-01-18.
    assert units[0].time.extracted_at != datetime(2025, 1, 18, tzinfo=UTC)
    assert units[0].time.extracted_at > datetime(2026, 4, 5, 9, 0, tzinfo=UTC)


def test_entity_resolver_matches_stable_identifier_and_keeps_uncertain_separate(tmp_path) -> None:
    db_path = tmp_path / "entities.db"
    repo = EntityRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    existing = Entity(
        entity_type="Company",
        canonical_name="Xiaomi Group Ltd.",
        aliases=["Xiaomi Group"],
        identifiers={"ticker": "1810.HK"},
        source_ku_ids=["seed"],
        created_at=now,
        updated_at=now,
    )
    repo.save_batch([existing])

    resolver = EntityResolver(repo)
    matched_unit = build_unit()
    matched_unit.entities[0].identifiers = {"ticker": "1810.HK"}

    separate_unit = build_unit(
        mention="Beijing Regulator",
        summary="Beijing Regulator issued a new compliance notice",
        doc_id="doc-2",
    )

    resolved_units, resolved_entities = resolver.resolve_units([matched_unit, separate_unit], persist=True)

    assert resolved_units[0].entities[0].entity_id == existing.entity_id
    assert resolved_units[1].entities[0].entity_id != existing.entity_id
    assert len(resolved_entities) == 2


def test_event_clusterer_merges_only_when_all_conditions_match(tmp_path) -> None:
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))
    clusterer = EventMerger(repo)

    unit_a = build_unit(summary="Xiaomi Group announced an investment update")
    unit_a.entities[0].entity_id = "ent_xiaomi"
    unit_a.entities[0].entity_type = "Company"

    unit_b = build_unit(summary="Xiaomi Group announced an investment update", doc_id="doc-2")
    unit_b.entities[0].entity_id = "ent_xiaomi"
    unit_b.entities[0].entity_type = "Company"

    unit_c = build_unit(
        summary="Xiaomi Group disclosed a lawsuit update",
        unit_type="lawsuit",
        doc_id="doc-3",
        published_at=datetime(2026, 4, 3, 10, 0, tzinfo=UTC),
    )
    unit_c.entities[0].entity_id = "ent_xiaomi"
    unit_c.entities[0].entity_type = "Company"

    clustered_units, clusters = clusterer.assign_clusters([unit_a, unit_b, unit_c], persist=True)

    assert clustered_units[0].cluster_id == clustered_units[1].cluster_id
    assert clustered_units[2].cluster_id != clustered_units[0].cluster_id
    assert len(clusters) == 2
    primary_cluster = next(
        cluster for cluster in clusters if cluster.cluster_id == clustered_units[0].cluster_id
    )
    assert primary_cluster.member_count == 2
    assert primary_cluster.source_count == 2
    assert primary_cluster.summary_variants[0].count == 2
    assert primary_cluster.representative_ku_id in primary_cluster.member_ku_ids


def test_event_clusterer_prefers_majority_summary_variant_for_representative(tmp_path) -> None:
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))
    clusterer = EventMerger(repo)

    unit_a = build_unit(
        summary="Xiaomi Group announced an investment plan",
        doc_id="doc-1",
    )
    unit_a.entities[0].entity_id = "ent_xiaomi"
    unit_a.entities[0].entity_type = "Company"
    unit_a.confidence = 0.72

    unit_b = build_unit(
        summary="Xiaomi Group announced an investment plan",
        doc_id="doc-2",
    )
    unit_b.entities[0].entity_id = "ent_xiaomi"
    unit_b.entities[0].entity_type = "Company"
    unit_b.confidence = 0.74

    unit_c = build_unit(
        summary="Xiaomi Group announced investment plan",
        doc_id="doc-3",
    )
    unit_c.entities[0].entity_id = "ent_xiaomi"
    unit_c.entities[0].entity_type = "Company"
    unit_c.confidence = 0.99

    _, clusters = clusterer.assign_clusters([unit_a, unit_b, unit_c], persist=False)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.summary == "Xiaomi Group announced an investment plan"
    assert cluster.title == "Xiaomi Group announced an investment plan"
    assert cluster.member_count == 3
    assert cluster.source_count == 3
    assert [variant.count for variant in cluster.summary_variants] == [2, 1]
    assert cluster.representative_ku_id in {unit_a.ku_id, unit_b.ku_id}


def test_event_clusterer_marks_adjacent_event_dates_as_possible_conflict(tmp_path) -> None:
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))
    clusterer = EventMerger(repo)

    unit_a = build_unit(
        summary="Xiaomi Group announced a product launch schedule",
        doc_id="doc-1",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_a.entities[0].entity_id = "ent_xiaomi"
    unit_a.entities[0].entity_type = "Company"

    unit_b = build_unit(
        summary="Xiaomi Group announced a product launch schedule",
        doc_id="doc-2",
        published_at=datetime(2026, 4, 2, 9, 0, tzinfo=UTC),
    )
    unit_b.entities[0].entity_id = "ent_xiaomi"
    unit_b.entities[0].entity_type = "Company"

    _, clusters = clusterer.assign_clusters([unit_a, unit_b], persist=False)

    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.conflict_status == "possible"
    assert cluster.conflict_reasons == ["multiple_event_time_values"]
    assert [variant.value for variant in cluster.event_time_variants] == ["2026-04-01", "2026-04-02"]


def test_event_cluster_snapshot_ignores_published_at_without_explicit_event_times() -> None:
    unit_a = build_unit(
        summary="Xiaomi Group announced a product launch schedule",
        doc_id="doc-1",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_b = build_unit(
        summary="Xiaomi Group announced a product launch schedule",
        doc_id="doc-2",
        published_at=datetime(2026, 4, 3, 10, 0, tzinfo=UTC),
    )
    for unit in (unit_a, unit_b):
        unit.entities[0].entity_id = "ent_xiaomi"
        unit.entities[0].entity_type = "Company"
        unit.time.event_time = None

    cluster = build_event_cluster_snapshot([unit_a, unit_b])

    assert cluster.conflict_status == "none"
    assert cluster.conflict_reasons == []
    assert cluster.event_time_variants == []


def test_event_cluster_snapshot_ignores_additive_participant_mentions() -> None:
    published_at = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    unit_a = build_unit(
        summary="Xiaomi Group received a regulatory penalty",
        doc_id="doc-1",
        published_at=published_at,
    )
    unit_b = build_unit(
        summary="Xiaomi Group received a regulatory penalty",
        doc_id="doc-2",
        published_at=published_at,
    )
    unit_a.entities = [
        EntityRef(
            mention="Xiaomi Group",
            entity_id="ent_xiaomi",
            entity_type="Company",
        )
    ]
    unit_b.entities = [
        EntityRef(
            mention="Xiaomi Group",
            entity_id="ent_xiaomi",
            entity_type="Company",
        ),
        EntityRef(mention="Beijing Regulator"),
    ]

    cluster = build_event_cluster_snapshot([unit_a, unit_b])

    assert cluster.conflict_status == "none"
    assert "participant_mismatch:entities" not in cluster.conflict_reasons
    assert cluster.conflict_details == []


def test_event_clusterer_merges_adjacent_high_similarity_but_keeps_distant_events_separate(tmp_path) -> None:
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))
    clusterer = EventMerger(repo)

    unit_a = build_unit(
        summary="Xiaomi Group announced a chip investment plan",
        doc_id="doc-1",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_b = build_unit(
        summary="Xiaomi Group announced chip investment plan",
        doc_id="doc-2",
        published_at=datetime(2026, 4, 2, 10, 0, tzinfo=UTC),
    )
    unit_c = build_unit(
        summary="Xiaomi Group announced a chip investment plan",
        doc_id="doc-3",
        published_at=datetime(2026, 4, 8, 10, 0, tzinfo=UTC),
    )
    for unit in (unit_a, unit_b, unit_c):
        unit.entities[0].entity_id = "ent_xiaomi"
        unit.entities[0].entity_type = "Company"

    clustered_units, clusters = clusterer.assign_clusters([unit_a, unit_b, unit_c], persist=False)

    assert clustered_units[0].cluster_id == clustered_units[1].cluster_id
    assert clustered_units[2].cluster_id != clustered_units[0].cluster_id
    assert len(clusters) == 2


def test_event_clusterer_merges_across_a_contiguous_adjacent_day_window(tmp_path) -> None:
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))
    clusterer = EventMerger(repo)

    units = [
        build_unit(
            summary="Xiaomi Group announced a product launch schedule",
            doc_id="doc-1",
            published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        ),
        build_unit(
            summary="Xiaomi Group announced a product launch schedule",
            doc_id="doc-2",
            published_at=datetime(2026, 4, 2, 10, 0, tzinfo=UTC),
        ),
        build_unit(
            summary="Xiaomi Group announced a product launch schedule",
            doc_id="doc-3",
            published_at=datetime(2026, 4, 3, 10, 0, tzinfo=UTC),
        ),
    ]
    for unit in units:
        unit.entities[0].entity_id = "ent_xiaomi"
        unit.entities[0].entity_type = "Company"

    clustered_units, clusters = clusterer.assign_clusters(units, persist=False)

    assert len(clusters) == 1
    assert len({unit.cluster_id for unit in clustered_units}) == 1
    assert clusters[0].member_count == 3
    assert clusters[0].time_range == {
        "start": "2026-04-01T10:00:00+00:00",
        "end": "2026-04-03T10:00:00+00:00",
    }


def test_event_cluster_repository_repairs_legacy_payload_with_aggregated_fields(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    knowledge_repo = KnowledgeUnitRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path), knowledge_units=knowledge_repo)
    clusterer = EventMerger(cluster_repo, knowledge_units=knowledge_repo)

    unit_a = build_unit(summary="Xiaomi Group announced an investment update", doc_id="doc-1")
    unit_b = build_unit(summary="Xiaomi Group announced an investment update", doc_id="doc-2")
    for unit in (unit_a, unit_b):
        unit.entities[0].entity_id = "ent_xiaomi"
        unit.entities[0].entity_type = "Company"
    knowledge_repo.save_batch([unit_a, unit_b])
    _, clusters = clusterer.assign_clusters([unit_a, unit_b], persist=True)
    cluster = clusters[0]

    legacy_payload = cluster.model_dump(mode="json")
    for key in (
        "representative_ku_id",
        "member_count",
        "source_count",
        "summary_variants",
        "event_time_variants",
        "conflict_reasons",
    ):
        legacy_payload.pop(key, None)

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "UPDATE event_clusters SET payload = ?, updated_at = ? WHERE cluster_id = ?",
            (
                json.dumps(legacy_payload, ensure_ascii=False),
                cluster.updated_at.isoformat(),
                cluster.cluster_id,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    repaired_cluster = cluster_repo.get_by_ids([cluster.cluster_id])[0]

    assert repaired_cluster.member_count == 2
    assert repaired_cluster.source_count == 2
    assert repaired_cluster.representative_ku_id in repaired_cluster.member_ku_ids
    assert repaired_cluster.summary_variants[0].count == 2

    connection = sqlite3.connect(db_path)
    try:
        repaired_payload = json.loads(
            connection.execute(
                "SELECT payload FROM event_clusters WHERE cluster_id = ?",
                (cluster.cluster_id,),
            ).fetchone()[0]
        )
    finally:
        connection.close()

    assert repaired_payload["member_count"] == 2
    assert repaired_payload["source_count"] == 2


def test_event_cluster_repository_filters_by_time_range_overlap(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    knowledge_repo = KnowledgeUnitRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path), knowledge_units=knowledge_repo)
    clusterer = EventMerger(cluster_repo, knowledge_units=knowledge_repo)

    unit_a = build_unit(
        summary="Xiaomi Group announced a product launch schedule",
        doc_id="doc-1",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_b = build_unit(
        summary="Xiaomi Group announced a product launch schedule",
        doc_id="doc-2",
        published_at=datetime(2026, 4, 2, 9, 0, tzinfo=UTC),
    )
    for unit in (unit_a, unit_b):
        unit.entities[0].entity_id = "ent_xiaomi"
        unit.entities[0].entity_type = "Company"

    knowledge_repo.save_batch([unit_a, unit_b])
    _, clusters = clusterer.assign_clusters([unit_a, unit_b], persist=True)

    same_day = cluster_repo.find_related(
        primary_entity_ids=["ent_xiaomi"],
        time_range=("2026-04-01", "2026-04-01"),
    )
    next_day = cluster_repo.find_related(
        primary_entity_ids=["ent_xiaomi"],
        time_range=("2026-04-02", "2026-04-02"),
    )

    assert [cluster.cluster_id for cluster in same_day] == [clusters[0].cluster_id]
    assert [cluster.cluster_id for cluster in next_day] == [clusters[0].cluster_id]


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((query, params))
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, session: FakeSession | FakeResultSession) -> None:
        self._session = session

    def session(self):
        return self._session


class FakeResultSession:
    def __init__(self, records: list[dict] | None = None, error: Exception | None = None) -> None:
        self.records = records or []
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((query, params))
        if self.error is not None:
            raise self.error
        # Check for both old and new Cypher patterns
        if "MATCH (start:Entity)-[:INVOLVED_IN]->(cluster:EventCluster)" in query:
            return self.records
        # multi-hop: edge variable may be named (rels:) or unnamed (:);
        # match on the invariant part of the path pattern.
        if (
            "MATCH path = (start:Entity)-[" in query
            and ":INVOLVED_IN*1.." in query
        ):
            return self.records
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_knowledge_graph_sync_emits_entity_cluster_and_edge_queries() -> None:
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="Xiaomi Group",
        aliases=["Xiaomi"],
        identifiers={},
        source_ku_ids=["ku_1"],
        created_at=now,
        updated_at=now,
    )

    cluster = EventCluster(
        cluster_id="clu_1",
        cluster_type="investment",
        title="Xiaomi Group announced an investment update",
        summary="Xiaomi Group announced an investment update",
        entity_ids=["ent_xiaomi"],
        primary_entity_id="ent_xiaomi",
        time_anchor=now,
        time_range=None,
        member_ku_ids=["ku_1"],
        source_doc_ids=["doc-1"],
        updated_at=now,
    )

    stats = graph_sync.sync([entity], [cluster])

    assert stats["entities_created"] == 1
    assert stats["clusters_created"] == 1
    assert stats["edges_created"] == 1
    queries = "\n".join(call[0] for call in session.calls)
    assert "MERGE (e:Entity {id: $id})" in queries
    assert "MERGE (c:EventCluster {id: $id})" in queries
    assert "MERGE (e)-[r:INVOLVED_IN]->(c)" in queries
    entity_write = next(params for query, params in session.calls if "MERGE (e:Entity {id: $id})" in query)
    cluster_write = next(params for query, params in session.calls if "MERGE (c:EventCluster {id: $id})" in query)
    assert entity_write["primary_identifier"] is None
    assert entity_write["identifiers_json"] == "{}"
    assert cluster_write["representative_ku_id"] is None
    assert cluster_write["member_count"] == 0
    assert cluster_write["source_count"] == 0
    assert cluster_write["time_range_json"] == "null"
    assert cluster_write["summary_variants_json"] == "[]"
    assert cluster_write["event_time_variants_json"] == "[]"
    assert cluster_write["conflict_reasons"] == []


def test_knowledge_graph_sync_writes_edge_role_scope_nature() -> None:
    """INVOLVED_IN edges must carry role/scope/nature for multi-hop pruning.

    role: primary entity → subject, other participants → object.
    scope: Company/Product → corporate, else environment.
    nature: reaction cluster_types → reaction, else action.
    """
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    company = Entity(
        entity_id="ent_xiaomi", entity_type="Company", canonical_name="Xiaomi",
        aliases=[], identifiers={}, source_ku_ids=["ku_1"],
        created_at=now, updated_at=now,
    )
    org = Entity(
        entity_id="ent_csrc", entity_type="Organization", canonical_name="CSRC",
        aliases=[], identifiers={}, source_ku_ids=["ku_1"],
        created_at=now, updated_at=now,
    )
    # investment cluster: nature=action; primary=ent_xiaomi (subject),
    # ent_csrc is a non-primary participant (object, environment scope).
    cluster = EventCluster(
        cluster_id="clu_1", cluster_type="investment",
        title="Xiaomi investment", summary="Xiaomi investment",
        entity_ids=["ent_xiaomi", "ent_csrc"],
        primary_entity_id="ent_xiaomi",
        time_anchor=now, time_range=None,
        member_ku_ids=["ku_1"], source_doc_ids=["doc-1"], updated_at=now,
    )
    # reaction cluster: nature=reaction.
    reaction_cluster = EventCluster(
        cluster_id="clu_2", cluster_type="stock_price_change",
        title="Xiaomi stock up", summary="Xiaomi stock up",
        entity_ids=["ent_xiaomi"],
        primary_entity_id="ent_xiaomi",
        time_anchor=now, time_range=None,
        member_ku_ids=["ku_2"], source_doc_ids=["doc-2"], updated_at=now,
    )

    graph_sync.sync([company, org], [cluster, reaction_cluster])

    # Collect INVOLVED_IN edge writes keyed by (entity_id, cluster_id) — an
    # entity appears once per cluster, and nature is per-edge (same entity in
    # an action cluster vs a reaction cluster gets different nature).
    edge_writes = {
        (params["entity_id"], params["cluster_id"]): params
        for query, params in session.calls
        if "MERGE (e)-[r:INVOLVED_IN]->(c)" in query
    }
    # primary Company in the action (investment) cluster
    primary = edge_writes[("ent_xiaomi", "clu_1")]
    assert primary["role"] == "subject"
    assert primary["scope"] == "corporate"
    assert primary["nature"] == "action"
    # non-primary Organization participant in the action cluster
    participant = edge_writes[("ent_csrc", "clu_1")]
    assert participant["role"] == "object"
    assert participant["scope"] == "environment"
    assert participant["nature"] == "action"
    # same primary entity in the reaction (stock_price_change) cluster
    reaction = edge_writes[("ent_xiaomi", "clu_2")]
    assert reaction["role"] == "subject"
    assert reaction["scope"] == "corporate"
    assert reaction["nature"] == "reaction"


def test_knowledge_graph_sync_missing_entity_falls_back_to_environment() -> None:
    """admin path may pass a partial entity list; a participant whose Entity
    object isn't passed must still get an edge (scope→environment fallback)."""
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    # Only pass the primary entity; cluster references a second id not in list.
    company = Entity(
        entity_id="ent_xiaomi", entity_type="Company", canonical_name="Xiaomi",
        aliases=[], identifiers={}, source_ku_ids=["ku_1"],
        created_at=now, updated_at=now,
    )
    cluster = EventCluster(
        cluster_id="clu_1", cluster_type="investment",
        title="t", summary="s",
        entity_ids=["ent_xiaomi", "ent_missing"],
        primary_entity_id="ent_xiaomi",
        time_anchor=now, time_range=None,
        member_ku_ids=["ku_1"], source_doc_ids=["doc-1"], updated_at=now,
    )
    graph_sync.sync([company], [cluster])
    edge_writes = {
        params["entity_id"]: params
        for query, params in session.calls
        if "MERGE (e)-[r:INVOLVED_IN]->(c)" in query
    }
    # ent_missing has no Entity passed → scope falls back to environment,
    # role is object (not primary), nature from cluster_type.
    missing = edge_writes["ent_missing"]
    assert missing["scope"] == "environment"
    assert missing["role"] == "object"


def _ku_with_hints(
    ku_id: str, hints: list[RelationHint], published_at: datetime | None = None
) -> KnowledgeUnit:
    """Minimal KU carrying relation_hints for direct-edge sync tests."""
    published_at = published_at or datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    return KnowledgeUnit(
        ku_id=ku_id,
        unit_kind="event",
        unit_type="investment",
        summary="relation hint test",
        entities=[],
        source=SourceRef(doc_id="doc-1", source_name="test"),
        evidence=[EvidenceSpan(text="relation hint test")],
        time=TimeRef(
            event_time=published_at,
            published_at=published_at,
            extracted_at=published_at,
        ),
        relation_hints=hints,
    )


def test_knowledge_graph_sync_writes_direct_edges_from_relation_hints() -> None:
    """Stable relation_hints become Entity→Entity direct edges (4 types)."""
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    a = Entity(
        entity_id="ent_a", entity_type="Company", canonical_name="A",
        aliases=[], identifiers={}, source_ku_ids=[], created_at=now, updated_at=now,
    )
    b = Entity(
        entity_id="ent_b", entity_type="Company", canonical_name="B",
        aliases=[], identifiers={}, source_ku_ids=[], created_at=now, updated_at=now,
    )
    # One hint per direct-edge type
    unit = _ku_with_hints(
        "ku_1",
        [
            RelationHint(relation_type="控股", subject_entity_id="ent_a", object_entity_id="ent_b"),
            RelationHint(relation_type="高管任职", subject_entity_id="ent_a", object_entity_id="ent_b"),
            RelationHint(relation_type="合作", subject_entity_id="ent_a", object_entity_id="ent_b"),
            RelationHint(relation_type="竞争", subject_entity_id="ent_a", object_entity_id="ent_b"),
        ],
    )
    graph_sync.sync([a, b], [], units=[unit])

    # Collect direct-edge MERGE queries by edge type
    direct_queries = [
        (query, params)
        for query, params in session.calls
        if "MERGE (a)-[r:" in query and "]->(b)" in query
    ]
    edge_types_seen = set()
    for query, _ in direct_queries:
        for t in ("OWNERSHIP", "GOVERNANCE", "COMMERCIAL", "RISK"):
            if f"[r:{t} " in query:
                edge_types_seen.add(t)
    assert edge_types_seen == {"OWNERSHIP", "GOVERNANCE", "COMMERCIAL", "RISK"}


def test_knowledge_graph_sync_skips_one_off_event_hints() -> None:
    """One-off event relation_types (袭击/签署/…) must NOT become direct edges."""
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    a = Entity(
        entity_id="ent_a", entity_type="Company", canonical_name="A",
        aliases=[], identifiers={}, source_ku_ids=[], created_at=now, updated_at=now,
    )
    unit = _ku_with_hints(
        "ku_1",
        [
            RelationHint(relation_type="袭击", subject_entity_id="ent_a", object_entity_id="ent_b"),
            RelationHint(relation_type="签署", subject_entity_id="ent_a", object_entity_id="ent_b"),
            RelationHint(relation_type="谴责", subject_entity_id="ent_a", object_entity_id="ent_b"),
        ],
    )
    graph_sync.sync([a], [], units=[unit])
    direct_queries = [
        query for query, _ in session.calls
        if "MERGE (a)-[r:" in query and "]->(b)" in query
    ]
    assert direct_queries == []  # no direct edges from one-off events


def test_knowledge_graph_sync_merges_repeated_direct_edge() -> None:
    """The same (A,B,type,subtype) from multiple KUs collapses into one MERGE."""
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    a = Entity(
        entity_id="ent_a", entity_type="Company", canonical_name="A",
        aliases=[], identifiers={}, source_ku_ids=[], created_at=now, updated_at=now,
    )
    # Two KUs both reporting A 控股 B → one OWNERSHIP edge, merged source_ku_ids
    unit1 = _ku_with_hints(
        "ku_1",
        [RelationHint(relation_type="控股", subject_entity_id="ent_a", object_entity_id="ent_b")],
    )
    unit2 = _ku_with_hints(
        "ku_2",
        [RelationHint(relation_type="控股", subject_entity_id="ent_a", object_entity_id="ent_b")],
    )
    graph_sync.sync([a], [], units=[unit1, unit2])
    ownership_queries = [
        (query, params)
        for query, params in session.calls
        if "[r:OWNERSHIP " in query
    ]
    assert len(ownership_queries) == 1  # collapsed, not duplicated
    # merged source_ku_ids should carry both ku_ids
    _, params = ownership_queries[0]
    assert "ku_1" in params["new_ku_ids"]
    assert "ku_2" in params["new_ku_ids"]


def test_knowledge_graph_sync_skips_unresolved_hints() -> None:
    """Hints whose entity_id couldn't be resolved (None) must be skipped."""
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    a = Entity(
        entity_id="ent_a", entity_type="Company", canonical_name="A",
        aliases=[], identifiers={}, source_ku_ids=[], created_at=now, updated_at=now,
    )
    # subject_entity_id is None (unresolved mention)
    unit = _ku_with_hints(
        "ku_1",
        [RelationHint(relation_type="控股", subject_entity_id=None, object_entity_id="ent_b")],
    )
    graph_sync.sync([a], [], units=[unit])
    direct_queries = [
        query for query, _ in session.calls
        if "MERGE (a)-[r:" in query and "]->(b)" in query
    ]
    assert direct_queries == []


def test_knowledge_graph_sync_no_units_skips_direct_edges() -> None:
    """admin path passes units=None → no direct edges written (backward compat)."""
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    a = Entity(
        entity_id="ent_a", entity_type="Company", canonical_name="A",
        aliases=[], identifiers={}, source_ku_ids=[], created_at=now, updated_at=now,
    )
    # units not passed (default None) — like all admin/service.py call sites
    stats = graph_sync.sync([a], [])
    assert stats["direct_edges_created"] == 0
    assert stats["direct_edges_merged"] == 0


def test_knowledge_graph_sync_serializes_identifiers_to_json() -> None:
    session = FakeSession()
    graph_sync = KnowledgeGraphSync(connection=FakeConnection(session))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="Xiaomi Group",
        aliases=["Xiaomi"],
        identifiers={"ticker": "1810.HK"},
        source_ku_ids=["ku_1"],
        created_at=now,
        updated_at=now,
    )

    graph_sync.sync([entity], [])

    entity_write = next(params for query, params in session.calls if "MERGE (e:Entity {id: $id})" in query)
    assert entity_write["primary_identifier"] == "1810.HK"
    assert entity_write["identifiers_json"] == '{"ticker": "1810.HK"}'


def test_knowledge_graph_retriever_returns_paths_with_filters(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    knowledge_repo = KnowledgeUnitRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path), knowledge_units=knowledge_repo)
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    start_entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="Xiaomi Group",
        aliases=["Xiaomi"],
        identifiers={},
        source_ku_ids=["ku_1"],
        created_at=now,
        updated_at=now,
    )
    neighbor_entity = Entity(
        entity_id="ent_supplier",
        entity_type="Company",
        canonical_name="Supplier Co",
        aliases=["Supplier"],
        identifiers={},
        source_ku_ids=["ku_2"],
        created_at=now,
        updated_at=now,
    )
    entity_repo.save_batch([start_entity, neighbor_entity])

    cluster = EventCluster(
        cluster_id="clu_1",
        cluster_type="market_impact",
        title="Xiaomi market impact",
        summary="Xiaomi market impact",
        entity_ids=["ent_xiaomi", "ent_supplier"],
        primary_entity_id="ent_xiaomi",
        time_anchor=now,
        time_range={
            "start": "2026-04-01T10:00:00+00:00",
            "end": "2026-04-02T10:00:00+00:00",
        },
        member_ku_ids=["ku_1", "ku_2"],
        source_doc_ids=["doc-1", "doc-2"],
        updated_at=now,
    )
    cluster_repo.save_batch([cluster])

    session = FakeResultSession(
        records=[
            {
                "start_entity_id": "ent_xiaomi",
                "cluster_id": "clu_1",
                "cluster_type": "market_impact",
                "cluster_title": "Xiaomi market impact",
                "cluster_summary": "Xiaomi market impact",
                "cluster_primary_entity_id": "ent_xiaomi",
                "member_ku_ids": ["ku_1", "ku_2"],
                "source_doc_ids": ["doc-1", "doc-2"],
                "conflict_status": "none",
                "representative_ku_id": "ku_1",
                "member_count": 2,
                "source_count": 2,
                "time_range_json": '{"start":"2026-04-01T10:00:00+00:00","end":"2026-04-02T10:00:00+00:00"}',
                "neighbor_entity_id": "ent_supplier",
            }
        ]
    )
    retriever = KnowledgeGraphRetriever(
        db_path=str(db_path),
        connection=FakeConnection(session),
        entity_repo=entity_repo,
        cluster_repo=cluster_repo,
    )

    result = retriever.search(
        StructuredQuery(
            intent=IntentType.RELATIONSHIP_QUERY,
            entities=["Xiaomi Group"],
            time_range=TimeRange(
                start=datetime(2026, 4, 1, tzinfo=UTC).date(),
                end=datetime(2026, 4, 2, tzinfo=UTC).date(),
            ),
            filters=QueryFilters(event_types=["market_impact"]),
            original_query="Show Xiaomi Group relationships",
            confidence=1.0,
        ),
        start_entities=[start_entity],
    )

    assert result.used is True
    assert result.candidate_count == 1
    assert result.expanded_cluster_count == 1
    assert result.expanded_entity_count == 1
    assert result.paths[0]["member_ku_ids"] == ["ku_1", "ku_2"]
    assert any(path["path_type"] == "Entity->EventCluster->Entity" for path in result.paths)
    assert result.hit_reasons["clu_1"] == ["seed_entity:Xiaomi Group"]
    assert result.hit_reasons["ent_supplier"] == ["co_involved_via:clu_1"]


def test_knowledge_graph_retriever_edge_role_filter_added_to_cypher(tmp_path) -> None:
    """When edge_role is set, the multi-hop Cypher carries a WHERE all(...) clause.

    Conservative pruning: passing edge_role adds the filter; NOT passing it
    leaves the Cypher equivalent to the original (no all(...) fragment).
    """
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    start_entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="Xiaomi Group",
        aliases=[], identifiers={}, source_ku_ids=["ku_1"],
        created_at=now, updated_at=now,
    )
    entity_repo.save_batch([start_entity])
    cluster_repo = EventClusterRepository(str(db_path))
    cluster_repo.save_batch([
        EventCluster(
            cluster_id="clu_1", cluster_type="investment",
            title="t", summary="s", entity_ids=["ent_xiaomi"],
            primary_entity_id="ent_xiaomi", time_anchor=now, time_range=None,
            member_ku_ids=["ku_1"], source_doc_ids=["doc-1"], updated_at=now,
        )
    ])

    # --- With edge_role filter: Cypher must contain the all(...) fragment ---
    session_filtered = FakeResultSession(
        [
            {
                "start_entity_id": "ent_xiaomi",
                "cluster_id": "clu_1",
                "cluster_type": "investment",
                "cluster_title": "t",
                "cluster_summary": "s",
                "cluster_primary_entity_id": "ent_xiaomi",
                "member_ku_ids": ["ku_1"],
                "source_doc_ids": ["doc-1"],
                "conflict_status": "none",
                "representative_ku_id": None,
                "member_count": 1,
                "source_count": 1,
                "time_range_json": "null",
                "neighbor_entity_id": None,
            }
        ]
    )
    retriever = KnowledgeGraphRetriever(
        db_path=str(db_path),
        connection=FakeConnection(session_filtered),
        entity_repo=entity_repo,
        cluster_repo=cluster_repo,
    )
    retriever.search(
        StructuredQuery(
            intent=IntentType.ENTITY_OVERVIEW,
            entities=["Xiaomi Group"],
            time_range=None,
            filters=QueryFilters(edge_role=["subject"]),
            original_query="x",
            confidence=1.0,
            hops=2,
        ),
        start_entities=[start_entity],
    )
    cypher_with_filter = session_filtered.calls[0][0]
    assert "all(r IN rels WHERE r.role IN $edge_roles)" in cypher_with_filter
    assert session_filtered.calls[0][1]["edge_roles"] == ["subject"]

    # --- Without edge_role: no all(...) fragment (behavior unchanged) ---
    session_plain = FakeResultSession([])
    retriever_plain = KnowledgeGraphRetriever(
        db_path=str(db_path),
        connection=FakeConnection(session_plain),
        entity_repo=entity_repo,
        cluster_repo=cluster_repo,
    )
    retriever_plain.search(
        StructuredQuery(
            intent=IntentType.ENTITY_OVERVIEW,
            entities=["Xiaomi Group"],
            time_range=None,
            filters=QueryFilters(),  # no edge filters
            original_query="x",
            confidence=1.0,
            hops=2,
        ),
        start_entities=[start_entity],
    )
    cypher_plain = session_plain.calls[0][0]
    assert "all(r IN rels" not in cypher_plain


def test_knowledge_graph_retriever_fails_open_without_breaking_result_shape(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    start_entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="Xiaomi Group",
        aliases=[],
        identifiers={},
        source_ku_ids=["ku_1"],
        created_at=now,
        updated_at=now,
    )
    entity_repo.save_batch([start_entity])

    retriever = KnowledgeGraphRetriever(
        db_path=str(db_path),
        connection=FakeConnection(FakeResultSession(error=RuntimeError("neo4j unavailable"))),
        entity_repo=entity_repo,
        cluster_repo=EventClusterRepository(str(db_path)),
    )

    result = retriever.search(
        StructuredQuery(
            intent=IntentType.RELATIONSHIP_QUERY,
            entities=["Xiaomi Group"],
            time_range=None,
            filters=QueryFilters(),
            original_query="Show Xiaomi Group relationships",
            confidence=1.0,
        ),
        start_entities=[start_entity],
    )

    assert result.used is False
    assert len(result.errors) == 1
    assert "图谱服务不可用" in result.errors[0]
    assert "RuntimeError" in result.errors[0]
    assert result.nodes == []
    assert result.edges == []
    assert result.paths == []


def test_knowledge_graph_retriever_does_not_write_schema_on_read_path(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    start_entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="Xiaomi Group",
        aliases=[],
        identifiers={},
        source_ku_ids=["ku_1"],
        created_at=now,
        updated_at=now,
    )
    entity_repo.save_batch([start_entity])

    session = FakeResultSession(records=[])
    retriever = KnowledgeGraphRetriever(
        db_path=str(db_path),
        connection=FakeConnection(session),
        entity_repo=entity_repo,
        cluster_repo=EventClusterRepository(str(db_path)),
    )

    result = retriever.search(
        StructuredQuery(
            intent=IntentType.RELATIONSHIP_QUERY,
            entities=["Xiaomi Group"],
            time_range=None,
            filters=QueryFilters(),
            original_query="Show Xiaomi Group relationships",
            confidence=1.0,
        ),
        start_entities=[start_entity],
    )

    assert result.used is True
    assert len(session.calls) == 1
    # Check for the variable-length path pattern (edge var may be named rels:).
    query_text = session.calls[0][0]
    assert "MATCH path = (start:Entity)-[" in query_text
    assert ":INVOLVED_IN*1.." in query_text


def test_knowledge_unit_repository_syncs_fts_rows(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    repo = KnowledgeUnitRepository(str(db_path))
    unit = build_unit()
    unit.entities[0].entity_id = "ent_xiaomi"
    repo.save_batch([unit])

    connection = sqlite3.connect(db_path)
    try:
        row = connection.execute(
            "SELECT summary, entity_mentions FROM knowledge_units_fts WHERE ku_id = ?",
            (unit.ku_id,),
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row[0] == unit.summary
    assert "Xiaomi Group" in row[1]


def test_knowledge_unit_repository_repairs_stale_entity_ids_and_fts_rows(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    repo = KnowledgeUnitRepository(str(db_path))
    unit = build_unit()
    unit.entities[0].entity_id = "ent_xiaomi"
    repo.save_batch([unit])

    connection = sqlite3.connect(db_path)
    try:
        connection.execute("UPDATE knowledge_units SET entity_ids = '[]'")
        connection.execute("DELETE FROM knowledge_units_fts")
        connection.commit()
    finally:
        connection.close()

    repaired = KnowledgeUnitRepository(str(db_path))

    connection = sqlite3.connect(db_path)
    try:
        entity_ids = connection.execute(
            "SELECT entity_ids FROM knowledge_units WHERE ku_id = ?",
            (unit.ku_id,),
        ).fetchone()[0]
        fts_count = connection.execute("SELECT COUNT(*) FROM knowledge_units_fts").fetchone()[0]
    finally:
        connection.close()

    assert repaired.get_by_ids([unit.ku_id])[0].entities[0].entity_id == "ent_xiaomi"
    assert entity_ids == '["ent_xiaomi"]'
    assert fts_count == 1


def test_entity_repository_find_by_names_and_cluster_repository_filters(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="\u5c0f\u7c73\u96c6\u56e2",
        aliases=["Xiaomi Group", "\u5c0f\u7c73"],
        identifiers={},
        source_ku_ids=["seed"],
        created_at=now,
        updated_at=now,
    )
    entity_repo.save_batch([entity])
    cluster_repo.save_batch(
        [
            EventCluster(
                cluster_id="clu_xiaomi",
                cluster_type="market_impact",
                title="Xiaomi market impact",
                summary="Xiaomi market impact",
                entity_ids=[entity.entity_id],
                primary_entity_id=entity.entity_id,
                time_anchor=now,
                time_range=None,
                member_ku_ids=["ku_1"],
                source_doc_ids=["doc-1"],
                updated_at=now,
            )
        ]
    )

    matched = entity_repo.find_by_names(["Xiaomi Group"])
    related = cluster_repo.find_related(
        primary_entity_ids=[entity.entity_id],
        cluster_types=["market_impact"],
        time_range=("2026-04-01", "2026-04-01"),
    )

    assert [item.entity_id for item in matched] == [entity.entity_id]
    assert [item.cluster_id for item in related] == ["clu_xiaomi"]


def test_knowledge_searcher_matches_alias_variants_and_reports_hybrid_sources(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="\u5c0f\u7c73\u96c6\u56e2",
        aliases=["\u5c0f\u7c73", "Xiaomi Group"],
        identifiers={},
        source_ku_ids=["ku_1"],
        created_at=now,
        updated_at=now,
    )
    entity_repo.save_batch([entity])
    cluster_repo.save_batch([])

    unit = KnowledgeUnit(
        unit_kind="event",
        unit_type="market_impact",
        summary="\u5c0f\u7c73\u96c6\u56e2\u56de\u5e94\u5e02\u573a\u5f71\u54cd",
        entities=[EntityRef(entity_id="ent_xiaomi", mention="\u5c0f\u7c73\u96c6\u56e2", entity_type="Company")],
        source=SourceRef(doc_id="doc-1", source_name="test-source"),
        evidence=[EvidenceSpan(text="\u5c0f\u7c73\u96c6\u56e2\u56de\u5e94\u5e02\u573a\u5f71\u54cd\u3002")],
        time=TimeRef(
            event_time=now,
            published_at=now,
            extracted_at=now,
        ),
    )
    KnowledgeUnitRepository(str(db_path)).save_batch([unit])

    searcher = KnowledgeSearcher(
        db_path=str(db_path),
        extractor=KnowledgeExtractor(enable_llm=False),
    )
    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query="Show Xiaomi Group market impact timeline",
                confidence=1.0,
            ),
            top_k=10,
        )
    )

    assert result.total_count == 1
    assert len(result.knowledge_units) == 1
    assert result.bm25_count == 1
    assert result.hit_scores[result.knowledge_units[0].ku_id]["sources"] == ["bm25"]


# ------------------------------------------------------------------
# Phase 1: Multi-path retrieval tests
# ------------------------------------------------------------------


def _setup_searcher_with_entities(
    tmp_path,
    entity_specs: list[tuple[str, str, list[str]]],
    ku_specs: list[tuple[str, str, str | None, datetime | None]] | None = None,
) -> tuple[KnowledgeSearcher, dict[str, str]]:
    """Helper: create a searcher with pre-populated entities and KUs.

    entity_specs: [(entity_id, canonical_name, [aliases])]
    ku_specs: [(mention, summary, entity_id, published_at)]
    Returns: (searcher, {canonical_name: entity_id})
    """
    db_path = tmp_path / "news.db"
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    entity_repo = EntityRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path))

    name_to_id: dict[str, str] = {}
    entities: list[Entity] = []
    for eid, name, aliases in entity_specs:
        entity = Entity(
            entity_id=eid,
            entity_type="Company",
            canonical_name=name,
            aliases=aliases,
            identifiers={},
            source_ku_ids=[],
            created_at=now,
            updated_at=now,
        )
        entities.append(entity)
        name_to_id[name] = eid
    entity_repo.save_batch(entities)
    cluster_repo.save_batch([])

    if ku_specs:
        ku_repo = KnowledgeUnitRepository(str(db_path))
        units: list[KnowledgeUnit] = []
        for mention, summary, entity_id, pub_at in ku_specs:
            pub_at_resolved: datetime = pub_at if pub_at is not None else now
            unit = KnowledgeUnit(
                unit_kind="event",
                unit_type="market_analysis",
                summary=summary,
                entities=[EntityRef(entity_id=entity_id, mention=mention, entity_type="Company")],
                source=SourceRef(doc_id=f"doc-{len(units)}", source_name="test"),
                evidence=[EvidenceSpan(text=summary)],
                time=TimeRef(event_time=pub_at_resolved, published_at=pub_at_resolved, extracted_at=pub_at_resolved),
            )
            units.append(unit)
        ku_repo.save_batch(units)
    db_path = tmp_path / "news.db"
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    entity_repo = EntityRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path))

    name_to_id: dict[str, str] = {}
    entities: list[Entity] = []
    for eid, name, aliases in entity_specs:
        entity = Entity(
            entity_id=eid,
            entity_type="Company",
            canonical_name=name,
            aliases=aliases,
            identifiers={},
            source_ku_ids=[],
            created_at=now,
            updated_at=now,
        )
        entities.append(entity)
        name_to_id[name] = eid
    entity_repo.save_batch(entities)
    cluster_repo.save_batch([])

    if ku_specs:
        ku_repo = KnowledgeUnitRepository(str(db_path))
        units: list[KnowledgeUnit] = []
        for mention, summary, entity_id, pub_at in ku_specs:
            pub_at = pub_at or now
            unit = KnowledgeUnit(
                unit_kind="event",
                unit_type="market_analysis",
                summary=summary,
                entities=[EntityRef(entity_id=entity_id, mention=mention, entity_type="Company")],
                source=SourceRef(doc_id=f"doc-{len(units)}", source_name="test"),
                evidence=[EvidenceSpan(text=summary)],
                time=TimeRef(event_time=pub_at, published_at=pub_at, extracted_at=pub_at),
            )
            units.append(unit)
        ku_repo.save_batch(units)

    searcher = KnowledgeSearcher(
        db_path=str(db_path),
        extractor=KnowledgeExtractor(enable_llm=False),
    )
    return searcher, name_to_id


def test_entity_id_lookup_finds_kus_by_entity(tmp_path) -> None:
    """Path A: Entity-ID lookup returns KUs linked to the resolved entity."""
    searcher, ids = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[
            ("ent_catl", "宁德时代", ["CATL"]),
            ("ent_byd", "比亚迪", ["BYD"]),
        ],
        ku_specs=[
            ("宁德时代", "宁德时代Q1营收破千亿", "ent_catl", None),
            ("比亚迪", "比亚迪发布新车型", "ent_byd", None),
            ("宁德时代", "宁德时代与比亚迪合作", "ent_catl", None),
        ],
    )

    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.ENTITY_OVERVIEW,
                entities=["宁德时代"],
                time_range=None,
                filters=QueryFilters(),
                original_query="宁德时代",
                confidence=1.0,
            ),
        )
    )

    assert result.total_count >= 2
    assert result.retrieval_path == "entity_id_lookup"


def test_relaxation_cascade_returns_results_when_entity_not_found(tmp_path) -> None:
    """When entity is not in DB, BM25 fallback runs; result depends on content match."""
    searcher, _ = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[
            ("ent_catl", "宁德时代", []),
        ],
        ku_specs=[
            ("宁德时代", "宁德时代Q1营收破千亿", "ent_catl", None),
        ],
    )

    # "量化交易" is not an entity and not in any KU text — should fall through
    # to BM25, which also finds nothing, yielding no_results.
    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.ENTITY_OVERVIEW,
                entities=["量化交易"],
                time_range=None,
                filters=QueryFilters(),
                original_query="量化交易",
                confidence=1.0,
            ),
        )
    )

    # BM25 fallback was attempted but found no matching content
    assert result.retrieval_path == "no_results"
    assert result.total_count == 0


def test_comparative_analysis_balances_both_entities(tmp_path) -> None:
    """COMPARATIVE_ANALYSIS returns KUs for both entities, not just the popular one."""
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    ku_specs_catl: list[tuple[str, str, str | None, datetime | None]] = [
        ("宁德时代", f"宁德时代事件{i}", "ent_catl", now + timedelta(days=i))
        for i in range(10)
    ]
    ku_specs_byd: list[tuple[str, str, str | None, datetime | None]] = [
        ("比亚迪", f"比亚迪事件{i}", "ent_byd", now + timedelta(days=i))
        for i in range(3)
    ]
    ku_specs = ku_specs_catl + ku_specs_byd

    searcher, _ = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[
            ("ent_catl", "宁德时代", []),
            ("ent_byd", "比亚迪", []),
        ],
        ku_specs=ku_specs,
    )

    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.COMPARATIVE_ANALYSIS,
                entities=["宁德时代", "比亚迪"],
                time_range=None,
                filters=QueryFilters(),
                original_query="宁德时代 vs 比亚迪",
                confidence=1.0,
            ),
            top_k=20,
        )
    )

    assert result.retrieval_path == "comparative"
    # Both entities should have representation
    byd_mentions = sum(
        1 for u in result.knowledge_units
        if any(e.entity_id == "ent_byd" for e in u.entities)
    )
    assert byd_mentions > 0, "比亚迪 should have at least one KU in results"


def test_comparative_analysis_unresolved_entities_falls_back_gracefully(tmp_path) -> None:
    """COMPARATIVE_ANALYSIS with unresolved entities returns results via BM25 fallback."""
    # Use distinct entity names that don't overlap in text
    searcher, _ = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[],
        ku_specs=[
            ("Apple", "Apple announced new iPhone features", None, None),
            ("Tesla", "Tesla reported strong quarterly deliveries", None, None),
            ("Apple", "Apple stock hit new high", None, None),
        ],
    )

    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.COMPARATIVE_ANALYSIS,
                entities=["Apple", "Tesla"],
                time_range=None,
                filters=QueryFilters(),
                original_query="Apple Tesla",
                confidence=1.0,
            ),
            top_k=20,
        )
    )

    assert result.retrieval_path == "comparative"
    assert result.total_count >= 2, f"Should return at least 2 KUs, got {result.total_count}"
    # Check that we have both Apple and Tesla related KUs
    ku_summaries = {u.summary for u in result.knowledge_units}
    has_apple = any("Apple" in s for s in ku_summaries)
    has_tesla = any("Tesla" in s for s in ku_summaries)
    assert has_apple, "Apple KU should be in results"
    assert has_tesla, "Tesla KU should be in results"


def test_comparative_analysis_co_occurrence_ranks_higher(tmp_path) -> None:
    """Co-occurrence KUs rank first; per-entity KUs get balanced coverage.

    First-principles for comparative: the query carries no comparison axis, so
    the layer cannot judge "comparative relevance". Its job is fair recall —
    co-occurrence statements go first (rare genuine multi-entity items), then
    the two sides alternate so neither buries the other.
    """
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    searcher, _ = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[],
        ku_specs=[
            ("Apple", "Single mention of Apple statement", None, now),
            ("Tesla", "Single mention of Tesla statement", None, now),
            ("Apple Tesla", "Statement mentioning both Apple and Tesla collaboration", None, now),
        ],
    )

    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.COMPARATIVE_ANALYSIS,
                entities=["Apple", "Tesla"],
                time_range=None,
                filters=QueryFilters(),
                original_query="Apple Tesla",
                confidence=1.0,
            ),
            top_k=10,
        )
    )

    assert result.total_count >= 3

    # Co-occurrence KU should rank FIRST — it is the rare genuine multi-entity
    # statement and is placed ahead of per-entity-exclusive KUs.
    co_occurrence_ku = None
    for ku in result.knowledge_units:
        if "Apple" in ku.summary and "Tesla" in ku.summary:
            co_occurrence_ku = ku
            break

    assert co_occurrence_ku is not None, "Co-occurrence KU should be in results"
    assert result.knowledge_units[0].ku_id == co_occurrence_ku.ku_id, (
        "Co-occurrence KU should rank first"
    )

    # Co-occurrence KU is flagged in component_scores (behavior contract, not
    # a specific bonus mechanism).
    score_info = result.hit_scores.get(co_occurrence_ku.ku_id, {})
    component_scores = score_info.get("component_scores", {}) if isinstance(score_info, dict) else {}
    assert isinstance(component_scores, dict), "component_scores should be a dict"
    assert component_scores.get("co_occurrence") is True, (
        "Co-occurrence KU should be flagged in component_scores"
    )

    # Both entities must appear in the result set — balanced coverage is the
    # core contract of comparative retrieval.
    summaries = " ".join(ku.summary for ku in result.knowledge_units)
    assert "Apple" in summaries, "Apple-exclusive KU should be in results"
    assert "Tesla" in summaries, "Tesla-exclusive KU should be in results"


def test_topic_research_fallback_to_text_search(tmp_path) -> None:
    """TOPIC_RESEARCH for unknown topic falls back to BM25 text search."""
    searcher, _ = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[],
        ku_specs=[
            ("人工智能", "大模型技术发展趋势分析", None, None),
        ],
    )

    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.TOPIC_RESEARCH,
                entities=["大模型"],
                time_range=None,
                filters=QueryFilters(),
                original_query="大模型",
                confidence=1.0,
            ),
        )
    )

    # "大模型" may or may not match as entity, but should not hard-gate to empty
    assert result.retrieval_path in ("bm25_fallback", "entity_id_lookup")


def test_timeline_covers_time_range(tmp_path) -> None:
    """ENTITY_TIMELINE returns results spread across months, not concentrated."""
    now = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)
    ku_specs: list[tuple[str, str, str | None, datetime | None]] = [
        (
            "宁德时代",
            f"宁德时代{i}月事件",
            "ent_catl",
            now + timedelta(days=30 * i),
        )
        for i in range(6)  # Jan through Jun
    ]

    searcher, _ = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[("ent_catl", "宁德时代", [])],
        ku_specs=ku_specs,
    )

    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=["宁德时代"],
                time_range=None,
                filters=QueryFilters(),
                original_query="宁德时代",
                confidence=1.0,
            ),
            top_k=20,
        )
    )

    assert result.retrieval_path == "timeline"
    assert len(result.knowledge_units) >= 3

    # Verify temporal spread — results should span multiple months
    months = {u.time.published_at.strftime("%Y-%m") for u in result.knowledge_units}
    assert len(months) >= 2, f"Expected results from multiple months, got: {months}"


def test_cross_lingual_alias_byd_resolves(tmp_path) -> None:
    """'BYD' resolves to 比亚迪 via cross-lingual alias mapping."""
    searcher, _ = _setup_searcher_with_entities(
        tmp_path,
        entity_specs=[
            ("ent_byd", "比亚迪", ["BYD"]),
        ],
        ku_specs=[
            ("比亚迪", "比亚迪发布新车型", "ent_byd", None),
        ],
    )

    result = searcher.search(
        KnowledgeSearchRequest(
            structured_query=StructuredQuery(
                intent=IntentType.ENTITY_OVERVIEW,
                entities=["BYD"],
                time_range=None,
                filters=QueryFilters(),
                original_query="BYD",
                confidence=1.0,
            ),
        )
    )

    assert result.total_count >= 1
    assert result.retrieval_path == "entity_id_lookup"


# ---------------------------------------------------------------------------
# LLMConflictDetector tests
# ---------------------------------------------------------------------------


def _make_llm_response(contradictions: list[dict[str, Any]]) -> SimpleNamespace:
    tool_input: dict[str, Any] = {"contradictions": contradictions}
    return SimpleNamespace(
        content=[
            ToolUseBlock(
                type="tool_use",
                id="test_tool_id",
                name="flag_contradictions",
                input=tool_input,
            )
        ]
    )


def test_llm_conflict_detector_detects_factual_contradiction() -> None:
    from src.conflict_detection import LLMConflictDetector

    detector = LLMConflictDetector()
    llm_response = _make_llm_response([
        {
            "conflict_type": "factual",
            "severity": "high",
            "description": "A称'腾讯收购搜狗'，B称'搜狗收购腾讯'",
        }
    ])
    detector._client = cast(Any, SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: llm_response)))
    detector._model = "test-model"

    unit_a = build_unit(summary="腾讯以425亿元收购搜狗", doc_id="doc-1")
    unit_b = build_unit(summary="搜狗以425亿元收购腾讯", doc_id="doc-2")

    results = detector.detect_semantic_conflicts(unit_a, [unit_a, unit_b])
    assert len(results) == 1
    assert results[0]["type"] == "semantic_factual"
    assert results[0]["severity"] == "high"


def test_llm_conflict_detector_returns_empty_on_no_conflict() -> None:
    from src.conflict_detection import LLMConflictDetector

    detector = LLMConflictDetector()
    llm_response = _make_llm_response([])
    detector._client = cast(Any, SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: llm_response)))
    detector._model = "test-model"

    unit_a = build_unit(summary="苹果公司发布iPhone 16", doc_id="doc-1")
    unit_b = build_unit(summary="苹果公司发布iPhone 16，配备AI芯片", doc_id="doc-2")

    results = detector.detect_semantic_conflicts(unit_a, [unit_a, unit_b])
    assert results == []


def test_llm_conflict_detector_falls_back_on_error() -> None:
    """LLM errors propagate to caller; caller is responsible for fallback."""
    from src.conflict_detection import LLMConflictDetector

    def raise_error(**kwargs: Any) -> None:
        raise RuntimeError("LLM service unavailable")

    detector = LLMConflictDetector()
    detector._client = cast(Any, SimpleNamespace(messages=SimpleNamespace(create=raise_error)))
    detector._model = "test-model"

    unit_a = build_unit(doc_id="doc-1")
    unit_b = build_unit(doc_id="doc-2")

    with pytest.raises(RuntimeError, match="LLM service unavailable"):
        detector.detect_semantic_conflicts(unit_a, [unit_a, unit_b])


def test_build_event_cluster_snapshot_handles_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cluster building should not crash when LLM detection fails."""
    from src.conflict_detection import LLMConflictDetector

    def raise_error(**kwargs: Any) -> None:
        raise RuntimeError("LLM service unavailable")

    mock_llm = LLMConflictDetector()
    mock_llm._client = cast(Any, SimpleNamespace(messages=SimpleNamespace(create=raise_error)))
    mock_llm._model = "test-model"
    monkeypatch.setattr("src.event_merging._LLM_DETECTOR", mock_llm)

    unit_a = build_unit(
        summary="苹果公司发布新产品",
        doc_id="doc-1",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_a.entities[0].entity_id = "ent_apple"
    unit_a.time.event_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    unit_b = build_unit(
        summary="苹果公司发布新产品，市场反应热烈",
        doc_id="doc-2",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_b.entities[0].entity_id = "ent_apple"
    unit_b.time.event_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    cluster = build_event_cluster_snapshot([unit_a, unit_b])
    assert cluster.conflict_status == "none"
    assert cluster.conflict_details == []


def test_build_event_cluster_snapshot_integrates_llm_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.conflict_detection import LLMConflictDetector

    mock_llm = LLMConflictDetector()
    llm_response = _make_llm_response([
        {
            "conflict_type": "sentiment",
            "severity": "medium",
            "description": "A称'利好科技板块'，B称'对科技板块构成利空'",
        }
    ])
    mock_llm._client = cast(Any, SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: llm_response)))
    mock_llm._model = "test-model"
    monkeypatch.setattr("src.event_merging._LLM_DETECTOR", mock_llm)

    unit_a = build_unit(
        summary="该政策利好科技板块",
        doc_id="doc-1",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_a.entities[0].entity_id = "ent_tech"
    unit_a.time.event_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    unit_b = build_unit(
        summary="该政策对科技板块构成利空",
        doc_id="doc-2",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_b.entities[0].entity_id = "ent_tech"
    unit_b.time.event_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    cluster = build_event_cluster_snapshot([unit_a, unit_b])

    assert cluster.conflict_status == "possible"
    assert "semantic:sentiment" in cluster.conflict_reasons
    semantic_details = [d for d in cluster.conflict_details if d["type"] == "semantic_sentiment"]
    assert len(semantic_details) == 1
    assert semantic_details[0]["severity"] == "medium"


# ---------------------------------------------------------------------------
# Embedding-enhanced clustering tests
# ---------------------------------------------------------------------------


class _MockEmbeddingProvider:
    """Deterministic embedding provider for testing."""

    def __init__(self, text_to_vector: dict[str, list[float]] | None = None):
        self._text_to_vector = text_to_vector if text_to_vector is not None else {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = self._text_to_vector.get(text)
            if vec is not None:
                results.append(vec)
            else:
                results.append([0.0] * 4)
        return results


def test_find_cluster_uses_embedding_similarity(tmp_path) -> None:
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))

    # High similarity embedding: same direction → cosine ≈ 0.99
    high_sim_vec_a = [0.9, 0.3, 0.1, 0.0]
    high_sim_vec_b = [0.85, 0.35, 0.15, 0.0]

    text_map: dict[str, list[float]] = {}
    provider = _MockEmbeddingProvider(text_map)
    clusterer = EventMerger(repo, embedding_provider=provider)

    from src.retrieval.vector_index import build_embedding_text

    unit_a = build_unit(
        summary="腾讯以425亿元收购搜狗",
        mention="腾讯",
        doc_id="doc-1",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_a.entities[0].entity_id = "ent_tencent"
    unit_a.time.event_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    text_map[build_embedding_text(unit_a)] = high_sim_vec_a

    unit_b = build_unit(
        summary="搜狗被腾讯全资收购",
        mention="搜狗",
        doc_id="doc-2",
        published_at=datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
    )
    unit_b.entities[0].entity_id = "ent_sogou"
    unit_b.entities.append(EntityRef(mention="腾讯", entity_id="ent_tencent", entity_type="Company"))
    unit_b.time.event_time = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    text_map[build_embedding_text(unit_b)] = high_sim_vec_b

    _, clusters = clusterer.assign_clusters([unit_a, unit_b], persist=False)
    assert len(clusters) == 1
    assert clusters[0].member_count == 2


def test_find_cluster_falls_back_to_sequencematcher(tmp_path) -> None:
    """Without embedding provider, uses SequenceMatcher fallback."""
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))
    clusterer = EventMerger(repo)  # No embedding_provider

    unit_a = build_unit(
        summary="腾讯以425亿元收购搜狗",
        mention="腾讯",
        doc_id="doc-1",
    )
    unit_a.entities[0].entity_id = "ent_tencent"

    unit_b = build_unit(
        summary="腾讯以425亿元收购搜狗",
        mention="腾讯",
        doc_id="doc-2",
    )
    unit_b.entities[0].entity_id = "ent_tencent"

    _, clusters = clusterer.assign_clusters([unit_a, unit_b], persist=False)
    assert len(clusters) == 1
    assert clusters[0].member_count == 2


def test_find_candidates_by_entity_overlap(tmp_path) -> None:
    """Relaxed entity matching: shared entity_id is enough to become a candidate."""
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))

    unit_a = build_unit(summary="A and B did something", doc_id="doc-1")
    unit_a.entities = [
        EntityRef(mention="A", entity_id="ent_a", entity_type="Company"),
        EntityRef(mention="B", entity_id="ent_b", entity_type="Company"),
    ]

    clusterer = EventMerger(repo)
    _, clusters = clusterer.assign_clusters([unit_a], persist=True)
    assert len(clusters) == 1

    candidates = repo._find_candidates_by_entity_overlap(["ent_a", "ent_c"], "investment")
    assert len(candidates) == 1
    assert candidates[0].cluster_id == clusters[0].cluster_id


def test_embedding_below_threshold_does_not_merge(tmp_path) -> None:
    """Clusters should NOT merge when embedding similarity is below threshold."""
    db_path = tmp_path / "clusters.db"
    repo = EventClusterRepository(str(db_path))

    vec_a = [1.0, 0.0, 0.0, 0.0]
    vec_b = [0.0, 1.0, 0.0, 0.0]

    text_map: dict[str, list[float]] = {}
    provider = _MockEmbeddingProvider(text_map)
    clusterer = EventMerger(repo, embedding_provider=provider)

    from src.retrieval.vector_index import build_embedding_text

    unit_a = build_unit(
        summary="腾讯发布Q1财报",
        mention="腾讯",
        doc_id="doc-1",
    )
    unit_a.entities[0].entity_id = "ent_tencent"
    text_map[build_embedding_text(unit_a)] = vec_a

    unit_b = build_unit(
        summary="腾讯被反垄断调查",
        mention="腾讯",
        doc_id="doc-2",
    )
    unit_b.entities[0].entity_id = "ent_tencent"
    text_map[build_embedding_text(unit_b)] = vec_b

    _, clusters = clusterer.assign_clusters([unit_a, unit_b], persist=False)
    assert len(clusters) == 2



def test_relationship_path_event_type_filter_added_to_cypher(tmp_path) -> None:
    """event_types 在路径查询中生成 cluster-type 过滤片段并带入展开后的类型参数。

    过滤发生在 Cypher 内（而非取回后过滤），被拒绝的路径不占用 LIMIT 预算；
    不传 event_types 时 Cypher 保持原样（行为不变）。
    """
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    cluster_repo = EventClusterRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    def _entity(entity_id: str, name: str) -> Entity:
        return Entity(
            entity_id=entity_id,
            entity_type="Company",
            canonical_name=name,
            aliases=[], identifiers={}, source_ku_ids=["ku_1"],
            created_at=now, updated_at=now,
        )

    entity_a = _entity("ent_a", "Company A")
    entity_b = _entity("ent_b", "Company B")

    # --- With event_types: Cypher carries the cluster-type all(...) fragment ---
    session_filtered = FakeResultSession([])
    retriever = KnowledgeGraphRetriever(
        db_path=str(db_path),
        connection=FakeConnection(session_filtered),
        entity_repo=entity_repo,
        cluster_repo=cluster_repo,
    )
    retriever.search_relationship_path(
        entity_a=entity_a,
        entity_b=entity_b,
        max_hops=2,
        event_types=["重组"],
    )
    cypher_with_filter = session_filtered.calls[0][0]
    assert (
        "all(n IN nodes(path) "
        "WHERE n:Entity OR n.cluster_type IN $cluster_types)" in cypher_with_filter
    )
    params = session_filtered.calls[0][1]
    assert "restructuring" in params["cluster_types"]

    # --- Without event_types: no cluster-type fragment (behavior unchanged) ---
    session_plain = FakeResultSession([])
    retriever_plain = KnowledgeGraphRetriever(
        db_path=str(db_path),
        connection=FakeConnection(session_plain),
        entity_repo=entity_repo,
        cluster_repo=cluster_repo,
    )
    retriever_plain.search_relationship_path(
        entity_a=entity_a,
        entity_b=entity_b,
        max_hops=2,
    )
    assert "$cluster_types" not in session_plain.calls[0][0]


def test_enhance_with_graph_passes_event_types_to_path_search(
    monkeypatch, tmp_path
) -> None:
    """RELATIONSHIP_QUERY + target_entity 时 filters.event_types 必须透传到
    search_relationship_path（图路径不再无视事件类型过滤）。"""
    from src.orchestration import graph as graph_module
    from src.graph.knowledge_retrieval import GraphRetrievalResult

    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)

    def _entity(entity_id: str, name: str) -> Entity:
        return Entity(
            entity_id=entity_id,
            entity_type="Company",
            canonical_name=name,
            aliases=[], identifiers={}, source_ku_ids=["ku_1"],
            created_at=now, updated_at=now,
        )

    ent_a = _entity("ent_a", "Company A")
    ent_b = _entity("ent_b", "Company B")
    by_name = {"Company A": ent_a, "Company B": ent_b}

    class FakeEntityRepo:
        def find_by_names(self, names):
            return [by_name[n] for n in names if n in by_name]

    recorded: dict[str, Any] = {}

    class FakeRetriever:
        def search_relationship_path(self, **kwargs):
            recorded.update(kwargs)
            return GraphRetrievalResult(used=True)

        def search(self, *args, **kwargs):
            raise AssertionError("带 target_entity 的 RELATIONSHIP_QUERY 不应走多跳 search")

    monkeypatch.setattr(
        graph_module, "_resolve_entity_repo", lambda db_path: FakeEntityRepo()
    )
    monkeypatch.setattr(
        graph_module, "_resolve_graph_retriever", lambda db_path: FakeRetriever()
    )

    query = StructuredQuery(
        intent=IntentType.RELATIONSHIP_QUERY,
        entities=["Company A"],
        time_range=None,
        filters=QueryFilters(event_types=["重组"]),
        original_query="A B 关系",
        target_entity="Company B",
        hops=2,
    )
    enhancement = graph_module._enhance_with_graph(
        structured_query=query,
        db_path=str(tmp_path / "news.db"),
    )

    assert recorded["event_types"] == ["重组"]
    assert recorded["max_hops"] == 2
    assert recorded["entity_a"] is ent_a
    assert recorded["entity_b"] is ent_b
    assert enhancement.graph_result.used is True
