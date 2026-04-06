"""
Multi-turn task consumption layer for skill-based knowledge retrieval.

This module provides session management and task orchestration capabilities
for executing multiple skill queries with context preservation.

Example usage:

    from src.session import (
        SessionOrchestrator,
        InMemorySessionStore,
        TaskExecutor,
    )

    # Create orchestrator
    store = InMemorySessionStore()
    executor = TaskExecutor()
    orchestrator = SessionOrchestrator(store, executor)

    # Create a session
    session = orchestrator.create_session()

    # Execute tasks
    result = await orchestrator.execute_task(
        session_id=session.session_id,
        skill_type="entity_overview",
        query="查看小米集团的最新动态",
    )

    # Close session when done
    orchestrator.close_session(session.session_id)
"""

from src.session.executor import ExecutionContext, TaskExecutor
from src.session.models import (
    SessionConfig,
    SessionContext,
    SessionState,
    TaskChain,
    TaskDefinition,
    TaskResult,
    TaskState,
    create_session_id,
    create_task_id,
)
from src.session.orchestrator import SessionOrchestrator, create_orchestrator
from src.session.store import InMemorySessionStore, RedisSessionStore, SessionStore

__all__ = [
    # Models
    "SessionState",
    "TaskState",
    "TaskDefinition",
    "TaskResult",
    "SessionContext",
    "TaskChain",
    "SessionConfig",
    # Store
    "SessionStore",
    "InMemorySessionStore",
    "RedisSessionStore",
    # Executor
    "TaskExecutor",
    "ExecutionContext",
    # Orchestrator
    "SessionOrchestrator",
    "create_orchestrator",
    # Helpers
    "create_session_id",
    "create_task_id",
]
