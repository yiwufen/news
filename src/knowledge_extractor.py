"""
KnowledgeUnit extraction service.
"""

from __future__ import annotations

import json
from typing import Any

from anthropic.types import Message, ToolUseBlock

from src.knowledge_base import KnowledgeUnit, RawDocument
from src.llm import DEFAULT_MAX_TOKENS, create_llm_client


SYSTEM_PROMPT = """你是一名金融知识工程助手，负责从新闻文档中抽取可溯源的 statement-level KnowledgeUnit。
# 核心要求
1. 每个 KnowledgeUnit 表示来源中的一次明确陈述，不要把多个事件强行合并。
2. evidence 至少保留 1 条可读证据片段。
3. source.doc_id、time.published_at、time.extracted_at 必填。
4. entities 保留原始 mention，entity_id 可以为空。
5. 发现不确定或冲突信息时，不要裁决对错，只标记 conflict_status。
# 输出要求
- 只输出一个 JSON 对象，格式为 {"knowledge_units": [...]}
- knowledge_units 可以为空列表
- unit_kind 只能是 event 或 fact
"""

EXTRACTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "extract_knowledge_units",
    "description": "从新闻文档中抽取 statement-level KnowledgeUnit 列表",
    "input_schema": {
        "type": "object",
        "properties": {
            "knowledge_units": {
                "type": "array",
                "items": KnowledgeUnit.model_json_schema(),
            }
        },
        "required": ["knowledge_units"],
    },
}


def build_extraction_prompt(doc: RawDocument) -> str:
    """Build the extraction prompt for one raw document."""
    payload = doc.model_dump(mode="json")
    return f"""请从下面文档中抽取 KnowledgeUnit。
## 文档信息
- doc_id: {payload["doc_id"]}
- title: {payload["title"]}
- source_name: {payload["source_name"]}
- published_at: {payload["published_at"]}

## 正文
{payload["content"]}
"""


class KnowledgeExtractor:
    """KnowledgeUnit extractor with fail-fast LLM-only behavior."""

    def __init__(self, enable_llm: bool | None = None):
        self.enable_llm = enable_llm if enable_llm is not None else True
        self.client = None
        self.model = None
        self.max_tokens = DEFAULT_MAX_TOKENS

    def extract(self, document: RawDocument) -> list[KnowledgeUnit]:
        """Extract KnowledgeUnits for one document."""
        if not self.enable_llm:
            raise RuntimeError(
                "KnowledgeExtractor is configured without LLM extraction; heuristic extraction has been removed"
            )

        try:
            return self._extract_with_llm(document)
        except Exception as exc:
            raise RuntimeError(
                f"KnowledgeUnit extraction failed for {document.doc_id}: {exc}"
            ) from exc

    def extract_batch(self, documents: list[RawDocument]) -> dict[str, list[KnowledgeUnit]]:
        """Extract documents in batch."""
        return {document.doc_id: self.extract(document) for document in documents}

    def _get_client(self) -> tuple[Any, str]:
        if self.client is None or self.model is None:
            self.client, self.model = create_llm_client()
        return self.client, self.model

    def _extract_with_llm(self, document: RawDocument) -> list[KnowledgeUnit]:
        client, model = self._get_client()
        response: Message = client.messages.create(
            model=model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            tools=[EXTRACTION_TOOL_SCHEMA],  # type: ignore[arg-type]
            tool_choice={"type": "tool", "name": "extract_knowledge_units"},
            messages=[{"role": "user", "content": build_extraction_prompt(document)}],
        )

        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "extract_knowledge_units":
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if not isinstance(payload, dict):
                    raise ValueError("extract_knowledge_units returned a non-object payload")
                units_payload = payload.get("knowledge_units", [])
                if not isinstance(units_payload, list):
                    raise ValueError("extract_knowledge_units.knowledge_units must be a list")
                return [KnowledgeUnit.model_validate(unit) for unit in units_payload]

        raise ValueError("LLM did not return extract_knowledge_units")
