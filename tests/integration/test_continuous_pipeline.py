"""
Continuous pipeline integration tests.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from collectors.database import Database
from src.intent.models import IntentType, QueryFilters, StructuredQuery
from src.knowledge_base import EntityRef, EvidenceSpan, KnowledgeUnit, SourceRef, TimeRef
from src.knowledge_extractor import KnowledgeExtractor
from src.orchestration import run_pipeline
from src.pipeline import ContinuousPipeline


def seed_articles(db_path: str) -> None:
    db = Database(db_path)
    db.insert_articles_batch(
        [
            {
                "doc_id": "doc-1",
                "title": "Xiaomi Group receives a regulatory penalty",
                "content": "Xiaomi Group received a regulatory penalty and started remediation.",
                "publish_time": "2026-04-01T09:00:00+00:00",
                "source_name": "test-source",
                "source_type": "news",
                "category": "company",
                "raw_tags": [],
            },
            {
                "doc_id": "doc-2",
                "title": "Xiaomi Group updates its remediation progress",
                "content": "Xiaomi Group shared an update on the remediation progress.",
                "publish_time": "2026-04-01T10:00:00+00:00",
                "source_name": "test-source",
                "source_type": "news",
                "category": "company",
                "raw_tags": [],
            },
        ]
    )


class StubExtractor(KnowledgeExtractor):
    def extract(self, document) -> list[KnowledgeUnit]:
        published_at = document.published_at
        return [
            KnowledgeUnit(
                unit_kind="event",
                unit_type="policy_sanction",
                summary=document.title,
                entities=[EntityRef(mention="Xiaomi Group")],
                source=SourceRef(
                    doc_id=document.doc_id,
                    source_name=document.source_name,
                    url=document.url,
                ),
                evidence=[EvidenceSpan(text=document.content)],
                time=TimeRef(
                    event_time=published_at,
                    published_at=published_at,
                    extracted_at=published_at + timedelta(minutes=5),
                ),
                confidence=0.9,
            )
        ]


def test_run_continuous_builds_knowledge_tables_and_backfills_legacy(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
    )
    result = pipeline.run()

    assert result.knowledge_units_extracted == 2
    assert result.knowledge_units_saved == 2
    assert result.entities_saved >= 1
    assert result.clusters_saved >= 1
    assert result.particles_saved == 2

    connection = sqlite3.connect(db_path)
    try:
        ku_count = connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
        entity_count = connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        cluster_count = connection.execute("SELECT COUNT(*) FROM event_clusters").fetchone()[0]
        legacy_count = connection.execute("SELECT COUNT(*) FROM intelligence_particles").fetchone()[0]
        log_rows = connection.execute(
            "SELECT doc_id, status, knowledge_units_count FROM knowledge_processing_log ORDER BY doc_id"
        ).fetchall()
    finally:
        connection.close()

    assert ku_count == 2
    assert entity_count >= 1
    assert cluster_count >= 1
    assert legacy_count == 2
    assert [(row[0], row[1], row[2]) for row in log_rows] == [
        ("doc-1", "success", 1),
        ("doc-2", "success", 1),
    ]


def test_run_pipeline_can_consume_backfilled_legacy_particles(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "data" / "news.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
    )
    pipeline.run()

    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    class FakeMasterAgent:
        def __init__(self, graph_enabled: bool = False):
            self.graph_enabled = graph_enabled

        def generate_timeline(self, entity: str, particles):
            events = [
                {
                    "date": particle.event_time.isoformat(),
                    "event_type": particle.event_type.value,
                    "description": particle.risk_signal.description,
                    "risk_level": particle.risk_level.value,
                    "source_ids": particle.source_doc_ids,
                    "particle_id": particle.id,
                }
                for particle in particles
                if entity in particle.risk_signal.description
                or any(entity in source_id for source_id in particle.source_doc_ids)
            ]
            return {
                "entity": entity,
                "events": events,
                "total_events": len(events),
                "time_range": {
                    "start": events[-1]["date"] if events else None,
                    "end": events[0]["date"] if events else None,
                },
            }

    import src.intent
    import src.orchestration.nodes as nodes_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(nodes_module, "MasterAgent", FakeMasterAgent)

    result = run_pipeline(
        raw_query="Show the Xiaomi Group timeline",
        graph_enabled=False,
    )

    assert result["timeline_data"]["entity"] == "Xiaomi Group"
    assert result["timeline_data"]["timeline"]["total_events"] >= 1


def test_run_continuous_reuses_stable_knowledge_ids_on_rebuild(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=False,
        db_path=str(db_path),
        extractor=StubExtractor(),
    )

    first = pipeline.run()
    second = pipeline.run()

    assert first.knowledge_units_saved == 2
    assert second.knowledge_units_saved == 2

    connection = sqlite3.connect(db_path)
    try:
        ku_count = connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
        legacy_count = connection.execute("SELECT COUNT(*) FROM intelligence_particles").fetchone()[0]
    finally:
        connection.close()

    assert ku_count == 2
    assert legacy_count == 2


def test_graph_sync_failure_keeps_documents_retryable(tmp_path) -> None:
    class FailingSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, query: str, **params):
            raise RuntimeError("neo4j unavailable")

    class FailingConnection:
        def session(self):
            return FailingSession()

    from src.knowledge_graph_sync import KnowledgeGraphSync

    db_path = tmp_path / "news.db"
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=True,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
    )
    pipeline.graph_sync = KnowledgeGraphSync(connection=FailingConnection())

    result = pipeline.run()

    assert "neo4j unavailable" in result.errors

    connection = sqlite3.connect(db_path)
    try:
        log_rows = connection.execute(
            "SELECT doc_id, status, error_message FROM knowledge_processing_log ORDER BY doc_id"
        ).fetchall()
    finally:
        connection.close()

    assert [(row[0], row[1], row[2]) for row in log_rows] == [
        ("doc-1", "failed", "neo4j unavailable"),
        ("doc-2", "failed", "neo4j unavailable"),
    ]
