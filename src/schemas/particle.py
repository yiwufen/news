"""
情报微粒 Schema 定义

核心数据契约，Worker Agent 输出的结构化情报。
严格按照 docs/SHARED_RULES.md 中的共享规范定义。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from src.schemas.enums import EventType, RiskLevel
from src.schemas.graph import GraphUpdates


class Metadata(BaseModel):
    """
    情报元数据

    记录情报的来源、时间和可信度。
    """

    source: str = Field(
        ...,
        description="来源文件名或 URL",
    )
    event_time: date = Field(
        ...,
        description="事件发生时间（非报道时间）",
    )
    reliability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="信息可靠度 (0-1)",
    )

    @field_validator("reliability")
    @classmethod
    def validate_reliability(cls, v: float) -> float:
        """确保可靠度在有效范围内"""
        return round(v, 2)


class RiskSignal(BaseModel):
    """
    风险信号

    描述识别到的风险类型、等级和详情。
    """

    type: EventType = Field(
        ...,
        description="事件类型",
    )
    level: RiskLevel = Field(
        ...,
        description="风险等级",
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="风险描述 (10-500字)",
    )


class Traceability(BaseModel):
    """
    可溯源性

    记录情报的来源文档和冲突状态。
    """

    source_doc_ids: list[str] = Field(
        default_factory=list,
        description="原始文档 ID 列表",
    )
    is_contradictory: bool = Field(
        default=False,
        description="是否存在冲突情报",
    )
    contradiction_notes: str | None = Field(
        default=None,
        description="冲突说明",
    )


class IntelligenceParticle(BaseModel):
    """
    情报微粒 - 核心数据契约

    Worker Agent 输出的结构化情报，包含：
    - 唯一标识
    - 元数据（来源、时间、可信度）
    - 风险信号（类型、等级、描述）
    - 图谱更新（节点、边）
    - 可溯源性（来源文档、冲突标记）
    """

    id: str = Field(
        default_factory=lambda: f"evt_{uuid4().hex[:12]}",
        description="微粒唯一标识",
    )
    metadata: Metadata = Field(
        ...,
        description="元数据",
    )
    risk_signal: RiskSignal = Field(
        ...,
        description="风险信号",
    )
    graph_updates: GraphUpdates = Field(
        default_factory=GraphUpdates,
        description="图谱更新数据",
    )
    traceability: Traceability = Field(
        default_factory=Traceability,
        description="可溯源性",
    )

    # === 便捷属性 ===

    @property
    def event_type(self) -> EventType:
        """获取事件类型"""
        return self.risk_signal.type

    @property
    def risk_level(self) -> RiskLevel:
        """获取风险等级"""
        return self.risk_signal.level

    @property
    def source_doc_ids(self) -> list[str]:
        """获取来源文档 ID 列表"""
        return self.traceability.source_doc_ids

    @property
    def event_time(self) -> date:
        """获取事件时间"""
        return self.metadata.event_time

    # === 工厂方法 ===

    @classmethod
    def from_db_dict(cls, data: dict[str, Any]) -> IntelligenceParticle | None:
        """从数据库字典创建 IntelligenceParticle

        处理数据库存储格式与 Schema 的差异。

        Args:
            data: 数据库中存储的微粒字典

        Returns:
            IntelligenceParticle 对象，转换失败返回 None
        """
        try:
            # 解析事件时间
            event_time_str = data.get("event_time")
            if event_time_str:
                try:
                    event_time = date.fromisoformat(event_time_str)
                except ValueError:
                    event_time = date.today()
            else:
                event_time = date.today()

            # 解析事件类型
            event_type_str = data.get("event_type", "RESTRUCTURING")
            try:
                event_type = EventType(event_type_str)
            except ValueError:
                event_type = EventType.RESTRUCTURING

            # 解析风险等级
            risk_level_str = data.get("risk_level", "MEDIUM")
            try:
                risk_level = RiskLevel(risk_level_str)
            except ValueError:
                risk_level = RiskLevel.MEDIUM

            return cls(
                id=data.get("particle_id", data.get("id", "")),
                metadata=Metadata(
                    source=data.get("source", "unknown"),
                    event_time=event_time,
                    reliability=float(data.get("reliability", 0.8)),
                ),
                risk_signal=RiskSignal(
                    type=event_type,
                    level=risk_level,
                    description=data.get("event_summary", ""),
                ),
                traceability=Traceability(
                    source_doc_ids=data.get("source_doc_ids", []),
                ),
            )
        except Exception:
            return None


class ExtractionResult(BaseModel):
    """提取结果包装"""

    success: bool
    particle: IntelligenceParticle | None = None
    error_message: str | None = None
    raw_response: str | None = None


# === Tool Use Schema ===

EXTRACTION_TOOL_SCHEMA: dict[str, Any] = {
    "name": "extract_intelligence_particle",
    "description": "从新闻文本中提取结构化情报微粒",
    "input_schema": IntelligenceParticle.model_json_schema(),
}
