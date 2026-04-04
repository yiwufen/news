"""
意图分类器

将用户自然语言查询解析为结构化查询。
"""

from __future__ import annotations

import re
from datetime import date

from dateutil.relativedelta import relativedelta

from src.intent.models import IntentType, QueryFilters, StructuredQuery, TimeRange
from src.llm import create_llm_client, extract_text_from_response, parse_json_from_text, DEFAULT_MAX_TOKENS


class IntentClassifier:
    """意图分类器

    将用户自然语言查询解析为结构化查询。
    """

    # System prompt for intent classification
    SYSTEM_PROMPT = """你是一个意图解析专家。你的任务是将用户的自然语言查询解析为结构化格式。

## 意图类型
- ENTITY_TIMELINE: 查看某实体的历史行为时间线
- RISK_ASSESSMENT: 评估某实体的风险暴露
- RELATIONSHIP_QUERY: 查询实体间的关系路径
- COMPARATIVE_ANALYSIS: 多实体对比分析
- EVENT_IMPACT: 事件影响分析

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
- 时间表达式保留原始表述
- 置信度反映解析的确定性"""

    def __init__(self):
        """初始化意图分类器"""
        self.client, self.model = create_llm_client()
        self.max_tokens = 1024

    def parse(self, raw_query: str) -> StructuredQuery:
        """解析用户查询

        Args:
            raw_query: 用户原始查询字符串

        Returns:
            StructuredQuery: 结构化查询对象
        """
        # 1. 调用 LLM 解析意图
        parsed = self._call_llm(raw_query)

        # 2. 提取意图类型
        intent = self._parse_intent(parsed.get("intent", ""))

        # 3. 提取实体
        entities = parsed.get("entities", [])

        # 4. 解析时间范围
        time_expression = parsed.get("time_expression", "")
        time_range = self.parse_time_range(time_expression) if time_expression else None

        # 5. 构建过滤条件
        filters_data = parsed.get("filters", {})
        filters = QueryFilters(
            event_types=filters_data.get("event_types"),
            risk_levels=filters_data.get("risk_levels"),
        )

        # 6. 获取置信度
        confidence = parsed.get("confidence", 0.8)

        return StructuredQuery(
            intent=intent,
            entities=entities,
            time_range=time_range,
            filters=filters,
            original_query=raw_query,
            confidence=confidence,
        )

    def _call_llm(self, query: str) -> dict:
        """调用 LLM 解析查询

        Args:
            query: 用户查询

        Returns:
            解析结果字典
        """
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"解析以下查询：{query}"}],
        )

        # 提取响应内容并解析 JSON
        content = extract_text_from_response(response)
        return parse_json_from_text(content, default={
            "intent": "ENTITY_TIMELINE",
            "entities": [],
            "confidence": 0.5,
        })

    def _parse_intent(self, intent_str: str) -> IntentType:
        """解析意图类型字符串

        Args:
            intent_str: 意图类型字符串

        Returns:
            IntentType 枚举值
        """
        intent_map = {
            "ENTITY_TIMELINE": IntentType.ENTITY_TIMELINE,
            "RISK_ASSESSMENT": IntentType.RISK_ASSESSMENT,
            "RELATIONSHIP_QUERY": IntentType.RELATIONSHIP_QUERY,
            "COMPARATIVE_ANALYSIS": IntentType.COMPARATIVE_ANALYSIS,
            "EVENT_IMPACT": IntentType.EVENT_IMPACT,
            "时间线": IntentType.ENTITY_TIMELINE,
            "风险评估": IntentType.RISK_ASSESSMENT,
            "关系查询": IntentType.RELATIONSHIP_QUERY,
            "对比分析": IntentType.COMPARATIVE_ANALYSIS,
            "事件影响": IntentType.EVENT_IMPACT,
        }
        return intent_map.get(intent_str, IntentType.ENTITY_TIMELINE)

    def parse_time_range(self, expression: str) -> TimeRange | None:
        """解析时间表达式

        Args:
            expression: 时间表达式

        Returns:
            TimeRange 或 None
        """
        expression = expression.strip().lower()
        ref = date.today()

        # 相对时间表达式
        if "过去一年" in expression or "最近一年" in expression:
            return TimeRange(
                start=ref - relativedelta(years=1),
                end=ref,
            )
        elif "过去三个月" in expression or "近三个月" in expression:
            return TimeRange(
                start=ref - relativedelta(months=3),
                end=ref,
            )
        elif "过去半年" in expression or "近半年" in expression:
            return TimeRange(
                start=ref - relativedelta(months=6),
                end=ref,
            )
        elif "今年以来" in expression:
            return TimeRange(
                start=date(ref.year, 1, 1),
                end=ref,
            )

        # 绝对时间表达式：季度
        quarter_match = re.search(r"(\d{4})年?Q(\d)", expression)
        if quarter_match:
            year = int(quarter_match.group(1))
            quarter = int(quarter_match.group(2))
            quarter_start_month = (quarter - 1) * 3 + 1
            quarter_end_month = quarter * 3
            return TimeRange(
                start=date(year, quarter_start_month, 1),
                end=date(year, quarter_end_month, 1) + relativedelta(months=1) - relativedelta(days=1),
            )

        # 绝对时间表达式：年份
        year_match = re.search(r"(\d{4})年", expression)
        if year_match:
            year = int(year_match.group(1))
            return TimeRange(
                start=date(year, 1, 1),
                end=date(year, 12, 31),
            )

        return None

    def classify_intent(self, query: str) -> IntentType:
        """仅分类意图类型

        Args:
            query: 用户查询

        Returns:
            意图类型
        """
        result = self._call_llm(query)
        return self._parse_intent(result.get("intent", ""))

    def extract_entities(self, query: str) -> list[str]:
        """仅提取实体

        Args:
            query: 用户查询

        Returns:
            实体名称列表
        """
        result = self._call_llm(query)
        return result.get("entities", [])
