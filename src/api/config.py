"""API configuration management."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class APIConfig(BaseSettings):
    """API configuration from environment variables."""

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_version: str = "1.0.0"
    api_title: str = "金融知识检索 API"
    api_description: str = "多轮任务会话管理与技能检索服务"

    session_default_ttl: int = 3600
    session_max_ttl: int = 86400
    session_cleanup_interval: int = 60

    storage_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"

    max_concurrent_tasks: int = 3
    task_timeout_seconds: int = 300

    model_config = {"env_prefix": "APP_", "env_file": ".env", "extra": "ignore"}


@lru_cache
def get_config() -> APIConfig:
    """Get configuration singleton."""
    return APIConfig()
