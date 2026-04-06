"""
Continuous pipeline integration tests.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from collectors.database import Database
from src.entities import Entity, EntityRepository
from src.intent.models import IntentType, QueryFilters, StructuredQuery
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


class StubEmbeddingClient:
    def __init__(self) -> None:
        self.model = "test-embedding-3-small"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        lower = text.lower()
        return [
            float(len(lower)),
            float(lower.count("xiaomi") + lower.count("\u5c0f\u7c73")),
            float(lower.count("penalty") + lower.count("sanction") + lower.count("\u5904\u7f5a")),
            float(lower.count("update") + lower.count("progress") + lower.count("\u66f4\u65b0")),
        ]


def build_index_builder(db_path: str) -> KnowledgeIndexBuilder:
    return KnowledgeIndexBuilder(
        knowledge_units=KnowledgeUnitRepository(db_path),
        entities=EntityRepository(db_path),
        embedding_client=StubEmbeddingClient(),
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
        embedding_count = connection.execute("SELECT COUNT(*) FROM knowledge_unit_embeddings").fetchone()[0]
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
    assert embedding_count == 2
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
    )
    pipeline.run()
    entity_repo = EntityRepository(str(db_path))
    entities = entity_repo.get_all()
    for entity in entities:
        if entity.canonical_name == "Xiaomi Group" and "小米集团" not in entity.aliases:
            entity.aliases.append("小米集团")
    entity_repo.save_batch(entities)

    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    import src.intent
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self) -> None:
            self._searcher = original_searcher_cls(
                db_path=str(db_path),
                embedding_client=StubEmbeddingClient(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    class FakeKnowledgeGraphRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities):
            from src.graph.knowledge_retrieval import GraphRetrievalResult

            return GraphRetrievalResult.empty(start_entities=start_entities)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    result = run_pipeline(raw_query="Show the Xiaomi Group timeline")

    assert result["source"] == "knowledge_base"
    assert result["query"]["entities"] == ["Xiaomi Group"]
    assert len(result["knowledge_units"]) >= 1
    assert len(result["entities"]) >= 1
    assert result["retrieval"]["retrieval_mode"] == "hybrid"
    assert result["retrieval"]["bm25_count"] >= 1
    assert result["retrieval"]["vector_count"] >= 1
    assert result["retrieval"]["graph_used"] is False
    assert result["retrieval"]["graph_candidate_count"] == 0
    assert result["timeline_data"]["entity"] == "Xiaomi Group"
    assert result["timeline_data"]["timeline"]["total_events"] >= 1
    assert len(result["event_clusters"]) >= 1
    assert result["event_clusters"][0]["source_count"] >= 1
    assert result["graph"]["enabled"] is True
    assert result["graph"]["used"] is False
    assert result["graph"]["nodes"] == []
    assert result["graph"]["paths"] == []
    assert "conflict_reasons" in result["event_clusters"][0]
    assert "summary_variants" in result["event_clusters"][0]
    assert "report" not in result
    assert "risk_assessment" not in result
    assert "comparison_report" not in result
    assert "event_impact" not in result
    assert "particles_count" not in result


def test_run_pipeline_falls_back_to_bm25_without_embedding_config(tmp_path, monkeypatch) -> None:
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

    import src.intent
    import src.orchestration.graph as graph_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(
        graph_module,
        "KnowledgeGraphRetriever",
        type(
            "FakeKnowledgeGraphRetriever",
            (),
            {
                "__init__": lambda self, *args, **kwargs: None,
                "search": lambda self, structured_query, *, start_entities: __import__(
                    "src.graph.knowledge_retrieval",
                    fromlist=["GraphRetrievalResult"],
                ).GraphRetrievalResult.empty(start_entities=start_entities),
            },
        ),
    )

    result = run_pipeline(raw_query="Show the Xiaomi Group timeline")

    assert result["source"] == "knowledge_base"
    assert result["retrieval"]["retrieval_mode"] == "bm25_only"
    assert result["retrieval"]["bm25_count"] >= 1
    assert result["retrieval"]["vector_count"] == 0
    assert len(result["knowledge_units"]) >= 1
    assert "risk_assessment" not in result


def test_run_pipeline_returns_transient_entities_for_direct_articles(monkeypatch) -> None:
    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    import src.intent
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self) -> None:
            self._searcher = original_searcher_cls(
                extractor=StubExtractor(),
                embedding_client=StubEmbeddingClient(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)

    result = run_pipeline(
        raw_query="Show the Xiaomi Group timeline",
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

    assert result["source"] == "direct_articles"
    assert len(result["knowledge_units"]) == 1
    assert len(result["entities"]) == 1
    assert len(result["event_clusters"]) == 1
    assert result["retrieval"]["retrieval_mode"] == "hybrid"
    assert result["retrieval"]["graph_used"] is False
    assert result["entities"][0]["entity_id"] == result["knowledge_units"][0]["entities"][0]["entity_id"]
    assert result["event_clusters"][0]["cluster_id"] == result["knowledge_units"][0]["cluster_id"]
    assert "event_impact" not in result


def test_run_pipeline_omits_graph_edges_when_disabled(monkeypatch) -> None:
    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    import src.intent
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self) -> None:
            self._searcher = original_searcher_cls(
                extractor=StubExtractor(),
                embedding_client=StubEmbeddingClient(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)

    result = run_pipeline(
        raw_query="Show the Xiaomi Group timeline",
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

    assert result["graph"]["enabled"] is False
    assert result["graph"]["used"] is False
    assert result["graph"]["nodes"] == []
    assert result["graph"]["edges"] == []
    assert result["graph"]["paths"] == []
    assert result["retrieval"]["graph_used"] is False
    assert len(result["knowledge_units"]) == 1
    assert len(result["entities"]) == 1
    assert len(result["event_clusters"]) == 1
    assert "comparison_report" not in result


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
    )

    first = pipeline.run()
    second = pipeline.run()

    assert "[index] embedding API unavailable" in first.errors
    assert second.knowledge_units_extracted == 0

    connection = sqlite3.connect(db_path)
    try:
        log_rows = connection.execute(
            "SELECT doc_id, status, error_message FROM knowledge_processing_log ORDER BY doc_id"
        ).fetchall()
    finally:
        connection.close()

    assert [(row[0], row[1], row[2]) for row in log_rows] == [
        ("doc-1", "success", "embedding API unavailable"),
        ("doc-2", "success", "embedding API unavailable"),
    ]


def test_run_pipeline_supplements_entities_and_time_range_when_llm_response_is_incomplete(
    tmp_path,
    monkeypatch,
) -> None:
    chinese_alias = "\u5c0f\u7c73\u96c6\u56e2"
    chinese_query = "\u67e5\u770b\u5c0f\u7c73\u96c6\u56e2\u8fc7\u53bb\u4e00\u5e74\u505a\u7684\u4e8b\u60c5"
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
    )
    pipeline.run()
    entity_repo = EntityRepository(str(db_path))
    entities = entity_repo.get_all()
    for entity in entities:
        if entity.canonical_name == "Xiaomi Group" and chinese_alias not in entity.aliases:
            entity.aliases.append(chinese_alias)
    entity_repo.save_batch(entities)

    class FallbackIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            from src.entities import EntityRepository
            from src.intent.classifier import IntentClassifier

            classifier = IntentClassifier(entity_repository=EntityRepository(str(db_path)))
            classifier._call_llm = lambda query: {  # type: ignore[method-assign]
                "intent": "ENTITY_TIMELINE",
                "entities": [],
                "time_expression": "",
                "filters": {},
                "confidence": 0.1,
            }
            original_parse_time_range = classifier.parse_time_range
            classifier.parse_time_range = lambda expression, ref=None: original_parse_time_range(  # type: ignore[method-assign]
                expression,
                ref=datetime(2026, 4, 4, tzinfo=UTC).date(),
            )
            return classifier.parse(raw_query)

    import src.intent
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self) -> None:
            self._searcher = original_searcher_cls(
                db_path=str(db_path),
                embedding_client=StubEmbeddingClient(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(src.intent, "IntentClassifier", FallbackIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FallbackIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)

    result = run_pipeline(raw_query=chinese_query, graph_enabled=False)

    assert result["query"]["entities"] == ["Xiaomi Group"]
    assert result["query"]["time_range"] == {
        "start": "2025-04-04",
        "end": "2026-04-04",
    }
    assert len(result["knowledge_units"]) >= 1


def test_run_continuous_graph_sync_serializes_entity_identifiers(tmp_path) -> None:
    class RecordingSession:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, query: str, **params):
            self.calls.append((query, params))
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

    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.ENTITY_TIMELINE,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    import src.intent
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self) -> None:
            self._searcher = original_searcher_cls(
                db_path=str(db_path),
                embedding_client=StubEmbeddingClient(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    class FakeKnowledgeGraphRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities):
            from src.graph.knowledge_retrieval import GraphRetrievalResult

            return GraphRetrievalResult.empty(start_entities=start_entities)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    result = run_pipeline(raw_query="Show the Xiaomi Group timeline")

    assert len(result["event_clusters"]) >= 1
    assert result["event_clusters"][0]["member_count"] >= 1
    assert "representative_ku_id" in result["event_clusters"][0]
    assert "summary_variants" in result["event_clusters"][0]


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
    )
    pipeline.run()

    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.RELATIONSHIP_QUERY,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    import src.intent
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self) -> None:
            self._searcher = original_searcher_cls(
                db_path=str(db_path),
                embedding_client=StubEmbeddingClient(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    class FakeKnowledgeGraphRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities):
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
                expanded_cluster_count=1,
                expanded_entity_count=1,
            )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    result = run_pipeline(raw_query="Show Xiaomi Group relationships", graph_enabled=True)

    assert result["graph"]["enabled"] is True
    assert result["graph"]["used"] is True
    assert len(result["graph"]["nodes"]) == 3
    assert len(result["graph"]["edges"]) == 2
    assert result["graph"]["paths"][0]["path_type"] == "Entity->EventCluster->Entity"
    assert result["retrieval"]["graph_used"] is True
    assert result["retrieval"]["graph_candidate_count"] == 1
    assert result["retrieval"]["graph_hit_reasons"] == {"ent_partner": ["co_involved_via:clu_1"]}


def test_run_pipeline_event_impact_analysis_expands_from_focus_cluster_entities(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "data" / "news.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime(2026, 4, 2, 9, 0, tzinfo=UTC)
    entity_repo = EntityRepository(str(db_path))
    entity_repo.save_batch(
        [
            Entity(
                entity_id="ent_xiaomi",
                entity_type="Company",
                canonical_name="Xiaomi Group",
                aliases=[],
                identifiers={},
                source_ku_ids=["ku_focus"],
                created_at=now,
                updated_at=now,
            ),
            Entity(
                entity_id="ent_partner",
                entity_type="Organization",
                canonical_name="Partner Co",
                aliases=[],
                identifiers={},
                source_ku_ids=["ku_focus"],
                created_at=now,
                updated_at=now,
            ),
        ]
    )

    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.EVENT_IMPACT_ANALYSIS,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    import src.intent
    import src.orchestration.graph as graph_module

    class FakeSearchResult:
        def to_dict(self) -> dict[str, Any]:
            return {
                "knowledge_units": [
                    {
                        "ku_id": "ku_focus",
                        "unit_kind": "event",
                        "unit_type": "policy_sanction",
                        "summary": "Xiaomi and Partner face a sanction event",
                        "entities": [
                            {"entity_id": "ent_xiaomi", "mention": "Xiaomi Group"},
                            {"entity_id": "ent_partner", "mention": "Partner Co"},
                        ],
                        "source": {"doc_id": "doc-1", "source_name": "test-source", "url": None},
                        "evidence": [{"text": "Focus event evidence"}],
                        "time": {
                            "event_time": "2026-04-02T09:00:00+00:00",
                            "published_at": "2026-04-02T09:00:00+00:00",
                            "extracted_at": "2026-04-02T09:05:00+00:00",
                        },
                        "confidence": 0.95,
                        "tags": [],
                        "relation_hints": [],
                        "cluster_id": "clu_focus",
                        "conflict_status": "none",
                        "status": "active",
                    }
                ],
                "entities": [
                    {
                        "entity_id": "ent_xiaomi",
                        "entity_type": "Company",
                        "canonical_name": "Xiaomi Group",
                        "aliases": [],
                        "identifiers": {},
                        "description": None,
                        "tags": [],
                        "source_ku_ids": ["ku_focus"],
                        "created_at": "2026-04-02T09:00:00+00:00",
                        "updated_at": "2026-04-02T09:00:00+00:00",
                    },
                    {
                        "entity_id": "ent_partner",
                        "entity_type": "Organization",
                        "canonical_name": "Partner Co",
                        "aliases": [],
                        "identifiers": {},
                        "description": None,
                        "tags": [],
                        "source_ku_ids": ["ku_focus"],
                        "created_at": "2026-04-02T09:00:00+00:00",
                        "updated_at": "2026-04-02T09:00:00+00:00",
                    },
                ],
                "event_clusters": [
                    {
                        "cluster_id": "clu_focus",
                        "cluster_type": "policy_sanction",
                        "title": "Focus sanction event",
                        "summary": "Focus sanction event",
                        "entity_ids": ["ent_xiaomi", "ent_partner"],
                        "primary_entity_id": "ent_xiaomi",
                        "time_anchor": "2026-04-02T09:00:00+00:00",
                        "time_range": {
                            "start": "2026-04-02T09:00:00+00:00",
                            "end": "2026-04-03T09:00:00+00:00",
                        },
                        "member_ku_ids": ["ku_focus"],
                        "source_doc_ids": ["doc-1"],
                        "conflict_status": "none",
                        "cluster_confidence": 0.95,
                        "representative_ku_id": "ku_focus",
                        "member_count": 1,
                        "source_count": 1,
                        "summary_variants": [],
                        "event_time_variants": [],
                        "conflict_reasons": [],
                        "updated_at": "2026-04-03T09:00:00+00:00",
                    }
                ],
                "total_count": 1,
                "retrieval": {
                    "retrieval_mode": "hybrid",
                    "bm25_count": 1,
                    "vector_count": 1,
                    "fusion_count": 1,
                    "applied_filters": {
                        "entities": ["Xiaomi Group"],
                        "resolved_entity_ids": ["ent_xiaomi"],
                        "event_types": [],
                        "time_range": None,
                    },
                    "hit_scores": {},
                },
            }

    class FakeKnowledgeSearcher:
        def search(self, request):
            return FakeSearchResult()

        def search_articles(self, articles, request):
            return FakeSearchResult()

    class FakeKnowledgeGraphRetriever:
        calls: list[list[str]] = []

        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities):
            from src.graph.knowledge_retrieval import GraphRetrievalResult

            self.calls.append([entity.entity_id for entity in start_entities])
            return GraphRetrievalResult.empty(start_entities=start_entities)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    run_pipeline(raw_query="Analyze Xiaomi event impact", graph_enabled=True)

    assert len(FakeKnowledgeGraphRetriever.calls) == 1
    assert sorted(FakeKnowledgeGraphRetriever.calls[0]) == ["ent_partner", "ent_xiaomi"]


def test_run_pipeline_rejects_relationship_query_for_direct_articles(monkeypatch) -> None:
    class FakeIntentClassifier:
        def parse(self, raw_query: str) -> StructuredQuery:
            return StructuredQuery(
                intent=IntentType.RELATIONSHIP_QUERY,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(),
                original_query=raw_query,
            )

    import src.intent
    import src.orchestration.graph as graph_module

    original_searcher_cls = graph_module.KnowledgeSearcher

    class FakeKnowledgeSearcher:
        def __init__(self) -> None:
            self._searcher = original_searcher_cls(
                extractor=StubExtractor(),
                embedding_client=StubEmbeddingClient(),
            )

        def search(self, request):
            return self._searcher.search(request)

        def search_articles(self, articles, request):
            return self._searcher.search_articles(articles, request)

    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeSearcher", FakeKnowledgeSearcher)

    result = run_pipeline(
        raw_query="Show Xiaomi Group relationships",
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

    assert result["source"] == "direct_articles"
    assert result["verification"]["passed"] is False
    assert result["errors"] == ["关系查询当前仅支持 knowledge_base 检索源，不支持 direct articles 输入"]
    assert result["graph"]["enabled"] is True
    assert result["graph"]["used"] is False
    assert result["graph"]["nodes"] == []
    assert result["graph"]["edges"] == []
    assert result["graph"]["paths"] == []
