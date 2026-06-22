"""
Continuous pipeline integration tests.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from collectors.database import Database
from src.alias_generator import AliasGenerator
from src.entities import Entity, EntityRepository
from src.entity_description import EntityDescriptionGenerator
from src.event_merging import EventCluster
from src.schemas.query import IntentType, QueryFilters, StructuredQuery
from src.knowledge_base import (
    EntityRef,
    EvidenceSpan,
    KnowledgeUnit,
    KnowledgeUnitRepository,
    SourceRef,
    TimeRef,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.knowledge_graph_sync import KnowledgeGraphSync
from src.orchestration import run_pipeline
from src.pipeline import ContinuousPipeline
from src.retrieval.indexing import KnowledgeIndexBuilder

# Disabled enhancement generators for integration tests. Tests use
# StubExtractor (no real LLM) and must not call the real description/alias
# APIs either — doing so would make them flaky and dependent on quota/network.
# EntityEnhancementError fail-fast now propagates these failures instead of
# silently degrading, so injecting disabled generators keeps tests deterministic.
_DISABLED_DESC_GEN = EntityDescriptionGenerator(enable=False)
_DISABLED_ALIAS_GEN = AliasGenerator(enable=False)


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
    def __init__(self) -> None:
        super().__init__(enable_llm=True)

    def extract(self, document, entity_context=None) -> list[KnowledgeUnit]:
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


def build_index_builder(db_path: str) -> KnowledgeIndexBuilder:
    return KnowledgeIndexBuilder(
        knowledge_units=KnowledgeUnitRepository(db_path),
    )


def _xiaomi_timeline_query() -> StructuredQuery:
    return StructuredQuery(
        intent=IntentType.ENTITY_TIMELINE,
        entities=["Xiaomi Group"],
        time_range=None,
        filters=QueryFilters(),
        original_query="Show the Xiaomi Group timeline",
    )


def _xiaomi_relationship_query() -> StructuredQuery:
    return StructuredQuery(
        intent=IntentType.RELATIONSHIP_QUERY,
        entities=["Xiaomi Group"],
        time_range=None,
        filters=QueryFilters(),
        original_query="Show Xiaomi Group relationships",
    )


def test_run_continuous_builds_knowledge_tables_without_legacy_backfill(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
        index_builder=build_index_builder(str(db_path)),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
    )
    result = pipeline.run()

    assert result.knowledge_units_extracted == 2
    assert result.knowledge_units_saved == 2
    assert result.entities_saved >= 1
    assert result.clusters_saved >= 1
    assert not hasattr(result, "particles_extracted")
    assert not hasattr(result, "particles_saved")
    assert not hasattr(result, "particles")

    connection = sqlite3.connect(db_path)
    try:
        ku_count = connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
        fts_count = connection.execute("SELECT COUNT(*) FROM knowledge_units_fts").fetchone()[0]
        entity_count = connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        cluster_count = connection.execute("SELECT COUNT(*) FROM event_clusters").fetchone()[0]
        cluster_payload = json.loads(
            connection.execute(
                "SELECT payload FROM event_clusters ORDER BY cluster_id ASC LIMIT 1"
            ).fetchone()[0]
        )
        log_rows = connection.execute(
            "SELECT doc_id, status, knowledge_units_count FROM knowledge_processing_log ORDER BY doc_id"
        ).fetchall()
    finally:
        connection.close()

    assert ku_count == 2
    assert fts_count == 2
    assert entity_count >= 1
    assert cluster_count >= 1
    assert cluster_payload["member_count"] >= 1
    assert cluster_payload["source_count"] >= 1
    assert "representative_ku_id" in cluster_payload
    assert "summary_variants" in cluster_payload
    assert "event_time_variants" in cluster_payload
    assert "conflict_reasons" in cluster_payload
    assert [(row[0], row[1], row[2]) for row in log_rows] == [
        ("doc-1", "success", 1),
        ("doc-2", "success", 1),
    ]


def test_run_pipeline_queries_new_knowledge_store(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "data" / "news.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
        index_builder=build_index_builder(str(db_path)),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
    )
    pipeline.run()
    entity_repo = EntityRepository(str(db_path))
    entities = entity_repo.get_all()
    for entity in entities:
        if entity.canonical_name == "Xiaomi Group" and "小米集团" not in entity.aliases:
            entity.aliases.append("小米集团")
    entity_repo.save_batch(entities)

    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._searcher = original_searcher_cls(
                db_path=str(db_path),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    class FakeKnowledgeGraphRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities, **kwargs):
            from src.graph.knowledge_retrieval import GraphRetrievalResult

            return GraphRetrievalResult.empty(start_entities=start_entities)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    result = run_pipeline(structured_query=_xiaomi_timeline_query())

    assert result.source == "knowledge_base"
    assert result.query.entities == ["Xiaomi Group"]
    assert len(result.knowledge_units) >= 1
    assert len(result.entities) >= 1
    assert result.retrieval.retrieval_mode == "timeline"
    assert result.retrieval.bm25_count >= 1
    assert result.graph.graph_used is False
    assert result.graph.candidate_count == 0
    assert len(result.event_clusters) >= 1
    assert result.event_clusters[0]["source_count"] >= 1
    assert result.graph.graph_enabled is True
    assert result.graph.graph_used is False
    assert result.graph_result is not None
    assert result.graph_result.nodes == []
    assert result.graph_result.paths == []
    assert "conflict_reasons" in result.event_clusters[0]
    assert "summary_variants" in result.event_clusters[0]
    assert not hasattr(result, "report")
    assert not hasattr(result, "risk_assessment")
    assert not hasattr(result, "comparison_report")
    assert not hasattr(result, "event_impact")
    assert not hasattr(result, "particles_count")


def test_run_pipeline_returns_transient_entities_for_direct_articles(monkeypatch) -> None:
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._searcher = original_searcher_cls(
                extractor=StubExtractor(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)

    result = run_pipeline(
        structured_query=_xiaomi_timeline_query(),
        articles=[
            {
                "doc_id": "doc-1",
                "title": "Xiaomi Group receives a regulatory penalty",
                "content": "Xiaomi Group received a regulatory penalty and started remediation.",
                "publish_time": "2026-04-01T09:00:00+00:00",
                "source_name": "test-source",
                "source_type": "news",
                "category": "company",
                "raw_tags": [],
            }
        ],
    )

    assert result.source == "direct_articles"
    assert len(result.knowledge_units) == 1
    assert len(result.entities) == 1
    assert len(result.event_clusters) == 1
    assert result.retrieval.retrieval_mode == "bm25"
    assert result.graph.graph_used is False
    assert result.entities[0]["entity_id"] == result.knowledge_units[0]["entities"][0]["entity_id"]
    assert result.event_clusters[0]["cluster_id"] == result.knowledge_units[0]["cluster_id"]
    assert not hasattr(result, "event_impact")


def test_run_pipeline_omits_graph_edges_when_disabled(monkeypatch) -> None:
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._searcher = original_searcher_cls(
                extractor=StubExtractor(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)

    result = run_pipeline(
        structured_query=_xiaomi_timeline_query(),
        articles=[
            {
                "doc_id": "doc-1",
                "title": "Xiaomi Group receives a regulatory penalty",
                "content": "Xiaomi Group received a regulatory penalty and started remediation.",
                "publish_time": "2026-04-01T09:00:00+00:00",
                "source_name": "test-source",
                "source_type": "news",
                "category": "company",
                "raw_tags": [],
            }
        ],
        graph_enabled=False,
    )

    assert result.graph.graph_enabled is False
    assert result.graph.graph_used is False
    assert result.graph_result is None
    assert result.graph.graph_used is False
    assert len(result.knowledge_units) == 1
    assert len(result.entities) == 1
    assert len(result.event_clusters) == 1
    assert not hasattr(result, "comparison_report")


def test_run_continuous_reuses_stable_knowledge_ids_on_rebuild(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=False,
        db_path=str(db_path),
        extractor=StubExtractor(),
        index_builder=build_index_builder(str(db_path)),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
    )

    first = pipeline.run()
    second = pipeline.run()

    assert first.knowledge_units_saved == 2
    assert second.knowledge_units_saved == 2

    connection = sqlite3.connect(db_path)
    try:
        ku_count = connection.execute("SELECT COUNT(*) FROM knowledge_units").fetchone()[0]
    finally:
        connection.close()

    assert ku_count == 2


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
        index_builder=build_index_builder(str(db_path)),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
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
        ("doc-1", "success", None),
        ("doc-2", "success", None),
    ]


def test_index_failure_does_not_make_persisted_documents_retryable(tmp_path) -> None:
    class FailingIndexBuilder:
        def build_for_units(self, units: list[KnowledgeUnit]) -> int:
            raise RuntimeError("embedding API unavailable")

    db_path = tmp_path / "news.db"
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
        index_builder=cast(Any, FailingIndexBuilder()),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
    )

    first = pipeline.run()
    second = pipeline.run()

    assert any("embedding API unavailable" in err for err in first.errors)
    assert second.knowledge_units_extracted == 0

    connection = sqlite3.connect(db_path)
    try:
        log_rows = connection.execute(
            "SELECT doc_id, status, error_message FROM knowledge_processing_log ORDER BY doc_id"
        ).fetchall()
    finally:
        connection.close()

    assert [(row[0], row[1], row[2]) for row in log_rows] == [
        ("doc-1", "success", "index failed: embedding API unavailable"),
        ("doc-2", "success", "index failed: embedding API unavailable"),
    ]


def test_run_continuous_graph_sync_serializes_entity_identifiers(tmp_path) -> None:
    class _Result:
        def __init__(self, rows: list) -> None:
            self._rows = rows

        def data(self):
            return self._rows

    class RecordingSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, query: str, **params):
            self.calls.append((query, params))
            # The pipeline's new prune step reads results via .data(). Return
            # empty rows for the prune discovery query so prune finds no
            # orphans and is a no-op; write-only queries stay None-returning.
            if "NOT o.id IN $live_ids" in query:
                return _Result([])
            return None

    class RecordingConnection:
        def __init__(self, session: RecordingSession) -> None:
            self._session = session

        def session(self):
            return self._session

    db_path = tmp_path / "news.db"
    seed_articles(str(db_path))
    session = RecordingSession()

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=True,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
        index_builder=build_index_builder(str(db_path)),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
    )
    pipeline.graph_sync = KnowledgeGraphSync(connection=RecordingConnection(session))

    result = pipeline.run()

    assert result.errors == []
    entity_write = next(params for query, params in session.calls if "MERGE (e:Entity {id: $id})" in query)
    cluster_write = next(params for query, params in session.calls if "MERGE (c:EventCluster {id: $id})" in query)
    assert "identifiers_json" in entity_write
    assert isinstance(entity_write["identifiers_json"], str)
    assert "summary_variants_json" in cluster_write
    assert "event_time_variants_json" in cluster_write
    assert "representative_ku_id" in cluster_write


def test_run_pipeline_repairs_legacy_event_cluster_payloads(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "data" / "news.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
        index_builder=build_index_builder(str(db_path)),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
    )
    pipeline.run()

    connection = sqlite3.connect(db_path)
    try:
        cluster_id, payload = connection.execute(
            "SELECT cluster_id, payload FROM event_clusters ORDER BY cluster_id ASC LIMIT 1"
        ).fetchone()
        legacy_payload = json.loads(payload)
        for key in (
            "representative_ku_id",
            "member_count",
            "source_count",
            "summary_variants",
            "event_time_variants",
            "conflict_reasons",
        ):
            legacy_payload.pop(key, None)
        connection.execute(
            "UPDATE event_clusters SET payload = ? WHERE cluster_id = ?",
            (json.dumps(legacy_payload, ensure_ascii=False), cluster_id),
        )
        connection.commit()
    finally:
        connection.close()

    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._searcher = original_searcher_cls(
                db_path=str(db_path),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    class FakeKnowledgeGraphRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities, **kwargs):
            from src.graph.knowledge_retrieval import GraphRetrievalResult

            return GraphRetrievalResult.empty(start_entities=start_entities)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    result = run_pipeline(structured_query=_xiaomi_timeline_query())

    assert len(result.event_clusters) >= 1
    assert result.event_clusters[0]["member_count"] >= 1
    assert "representative_ku_id" in result.event_clusters[0]
    assert "summary_variants" in result.event_clusters[0]


def test_run_pipeline_relationship_query_returns_formal_graph_results(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "data" / "news.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    seed_articles(str(db_path))

    pipeline = ContinuousPipeline(
        batch_size=10,
        graph_enabled=False,
        incremental=True,
        db_path=str(db_path),
        extractor=StubExtractor(),
        index_builder=build_index_builder(str(db_path)),
        description_generator=_DISABLED_DESC_GEN,
        alias_generator=_DISABLED_ALIAS_GEN,
    )
    pipeline.run()

    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._searcher = original_searcher_cls(
                db_path=str(db_path),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    class FakeKnowledgeGraphRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities, **kwargs):
            from src.graph.knowledge_retrieval import GraphRetrievalResult

            start_entity = start_entities[0]
            return GraphRetrievalResult(
                used=True,
                nodes=[
                    {"id": start_entity.entity_id, "type": "Entity", "name": start_entity.canonical_name},
                    {"id": "clu_1", "type": "EventCluster", "name": "Xiaomi relationship cluster"},
                    {"id": "ent_partner", "type": "Entity", "name": "Partner Co"},
                ],
                edges=[
                    {"source": start_entity.entity_id, "target": "clu_1", "type": "INVOLVED_IN"},
                    {"source": "ent_partner", "target": "clu_1", "type": "INVOLVED_IN"},
                ],
                paths=[
                    {
                        "path_type": "Entity->EventCluster->Entity",
                        "start_entity_id": start_entity.entity_id,
                        "cluster_id": "clu_1",
                        "neighbor_entity_id": "ent_partner",
                        "member_ku_ids": ["ku_1"],
                    }
                ],
                summary={
                    "start_entities": [{"entity_id": start_entity.entity_id, "name": start_entity.canonical_name}],
                    "event_cluster_count": 1,
                    "expanded_entity_count": 1,
                    "expanded": True,
                },
                hit_reasons={"ent_partner": ["co_involved_via:clu_1"]},
                candidate_count=1,
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    result = run_pipeline(structured_query=_xiaomi_relationship_query(), graph_enabled=True, db_path=str(db_path))

    assert result.graph.graph_enabled is True
    assert result.graph.graph_used is True
    assert result.graph_result is not None
    assert len(result.graph_result.nodes) == 3
    assert len(result.graph_result.edges) == 2
    assert result.graph_result.paths[0]["path_type"] == "Entity->EventCluster->Entity"
    assert result.graph.candidate_count == 1
    assert result.graph.hit_reasons == {"ent_partner": ["co_involved_via:clu_1"]}


def test_run_pipeline_rejects_relationship_query_for_direct_articles(monkeypatch) -> None:
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self._searcher = original_searcher_cls(
                extractor=StubExtractor(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)

    result = run_pipeline(
        structured_query=_xiaomi_relationship_query(),
        articles=[
            {
                "doc_id": "doc-1",
                "title": "Xiaomi Group receives a regulatory penalty",
                "content": "Xiaomi Group received a regulatory penalty and started remediation.",
                "publish_time": "2026-04-01T09:00:00+00:00",
                "source_name": "test-source",
                "source_type": "news",
                "category": "company",
                "raw_tags": [],
            }
        ],
        graph_enabled=True,
    )

    assert result.source == "direct_articles"
    assert result.graph.graph_enabled is True
    assert result.graph.graph_used is False
    assert result.graph_result is not None
    assert result.graph_result.nodes == []
    assert result.graph_result.edges == []
    assert result.graph_result.paths == []
