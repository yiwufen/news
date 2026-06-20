"""Tests for EntityDescriptionGenerator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from anthropic.types import ToolUseBlock
from src.entity_description import EntityDescriptionGenerator


def _make_mock_llm_response(description: str) -> MagicMock:
    """Create a mock Anthropic response with a tool use block."""
    tool_block = ToolUseBlock(
        id="test_id",
        type="tool_use",
        name="generate_entity_description",
        input={"description": description},
    )

    response = MagicMock()
    response.content = [tool_block]
    return response


class TestEntityDescriptionGenerator:
    def test_generate_returns_description(self):
        gen = EntityDescriptionGenerator(enable=True)
        gen.client = MagicMock()
        gen.model = "test-model"
        gen.client.messages.create.return_value = _make_mock_llm_response(
            "一家中国新能源汽车制造商"
        )

        result = gen.generate("比亚迪", "Company")
        assert result == "一家中国新能源汽车制造商"

    def test_generate_disabled_returns_none(self):
        gen = EntityDescriptionGenerator(enable=False)
        result = gen.generate("比亚迪", "Company")
        assert result is None

    def test_generate_failure_raises(self):
        """API failures now propagate (fail-fast) instead of returning None.

        Silently returning None on API failure was a root cause of the
        duplicate-entity outbreak: an entity created without a description
        weakens disambiguation signal and cascades into mismatches.
        """
        gen = EntityDescriptionGenerator(enable=True)
        gen.client = MagicMock()
        gen.model = "test-model"
        gen.client.messages.create.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            gen.generate("比亚迪", "Company")

    def test_generate_empty_response_returns_none(self):
        gen = EntityDescriptionGenerator(enable=True)
        gen.client = MagicMock()
        gen.model = "test-model"

        # Response with no tool use block
        response = MagicMock()
        response.content = []
        gen.client.messages.create.return_value = response

        result = gen.generate("比亚迪", "Company")
        assert result is None

    def test_generate_with_identifiers_and_summaries(self):
        gen = EntityDescriptionGenerator(enable=True)
        gen.client = MagicMock()
        gen.model = "test-model"
        gen.client.messages.create.return_value = _make_mock_llm_response(
            "腾讯控股，中国互联网巨头"
        )

        result = gen.generate(
            "腾讯控股",
            "Company",
            identifiers={"ticker": "0700.HK"},
            source_summaries=["腾讯发布Q4财报", "净利润增长20%"],
        )
        assert result == "腾讯控股，中国互联网巨头"

        # Verify prompt includes all context
        call_args = gen.client.messages.create.call_args
        prompt = call_args.kwargs["messages"][0]["content"]
        assert "腾讯控股" in prompt
        assert "0700.HK" in prompt
        assert "腾讯发布Q4财报" in prompt

    def test_prompt_build_includes_all_fields(self):
        gen = EntityDescriptionGenerator(enable=True)
        prompt = gen._build_prompt(
            "比亚迪",
            "Company",
            identifiers={"ticker": "002594.SZ"},
            source_summaries=["比亚迪Q3营收超预期"],
        )
        assert "比亚迪" in prompt
        assert "Company" in prompt
        assert "002594.SZ" in prompt
        assert "比亚迪Q3营收超预期" in prompt
