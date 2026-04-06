"""API request models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.skills.models import SkillType


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""

    user_id: str | None = Field(default=None, description="用户标识")
    ttl_seconds: int | None = Field(
        default=None, ge=60, le=86400, description="会话 TTL (秒)"
    )
    initial_context: dict[str, Any] | None = Field(default=None, description="初始上下文变量")


class ExtendTTLRequest(BaseModel):
    """Request to extend session TTL."""

    ttl_seconds: int = Field(..., ge=60, le=86400, description="新的 TTL (秒)")


class ExecuteTaskRequest(BaseModel):
    """Request to execute a single task."""

    skill_type: SkillType = Field(..., description="技能类型")
    query: str = Field(..., min_length=1, max_length=2000, description="查询文本")
    use_context: bool = Field(default=True, description="是否使用会话上下文")
    input_variables: dict[str, Any] | None = Field(default=None, description="输入变量映射")


class TaskDefinitionRequest(BaseModel):
    """Request model for task definition in a chain."""

    task_id: str = Field(..., description="任务 ID")
    skill_type: SkillType = Field(..., description="技能类型")
    query: str = Field(..., min_length=1, max_length=2000, description="查询文本")
    depends_on: list[str] = Field(default_factory=list, description="依赖任务 ID 列表")
    input_mapping: dict[str, str] = Field(default_factory=dict, description="输入变量映射")
    condition: str | None = Field(default=None, description="执行条件")


class ExecuteChainRequest(BaseModel):
    """Request to execute a chain of tasks."""

    tasks: list[TaskDefinitionRequest] = Field(
        ..., min_length=1, max_length=20, description="任务列表"
    )
    parallel: bool = Field(default=False, description="是否并行执行")
    stop_on_failure: bool = Field(default=True, description="失败时是否停止")


class SetVariableRequest(BaseModel):
    """Request to set a session variable."""

    value: Any = Field(..., description="变量值")
