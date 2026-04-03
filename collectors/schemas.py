"""
数据收集器 - Schema 模块

向后兼容层，导出新的 Schema 定义。
保留旧版 IntelligenceParticle 以便渐进迁移。
"""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

# === 从新模块导入 ===
from src.schemas import (
    EntityType,
    EventType,
    ExtractionResult,
    GraphEdge,
    GraphNode,
    GraphUpdates,
    IntelligenceParticle,
    Metadata,
    RelationType,
    RiskLevel,
    RiskSignal,
    Traceability,
    EXTRACTION_TOOL_SCHEMA,
)

# === 旧版 Schema（向后兼容）===


class LegacyIntelligenceParticle(BaseModel):
    """
    旧版情报微粒 - 已废弃

    保留用于渐进迁移，新代码应使用 src.schemas.IntelligenceParticle。
    """

    particle_id: str = Field(
        default_factory=lambda: f"evt_{uuid4().hex[:12]}",
        description="微粒唯一标识",
    )
    slice_window: str = Field(
        ...,
        description="时间切片，格式: YYYY-WNN",
        pattern=r"^\d{4}-W\d{2}$",
    )
    event_type: str = Field(
        ...,
        description="事件类型",
    )
    event_summary: str = Field(
        ...,
        description="事件摘要 (50-300字)",
        min_length=50,
        max_length=300,
    )
    entities: list[str] = Field(
        default_factory=list,
        description="涉及实体名称列表",
    )
    source_doc_ids: list[str] = Field(
        default_factory=list,
        description="原始文档ID列表",
    )


# === 旧版 Tool Schema（向后兼容）===

LEGACY_EXTRACTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "extract_intelligence_particle",
    "description": "从新闻文本中提取结构化情报微粒",
    "input_schema": LegacyIntelligenceParticle.model_json_schema(),
}


# === 导出 ===

__all__ = [
    # 新版 Schema
    "IntelligenceParticle",
    "Metadata",
    "RiskSignal",
    "Traceability",
    "GraphUpdates",
    "GraphNode",
    "GraphEdge",
    "ExtractionResult",
    "EXTRACTION_TOOL_SCHEMA",
    # 枚举
    "EventType",
    "RelationType",
    "EntityType",
    "RiskLevel",
    # 旧版兼容
    "LegacyIntelligenceParticle",
    "LEGACY_EXTRACTION_TOOL_SCHEMA",
]
