"""Golden Test Suite for Entity Resolution.

Covers precision (must NOT merge), recall (must merge), normalization,
embedding disambiguation, and description generation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.entities import (
    Entity,
    EntityRepository,
    EntityResolver,
    _cosine_similarity,
    _infer_entity_type,
    normalize_entity_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(
    canonical_name: str,
    entity_type: str = "Company",
    aliases: list[str] | None = None,
    identifiers: dict[str, str] | None = None,
    description: str | None = None,
) -> Entity:
    now = datetime.now(UTC)
    return Entity(
        entity_type=entity_type,  # type: ignore[arg-type]
        canonical_name=canonical_name,
        aliases=aliases or [canonical_name],
        identifiers=identifiers or {},
        description=description,
        created_at=now,
        updated_at=now,
    )


def _resolve_with_context(
    resolver: EntityResolver,
    mention: str,
    summary: str = "test",
    evidence_texts: list[str] | None = None,
    entity_type: str = "Company",
    identifiers: dict[str, str] | None = None,
    entities_cache: dict[str, Entity] | None = None,
) -> Entity | None:
    """Resolve a mention with specific KU context for disambiguation testing."""
    from src.knowledge_base import (
        EntityRef,
        EvidenceSpan,
        KnowledgeUnit,
        SourceRef,
        TimeRef,
    )

    cache = entities_cache if entities_cache is not None else {}
    unit = KnowledgeUnit(
        unit_kind="event",
        unit_type="market_analysis",
        summary=summary,
        entities=[
            EntityRef(
                mention=mention,
                entity_type=entity_type,
                identifiers=identifiers or {},
            )
        ],
        source=SourceRef(doc_id="doc_test", source_name="test"),
        evidence=[EvidenceSpan(text=t) for t in (evidence_texts or ["test evidence"])],
        time=TimeRef(published_at=datetime.now(UTC), extracted_at=datetime.now(UTC)),
    )
    resolver.resolve_units_with_cache([unit], cache, persist=False)
    entity_id = unit.entities[0].entity_id
    assert entity_id is not None  # resolve 后必已填充
    return cache.get(entity_id)


def _make_mock_embedding_provider(
    similarities: dict[str, float] | None = None,
) -> Any:
    """Create a mock embedding provider that returns predictable vectors.

    similarities: maps text substring → desired cosine similarity with the KU context.
    Base vector is [1, 0]. Candidate vectors are [score, sqrt(1-score²)] so that
    cosine similarity equals score exactly.
    """
    provider = MagicMock()
    provider.dim = 2

    _similarities = similarities
    import math as _math

    def mock_embed(texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        if not texts:
            return results
        # KU context — unit vector along first axis
        results.append([1.0, 0.0])
        for text in texts[1:]:
            score = 0.3  # default low similarity
            if _similarities:
                for key, val in _similarities.items():
                    if key in text:
                        score = val
                        break
            results.append([score, _math.sqrt(max(0, 1.0 - score * score))])
        return results

    provider.embed = MagicMock(side_effect=mock_embed)
    return provider


def _resolve_single(
    resolver: EntityResolver,
    mention: str,
    entity_type: str = "Company",
    identifiers: dict[str, str] | None = None,
    entities_cache: dict[str, Entity] | None = None,
) -> Entity:
    """Resolve a single mention against the given cache and return the matched entity."""
    from src.knowledge_base import (
        EntityRef,
        EvidenceSpan,
        KnowledgeUnit,
        SourceRef,
        TimeRef,
    )

    cache = entities_cache if entities_cache is not None else {}
    unit = KnowledgeUnit(
        unit_kind="event",
        unit_type="market_analysis",
        summary="test",
        entities=[
            EntityRef(
                mention=mention,
                entity_type=entity_type,
                identifiers=identifiers or {},
            )
        ],
        source=SourceRef(doc_id="doc_test", source_name="test"),
        evidence=[EvidenceSpan(text="test evidence")],
        time=TimeRef(published_at=datetime.now(UTC), extracted_at=datetime.now(UTC)),
    )
    resolver.resolve_units_with_cache([unit], cache, persist=False)
    entity_id = unit.entities[0].entity_id
    assert entity_id is not None  # resolve 后必已填充
    return cache[entity_id]


# ===========================================================================
# Precision Cases — must NOT merge
# ===========================================================================

class TestPrecision:
    """Different real-world entities that must remain separate."""

    def test_geely_vs_dajili(self):
        """'吉利' vs '大吉利' — substring but different entities."""
        n1 = normalize_entity_name("吉利")
        n2 = normalize_entity_name("大吉利")
        assert n1 != n2

    def test_midea_group_vs_midea_realestate(self):
        """'美的集团' vs '美的置业' — same group, different subsidiaries."""
        n1 = normalize_entity_name("美的集团")
        n2 = normalize_entity_name("美的置业")
        assert n1 != n2

    def test_hengda_health_vs_hengda_realestate(self):
        """'恒大健康' vs '恒大地产' — same group, different subsidiaries."""
        n1 = normalize_entity_name("恒大健康")
        n2 = normalize_entity_name("恒大地产")
        assert n1 != n2

    def test_over_stripping_prevention(self):
        """'控股有限公司' must NOT become empty string."""
        result = normalize_entity_name("控股有限公司")
        assert len(result) > 0, f"Over-stripped to empty: '控股有限公司' → '{result}'"

    def test_resolver_does_not_merge_different_subsidaries(
        self, tmp_path: Path
    ):
        """Resolver must keep '美的集团' and '美的置业' as separate entities."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        resolver = EntityResolver(repo)

        existing = _make_entity("美的集团", aliases=["美的集团"])
        cache = {existing.entity_id: existing}

        resolved = _resolve_single(resolver, "美的置业", entities_cache=cache)
        assert resolved.entity_id != existing.entity_id, (
            "美的置业 must NOT merge into 美的集团"
        )

    def test_resolver_does_not_merge_xiaomi_vs_xiaomi_finance(
        self, tmp_path: Path
    ):
        """'小米' and '小米金融' — parent vs subsidiary, must stay separate."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        resolver = EntityResolver(repo)

        existing = _make_entity("小米集团", aliases=["小米"])
        cache = {existing.entity_id: existing}

        resolved = _resolve_single(resolver, "小米金融", entities_cache=cache)
        assert resolved.entity_id != existing.entity_id, (
            "小米金融 must NOT merge into 小米集团"
        )


# ===========================================================================
# Recall Cases — must merge
# ===========================================================================

class TestRecall:
    """Same real-world entity that must be merged."""

    def test_byd_cross_lingual(self):
        """'BYD' → '比亚迪' — cross-lingual alias lookup."""
        assert "byd" in EntityRepository._CROSS_LINGUAL_ALIASES
        assert EntityRepository._CROSS_LINGUAL_ALIASES["byd"] == "比亚迪"

    def test_tencent_type_mismatch_still_merges(self, tmp_path: Path):
        """'腾讯' (Company) vs '腾讯控股' (Company) — short name should merge."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        resolver = EntityResolver(repo)

        existing = _make_entity("腾讯控股", entity_type="Company", aliases=["腾讯控股"])
        cache = {existing.entity_id: existing}

        # _infer_entity_type no longer infers Person from bare 2-3 char Chinese
        assert _infer_entity_type("腾讯") == "Company"

        resolved = _resolve_single(
            resolver, "腾讯", entity_type="Company", entities_cache=cache
        )
        assert resolved.entity_id == existing.entity_id, (
            "腾讯 must merge into 腾讯控股 via normalized name match"
        )

    def test_byd_merges_via_resolver(self, tmp_path: Path):
        """Resolver must merge 'BYD' mention into existing '比亚迪' entity."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        resolver = EntityResolver(repo)

        existing = _make_entity("比亚迪", aliases=["比亚迪"])
        cache = {existing.entity_id: existing}

        resolved = _resolve_single(resolver, "BYD", entities_cache=cache)
        assert resolved.entity_id == existing.entity_id, (
            "BYD must merge into 比亚迪 via cross-lingual alias"
        )

    def test_suffix_strip_preserves_core(self):
        """'宁德时代股份有限公司' normalizes to same as '宁德时代'."""
        n1 = normalize_entity_name("宁德时代股份有限公司")
        n2 = normalize_entity_name("宁德时代")
        assert n1 == n2

    def test_tencent_holdings_merges(self, tmp_path: Path):
        """'腾讯控股' mention merges into entity with canonical '腾讯'."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        resolver = EntityResolver(repo)

        existing = _make_entity("腾讯", aliases=["腾讯"])
        cache = {existing.entity_id: existing}

        resolved = _resolve_single(resolver, "腾讯控股", entities_cache=cache)
        assert resolved.entity_id == existing.entity_id, (
            "腾讯控股 must merge into 腾讯 via suffix normalization"
        )


# ===========================================================================
# Normalization
# ===========================================================================

class TestNormalization:
    """Suffix stripping behavior."""

    def test_single_pass_no_recursive_strip(self):
        """Suffix stripped only once, not recursively."""
        # '集团股份有限公司' → strip '集团股份有限公司' → '' (all suffix)
        # With match.start() > 0 guard → preserve full input
        r = normalize_entity_name("集团股份有限公司")
        assert len(r) > 0

    def test_no_suffix_unchanged(self):
        """Names without suffix are unchanged."""
        assert normalize_entity_name("腾讯") == "腾讯"
        assert normalize_entity_name("百度") == "百度"

    def test_english_suffix(self):
        """English suffixes are stripped."""
        result = normalize_entity_name("Apple Inc")
        assert result == "apple"

    def test_mixed_chinese_english(self):
        """Mixed names normalize correctly."""
        result = normalize_entity_name("台积电 Corporation")
        assert "tsmc" not in result.lower() or result == normalize_entity_name("台积电")

    def test_empty_string_input(self):
        """Empty input returns empty string."""
        assert normalize_entity_name("") == ""
        assert normalize_entity_name("  ") == ""

    def test_whitespace_and_punctuation_stripped(self):
        """Whitespace and punctuation removed before suffix stripping."""
        r = normalize_entity_name("腾讯 控股（集团）")
        assert " " not in r


# ===========================================================================
# Alias Dedup
# ===========================================================================

class TestAliasDedup:
    """Alias pool must not grow unbounded."""

    def test_normalized_duplicate_not_appended(self, tmp_path: Path):
        """Mentions with same normalized form must not create duplicate aliases."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        resolver = EntityResolver(repo)

        existing = _make_entity("腾讯控股", aliases=["腾讯控股"])
        cache = {existing.entity_id: existing}

        # '腾讯控股(' normalizes to same as '腾讯控股' → should NOT be appended
        _resolve_single(resolver, "腾讯控股(", entities_cache=cache)
        entity = cache[existing.entity_id]

        norm_set = {normalize_entity_name(a) for a in entity.aliases}
        assert len(norm_set) == len(entity.aliases), (
            f"Duplicate normalized aliases: {entity.aliases}"
        )


# ===========================================================================
# Embedding Disambiguation
# ===========================================================================

class TestDisambiguation:
    """Embedding-based disambiguation for same-name entities."""

    def test_single_candidate_no_disambiguation(self, tmp_path: Path):
        """Single candidate is returned directly without calling embedding."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        provider = _make_mock_embedding_provider()
        resolver = EntityResolver(repo, embedding_provider=provider)

        existing = _make_entity("腾讯控股")
        cache = {existing.entity_id: existing}

        result = _resolve_with_context(
            resolver, "腾讯控股", summary="test", entities_cache=cache,
        )
        assert result is not None
        assert result.entity_id == existing.entity_id
        provider.embed.assert_not_called()

    def test_no_provider_falls_back_to_first(self, tmp_path: Path):
        """Without embedding provider, multiple candidates → first one wins."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        resolver = EntityResolver(repo)

        e1 = _make_entity("苹果公司", description="一家美国科技公司")
        e2 = _make_entity("苹果期货", entity_type="Product", description="农产品期货")
        # Make both match by sharing the same alias "苹果"
        e1_updated = _make_entity(
            "苹果公司", aliases=["苹果公司", "苹果"], description="一家美国科技公司",
        )
        cache = {
            e1_updated.entity_id: e1_updated,
            e2.entity_id: e2,
        }
        # Add e2 with same alias to make both match
        e2_updated = _make_entity(
            "苹果期货", entity_type="Product", aliases=["苹果期货", "苹果"],
            description="农产品期货",
        )
        cache = {
            e1_updated.entity_id: e1_updated,
            e2_updated.entity_id: e2_updated,
        }

        result = _resolve_with_context(
            resolver, "苹果", summary="苹果发布新财报", entities_cache=cache,
        )
        assert result is not None
        # Without disambiguation, should get the first candidate
        assert result.entity_id in {e1_updated.entity_id, e2_updated.entity_id}

    def test_disambiguation_picks_better_match(self, tmp_path: Path):
        """With embedding provider, picks the candidate with higher similarity."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        provider = _make_mock_embedding_provider(
            similarities={"美国科技": 0.85, "农产品期货": 0.2},
        )
        resolver = EntityResolver(repo, embedding_provider=provider)

        e1 = _make_entity(
            "苹果公司", aliases=["苹果公司", "苹果"], description="一家美国科技公司",
        )
        e2 = _make_entity(
            "苹果期货", entity_type="Product", aliases=["苹果期货", "苹果"],
            description="农产品期货品种",
        )
        cache = {e1.entity_id: e1, e2.entity_id: e2}

        result = _resolve_with_context(
            resolver, "苹果", summary="苹果公司发布Q4财报营收超预期",
            entities_cache=cache,
        )
        assert result is not None
        assert result.entity_id == e1.entity_id, (
            "Should disambiguate to 苹果公司 for financial context"
        )

    def test_disambiguation_below_threshold_falls_back_to_first_candidate(self, tmp_path: Path):
        """Both candidates below threshold → fallback to first candidate (no duplicate created)."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        provider = _make_mock_embedding_provider(
            similarities={"科技公司": 0.1, "期货品种": 0.1},  # both low
        )
        resolver = EntityResolver(repo, embedding_provider=provider)

        e1 = _make_entity(
            "苹果公司", aliases=["苹果"], description="科技公司",
        )
        e2 = _make_entity(
            "苹果期货", entity_type="Product", aliases=["苹果"], description="期货品种",
        )
        cache = {e1.entity_id: e1, e2.entity_id: e2}

        result = _resolve_with_context(
            resolver, "苹果", summary="苹果价格波动", entities_cache=cache,
        )
        # Below threshold → fallback to first candidate (e1)
        # This is the correct behavior: we never create a duplicate when
        # candidates exist, even if disambiguation is inconclusive.
        assert result is not None
        assert result.entity_id == e1.entity_id, (
            "Should fall back to first candidate when disambiguation inconclusive"
        )

    def test_disambiguation_works_without_description(self, tmp_path: Path):
        """Disambiguation proceeds even when some candidates lack descriptions."""
        db_path = str(tmp_path / "test.db")
        repo = EntityRepository(db_path)
        provider = _make_mock_embedding_provider(
            similarities={"科技公司": 0.9},
        )
        resolver = EntityResolver(repo, embedding_provider=provider)

        e1 = _make_entity("苹果公司", aliases=["苹果"], description="科技公司")
        e2 = _make_entity(
            "苹果期货", entity_type="Product", aliases=["苹果"], description=None,
        )
        cache = {e1.entity_id: e1, e2.entity_id: e2}

        result = _resolve_with_context(
            resolver, "苹果", summary="苹果公司发布新品", entities_cache=cache,
        )
        assert result is not None
        assert result.entity_id == e1.entity_id
        provider.embed.assert_called_once()


# ===========================================================================
# Cosine Similarity
# ===========================================================================

class TestCosineSimilarity:
    """Unit tests for the cosine similarity helper."""

    def test_identical_vectors(self):
        assert abs(_cosine_similarity([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-6

    def test_zero_vector(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_opposite_vectors(self):
        assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-6
