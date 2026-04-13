"""
Request context models for the knowledge retrieval pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from src.schemas.query import IntentType, QueryFilters, TimeRange


@dataclass
class QueryInput:
    """用户查询输入。"""

    raw_query: str = ""
    entities: list[str] = field(default_factory=list)
    time_range: TimeRange | None = None
    intent: IntentType | None = None
    filters: QueryFilters = field(default_factory=QueryFilters)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "raw_query": self.raw_query,
            "entities": self.entities,
            "time_range": self.time_range.to_dict() if self.time_range else None,
            "intent": self.intent.value if self.intent else None,
            "filters": self.filters.to_dict(),
        }


@dataclass
class StageOutput:
    """单个阶段的输出。"""

    stage_name: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "stage_name": self.stage_name,
            "success": self.success,
            "data": self.data,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def failure(cls, stage_name: str, errors: list[str]) -> StageOutput:
        """创建失败输出的便捷方法。"""
        return cls(stage_name=stage_name, success=False, errors=errors)

    @classmethod
    def ok(
        cls,
        stage_name: str,
        data: dict[str, Any],
        duration_ms: int = 0,
    ) -> StageOutput:
        """创建成功输出的便捷方法。"""
        return cls(
            stage_name=stage_name,
            success=True,
            data=data,
            duration_ms=duration_ms,
        )


@dataclass
class PipelineContext:
    """一次知识检索请求的上下文载体。"""

    request_id: str = field(default_factory=lambda: str(uuid4())[:8])
    created_at: datetime = field(default_factory=datetime.now)
    input: QueryInput | None = None
    stages: dict[str, StageOutput] = field(default_factory=dict)
    graph_enabled: bool = True
    retry_count: int = 0
    current_stage: str = "init"

    def get_knowledge_units(self) -> list[dict[str, Any]]:
        """获取知识单元结果。"""
        retrieval = self.stages.get("retrieval")
        if retrieval and retrieval.success:
            units = retrieval.data.get("knowledge_units", [])
            if isinstance(units, list):
                return units

        worker = self.stages.get("worker")
        if worker and worker.success:
            units = worker.data.get("knowledge_units", [])
            if isinstance(units, list):
                return units

        return []

    def get_entities(self) -> list[dict[str, Any]]:
        """获取实体结果。"""
        retrieval = self.stages.get("retrieval")
        if retrieval and retrieval.success:
            entities = retrieval.data.get("entities", [])
            if isinstance(entities, list):
                return entities

        integrator = self.stages.get("integrator")
        if integrator and integrator.success:
            entities = integrator.data.get("entities", [])
            if isinstance(entities, list):
                return entities

        return []

    def get_event_clusters(self) -> list[dict[str, Any]]:
        """获取事件簇结果。"""
        retrieval = self.stages.get("retrieval")
        if retrieval and retrieval.success:
            clusters = retrieval.data.get("event_clusters", [])
            if isinstance(clusters, list):
                return clusters

        integrator = self.stages.get("integrator")
        if integrator and integrator.success:
            clusters = integrator.data.get("event_clusters", [])
            if isinstance(clusters, list):
                return clusters

        return []

    def get_articles(self) -> list[dict[str, Any]]:
        """获取文章数据。"""
        input_stage = self.stages.get("input")
        if input_stage and input_stage.success:
            articles = input_stage.data.get("articles", [])
            if isinstance(articles, list):
                return articles

        retrieval = self.stages.get("retrieval")
        if retrieval and retrieval.success:
            articles = retrieval.data.get("articles", [])
            if isinstance(articles, list):
                return articles

        return []

    def get_stage_data(self, stage_name: str) -> dict[str, Any]:
        """获取指定阶段的数据。"""
        stage = self.stages.get(stage_name)
        if stage and stage.success:
            return stage.data
        return {}

    def add_stage(self, output: StageOutput) -> None:
        """添加阶段输出。"""
        self.stages[output.stage_name] = output
        self.current_stage = output.stage_name

    def add_error(self, stage: str, error: str) -> None:
        """记录错误。"""
        if stage not in self.stages:
            self.stages[stage] = StageOutput(
                stage_name=stage,
                success=False,
                errors=[error],
            )
        else:
            self.stages[stage].errors.append(error)

    def is_verification_passed(self) -> bool:
        """检查质量核查是否通过。"""
        critic = self.stages.get("critic")
        return critic is not None and critic.data.get("passed", False)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        return {
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
            "input": self.input.to_dict() if self.input else None,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "graph_enabled": self.graph_enabled,
            "retry_count": self.retry_count,
            "current_stage": self.current_stage,
        }
