"""
Knowledge pipeline component tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.entities_v2 import Entity, EntityRepository, EntityResolver
from src.event_clustering import EventClusterRepository, EventClusterer
from src.knowledge_base import (
    EntityRef,
    EvidenceSpan,
    KnowledgeToLegacyParticleAdapter,
    KnowledgeUnit,
    SourceRef,
    TimeRef,
    adapt_article_to_raw_document,
)
from src.knowledge_graph_sync import KnowledgeGraphSync


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
    clusterer = EventClusterer(repo)

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


def test_legacy_adapter_builds_compatible_particle_row() -> None:
    adapter = KnowledgeToLegacyParticleAdapter()
    unit = build_unit(
        summary="Xiaomi Group received a regulatory penalty notice",
        unit_type="policy_sanction",
    )

    row = adapter.to_legacy_row(unit)
    particle = adapter.to_legacy_particle(unit)

    assert row is not None
    assert particle is not None
    assert row["particle_id"] == unit.ku_id
    assert row["event_summary"] == unit.summary
    assert row["entities"] == ["Xiaomi Group"]
    assert row["source_doc_ids"] == ["doc-1"]
    assert particle.id == unit.ku_id
    assert particle.source_doc_ids == ["doc-1"]
    assert particle.risk_signal.description == unit.summary


def test_legacy_adapter_skips_unsupported_unit_types() -> None:
    adapter = KnowledgeToLegacyParticleAdapter()
    unit = build_unit(
        unit_type="investment",
        summary="Xiaomi Group announced an investment update",
    )

    assert adapter.to_legacy_row(unit) is None
    assert adapter.to_legacy_particle(unit) is None


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
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def session(self):
        return self._session


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

    from src.event_clustering import EventCluster

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
