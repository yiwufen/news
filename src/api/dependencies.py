"""Dependency injection for API routes."""

from __future__ import annotations

from functools import lru_cache

from src.api.config import APIConfig, get_config
from src.session import (
    InMemorySessionStore,
    RedisSessionStore,
    SessionConfig,
    SessionOrchestrator,
    TaskExecutor,
)


@lru_cache
def get_session_store() -> InMemorySessionStore | RedisSessionStore:
    """Get session store instance based on configuration."""
    config = get_config()
    if config.storage_backend == "redis":
        return RedisSessionStore(redis_url=config.redis_url)
    return InMemorySessionStore(cleanup_interval_seconds=config.session_cleanup_interval)


@lru_cache
def get_orchestrator() -> SessionOrchestrator:
    """Get SessionOrchestrator singleton."""
    config = get_config()
    store = get_session_store()
    executor = TaskExecutor(max_workers=config.max_concurrent_tasks)
    session_config = SessionConfig(
        max_concurrent_tasks=config.max_concurrent_tasks,
        default_ttl=config.session_default_ttl,
    )
    return SessionOrchestrator(store=store, executor=executor, config=session_config)
