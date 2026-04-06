"""
Session and task models for multi-turn task consumption layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from src.skills.models import SkillType


class SessionState(str, Enum):
    """Session lifecycle state."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class TaskState(str, Enum):
    """Task execution state."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class TaskDefinition:
    """Definition of a task to be executed."""

    task_id: str
    skill_type: SkillType
    query: str
    depends_on: list[str] = field(default_factory=list)
    input_mapping: dict[str, str] = field(default_factory=dict)
    condition: str | None = None
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "skill_type": self.skill_type,
            "query": self.query,
            "depends_on": self.depends_on,
            "input_mapping": self.input_mapping,
            "condition": self.condition,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


@dataclass
class TaskResult:
    """Result of a task execution."""

    task_id: str
    skill_type: SkillType
    state: TaskState
    started_at: datetime
    completed_at: datetime | None = None
    output: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "skill_type": self.skill_type,
            "state": self.state.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "output": self.output,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
        }


@dataclass
class SessionContext:
    """Session context that maintains state across multiple turns."""

    session_id: str
    created_at: datetime
    updated_at: datetime
    user_id: str | None = None
    state: SessionState = SessionState.ACTIVE
    ttl_seconds: int = 3600

    # Accumulated entity knowledge
    known_entities: list[dict[str, Any]] = field(default_factory=list)

    # Accumulated event clusters
    known_clusters: list[dict[str, Any]] = field(default_factory=list)

    # Task execution history
    task_history: list[TaskResult] = field(default_factory=list)

    # Session-level variable storage (for inter-task passing)
    variables: dict[str, Any] = field(default_factory=dict)

    # User preferences
    preferences: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "user_id": self.user_id,
            "state": self.state.value,
            "ttl_seconds": self.ttl_seconds,
            "known_entities": self.known_entities,
            "known_clusters": self.known_clusters,
            "task_history": [t.to_dict() for t in self.task_history],
            "variables": self.variables,
            "preferences": self.preferences,
        }

    def is_expired(self) -> bool:
        """Check if session has expired."""
        elapsed = (datetime.now() - self.updated_at).total_seconds()
        return elapsed > self.ttl_seconds

    def touch(self) -> None:
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now()

    def add_task_result(self, result: TaskResult) -> None:
        """Add a task result to history."""
        self.task_history.append(result)
        self.touch()

    def merge_entities(self, entities: list[dict[str, Any]]) -> None:
        """Merge new entities into known entities, avoiding duplicates."""
        existing_ids = {e.get("entity_id") for e in self.known_entities if e.get("entity_id")}
        for entity in entities:
            entity_id = entity.get("entity_id")
            if entity_id and entity_id not in existing_ids:
                self.known_entities.append(entity)
                existing_ids.add(entity_id)
        self.touch()

    def merge_clusters(self, clusters: list[dict[str, Any]]) -> None:
        """Merge new clusters into known clusters, avoiding duplicates."""
        existing_ids = {c.get("cluster_id") for c in self.known_clusters if c.get("cluster_id")}
        for cluster in clusters:
            cluster_id = cluster.get("cluster_id")
            if cluster_id and cluster_id not in existing_ids:
                self.known_clusters.append(cluster)
                existing_ids.add(cluster_id)
        self.touch()


@dataclass
class TaskChain:
    """Definition of a task chain to be executed."""

    chain_id: str
    tasks: list[TaskDefinition]
    parallel_groups: list[list[str]] = field(default_factory=list)
    rollback_on_failure: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chain_id": self.chain_id,
            "tasks": [t.to_dict() for t in self.tasks],
            "parallel_groups": self.parallel_groups,
            "rollback_on_failure": self.rollback_on_failure,
        }


@dataclass
class SessionConfig:
    """Configuration for session management."""

    max_concurrent_tasks: int = 3
    default_ttl: int = 3600
    enable_auto_entity_tracking: bool = True
    context_max_entities: int = 100
    context_max_clusters: int = 50


def create_session_id() -> str:
    """Generate a new session ID."""
    return uuid4().hex[:12]


def create_task_id(index: int) -> str:
    """Generate a task ID from an index."""
    return f"task-{index}-{str(uuid4())[:6]}"
