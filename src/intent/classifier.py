"""Intent parsing and deterministic query normalization."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from dateutil.relativedelta import relativedelta

from src.entities import EntityRepository, entity_matches_query_name, entity_name_in_text
from src.intent.models import IntentType, QueryFilters, StructuredQuery, TimeRange
from src.llm import (
    DEFAULT_MAX_TOKENS,
    create_llm_client,
    extract_text_from_response,
    parse_json_from_text,
)


class IntentClassifier:
    """Parse natural language into StructuredQuery."""

    SYSTEM_PROMPT = """你是一个意图解析专家。你的任务是将用户的自然语言查询解析成结构化格式。
## 意图类型
- ENTITY_TIMELINE: 查看某实体的历史行为时间线
- ENTITY_OVERVIEW: 给出某实体的整体知识概览
- RELATIONSHIP_QUERY: 查询实体间的关系路径
- COMPARATIVE_ANALYSIS: 多实体对比分析
- EVENT_ANALYSIS: 事件知识分析

## 输出要求
返回 JSON 格式：
{
  "intent": "意图类型",
  "entities": ["实体名称列表"],
  "time_expression": "时间表达式（如果有）",
  "filters": {
    "event_types": ["事件类型过滤"],
    "risk_levels": ["风险等级过滤"]
  },
  "confidence": 0.0-1.0
}

## 注意事项
- 实体名称保持原样，不要猜测或修改
- 时间表达式保留原始表达
- 置信度反映解析的确定性"""

    def __init__(self, entity_repository: EntityRepository | None = None):
        self.client = None
        self.model = None
        self.max_tokens = min(DEFAULT_MAX_TOKENS, 1024)
        self.entity_repository = entity_repository or EntityRepository()

    def parse(self, raw_query: str) -> StructuredQuery:
        parsed = self._call_llm(raw_query)
        intent = self._parse_intent(parsed.get("intent", ""))

        llm_entities = self._normalize_entities(parsed.get("entities"))
        fallback_entities = self._match_entities_from_query(raw_query)
        entities = self._merge_entities(llm_entities, fallback_entities)

        time_expression = self._extract_time_expression(parsed, raw_query)
        time_range = self.parse_time_range(time_expression)

        filters_data = parsed.get("filters", {})
        if not isinstance(filters_data, dict):
            filters_data = {}
        filters = QueryFilters(
            event_types=filters_data.get("event_types"),
            risk_levels=filters_data.get("risk_levels"),
        )

        confidence = parsed.get("confidence", 0.8)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.8

        return StructuredQuery(
            intent=intent,
            entities=entities,
            time_range=time_range,
            filters=filters,
            original_query=raw_query,
            confidence=max(0.0, min(1.0, confidence)),
        )

    def _get_client(self):
        if self.client is None or self.model is None:
            self.client, self.model = create_llm_client()
        return self.client, self.model

    def _call_llm(self, query: str) -> dict[str, Any]:
        client, model = self._get_client()
        response = client.messages.create(
            model=model,
            max_tokens=self.max_tokens,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"解析以下查询：{query}"}],
        )

        content = extract_text_from_response(response)
        return parse_json_from_text(
            content,
            default={
                "intent": "ENTITY_TIMELINE",
                "entities": [],
                "confidence": 0.5,
            },
        )

    def _parse_intent(self, intent_str: str) -> IntentType:
        normalized = (intent_str or "").strip()
        intent_map = {
            "ENTITY_TIMELINE": IntentType.ENTITY_TIMELINE,
            "ENTITY_OVERVIEW": IntentType.ENTITY_OVERVIEW,
            "RELATIONSHIP_QUERY": IntentType.RELATIONSHIP_QUERY,
            "COMPARATIVE_ANALYSIS": IntentType.COMPARATIVE_ANALYSIS,
            "EVENT_ANALYSIS": IntentType.EVENT_ANALYSIS,
            "RISK_ASSESSMENT": IntentType.ENTITY_OVERVIEW,
            "EVENT_IMPACT": IntentType.EVENT_ANALYSIS,
            "时间线": IntentType.ENTITY_TIMELINE,
            "实体概览": IntentType.ENTITY_OVERVIEW,
            "风险评估": IntentType.ENTITY_OVERVIEW,
            "关系查询": IntentType.RELATIONSHIP_QUERY,
            "对比分析": IntentType.COMPARATIVE_ANALYSIS,
            "事件分析": IntentType.EVENT_ANALYSIS,
            "事件影响": IntentType.EVENT_ANALYSIS,
        }
        return intent_map.get(normalized, IntentType.ENTITY_TIMELINE)

    def parse_time_range(
        self,
        expression: str,
        ref: date | None = None,
    ) -> TimeRange | None:
        if not expression:
            return None

        expression = expression.strip().lower()
        ref = ref or date.today()

        relative_patterns = (
            (r"(过去一年|最近一年)", relativedelta(years=1)),
            (r"(过去三个月|最近三个月)", relativedelta(months=3)),
            (r"(过去半年|最近半年)", relativedelta(months=6)),
            (r"(今年以来)", "ytd"),
            (r"\b(last year|past year|over the last year)\b", relativedelta(years=1)),
            (r"\b(last 3 months|past 3 months|over the last 3 months)\b", relativedelta(months=3)),
            (r"\b(last 6 months|past 6 months|over the last 6 months)\b", relativedelta(months=6)),
            (r"\b(year to date|ytd)\b", "ytd"),
        )

        for pattern, delta in relative_patterns:
            if re.search(pattern, expression):
                if isinstance(delta, str):
                    return TimeRange(start=date(ref.year, 1, 1), end=ref)
                return TimeRange(start=ref - delta, end=ref)

        quarter_match = re.search(r"(\d{4})\s*[年-]?\s*q([1-4])", expression, re.IGNORECASE)
        if quarter_match:
            year = int(quarter_match.group(1))
            quarter = int(quarter_match.group(2))
            start_month = (quarter - 1) * 3 + 1
            start = date(year, start_month, 1)
            end = start + relativedelta(months=3) - relativedelta(days=1)
            return TimeRange(start=start, end=end)

        year_match = re.search(r"\b(20\d{2})\b", expression)
        if year_match:
            year = int(year_match.group(1))
            return TimeRange(
                start=date(year, 1, 1),
                end=date(year, 12, 31),
            )

        return None

    def classify_intent(self, query: str) -> IntentType:
        result = self._call_llm(query)
        return self._parse_intent(result.get("intent", ""))

    def extract_entities(self, query: str) -> list[str]:
        result = self._call_llm(query)
        llm_entities = self._normalize_entities(result.get("entities"))
        return self._merge_entities(llm_entities, self._match_entities_from_query(query))

    def _normalize_entities(self, entities: Any) -> list[str]:
        if not isinstance(entities, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            if not isinstance(entity, str):
                continue
            candidate = entity.strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(candidate)
        return normalized

    def _merge_entities(self, primary: list[str], fallback: list[str]) -> list[str]:
        merged: list[str] = []
        for entity in primary + fallback:
            if any(entity_matches_query_name([existing], entity) for existing in merged):
                continue
            merged.append(entity)
        return merged

    def _extract_time_expression(self, parsed: dict[str, Any], raw_query: str) -> str:
        time_expression = parsed.get("time_expression", "")
        if isinstance(time_expression, str) and time_expression.strip():
            return time_expression.strip()
        return raw_query

    def _match_entities_from_query(self, raw_query: str) -> list[str]:
        query = raw_query.strip()
        if not query:
            return []

        matched: list[tuple[int, str]] = []
        for entity in self.entity_repository.get_all():
            candidates = [entity.canonical_name, *entity.aliases]
            longest_match = 0
            best_name: str | None = None
            for candidate in candidates:
                if not candidate.strip():
                    continue
                if not entity_name_in_text([candidate], query):
                    continue
                score = len(candidate.strip())
                if score > longest_match:
                    longest_match = score
                    best_name = candidate.strip()

            if best_name:
                matched.append((longest_match, entity.canonical_name))

        matched.sort(key=lambda item: (-item[0], item[1]))
        deduped: list[str] = []
        for _, entity_name in matched:
            if any(entity_matches_query_name([existing], entity_name) for existing in deduped):
                continue
            deduped.append(entity_name)
        return deduped[:5]
