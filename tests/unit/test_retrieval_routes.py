"""
Two-route retrieval tests: entity route (strict event recall + semantic filter
+ rerank) and text route (hybrid recall + rerank), plus the SiliconFlow
reranker client (mocked transport — never real network).
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from src.entities import Entity, EntityRepository
from src.event_merging import EventCluster, EventClusterRepository
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
from src.retrieval.knowledge_search import KnowledgeSearchRequest, KnowledgeSearcher
from src.retrieval.reranker import SiliconFlowReranker, try_create_reranker

NOW = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# SiliconFlow reranker client (httpx.MockTransport)
# ---------------------------------------------------------------------------


def _install_transport(monkeypatch, handler) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    monkeypatch.setattr(httpx, "post", client.post)
    monkeypatch.setattr("src.retrieval.reranker.time.sleep", lambda _s: None)
    return requests


def _make_reranker(monkeypatch, key: str = "sk-test") -> SiliconFlowReranker:
    monkeypatch.setenv("SILICONFLOW_API_KEY", key)
    monkeypatch.setenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    return SiliconFlowReranker()


def test_reranker_parses_and_sorts_response(monkeypatch) -> None:
    payload = {
        "results": [
            {"index": 0, "relevance_score": 0.42},
            {"index": 2, "relevance_score": 0.91},
            {"index": 1, "relevance_score": 0.77},
        ]
    }
    requests = _install_transport(
        monkeypatch, lambda req: httpx.Response(200, json=payload)
    )
    reranker = _make_reranker(monkeypatch)

    ranked = reranker.rerank("哪家公司发布了财报", ["a", "b", "c"])

    assert ranked == [(2, 0.91), (1, 0.77), (0, 0.42)]
    assert len(requests) == 1
    body = requests[0].read()
    assert b'"model":"BAAI/bge-reranker-v2-m3"' in body
    assert requests[0].url.host == "api.siliconflow.cn"
    assert requests[0].url.path == "/v1/rerank"
    assert requests[0].headers["Authorization"] == "Bearer sk-test"


def test_reranker_empty_documents_short_circuits(monkeypatch) -> None:
    requests = _install_transport(
        monkeypatch, lambda req: httpx.Response(200, json={"results": []})
    )
    reranker = _make_reranker(monkeypatch)

    assert reranker.rerank("q", []) == []
    assert requests == []


def test_reranker_retries_then_raises(monkeypatch) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="boom")

    _install_transport(monkeypatch, handler)
    reranker = _make_reranker(monkeypatch)

    with pytest.raises(RuntimeError, match="after 3 retries"):
        reranker.rerank("q", ["a"])
    assert calls["n"] == 3


def test_try_create_reranker_env_gates(monkeypatch) -> None:
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("KNOWLEDGE_RERANK_DISABLED", raising=False)
    assert try_create_reranker() is None

    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-x")
    assert isinstance(try_create_reranker(), SiliconFlowReranker)

    monkeypatch.setenv("KNOWLEDGE_RERANK_DISABLED", "1")
    assert try_create_reranker() is None


# ---------------------------------------------------------------------------
# Route fixtures
# ---------------------------------------------------------------------------


class _FakeReranker:
    """Deterministic reranker: emits the given priority order of pool indices."""

    def __init__(self, priority: list[int] | None = None, error: Exception | None = None):
        self.priority = priority
        self.error = error
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        self.calls.append((query, list(documents)))
        if self.error is not None:
            raise self.error
        priority = self.priority if self.priority is not None else list(range(len(documents)))
        return [(i, float(len(documents) - pos)) for pos, i in enumerate(priority)]


def _seed_db(
    tmp_path,
    ku_summaries: list[str],
    *,
    clusters: bool,
) -> tuple[str, list[KnowledgeUnit]]:
    db_path = str(tmp_path / "news.db")
    entity_repo = EntityRepository(db_path)
    cluster_repo = EventClusterRepository(db_path)

    entity = Entity(
        entity_id="ent_xiaomi",
        entity_type="Company",
        canonical_name="小米集团",
        aliases=[],
        identifiers={},
        source_ku_ids=[],
        created_at=NOW,
        updated_at=NOW,
    )
    entity_repo.save_batch([entity])

    ku_repo = KnowledgeUnitRepository(db_path)
    units: list[KnowledgeUnit] = []
    for idx, summary in enumerate(ku_summaries):
        pub = datetime(2026, 4, idx + 1, 10, 0, tzinfo=UTC)
        unit = KnowledgeUnit(
            unit_kind="event",
            unit_type="market_analysis",
            summary=summary,
            entities=[EntityRef(entity_id="ent_xiaomi", mention="小米集团", entity_type="Company")],
            source=SourceRef(doc_id=f"doc-{idx}", source_name="test"),
            evidence=[EvidenceSpan(text=summary)],
            time=TimeRef(event_time=pub, published_at=pub, extracted_at=pub),
        )
        units.append(unit)
    ku_repo.save_batch(units)

    if clusters:
        cluster_repo.save_batch([
            EventCluster(
                cluster_type="market_analysis",
                title="小米集团事件",
                summary=ku_summaries[0],
                entity_ids=["ent_xiaomi"],
                primary_entity_id="ent_xiaomi",
                member_ku_ids=[u.ku_id for u in units],
                source_doc_ids=[u.source.doc_id for u in units],
                time_anchor=NOW,
                updated_at=NOW,
                member_count=len(units),
                representative_ku_id=units[0].ku_id,
            )
        ])
    return db_path, units


def _entity_query(top_k: int = 3) -> KnowledgeSearchRequest:
    return KnowledgeSearchRequest(
        structured_query=StructuredQuery(
            intent=IntentType.ENTITY_OVERVIEW,
            entities=["小米集团"],
            time_range=None,
            filters=QueryFilters(),
            original_query="小米集团",
            confidence=1.0,
        ),
        top_k=top_k,
    )


def _make_searcher(db_path: str, reranker=None) -> KnowledgeSearcher:
    return KnowledgeSearcher(
        db_path=db_path,
        extractor=KnowledgeExtractor(enable_llm=False),
        reranker=reranker,
    )


# ---------------------------------------------------------------------------
# Entity route
# ---------------------------------------------------------------------------


def test_entity_route_strict_event_recall(tmp_path) -> None:
    """With a populated cluster map, candidates come only from clusters."""
    db_path, units = _seed_db(
        tmp_path,
        [f"小米集团新闻第{i}条" for i in range(4)],
        clusters=True,
    )
    searcher = _make_searcher(db_path)

    result = searcher.search(_entity_query())

    assert result.retrieval_path == "entity_events"
    assert result.applied_filters["event_recall"] == "clusters"
    assert result.applied_filters["semantic_filter"] == "skipped_no_index"
    assert {u.ku_id for u in result.knowledge_units} <= {u.ku_id for u in units}
    assert len(result.knowledge_units) == 3


def test_entity_route_falls_back_when_clusters_missing(tmp_path) -> None:
    """No cluster map rows → direct entity-id recall backfills (guardrail)."""
    db_path, units = _seed_db(
        tmp_path,
        [f"小米集团新闻第{i}条" for i in range(4)],
        clusters=False,
    )
    searcher = _make_searcher(db_path)

    result = searcher.search(_entity_query())

    assert result.retrieval_path == "entity_events"
    assert result.applied_filters["event_recall"] == "fallback_direct"
    assert len(result.knowledge_units) == 3


def test_entity_route_reranker_reorders_and_labels_path(tmp_path) -> None:
    """Injected reranker flips the fused order; path gains +rerank suffix."""
    db_path, units = _seed_db(
        tmp_path,
        [f"小米集团新闻第{i}条" for i in range(4)],
        clusters=True,
    )
    # Fused order for entity route is recency-first (newest KU seeded last),
    # so pool index 0 = newest. Priority [3,2,1,0] flips it to oldest-first.
    fake = _FakeReranker(priority=[3, 2, 1, 0])
    searcher = _make_searcher(db_path, reranker=fake)

    result = searcher.search(_entity_query())

    assert result.retrieval_path == "entity_events+rerank"
    assert result.knowledge_units[0].ku_id == units[0].ku_id
    assert result.knowledge_units[0].summary.startswith("小米集团新闻第0条")
    # Reranker saw the embedding-style document text (summary + metadata).
    query, docs = fake.calls[0]
    assert query == "小米集团"
    assert "小米集团新闻第3条" in docs[0]  # newest was pool[0] before the flip


def test_entity_route_reranker_failure_degrades_with_warning(tmp_path) -> None:
    """Reranker raising → fused order kept + explicit RERANKER_DEGRADED warning."""
    db_path, _units = _seed_db(
        tmp_path,
        [f"小米集团新闻第{i}条" for i in range(4)],
        clusters=True,
    )
    fake = _FakeReranker(error=RuntimeError("api down"))
    searcher = _make_searcher(db_path, reranker=fake)

    result = searcher.search(_entity_query())

    assert result.retrieval_path == "entity_events"
    assert len(result.knowledge_units) == 3
    codes = [w["code"] for w in result.warnings]
    assert "RERANKER_DEGRADED" in codes


# ---------------------------------------------------------------------------
# Text route
# ---------------------------------------------------------------------------


def test_text_route_hybrid_when_entity_unresolved(tmp_path) -> None:
    """Unknown topic → hybrid route (BM25 recall; dense unavailable in tests)."""
    db_path, _units = _seed_db(
        tmp_path,
        [f"大模型行业研究第{i}条" for i in range(3)],
        clusters=False,
    )
    searcher = _make_searcher(db_path)

    request = KnowledgeSearchRequest(
        structured_query=StructuredQuery(
            intent=IntentType.TOPIC_RESEARCH,
            entities=["完全不存在的主题词XYZ"],
            time_range=None,
            filters=QueryFilters(),
            original_query="大模型",
            confidence=1.0,
        ),
        top_k=2,
    )
    result = searcher.search(request)

    assert result.retrieval_path == "hybrid"
    assert result.total_count >= 1


def test_text_route_reranker_applied(tmp_path) -> None:
    db_path, _units = _seed_db(
        tmp_path,
        [f"大模型行业研究第{i}条" for i in range(3)],
        clusters=False,
    )
    fake = _FakeReranker(priority=[2, 1, 0])
    searcher = _make_searcher(db_path, reranker=fake)

    request = KnowledgeSearchRequest(
        structured_query=StructuredQuery(
            intent=IntentType.TOPIC_RESEARCH,
            entities=[],
            time_range=None,
            filters=QueryFilters(),
            original_query="大模型",
            confidence=1.0,
        ),
        top_k=2,
    )
    result = searcher.search(request)

    assert result.retrieval_path == "hybrid+rerank"
    assert len(result.knowledge_units) == 2
    assert fake.calls, "reranker must be called on the text route"


# ---------------------------------------------------------------------------
# VectorIndex.score_ids against a REAL faiss IndexIDMap
# (regression: reconstruct_batch is not implemented for IndexIDMap in some
#  faiss builds — production crashed until this went through the inner index)
# ---------------------------------------------------------------------------


class _FakeEmbeddingProvider:
    """Deterministic small-dim embeddings keyed by exact text."""

    def __init__(self, text_to_vector: dict[str, list[float]]):
        self._map = text_to_vector

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._map.get(t, [0.0, 0.0, 0.0, 0.0]) for t in texts]

    @property
    def dim(self) -> int:
        return 4

    @property
    def model_name(self) -> str:
        return "fake-provider"


def _build_unit_for_index(ku_id_seed: str, summary: str) -> KnowledgeUnit:
    pub = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    return KnowledgeUnit(
        unit_kind="event",
        unit_type="market_analysis",
        summary=summary,
        entities=[EntityRef(mention="测试")],
        source=SourceRef(doc_id=f"doc-{ku_id_seed}", source_name="test"),
        evidence=[EvidenceSpan(text=summary)],
        time=TimeRef(event_time=pub, published_at=pub, extracted_at=pub),
    )


def test_vector_index_score_ids_matches_search(tmp_path) -> None:
    """score_ids must return the same cosine scores as a global search."""
    from src.retrieval.vector_index import VectorIndex

    units = [
        _build_unit_for_index("a", "电池技术进展"),
        _build_unit_for_index("b", "财报发布"),
        _build_unit_for_index("c", "电池产能扩张"),
    ]
    # Distinct directions; "电池*" queries should prefer units 0 and 2.
    text_map = {
        "电池技术进展 [实体] 测试 [类型] market_analysis": [0.9, 0.1, 0.0, 0.0],
        "财报发布 [实体] 测试 [类型] market_analysis": [0.0, 0.0, 0.9, 0.1],
        "电池产能扩张 [实体] 测试 [类型] market_analysis": [0.85, 0.2, 0.0, 0.0],
        "电池技术": [0.9, 0.15, 0.0, 0.0],
    }
    provider = _FakeEmbeddingProvider(text_map)
    idx = VectorIndex(str(tmp_path / "news.db"), provider)
    assert idx.index_units(units) == 3

    scores = idx.score_ids("电池技术", [u.ku_id for u in units])

    assert set(scores) == {u.ku_id for u in units}
    # Cross-check against the global search path.
    search_scores = dict(idx.search("电池技术", top_k=3))
    for ku_id, score in scores.items():
        assert score == pytest.approx(search_scores[ku_id], abs=1e-5)
    # The two battery units outrank the finance one.
    assert scores[units[1].ku_id] < scores[units[0].ku_id]
    assert scores[units[1].ku_id] < scores[units[2].ku_id]
    # Missing/unknown ids are simply absent, no error.
    assert idx.score_ids("电池技术", ["ku_unknown"]) == {}


def test_entity_route_semantic_error_degrades_instead_of_crashing(tmp_path, monkeypatch) -> None:
    """A broken vector index must degrade the semantic filter, not fail search."""
    db_path, _units = _seed_db(
        tmp_path,
        [f"小米集团新闻第{i}条" for i in range(4)],
        clusters=True,
    )
    searcher = _make_searcher(db_path)

    class _BrokenVectorIndex:
        def score_ids(self, query_text, ku_ids):
            raise RuntimeError("reconstruct not implemented")

    searcher._vector_index = _BrokenVectorIndex()  # type: ignore[assignment]

    result = searcher.search(_entity_query())

    assert result.retrieval_path == "entity_events"
    assert len(result.knowledge_units) == 3
    assert result.applied_filters["semantic_filter"] == "skipped_error"
    codes = [w["code"] for w in result.warnings]
    assert "SEMANTIC_FILTER_SKIPPED" in codes
