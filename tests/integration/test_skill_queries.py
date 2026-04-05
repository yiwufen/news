"""
Skill-facing contract integration tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from collectors.database import Database
from src.entities import EntityRepository
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
from src.pipeline import ContinuousPipeline
from src.retrieval.indexing import KnowledgeIndexBuilder
from src.skills import run_skill_query


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
                "publish_time": "2026-04-02T09:00:00+00:00",
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


def test_run_skill_query_returns_entity_timeline_contract(tmp_path, monkeypatch) -> None:
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

    result = run_skill_query(raw_query="Show Xiaomi timeline")

    assert result["contract_version"] == "v1"
    assert result["ok"] is True
    assert result["skill_type"] == "entity_timeline"
    assert result["source"] == "knowledge_base"
    assert result["capabilities"]["graph_supported"] is True
    assert result["capabilities"]["timeline_supported"] is True
    assert len(result["payload"]["timeline_events"]) >= 1


def test_run_skill_query_returns_entity_overview_contract(tmp_path, monkeypatch) -> None:
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
                intent=IntentType.ENTITY_OVERVIEW,
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

    result = run_skill_query(raw_query="Show Xiaomi overview")

    assert result["ok"] is True
    assert result["skill_type"] == "entity_overview"
    assert result["payload"]["target_entity"] == "Xiaomi Group"
    assert len(result["payload"]["recent_event_clusters"]) >= 1
    assert isinstance(result["payload"]["supporting_evidence"], list)


def test_run_skill_query_returns_event_analysis_contract(tmp_path, monkeypatch) -> None:
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
                intent=IntentType.EVENT_ANALYSIS,
                entities=["Xiaomi Group"],
                time_range=None,
                filters=QueryFilters(event_types=["policy_sanction"]),
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

    result = run_skill_query(raw_query="Analyze Xiaomi event")

    assert result["ok"] is True
    assert result["skill_type"] == "event_analysis"
    assert result["payload"]["focus_event_types"] == ["policy_sanction"]
    assert len(result["payload"]["event_clusters"]) >= 1
    assert len(result["payload"]["involved_entities"]) >= 1


def test_run_skill_query_handles_direct_articles_with_explicit_graph_capabilities(monkeypatch) -> None:
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

    result = run_skill_query(
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
        graph_enabled=True,
    )

    assert result["source"] == "direct_articles"
    assert result["capabilities"] == {
        "graph_supported": False,
        "graph_used": False,
        "timeline_supported": True,
    }
    assert len(result["payload"]["timeline_events"]) == 1


def test_run_skill_query_falls_back_to_bm25_without_embedding_config(tmp_path, monkeypatch) -> None:
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

    class FakeKnowledgeGraphRetriever:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def search(self, structured_query, *, start_entities):
            from src.graph.knowledge_retrieval import GraphRetrievalResult

            return GraphRetrievalResult.empty(start_entities=start_entities)

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(src.intent, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "IntentClassifier", FakeIntentClassifier)
    monkeypatch.setattr(graph_module, "KnowledgeGraphRetriever", FakeKnowledgeGraphRetriever)

    result = run_skill_query(raw_query="Show Xiaomi timeline")

    assert result["ok"] is True
    assert result["skill_type"] == "entity_timeline"
    assert result["summary"]["knowledge_unit_count"] >= 1
    assert result["capabilities"]["graph_supported"] is True
