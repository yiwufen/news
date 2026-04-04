"""
意图解析层数据模型

定义意图类型、结构化查询等核心数据结构。
按 .claude/rules/04-intent-retrieval.md 规范实现。
"""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


class IntentType(Enum):
    """意图类型枚举

    用户查询意图的分类。
    """

    ENTITY_TIMELINE = "ENTITY_TIMELINE"  # 实体历史行为时间线
    RISK_ASSESSMENT = "RISK_ASSESSMENT"  # 实体风险评估
    RELATIONSHIP_QUERY = "RELATIONSHIP_QUERY"  # 实体关系路径查询
    COMPARATIVE_ANALYSIS = "COMPARATIVE_ANALYSIS"  # 多实体对比分析
    EVENT_IMPACT = "EVENT_IMPACT"  # 事件影响分析


@dataclass
class TimeRange:
    """时间范围

    表示查询的时间边界。
    """

    start: date
    end: date

    def to_dict(self) -> dict[str, str]:
        """转换为字典"""
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
        }

    def __str__(self) -> str:
        return f"{self.start.isoformat()} ~ {self.end.isoformat()}"


@dataclass
class QueryFilters:
    """查询过滤条件

    用于检索层的元数据过滤。
    """

    event_types: list[str] | None = None
    risk_levels: list[str] | None = None
    sources: list[str] | None = None
    min_credibility: float = 0.5
    categories: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "event_types": self.event_types,
            "risk_levels": self.risk_levels,
            "sources": self.sources,
            "min_credibility": self.min_credibility,
            "categories": self.categories,
        }


@dataclass
class StructuredQuery:
    """结构化查询

    意图解析层的输出，包含解析后的查询信息。
    """

    intent: IntentType
    entities: list[str]
    time_range: TimeRange | None
    filters: QueryFilters
    original_query: str
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "intent": self.intent.value,
            "entities": self.entities,
            "time_range": self.time_range.to_dict() if self.time_range else None,
            "filters": self.filters.to_dict(),
            "original_query": self.original_query,
            "confidence": self.confidence,
        }

    def get_target_entity(self) -> str | None:
        """获取主要目标实体"""
        return self.entities[0] if self.entities else None
