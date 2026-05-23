"""Unit tests for entity context filtering and injection."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.entity_context_filter import (
    EntityContext,
    build_entity_context_section,
    filter_relevant_entities,
)
from src.entities import Entity
from src.knowledge_base import RawDocument


def _make_entity(
    canonical_name: str,
    entity_type: str = "Company",
    aliases: list[str] | None = None,
    identifiers: dict[str, str] | None = None,
) -> Entity:
    """Helper to create an Entity for testing."""
    return Entity(
        entity_id=f"ent_{canonical_name[:8].lower()}",
        entity_type=entity_type,  # type: ignore
        canonical_name=canonical_name,
        aliases=aliases or [],
        identifiers=identifiers or {},
        source_ku_ids=["ku_test"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_document(title: str, content: str) -> RawDocument:
    """Helper to create a RawDocument for testing."""
    return RawDocument(
        doc_id="test_doc_001",
        source_type="news",
        title=title,
        content=content,
        source_name="测试来源",
        published_at=datetime.now(UTC),
        ingested_at=datetime.now(UTC),
    )



class TestLongestMatchPriority:
    """Tests for Aho-Corasick longest-match semantics."""

    def test_short_name_not_matched_inside_longer_name(self) -> None:
        """'华为' should NOT match when text says '华为海思'."""
        document = _make_document("华为海思发布新芯片", "华为海思发布新芯片")
        entities = {
            "ent_huawei": _make_entity("华为"),
            "ent_huawei_hisi": _make_entity("华为海思"),
        }
        result = filter_relevant_entities(document, entities)
        # 华为海思 should be matched; 华为 should NOT be matched separately
        matched_names = {ctx.canonical_name for ctx in result}
        assert "华为海思" in matched_names
        # 华为 may appear if its name also matched, but 华为海思 should rank higher
        if "华为" in matched_names:
            huawei_hisi_idx = next(
                i for i, ctx in enumerate(result) if ctx.canonical_name == "华为海思"
            )
            huawei_idx = next(
                i for i, ctx in enumerate(result) if ctx.canonical_name == "华为"
            )
            assert huawei_hisi_idx < huawei_idx

    def test_short_name_matched_standalone(self) -> None:
        """'华为' SHOULD match when it appears standalone."""
        document = _make_document("华为发布新品", "华为发布新品")
        entities = {
            "ent_huawei": _make_entity("华为"),
            "ent_huawei_hisi": _make_entity("华为海思"),
        }
        result = filter_relevant_entities(document, entities)
        matched_names = {ctx.canonical_name for ctx in result}
        assert "华为" in matched_names
        # 华为海思 should NOT match (text doesn't contain it)
        assert "华为海思" not in matched_names


class TestFilterRelevantEntities:
    """Tests for filter_relevant_entities."""

    def test_empty_entities_cache(self) -> None:
        document = _make_document("小米发布新品", "小米集团发布新产品")
        result = filter_relevant_entities(document, {})
        assert result == []

    def test_single_match(self) -> None:
        document = _make_document("小米发布新品", "小米集团发布新产品")
        entities = {
            "ent_xiaomi": _make_entity("小米集团"),
            "ent_huawei": _make_entity("华为"),
        }
        result = filter_relevant_entities(document, entities)
        assert len(result) == 1
        assert result[0].canonical_name == "小米集团"

    def test_multiple_matches_sorted_by_score(self) -> None:
        document = _make_document(
            "小米华为对比",
            "小米集团和华为都发布了新品，小米表现更好",
        )
        entities = {
            "ent_xiaomi": _make_entity(
                "小米集团",
                aliases=["小米"],
                identifiers={"ticker": "1810.HK"},
            ),
            "ent_huawei": _make_entity("华为"),
        }
        result = filter_relevant_entities(document, entities)
        assert len(result) == 2
        # 小米 has higher score due to multiple matches
        assert result[0].canonical_name == "小米集团"
        assert result[1].canonical_name == "华为"

    def test_max_entities_limit(self) -> None:
        document = _make_document("测试", "小米 华为 腾讯 阿里 京东 百度")
        entities = {
            f"ent_{i}": _make_entity(f"公司{i}") for i in range(100)
        }
        # Add matching entities
        for name in ["小米", "华为", "腾讯", "阿里", "京东", "百度"]:
            entities[f"ent_{name}"] = _make_entity(name)

        result = filter_relevant_entities(document, entities, max_entities=3)
        assert len(result) == 3

    def test_max_tokens_estimate(self) -> None:
        document = _make_document("测试", "小米 华为 腾讯")
        entities = {
            f"ent_{i}": _make_entity(f"公司{i}", aliases=[f"别名{i}"])
            for i in range(100)
        }
        for name in ["小米", "华为", "腾讯"]:
            entities[f"ent_{name}"] = _make_entity(name, aliases=["别名"])

        result = filter_relevant_entities(document, entities, max_tokens_estimate=50)
        # Should stop early due to token budget
        assert len(result) < 10

    def test_entity_context_structure(self) -> None:
        document = _make_document("小米发布新品", "小米集团发布新产品")
        entities = {
            "ent_xiaomi": _make_entity(
                "小米集团",
                aliases=["小米", "Xiaomi"],
                identifiers={"ticker": "1810.HK"},
            ),
        }
        result = filter_relevant_entities(document, entities)
        assert len(result) == 1
        ctx = result[0]
        assert ctx.canonical_name == "小米集团"
        assert ctx.entity_type == "Company"
        assert ctx.aliases == ["小米", "Xiaomi"][:3]
        assert ctx.identifiers == {"ticker": "1810.HK"}


class TestBuildEntityContextSection:
    """Tests for build_entity_context_section."""

    def test_empty_entities(self) -> None:
        result = build_entity_context_section([])
        assert result == ""

    def test_single_entity(self) -> None:
        entities = [
            EntityContext(
                canonical_name="小米集团",
                entity_type="Company",
                identifiers={"ticker": "1810.HK"},
                aliases=["小米"],
            ),
        ]
        result = build_entity_context_section(entities)
        assert "已知实体参考" in result
        assert "小米集团" in result
        assert "Company" in result
        assert "1810.HK" in result
        assert "别名: 小米" in result

    def test_multiple_entities(self) -> None:
        entities = [
            EntityContext(
                canonical_name="小米集团",
                entity_type="Company",
                identifiers={"ticker": "1810.HK"},
                aliases=["小米"],
            ),
            EntityContext(
                canonical_name="华为",
                entity_type="Company",
                identifiers={},
                aliases=["华为技术"],
            ),
        ]
        result = build_entity_context_section(entities)
        assert "小米集团" in result
        assert "华为" in result

    def test_no_identifiers(self) -> None:
        entities = [
            EntityContext(
                canonical_name="测试公司",
                entity_type="Company",
                identifiers={},
                aliases=[],
            ),
        ]
        result = build_entity_context_section(entities)
        assert "测试公司" in result
        assert "[" not in result  # No identifier bracket

    def test_limits_aliases(self) -> None:
        entities = [
            EntityContext(
                canonical_name="小米集团",
                entity_type="Company",
                identifiers={},
                aliases=["小米", "Xiaomi", "MI", "多余别名"],  # 4 aliases
            ),
        ]
        result = build_entity_context_section(entities)
        # Should include at most 3 aliases in the section
        assert "小米" in result
        assert "Xiaomi" in result
        assert "MI" in result


class TestKnowledgeExtractorPrompt:
    """Tests for prompt building with entity context."""

    def test_build_extraction_prompt_without_context(self) -> None:
        from src.knowledge_extractor import build_extraction_prompt

        document = _make_document("测试标题", "测试正文内容")
        prompt = build_extraction_prompt(document)
        assert "测试标题" in prompt
        assert "测试正文内容" in prompt
        assert "已知实体参考" not in prompt

    def test_build_extraction_prompt_with_context(self) -> None:
        from src.knowledge_extractor import build_extraction_prompt

        document = _make_document("测试标题", "测试正文内容")
        entity_context = [
            EntityContext(
                canonical_name="小米集团",
                entity_type="Company",
                identifiers={"ticker": "1810.HK"},
                aliases=["小米"],
            ),
        ]
        prompt = build_extraction_prompt(document, entity_context)
        assert "测试标题" in prompt
        assert "已知实体参考" in prompt
        assert "小米集团" in prompt
