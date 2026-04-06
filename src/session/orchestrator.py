"""
Session orchestrator service for managing multi-turn task execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.session.executor import TaskExecutor
from src.session.models import (
    SessionConfig,
    SessionContext,
    SessionState,
    TaskDefinition,
    TaskResult,
    TaskState,
    create_session_id,
    create_task_id,
)
from src.session.store import SessionStore


class SessionOrchestrator:
    """Orchestrator for multi-turn session management and task execution."""

    def __init__(
        self,
        store: SessionStore,
        executor: TaskExecutor | None = None,
        config: SessionConfig | None = None,
    ):
        self._store = store
        self._executor = executor or TaskExecutor()
        self._config = config or SessionConfig()

    def create_session(
        self,
        user_id: str | None = None,
        ttl_seconds: int | None = None,
        initial_context: dict[str, Any] | None = None,
    ) -> SessionContext:
        """Create a new session."""
        now = datetime.now()
        session = SessionContext(
            session_id=create_session_id(),
            created_at=now,
            updated_at=now,
            user_id=user_id,
            ttl_seconds=ttl_seconds or self._config.default_ttl,
            variables=initial_context or {},
        )
        self._store.set(session)
        return session

    def get_session(self, session_id: str) -> SessionContext | None:
        """Get a session by ID."""
        return self._store.get(session_id)

    def close_session(self, session_id: str) -> bool:
        """Close a session."""
        session = self._store.get(session_id)
        if session:
            session.state = SessionState.COMPLETED
            session.touch()
            self._store.set(session)
            return True
        return False

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        return self._store.delete(session_id)

    def extend_session_ttl(self, session_id: str, ttl_seconds: int) -> bool:
        """Extend session TTL."""
        return self._store.extend_ttl(session_id, ttl_seconds)

    async def execute_task(
        self,
        session_id: str,
        skill_type: str,
        query: str,
        use_context: bool = True,
        input_variables: dict[str, Any] | None = None,
    ) -> TaskResult:
        """Execute a single task within a session."""
        session = self._store.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if session.state != SessionState.ACTIVE:
            raise ValueError(f"Session is not active: {session.state.value}")

        # Create task definition
        task = TaskDefinition(
            task_id=create_task_id(len(session.task_history) + 1),
            skill_type=skill_type,  # type: ignore
            query=query,
            input_mapping=input_variables or {},
        )

        # Execute the task
        result = await self._executor.execute(task, session)

        # Update session context with results
        if result.state == TaskState.COMPLETED and use_context:
            self._update_context(session, result)

        # Record task history
        session.add_task_result(result)
        self._store.set(session)

        return result

    async def execute_chain(
        self,
        session_id: str,
        tasks: list[TaskDefinition],
        parallel: bool = False,
        stop_on_failure: bool = True,
    ) -> list[TaskResult]:
        """Execute a chain of tasks within a session."""
        session = self._store.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if session.state != SessionState.ACTIVE:
            raise ValueError(f"Session is not active: {session.state.value}")

        # Execute the chain
        results = await self._executor.execute_chain(
            tasks, session, parallel, stop_on_failure
        )

        # Update session with completed results
        for result in results:
            if result.state == TaskState.COMPLETED:
                self._update_context(session, result)
            session.task_history.append(result)

        session.touch()
        self._store.set(session)

        return results

    def set_variable(
        self,
        session_id: str,
        key: str,
        value: Any,
    ) -> bool:
        """Set a session variable."""
        session = self._store.get(session_id)
        if not session:
            return False
        session.variables[key] = value
        session.touch()
        self._store.set(session)
        return True

    def get_variable(
        self,
        session_id: str,
        key: str,
    ) -> Any:
        """Get a session variable."""
        session = self._store.get(session_id)
        if not session:
            return None
        return session.variables.get(key)

    def get_context_summary(self, session_id: str) -> dict[str, Any]:
        """Get a summary of the session context."""
        session = self._store.get(session_id)
        if not session:
            return {}

        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "known_entities": [
                {"id": e.get("entity_id"), "name": e.get("canonical_name")}
                for e in session.known_entities[:10]
            ],
            "known_clusters_count": len(session.known_clusters),
            "task_count": len(session.task_history),
            "variables": list(session.variables.keys()),
        }

    def _update_context(self, session: SessionContext, result: TaskResult) -> None:
        """Update session context with task result."""
        if not self._config.enable_auto_entity_tracking:
            return

        output = result.output

        # Extract entities from payload
        payload = output.get("payload", {})
        if isinstance(payload, dict):
            # Add entities from various payload types
            entities = payload.get("related_entities", [])
            if isinstance(entities, list):
                session.merge_entities(entities)

            # Add directly affected entities from impact analysis
            affected = payload.get("directly_affected_entities", [])
            if isinstance(affected, list):
                session.merge_entities(affected)

            # Add target entity from risk assessment
            target = payload.get("target_entity")
            if target and isinstance(target, dict):
                session.merge_entities([target])

        # Extract entities from top-level output
        output_entities = output.get("entities", [])
        if isinstance(output_entities, list):
            session.merge_entities(output_entities)

        # Extract event clusters
        output_clusters = output.get("event_clusters", [])
        if isinstance(output_clusters, list):
            session.merge_clusters(output_clusters)

        # Limit context size
        self._trim_context(session)

    def _trim_context(self, session: SessionContext) -> None:
        """Trim context to stay within configured limits."""
        if len(session.known_entities) > self._config.context_max_entities:
            session.known_entities = session.known_entities[
                -self._config.context_max_entities :
            ]

        if len(session.known_clusters) > self._config.context_max_clusters:
            session.known_clusters = session.known_clusters[
                -self._config.context_max_clusters :
            ]

    def shutdown(self) -> None:
        """Shutdown the executor."""
        self._executor.shutdown()


def create_orchestrator(
    store: SessionStore | None = None,
    executor: TaskExecutor | None = None,
    config: SessionConfig | None = None,
) -> SessionOrchestrator:
    """Create a session orchestrator with default dependencies."""
    from src.session.store import InMemorySessionStore

    actual_store = store or InMemorySessionStore()
    actual_executor = executor or TaskExecutor()
    actual_config = config or SessionConfig()

    return SessionOrchestrator(
        store=actual_store,
        executor=actual_executor,
        config=actual_config,
    )
