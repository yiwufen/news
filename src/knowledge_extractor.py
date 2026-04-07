"""
KnowledgeUnit extraction service.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from anthropic.types import Message, ToolUseBlock

from src.knowledge_base import KnowledgeUnit, RawDocument
from src.llm import create_offline_llm_client, get_offline_max_tokens
from src.time_normalization import TimeNormalizationContext, TimeNormalizer

logger = logging.getLogger(__name__)


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
    """KnowledgeUnit extractor with retry support for LLM format instability."""

    def __init__(self, enable_llm: bool | None = None, max_retries: int = 2):
        self.enable_llm = enable_llm if enable_llm is not None else True
        self.max_retries = max_retries
        self.client = None
        self.model = None
        self.max_tokens = get_offline_max_tokens()
        self._time_normalizer = TimeNormalizer()  # Cache instance
        logger.debug(f"KnowledgeExtractor initialized (enable_llm={self.enable_llm}, max_retries={self.max_retries})")

    def extract(self, document: RawDocument) -> list[KnowledgeUnit]:
        """Extract KnowledgeUnits for one document."""
        if not self.enable_llm:
            raise RuntimeError(
                "KnowledgeExtractor is configured without LLM extraction; heuristic extraction has been removed"
            )

        logger.debug(f"Extracting KnowledgeUnits from document: {document.doc_id}")
        try:
            units = self._extract_with_llm(document)
            logger.info(f"Extracted {len(units)} KnowledgeUnits from {document.doc_id}")
            return units
        except Exception as exc:
            logger.error(f"Failed to extract from {document.doc_id}: {exc}")
            raise RuntimeError(
                f"KnowledgeUnit extraction failed for {document.doc_id}: {exc}"
            ) from exc

    def extract_batch(self, documents: list[RawDocument]) -> dict[str, list[KnowledgeUnit]]:
        """Extract documents in batch."""
        return {document.doc_id: self.extract(document) for document in documents}

    def _get_client(self) -> tuple[Any, str]:
        if self.client is None or self.model is None:
            self.client, self.model = create_offline_llm_client()
            logger.debug(f"LLM client initialized with model: {self.model}")
        return self.client, self.model

    def _extract_with_llm(self, document: RawDocument) -> list[KnowledgeUnit]:
        client, model = self._get_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response: Message = client.messages.create(
                    model=model,
                    max_tokens=self.max_tokens,
                    system=SYSTEM_PROMPT,
                    tools=[EXTRACTION_TOOL_SCHEMA],  # type: ignore[arg-type]
                    tool_choice={"type": "tool", "name": "extract_knowledge_units"},
                    messages=[{"role": "user", "content": build_extraction_prompt(document)}],
                )
                return self._parse_llm_response(response, document)
            except ValueError as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning(
                        f"LLM format error for {document.doc_id} (attempt {attempt + 1}/{self.max_retries + 1}): {e}"
                    )
                    time.sleep(0.5 * (attempt + 1))  # 递增延迟
                else:
                    raise

        raise last_error or ValueError("LLM extraction failed")

    def _parse_llm_response(self, response: Message, document: RawDocument) -> list[KnowledgeUnit]:
        """Parse LLM response into KnowledgeUnit list."""
        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "extract_knowledge_units":
                payload = block.input
                if isinstance(payload, str):
                    payload = json.loads(payload)
                if not isinstance(payload, dict):
                    raise ValueError("extract_knowledge_units returned a non-object payload")
                units_payload = payload.get("knowledge_units")
                # 容错处理：None 或非列表类型触发重试
                if units_payload is None:
                    raise ValueError("LLM returned null knowledge_units")
                if not isinstance(units_payload, list):
                    raise ValueError(
                        f"LLM returned non-list knowledge_units (type={type(units_payload).__name__})"
                    )
                context = self._build_time_normalization_context(document)
                normalized_units_payload = [
                    self._normalize_unit_payload_time(unit, context)
                    for unit in units_payload
                ]
                return [
                    KnowledgeUnit.model_validate(unit)
                    for unit in normalized_units_payload
                ]

        raise ValueError("LLM did not return extract_knowledge_units")

    def _build_time_normalization_context(
        self,
        document: RawDocument,
    ) -> TimeNormalizationContext:
        return TimeNormalizationContext(
            published_at=document.published_at,
            extracted_at=datetime.now(UTC),
            document_title=document.title,
        )

    def _normalize_unit_payload_time(
        self,
        unit_payload: Any,
        context: TimeNormalizationContext,
    ) -> Any:
        """Normalize event_time before KnowledgeUnit validation."""
        if not isinstance(unit_payload, dict):
            return unit_payload

        time_payload = unit_payload.get("time")
        if not isinstance(time_payload, dict):
            return unit_payload

        raw_time = time_payload.get("event_time")
        if raw_time is None:
            return unit_payload

        result = self._time_normalizer.normalize_event_time(raw_time, context)
        normalized_time_payload = dict(time_payload)
        normalized_time_payload["event_time"] = result.normalized_time
        normalized_time_payload["event_time_resolution"] = result.resolution_type
        if result.original_expression is not None:
            normalized_time_payload["raw_event_time_expression"] = (
                result.original_expression
            )

        normalized_unit_payload = dict(unit_payload)
        normalized_unit_payload["time"] = normalized_time_payload
        return normalized_unit_payload
