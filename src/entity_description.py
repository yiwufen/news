"""Entity description generation via offline LLM."""

from __future__ import annotations

import json
import logging
from typing import Any

from anthropic.types import Message, ToolUseBlock

from src.llm import create_offline_llm_client, get_offline_max_tokens

logger = logging.getLogger(__name__)

_DESCRIPTION_SYSTEM_PROMPT = """你是一名金融实体描述生成器。
给定实体名称、类型、标识符和来源摘要，生成一句简洁的实体描述（50字以内）。
描述应区分同名但不同领域的实体。
"""

_DESCRIPTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "generate_entity_description",
    "description": "为实体生成一句简洁描述",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "实体描述，50字以内",
            }
        },
        "required": ["description"],
    },
}


class EntityDescriptionGenerator:
    """Generate entity descriptions using offline LLM."""

    def __init__(self, enable: bool = True):
        self.enable = enable
        self.client = None
        self.model = None
        self.max_tokens = get_offline_max_tokens()

    def _get_client(self) -> tuple[Any, str]:
        if self.client is None or self.model is None:
            self.client, self.model = create_offline_llm_client()
        return self.client, self.model

    def generate(
        self,
        entity_name: str,
        entity_type: str,
        identifiers: dict[str, str] | None = None,
        source_summaries: list[str] | None = None,
    ) -> str | None:
        """Generate a description for an entity.

        Returns the description string, or None on failure.
        """
        if not self.enable:
            return None

        prompt = self._build_prompt(entity_name, entity_type, identifiers, source_summaries)
        try:
            return self._call_llm(prompt)
        except Exception as exc:
            logger.warning("Description generation failed for '%s': %s", entity_name, exc)
            return None

    def _build_prompt(
        self,
        entity_name: str,
        entity_type: str,
        identifiers: dict[str, str] | None,
        source_summaries: list[str] | None,
    ) -> str:
        parts = [f"实体名称: {entity_name}", f"实体类型: {entity_type}"]
        if identifiers:
            id_parts = [f"{k}: {v}" for k, v in identifiers.items()]
            parts.append(f"标识符: {', '.join(id_parts)}")
        if source_summaries:
            summaries_text = "\n".join(f"- {s}" for s in source_summaries[:5])
            parts.append(f"相关摘要:\n{summaries_text}")
        parts.append("请生成该实体的简洁描述。")
        return "\n".join(parts)

    def _call_llm(self, prompt: str) -> str | None:
        client, model = self._get_client()
        response: Message = client.messages.create(
            model=model,
            max_tokens=256,
            system=_DESCRIPTION_SYSTEM_PROMPT,
            tools=[_DESCRIPTION_TOOL_SCHEMA],  # type: ignore[arg-type]
            tool_choice={"type": "tool", "name": "generate_entity_description"},
            messages=[{"role": "user", "content": prompt}],
        )

        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "generate_entity_description":
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if isinstance(payload, dict) and "description" in payload:
                    desc = payload["description"]
                    if isinstance(desc, str) and desc.strip():
                        return desc.strip()
        return None
