"""
KnowledgeUnit 抽取服务。
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from typing import Any

from anthropic.types import Message, ToolUseBlock

from src.knowledge_base import (
    EntityRef,
    EvidenceSpan,
    KnowledgeUnit,
    RawDocument,
    SourceRef,
    TimeRef,
)
from src.llm import DEFAULT_MAX_TOKENS, create_llm_client


SYSTEM_PROMPT = """你是一名金融知识工程助手，负责从新闻文档中抽取可溯源的 statement-level KnowledgeUnit。

# 核心要求
1. 每个 KnowledgeUnit 表示来源中的一次明确陈述，不要把多个事件强行合并。
2. evidence 至少保留 1 条可读证据片段。
3. source.doc_id、time.published_at、time.extracted_at 必填。
4. entities 保留原始 mention；entity_id 可以为空。
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
    """构建单篇原始文档的抽取提示词。"""
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
    """KnowledgeUnit 抽取器。

    默认优先使用 LLM；若本地没有 API 配置或抽取失败，则退化到启发式抽取。
    """

    ENTITY_PATTERN = re.compile(
        r"([A-Z][A-Za-z0-9&.\- ]{1,40}|[\u4e00-\u9fff]{2,20}(?:集团|公司|银行|科技|股份|控股|有限公司|有限责任公司|研究院|汽车|证券|基金))"
    )

    def __init__(self, enable_llm: bool | None = None):
        self.enable_llm = enable_llm if enable_llm is not None else bool(os.environ.get("ANTHROPIC_API_KEY"))
        self.client = None
        self.model = None
        self.max_tokens = DEFAULT_MAX_TOKENS

    def extract(self, document: RawDocument) -> list[KnowledgeUnit]:
        """抽取单篇文档的 KnowledgeUnit。"""
        if self.enable_llm:
            try:
                return self._extract_with_llm(document)
            except Exception:
                pass
        return self._extract_with_heuristics(document)

    def extract_batch(self, documents: list[RawDocument]) -> dict[str, list[KnowledgeUnit]]:
        """按文档批量抽取。"""
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
                    raise ValueError("extract_knowledge_units 杩斿洖浜嗛潪瀵硅薄 payload")
                units_payload = payload.get("knowledge_units", [])
                if not isinstance(units_payload, list):
                    raise ValueError("extract_knowledge_units.knowledge_units 蹇呴』鏄垪琛?")
                units = units_payload
                return [KnowledgeUnit.model_validate(unit) for unit in units]

        raise ValueError("LLM 未返回 extract_knowledge_units")

    def _extract_with_heuristics(self, document: RawDocument) -> list[KnowledgeUnit]:
        extracted_at = datetime.now(UTC)
        mentions = self._extract_entity_mentions(document.title, document.content)
        if not mentions:
            mentions = [document.title[:20].strip() or document.source_name]

        evidence = self._extract_evidence(document.content)
        unit = KnowledgeUnit(
            unit_kind="event",
            unit_type=self._infer_unit_type(document.title, document.content),
            summary=self._build_summary(document.title, document.content),
            entities=[EntityRef(mention=mention) for mention in mentions],
            source=SourceRef(
                doc_id=document.doc_id,
                source_name=document.source_name,
                url=document.url,
            ),
            evidence=[EvidenceSpan(text=evidence)],
            time=TimeRef(
                event_time=document.published_at,
                published_at=document.published_at,
                extracted_at=extracted_at,
            ),
            confidence=0.72,
            tags=self._infer_tags(document.title, document.content),
        )
        return [unit]

    def _extract_entity_mentions(self, title: str, content: str) -> list[str]:
        seen: list[str] = []
        text = f"{title}\n{content[:500]}"
        for match in self.ENTITY_PATTERN.findall(text):
            mention = re.sub(r"\s+", " ", match).strip(" ,，。；;：:")
            if len(mention) < 2:
                continue
            if mention not in seen:
                seen.append(mention)
        return seen[:5]

    def _extract_evidence(self, content: str) -> str:
        content = content.strip()
        if not content:
            return "原文缺失"
        sentence = re.split(r"[。！？!?\n]", content)[0].strip()
        return sentence or content[:200]

    def _build_summary(self, title: str, content: str) -> str:
        sentence = self._extract_evidence(content)
        if sentence and title not in sentence:
            return f"{title}。{sentence}"[:240]
        return (title or sentence)[:240]

    def _infer_unit_type(self, title: str, content: str) -> str:
        text = f"{title} {content}"
        mapping = {
            "lawsuit": ("诉讼", "仲裁", "法院"),
            "debt_default": ("违约", "逾期", "债务"),
            "equity_pledge": ("质押",),
            "control_change": ("实控", "控制权变更", "董事长辞任"),
            "policy_sanction": ("处罚", "制裁", "监管", "政策"),
            "investment": ("投资", "融资", "收购", "并购"),
            "cooperation": ("合作", "签约", "协议"),
        }
        for unit_type, keywords in mapping.items():
            if any(keyword in text for keyword in keywords):
                return unit_type
        return "general_event"

    def _infer_tags(self, title: str, content: str) -> list[str]:
        text = f"{title} {content}"
        tags: list[str] = []
        if any(keyword in text for keyword in ("监管", "处罚", "制裁")):
            tags.append("监管")
        if any(keyword in text for keyword in ("投资", "融资", "并购")):
            tags.append("资本运作")
        if any(keyword in text for keyword in ("产品", "发布", "上市")):
            tags.append("业务进展")
        return tags
