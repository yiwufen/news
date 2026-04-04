"""
LangGraph 状态定义

定义多 Agent 流水线的全局状态。
采用 PipelineContext 上下文对象架构，实现职责分离。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from src.intent.models import IntentType, QueryFilters, TimeRange
from src.schemas import IntelligenceParticle


@dataclass
class QueryInput:
    """用户查询输入

    职责：只承载用户的原始输入和意图解析结果。
    不包含中间处理数据。

    Attributes:
        raw_query: 用户的原始自然语言查询
        entities: 从查询中提取的实体列表
        time_range: 解析出的时间范围
        intent: 识别的意图类型
        filters: 查询过滤条件
    """

    raw_query: str = ""
    entities: list[str] = field(default_factory=list)
    time_range: TimeRange | None = None
    intent: IntentType | None = None
    filters: QueryFilters = field(default_factory=QueryFilters)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "raw_query": self.raw_query,
            "entities": self.entities,
            "time_range": self.time_range.to_dict() if self.time_range else None,
            "intent": self.intent.value if self.intent else None,
            "filters": self.filters.to_dict(),
        }


@dataclass
class StageOutput:
    """单个阶段的输出

    职责：记录一个处理阶段的执行结果。
    包含成功/失败状态、输出数据、错误信息和执行耗时。

    Attributes:
        stage_name: 阶段名称（如 "intent_parse", "retrieval", "master"）
        success: 是否执行成功
        data: 阶段输出数据
        errors: 错误信息列表
        duration_ms: 执行耗时（毫秒）
    """

    stage_name: str
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "stage_name": self.stage_name,
            "success": self.success,
            "data": self.data,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def failure(cls, stage_name: str, errors: list[str]) -> StageOutput:
        """创建失败输出的便捷方法"""
        return cls(stage_name=stage_name, success=False, errors=errors)

    @classmethod
    def ok(
        cls,
        stage_name: str,
        data: dict[str, Any],
        duration_ms: int = 0,
    ) -> StageOutput:
        """创建成功输出的便捷方法"""
        return cls(
            stage_name=stage_name,
            success=True,
            data=data,
            duration_ms=duration_ms,
        )


@dataclass
class PipelineContext:
    """流水线上下文

    职责：作为一次请求的完整生命周期载体。
    - 管理流程控制状态（当前阶段、重试次数）
    - 记录各阶段的输入输出
    - 提供便捷的数据访问方法

    设计原则：
    - 输入与输出分离：input 只包含用户输入，stages 记录各阶段产出
    - 不可变历史：已完成的阶段输出不应被修改
    - 可追溯：通过 request_id 和 stages 可复现完整执行过程

    Attributes:
        request_id: 请求唯一标识
        created_at: 请求创建时间
        input: 用户查询输入
        stages: 各阶段输出（按执行顺序记录）
        graph_enabled: 是否启用图谱同步
        retry_count: Critic 重试次数
        current_stage: 当前执行阶段
    """

    request_id: str = field(default_factory=lambda: str(uuid4())[:8])
    created_at: datetime = field(default_factory=datetime.now)
    input: QueryInput | None = None
    stages: dict[str, StageOutput] = field(default_factory=dict)
    graph_enabled: bool = True
    retry_count: int = 0
    current_stage: str = "init"

    def get_particles(self) -> list[IntelligenceParticle]:
        """获取情报微粒

        优先级：
        1. retrieval 阶段检索到的微粒
        2. worker 阶段提取的微粒

        Returns:
            情报微粒列表
        """
        # 优先从检索结果获取
        retrieval = self.stages.get("retrieval")
        if retrieval and retrieval.success:
            particles_data = retrieval.data.get("particles", [])
            if particles_data:
                return self._convert_particle_dicts(particles_data)

        # 其次从 worker 获取
        worker = self.stages.get("worker")
        if worker and worker.success:
            return worker.data.get("particles", [])

        return []

    def get_report(self) -> dict[str, Any]:
        """获取分析报告

        Returns:
            Master Agent 生成的报告
        """
        master = self.stages.get("master")
        if master and master.success:
            return master.data
        return {}

    def get_articles(self) -> list[dict[str, Any]]:
        """获取文章数据

        优先级：
        1. 直接输入的文章
        2. retrieval 阶段检索到的文章

        Returns:
            文章列表
        """
        # 从直接输入获取
        input_stage = self.stages.get("input")
        if input_stage and input_stage.success:
            articles = input_stage.data.get("articles", [])
            if articles:
                return articles

        # 从检索结果获取（回退场景）
        retrieval = self.stages.get("retrieval")
        if retrieval and retrieval.success:
            return retrieval.data.get("articles", [])

        return []

    def add_stage(self, output: StageOutput) -> None:
        """添加阶段输出

        Args:
            output: 阶段输出
        """
        self.stages[output.stage_name] = output
        self.current_stage = output.stage_name

    def add_error(self, stage: str, error: str) -> None:
        """记录错误

        Args:
            stage: 阶段名称
            error: 错误信息
        """
        if stage not in self.stages:
            self.stages[stage] = StageOutput(
                stage_name=stage,
                success=False,
                errors=[error],
            )
        else:
            self.stages[stage].errors.append(error)

    def is_verification_passed(self) -> bool:
        """检查 Critic 核查是否通过"""
        critic = self.stages.get("critic")
        return critic is not None and critic.data.get("passed", False)

    def _convert_particle_dicts(
        self, particles_data: list[dict]
    ) -> list[IntelligenceParticle]:
        """将数据库中的微粒字典转换为 IntelligenceParticle 对象

        Args:
            particles_data: 数据库中存储的微粒字典列表

        Returns:
            IntelligenceParticle 对象列表
        """
        particles = []
        for data in particles_data:
            particle = IntelligenceParticle.from_db_dict(data)
            if particle is not None:
                particles.append(particle)
        return particles

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "created_at": self.created_at.isoformat(),
            "input": self.input.to_dict() if self.input else None,
            "stages": {k: v.to_dict() for k, v in self.stages.items()},
            "graph_enabled": self.graph_enabled,
            "retry_count": self.retry_count,
            "current_stage": self.current_stage,
        }
