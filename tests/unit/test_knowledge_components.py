"""
Knowledge pipeline component tests.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from src.entities import Entity, EntityRepository, EntityResolver
from src.event_clustering import EventCluster, EventClusterRepository, EventClusterer
from src.intent.classifier import IntentClassifier
from src.intent.models import IntentType, QueryFilters, StructuredQuery, TimeRange
from src.knowledge_base import (
    EntityRef,
    EvidenceSpan,
    KnowledgeUnit,
    KnowledgeUnitRepository,
    RawDocument,
    SourceRef,
    TimeRef,
    adapt_article_to_raw_document,
)
from src.knowledge_extractor import KnowledgeExtractor
from src.knowledge_graph_sync import KnowledgeGraphSync
from src.retrieval.embedding_client import OpenAIEmbeddingClient
from src.retrieval.indexing import KnowledgeIndexBuilder
from src.retrieval.knowledge_search import KnowledgeSearchRequest, KnowledgeSearcher


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
            float(lower.count("impact") + lower.count("update") + lower.count("\u5f71\u54cd")),
            float(lower.count("market") + lower.count("\u5e02\u573a")),
        ]


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
    assert entity_write["primary_identifier"] is None
    assert entity_write["identifiers_json"] == "{}"


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


def test_intent_classifier_parses_chinese_and_english_time_ranges() -> None:
    classifier = IntentClassifier()
    ref = datetime(2026, 4, 4, tzinfo=UTC).date()

    last_year = classifier.parse_time_range(
        "\u67e5\u770b\u5c0f\u7c73\u96c6\u56e2\u8fc7\u53bb\u4e00\u5e74\u505a\u7684\u4e8b\u60c5",
        ref=ref,
    )
    assert last_year == TimeRange(start=datetime(2025, 4, 4, tzinfo=UTC).date(), end=ref)

    ytd = classifier.parse_time_range("show xiaomi group year to date timeline", ref=ref)
    assert ytd == TimeRange(start=datetime(2026, 1, 1, tzinfo=UTC).date(), end=ref)


def test_intent_classifier_supplements_entities_from_repository_when_llm_is_incomplete(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    repo = EntityRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    repo.save_batch(
        [
            Entity(
                entity_type="Company",
                canonical_name="\u5c0f\u7c73\u96c6\u56e2",
                aliases=["\u5c0f\u7c73", "Xiaomi Group"],
                identifiers={},
                source_ku_ids=["seed"],
                created_at=now,
                updated_at=now,
            )
        ]
    )

    classifier = IntentClassifier(entity_repository=repo)
    classifier._call_llm = lambda query: {  # type: ignore[method-assign]
        "intent": "ENTITY_TIMELINE",
        "entities": [],
        "time_expression": "",
        "filters": {},
        "confidence": 0.2,
    }

    parsed = classifier.parse("\u67e5\u770b\u5c0f\u7c73\u96c6\u56e2\u8fc7\u53bb\u4e00\u5e74\u505a\u7684\u4e8b\u60c5")

    assert parsed.intent is IntentType.ENTITY_TIMELINE
    assert parsed.entities == ["\u5c0f\u7c73\u96c6\u56e2"]
    assert parsed.time_range is not None


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


def test_knowledge_index_builder_saves_embeddings(tmp_path) -> None:
    db_path = tmp_path / "news.db"
    entity_repo = EntityRepository(str(db_path))
    repo = KnowledgeUnitRepository(str(db_path))
    now = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="Xiaomi Group",
        aliases=["\u5c0f\u7c73\u96c6\u56e2"],
        identifiers={},
        source_ku_ids=["ku_1"],
        created_at=now,
        updated_at=now,
    )
    entity_repo.save_batch([entity])

    unit = build_unit()
    unit.entities[0].entity_id = entity.entity_id
    unit.entities[0].entity_type = entity.entity_type
    repo.save_batch([unit])

    builder = KnowledgeIndexBuilder(repo, entity_repo, embedding_client=StubEmbeddingClient())
    saved = builder.build_for_units([unit])
    embeddings = repo.get_embeddings(ku_ids=[unit.ku_id])

    assert saved == 1
    assert len(embeddings) == 1
    assert embeddings[0].embedding_model == "test-embedding-3-small"
    assert embeddings[0].embedding_dim == 4


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
    KnowledgeIndexBuilder(
        KnowledgeUnitRepository(str(db_path)),
        entity_repo,
        embedding_client=StubEmbeddingClient(),
    ).build_for_units([unit])

    searcher = KnowledgeSearcher(
        db_path=str(db_path),
        extractor=KnowledgeExtractor(enable_llm=False),
        embedding_client=StubEmbeddingClient(),
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
    assert result.vector_count == 1
    assert result.hit_scores[result.knowledge_units[0].ku_id]["sources"] == ["bm25", "vector"]


def test_knowledge_searcher_requires_embedding_config_for_hybrid_search(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "news.db"
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    searcher = KnowledgeSearcher(
        db_path=str(db_path),
        extractor=KnowledgeExtractor(enable_llm=False),
    )

    with pytest.raises(ValueError, match="OPENAI_EMBEDDING_API_KEY or OPENAI_API_KEY"):
        searcher.search(
            KnowledgeSearchRequest(
                structured_query=StructuredQuery(
                    intent=IntentType.ENTITY_TIMELINE,
                    entities=[],
                    time_range=None,
                    filters=QueryFilters(),
                    original_query="show xiaomi timeline",
                    confidence=1.0,
                ),
            )
        )


def test_embedding_client_prefers_embedding_specific_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embed-key")
    monkeypatch.setenv("OPENAI_API_KEY", "shared-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://embedding.example.com/v1")

    client = OpenAIEmbeddingClient()

    assert client.api_key == "embed-key"
    assert client.base_url == "https://embedding.example.com/v1"
