"""API response models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Error detail structure."""

    code: str = Field(..., description="错误代码")
    message: str = Field(..., description="错误消息")
    details: dict[str, Any] | None = Field(default=None, description="额外详情")


class APIError(BaseModel):
    """API error response."""

    error: ErrorDetail = Field(..., description="错误详情")
    request_id: str | None = Field(default=None, description="请求 ID")


class SessionResponse(BaseModel):
    """Session response model."""

    session_id: str = Field(..., description="会话 ID")
    user_id: str | None = Field(default=None, description="用户 ID")
    state: str = Field(..., description="会话状态")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    ttl_seconds: int = Field(..., description="TTL (秒)")
    expires_in: int | None = Field(default=None, description="剩余秒数")


class TaskResultResponse(BaseModel):
    """Task result response model."""

    task_id: str = Field(..., description="任务 ID")
    skill_type: str = Field(..., description="技能类型")
    state: str = Field(..., description="任务状态")
    started_at: datetime = Field(..., description="开始时间")
    completed_at: datetime | None = Field(default=None, description="完成时间")
    output: dict[str, Any] = Field(default_factory=dict, description="输出结果")
    errors: list[str] = Field(default_factory=list, description="错误列表")
    duration_ms: int = Field(default=0, description="执行耗时 (毫秒)")


class ContextSummaryResponse(BaseModel):
    """Context summary response model."""

    session_id: str = Field(..., description="会话 ID")
    state: str = Field(..., description="会话状态")
    known_entities: list[dict[str, Any]] = Field(default_factory=list, description="已知实体")
    known_clusters_count: int = Field(default=0, description="已知事件簇数量")
    task_count: int = Field(default=0, description="任务数量")
    variables: list[str] = Field(default_factory=list, description="变量名列表")


class VariableResponse(BaseModel):
    """Single variable response model."""

    key: str = Field(..., description="变量名")
    value: Any = Field(..., description="变量值")


class VariablesResponse(BaseModel):
    """All variables response model."""

    variables: dict[str, Any] = Field(default_factory=dict, description="变量字典")


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str = Field(..., description="状态: healthy | unhealthy")
    version: str = Field(..., description="API 版本")
    timestamp: datetime = Field(..., description="时间戳")


class ReadyResponse(BaseModel):
    """Readiness check response model."""

    status: str = Field(..., description="状态: ready | not_ready")
    checks: dict[str, bool] = Field(default_factory=dict, description="检查项")
