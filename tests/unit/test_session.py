"""Unit tests for the session module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.session import (
    InMemorySessionStore,
    SessionConfig,
    SessionContext,
    SessionOrchestrator,
    SessionState,
    TaskDefinition,
    TaskExecutor,
    TaskResult,
    TaskState,
    create_orchestrator,
    create_session_id,
    create_task_id,
)


class TestSessionModels:
    """Tests for session models."""

    def test_create_session_id(self) -> None:
        """Test session ID generation."""
        id1 = create_session_id()
        id2 = create_session_id()
        assert len(id1) == 12
        assert len(id2) == 12
        assert id1 != id2

    def test_create_task_id(self) -> None:
        """Test task ID generation."""
        task_id = create_task_id(1)
        assert task_id.startswith("task-1-")
        assert len(task_id) > 7

    def test_session_context_to_dict(self) -> None:
        """Test SessionContext serialization."""
        now = datetime.now()
        session = SessionContext(
            session_id="test-session",
            created_at=now,
            updated_at=now,
            user_id="user-1",
            ttl_seconds=3600,
        )
        data = session.to_dict()

        assert data["session_id"] == "test-session"
        assert data["user_id"] == "user-1"
        assert data["state"] == "active"
        assert data["ttl_seconds"] == 3600

    def test_session_context_is_expired(self) -> None:
        """Test session expiration check."""
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
            ttl_seconds=60,
        )
        assert not session.is_expired()

        # Simulate expiration
        session.updated_at = now - timedelta(seconds=120)
        assert session.is_expired()

    def test_session_context_merge_entities(self) -> None:
        """Test entity merging without duplicates."""
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
            known_entities=[
                {"entity_id": "e1", "canonical_name": "Entity 1"},
            ],
        )

        # Merge new entities
        session.merge_entities([
            {"entity_id": "e2", "canonical_name": "Entity 2"},
            {"entity_id": "e1", "canonical_name": "Entity 1 Updated"},  # Duplicate
        ])

        assert len(session.known_entities) == 2
        # Original entity should not be updated
        assert session.known_entities[0]["canonical_name"] == "Entity 1"

    def test_task_definition_to_dict(self) -> None:
        """Test TaskDefinition serialization."""
        task = TaskDefinition(
            task_id="task-1",
            skill_type="entity_overview",
            query="Test query",
            depends_on=["task-0"],
        )
        data = task.to_dict()

        assert data["task_id"] == "task-1"
        assert data["skill_type"] == "entity_overview"
        assert data["query"] == "Test query"
        assert data["depends_on"] == ["task-0"]

    def test_task_result_to_dict(self) -> None:
        """Test TaskResult serialization."""
        now = datetime.now()
        result = TaskResult(
            task_id="task-1",
            skill_type="entity_overview",
            state=TaskState.COMPLETED,
            started_at=now,
            completed_at=now,
            output={"ok": True},
            duration_ms=100,
        )
        data = result.to_dict()

        assert data["task_id"] == "task-1"
        assert data["state"] == "completed"
        assert data["output"] == {"ok": True}
        assert data["duration_ms"] == 100


class TestInMemorySessionStore:
    """Tests for in-memory session store."""

    def test_set_and_get(self) -> None:
        """Test basic set/get operations."""
        store = InMemorySessionStore()
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
        )

        store.set(session)
        retrieved = store.get("test")

        assert retrieved is not None
        assert retrieved.session_id == "test"

    def test_get_nonexistent(self) -> None:
        """Test getting a nonexistent session."""
        store = InMemorySessionStore()
        assert store.get("nonexistent") is None

    def test_delete(self) -> None:
        """Test deleting a session."""
        store = InMemorySessionStore()
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
        )

        store.set(session)
        assert store.delete("test") is True
        assert store.get("test") is None
        assert store.delete("test") is False

    def test_exists(self) -> None:
        """Test checking existence."""
        store = InMemorySessionStore()
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
        )

        assert not store.exists("test")
        store.set(session)
        assert store.exists("test")

    def test_extend_ttl(self) -> None:
        """Test extending TTL."""
        store = InMemorySessionStore()
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
            ttl_seconds=60,
        )

        store.set(session)
        assert store.extend_ttl("test", 120) is True

        retrieved = store.get("test")
        assert retrieved is not None
        assert retrieved.ttl_seconds == 120

    def test_cleanup_expired(self) -> None:
        """Test cleaning up expired sessions."""
        store = InMemorySessionStore()
        now = datetime.now()

        # Create an expired session
        expired = SessionContext(
            session_id="expired",
            created_at=now - timedelta(seconds=200),
            updated_at=now - timedelta(seconds=200),
            ttl_seconds=60,
        )

        # Create an active session
        active = SessionContext(
            session_id="active",
            created_at=now,
            updated_at=now,
            ttl_seconds=3600,
        )

        store.set(expired)
        store.set(active)

        count = store.cleanup_expired()

        assert count == 1
        assert store.get("expired") is None
        assert store.get("active") is not None

    def test_get_expired_returns_none(self) -> None:
        """Test that getting an expired session returns None and removes it."""
        store = InMemorySessionStore()
        now = datetime.now()

        expired = SessionContext(
            session_id="expired",
            created_at=now - timedelta(seconds=200),
            updated_at=now - timedelta(seconds=200),
            ttl_seconds=60,
        )

        store.set(expired)

        # Getting expired session should return None
        assert store.get("expired") is None

        # And the session should be removed
        assert "expired" not in store._sessions


class TestTaskExecutor:
    """Tests for task executor."""

    @pytest.mark.asyncio
    async def test_execute_task_success(self) -> None:
        """Test successful task execution."""
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
        )
        task = TaskDefinition(
            task_id="task-1",
            skill_type="entity_overview",
            query="Test query",
        )

        executor = TaskExecutor()

        with patch(
            "src.session.executor.run_skill_query",
            return_value={"ok": True, "skill_type": "entity_overview"},
        ):
            result = await executor.execute(task, session)

        assert result.state == TaskState.COMPLETED
        assert result.output["ok"] is True

    @pytest.mark.asyncio
    async def test_execute_task_failure(self) -> None:
        """Test task execution failure."""
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
        )
        task = TaskDefinition(
            task_id="task-1",
            skill_type="entity_overview",
            query="Test query",
        )

        executor = TaskExecutor()

        with patch(
            "src.session.executor.run_skill_query",
            side_effect=ValueError("Test error"),
        ):
            result = await executor.execute(task, session)

        assert result.state == TaskState.FAILED
        assert "Test error" in result.errors

    @pytest.mark.asyncio
    async def test_execute_chain_sequential(self) -> None:
        """Test sequential chain execution."""
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
        )
        tasks = [
            TaskDefinition(
                task_id="task-1",
                skill_type="entity_overview",
                query="Query 1",
            ),
            TaskDefinition(
                task_id="task-2",
                skill_type="entity_timeline",
                query="Query 2",
                depends_on=["task-1"],
            ),
        ]

        executor = TaskExecutor()
        call_count = 0

        def mock_run_skill_query(**kwargs):  # type: ignore
            nonlocal call_count
            call_count += 1
            return {"ok": True, "call": call_count}

        with patch(
            "src.session.executor.run_skill_query",
            side_effect=mock_run_skill_query,
        ):
            results = await executor.execute_chain(tasks, session, parallel=False)

        assert len(results) == 2
        assert all(r.state == TaskState.COMPLETED for r in results)

    @pytest.mark.asyncio
    async def test_execute_chain_with_failure_stop(self) -> None:
        """Test chain execution stops on failure."""
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
        )
        tasks = [
            TaskDefinition(
                task_id="task-1",
                skill_type="entity_overview",
                query="Query 1",
            ),
            TaskDefinition(
                task_id="task-2",
                skill_type="entity_timeline",
                query="Query 2",
            ),
        ]

        executor = TaskExecutor()

        with patch(
            "src.session.executor.run_skill_query",
            side_effect=[{"ok": True}, ValueError("Failure")],
        ):
            results = await executor.execute_chain(
                tasks, session, parallel=False, stop_on_failure=True
            )

        assert len(results) == 2
        assert results[0].state == TaskState.COMPLETED
        assert results[1].state == TaskState.FAILED

    def test_topological_sort(self) -> None:
        """Test topological sort of tasks."""
        executor = TaskExecutor()
        tasks = [
            TaskDefinition(
                task_id="task-3",
                skill_type="entity_overview",
                query="Q3",
                depends_on=["task-1", "task-2"],
            ),
            TaskDefinition(
                task_id="task-1",
                skill_type="entity_overview",
                query="Q1",
            ),
            TaskDefinition(
                task_id="task-2",
                skill_type="entity_overview",
                query="Q2",
                depends_on=["task-1"],
            ),
        ]

        order = executor._topological_sort(tasks)

        # task-1 should come before task-2 and task-3
        assert order.index("task-1") < order.index("task-2")
        assert order.index("task-1") < order.index("task-3")
        assert order.index("task-2") < order.index("task-3")

    def test_build_query_with_variable_injection(self) -> None:
        """Test query building with variable injection."""
        now = datetime.now()
        session = SessionContext(
            session_id="test",
            created_at=now,
            updated_at=now,
            variables={"company": "小米集团"},
        )
        task = TaskDefinition(
            task_id="task-1",
            skill_type="entity_overview",
            query="查看 ${company} 的动态",
            input_mapping={"company": "context.company"},
        )

        executor = TaskExecutor()
        query = executor._build_query(task, session, {})

        assert query == "查看 小米集团 的动态"


class TestSessionOrchestrator:
    """Tests for session orchestrator."""

    def test_create_session(self) -> None:
        """Test session creation."""
        orchestrator = create_orchestrator()

        session = orchestrator.create_session(user_id="user-1")

        assert session.session_id is not None
        assert session.user_id == "user-1"
        assert session.state == SessionState.ACTIVE

    def test_get_session(self) -> None:
        """Test getting a session."""
        orchestrator = create_orchestrator()
        created = orchestrator.create_session()

        retrieved = orchestrator.get_session(created.session_id)

        assert retrieved is not None
        assert retrieved.session_id == created.session_id

    def test_close_session(self) -> None:
        """Test closing a session."""
        orchestrator = create_orchestrator()
        session = orchestrator.create_session()

        result = orchestrator.close_session(session.session_id)

        assert result is True
        retrieved = orchestrator.get_session(session.session_id)
        assert retrieved is not None
        assert retrieved.state == SessionState.COMPLETED

    def test_delete_session(self) -> None:
        """Test deleting a session."""
        orchestrator = create_orchestrator()
        session = orchestrator.create_session()

        result = orchestrator.delete_session(session.session_id)

        assert result is True
        assert orchestrator.get_session(session.session_id) is None

    @pytest.mark.asyncio
    async def test_execute_task(self) -> None:
        """Test task execution within a session."""
        orchestrator = create_orchestrator()
        session = orchestrator.create_session()

        with patch(
            "src.session.executor.run_skill_query",
            return_value={
                "ok": True,
                "skill_type": "entity_overview",
                "entities": [{"entity_id": "e1", "canonical_name": "Test Entity"}],
            },
        ):
            result = await orchestrator.execute_task(
                session_id=session.session_id,
                skill_type="entity_overview",
                query="Test query",
            )

        assert result.state == TaskState.COMPLETED

        # Check context was updated
        updated = orchestrator.get_session(session.session_id)
        assert updated is not None
        assert len(updated.known_entities) == 1
        assert updated.known_entities[0]["entity_id"] == "e1"

    @pytest.mark.asyncio
    async def test_execute_task_session_not_found(self) -> None:
        """Test task execution with invalid session."""
        orchestrator = create_orchestrator()

        with pytest.raises(ValueError, match="Session not found"):
            await orchestrator.execute_task(
                session_id="nonexistent",
                skill_type="entity_overview",
                query="Test query",
            )

    def test_set_and_get_variable(self) -> None:
        """Test setting and getting session variables."""
        orchestrator = create_orchestrator()
        session = orchestrator.create_session()

        orchestrator.set_variable(session.session_id, "key", "value")
        value = orchestrator.get_variable(session.session_id, "key")

        assert value == "value"

    def test_get_context_summary(self) -> None:
        """Test getting context summary."""
        orchestrator = create_orchestrator()
        session = orchestrator.create_session()
        orchestrator.set_variable(session.session_id, "var1", "value1")

        summary = orchestrator.get_context_summary(session.session_id)

        assert summary["session_id"] == session.session_id
        assert "var1" in summary["variables"]

    @pytest.mark.asyncio
    async def test_execute_chain(self) -> None:
        """Test chain execution within a session."""
        orchestrator = create_orchestrator()
        session = orchestrator.create_session()

        tasks = [
            TaskDefinition(
                task_id="task-1",
                skill_type="entity_overview",
                query="Query 1",
            ),
            TaskDefinition(
                task_id="task-2",
                skill_type="entity_timeline",
                query="Query 2",
                depends_on=["task-1"],
            ),
        ]

        with patch(
            "src.session.executor.run_skill_query",
            return_value={"ok": True},
        ):
            results = await orchestrator.execute_chain(
                session_id=session.session_id,
                tasks=tasks,
                parallel=False,
            )

        assert len(results) == 2
        assert all(r.state == TaskState.COMPLETED for r in results)

        # Check task history
        updated = orchestrator.get_session(session.session_id)
        assert updated is not None
        assert len(updated.task_history) == 2
