"""
Session storage implementations for multi-turn task consumption layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, cast

from src.session.models import SessionContext, TaskResult


class SessionStore(Protocol):
    """Protocol for session storage backends."""

    def get(self, session_id: str) -> SessionContext | None:
        """Get a session by ID."""
        ...

    def set(self, session: SessionContext) -> None:
        """Save a session."""
        ...

    def delete(self, session_id: str) -> bool:
        """Delete a session. Returns True if deleted."""
        ...

    def exists(self, session_id: str) -> bool:
        """Check if a session exists."""
        ...

    def extend_ttl(self, session_id: str, ttl_seconds: int) -> bool:
        """Extend session TTL. Returns True if extended."""
        ...


class InMemorySessionStore:
    """In-memory session storage suitable for single-instance deployments."""

    def __init__(self, cleanup_interval_seconds: int = 60):
        self._sessions: dict[str, SessionContext] = {}
        self._cleanup_interval = cleanup_interval_seconds
        self._last_cleanup = datetime.now()

    def get(self, session_id: str) -> SessionContext | None:
        # Periodic cleanup check
        if (datetime.now() - self._last_cleanup).total_seconds() > self._cleanup_interval:
            self.cleanup_expired()

        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.is_expired():
            del self._sessions[session_id]
            return None
        return session

    def set(self, session: SessionContext) -> None:
        self._sessions[session.session_id] = session

    def delete(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def exists(self, session_id: str) -> bool:
        return self.get(session_id) is not None

    def extend_ttl(self, session_id: str, ttl_seconds: int) -> bool:
        session = self.get(session_id)
        if session:
            session.ttl_seconds = ttl_seconds
            session.touch()
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove expired sessions and return the count of removed sessions."""
        expired_ids = [
            sid for sid, sess in self._sessions.items() if sess.is_expired()
        ]
        for sid in expired_ids:
            del self._sessions[sid]
        self._last_cleanup = datetime.now()
        return len(expired_ids)

    def count(self) -> int:
        """Return the number of active sessions."""
        return len(self._sessions)

    def clear(self) -> None:
        """Remove all sessions."""
        self._sessions.clear()


class RedisSessionStore:
    """Redis-backed session storage for distributed deployments.

    Requires redis package to be installed.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "session:",
    ):
        try:
            import redis  # type: ignore[import]
        except ImportError as e:
            raise ImportError(
                "Redis session store requires the 'redis' package. "
                "Install it with: pip install redis"
            ) from e

        self._client = redis.from_url(redis_url)  # type: ignore[union-attr]
        self._key_prefix = key_prefix

    def _key(self, session_id: str) -> str:
        return f"{self._key_prefix}{session_id}"

    def get(self, session_id: str) -> SessionContext | None:
        import json

        data = self._client.get(self._key(session_id))
        if data is None:
            return None
        serialized = cast(str | bytes | bytearray, data)
        return self._deserialize(json.loads(serialized))

    def set(self, session: SessionContext) -> None:
        import json

        self._client.setex(
            self._key(session.session_id),
            session.ttl_seconds,
            json.dumps(self._serialize(session)),
        )

    def delete(self, session_id: str) -> bool:
        return bool(self._client.delete(self._key(session_id)))

    def exists(self, session_id: str) -> bool:
        return bool(self._client.exists(self._key(session_id)))

    def extend_ttl(self, session_id: str, ttl_seconds: int) -> bool:
        return bool(self._client.expire(self._key(session_id), ttl_seconds))

    def _serialize(self, session: SessionContext) -> dict:
        """Serialize SessionContext to a JSON-compatible dict."""
        return session.to_dict()

    def _deserialize(self, data: dict) -> SessionContext:
        """Deserialize dict back to SessionContext."""
        from src.session.models import SessionState, TaskResult, TaskState

        return SessionContext(
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            user_id=data.get("user_id"),
            state=SessionState(data["state"]),
            ttl_seconds=data["ttl_seconds"],
            known_entities=data.get("known_entities", []),
            known_clusters=data.get("known_clusters", []),
            task_history=[
                self._deserialize_task_result(t) for t in data.get("task_history", [])
            ],
            variables=data.get("variables", {}),
            preferences=data.get("preferences", {}),
        )

    def _deserialize_task_result(self, data: dict) -> TaskResult:
        """Deserialize dict back to TaskResult."""
        from src.session.models import TaskState

        return TaskResult(
            task_id=data["task_id"],
            skill_type=data["skill_type"],
            state=TaskState(data["state"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=(
                datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
            ),
            output=data.get("output", {}),
            errors=data.get("errors", []),
            duration_ms=data.get("duration_ms", 0),
        )
