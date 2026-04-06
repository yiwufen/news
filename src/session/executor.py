"""
Task executor for running skill queries within sessions.
"""

from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.skills import run_skill_query
from src.session.models import (
    SessionContext,
    TaskDefinition,
    TaskResult,
    TaskState,
)


@dataclass
class ExecutionContext:
    """Context for a single task execution."""

    session: SessionContext
    task: TaskDefinition
    upstream_results: dict[str, TaskResult]
    variables: dict[str, Any]


class TaskExecutor:
    """Executor for running skill queries with session context support."""

    def __init__(
        self,
        max_workers: int = 4,
        thread_pool: ThreadPoolExecutor | None = None,
    ):
        self._pool = thread_pool or ThreadPoolExecutor(max_workers=max_workers)

    async def execute(
        self,
        task: TaskDefinition,
        context: SessionContext,
        upstream_results: dict[str, TaskResult] | None = None,
    ) -> TaskResult:
        """Execute a single task asynchronously."""
        started_at = datetime.now()

        try:
            # Build the query with context injection
            query = self._build_query(task, context, upstream_results or {})

            # Run the synchronous skill query in a thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                self._pool,
                lambda: run_skill_query(
                    raw_query=query,
                    graph_enabled=True,
                ),
            )

            completed_at = datetime.now()
            return TaskResult(
                task_id=task.task_id,
                skill_type=task.skill_type,
                state=TaskState.COMPLETED,
                started_at=started_at,
                completed_at=completed_at,
                output=result,
                duration_ms=int((completed_at - started_at).total_seconds() * 1000),
            )

        except Exception as e:
            completed_at = datetime.now()
            return TaskResult(
                task_id=task.task_id,
                skill_type=task.skill_type,
                state=TaskState.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                errors=[str(e)],
                duration_ms=int((completed_at - started_at).total_seconds() * 1000),
            )

    async def execute_chain(
        self,
        tasks: list[TaskDefinition],
        context: SessionContext,
        parallel: bool = False,
        stop_on_failure: bool = True,
    ) -> list[TaskResult]:
        """Execute a chain of tasks with dependency support."""
        if not tasks:
            return []

        task_map = {t.task_id: t for t in tasks}

        # Topological sort to determine execution order
        execution_order = self._topological_sort(tasks)

        if parallel:
            return await self._execute_parallel(
                execution_order, task_map, context, stop_on_failure
            )
        else:
            return await self._execute_sequential(
                execution_order, task_map, context, stop_on_failure
            )

    async def _execute_sequential(
        self,
        execution_order: list[str],
        task_map: dict[str, TaskDefinition],
        context: SessionContext,
        stop_on_failure: bool,
    ) -> list[TaskResult]:
        """Execute tasks sequentially in dependency order."""
        results: dict[str, TaskResult] = {}

        for task_id in execution_order:
            task = task_map[task_id]
            upstream = {
                dep_id: results[dep_id]
                for dep_id in task.depends_on
                if dep_id in results
            }

            result = await self.execute(task, context, upstream)
            results[task_id] = result

            if result.state == TaskState.FAILED and stop_on_failure:
                break

        return list(results.values())

    async def _execute_parallel(
        self,
        execution_order: list[str],
        task_map: dict[str, TaskDefinition],
        context: SessionContext,
        stop_on_failure: bool,
    ) -> list[TaskResult]:
        """Execute tasks in parallel where dependencies allow."""
        results: dict[str, TaskResult] = {}
        completed: set[str] = set()

        while len(completed) < len(execution_order):
            # Find tasks whose dependencies are all satisfied
            ready = [
                tid
                for tid in execution_order
                if tid not in completed
                and all(dep in completed for dep in task_map[tid].depends_on)
            ]

            if not ready:
                break

            # Execute ready tasks in parallel
            tasks_to_run = [task_map[tid] for tid in ready]
            coroutines = [
                self.execute(
                    task,
                    context,
                    {dep: results[dep] for dep in task.depends_on},
                )
                for task in tasks_to_run
            ]

            task_results = await asyncio.gather(*coroutines, return_exceptions=True)

            for tid, result in zip(ready, task_results):
                if isinstance(result, Exception):
                    results[tid] = TaskResult(
                        task_id=tid,
                        skill_type=task_map[tid].skill_type,
                        state=TaskState.FAILED,
                        started_at=datetime.now(),
                        errors=[str(result)],
                    )
                else:
                    results[tid] = result  # type: ignore[assignment]
                completed.add(tid)

                if results[tid].state == TaskState.FAILED and stop_on_failure:
                    return list(results.values())

        return list(results.values())

    def _build_query(
        self,
        task: TaskDefinition,
        context: SessionContext,
        upstream_results: dict[str, TaskResult],
    ) -> str:
        """Build a query with context injection."""
        query = task.query

        # Replace variable references from input_mapping
        for var_name, var_path in task.input_mapping.items():
            value = self._resolve_variable(var_path, context, upstream_results)
            if value is not None:
                placeholder = f"${{{var_name}}}"
                query = query.replace(placeholder, str(value))

        # Optionally inject known entities
        if context.known_entities and self._should_inject_entities(task, query):
            entity_names = [
                e.get("canonical_name")
                for e in context.known_entities[:5]
                if e.get("canonical_name")
            ]
            # Filter out None values for type safety
            entity_names_str = [str(name) for name in entity_names if name]
            if entity_names_str:
                query = f"{query}，相关实体：{', '.join(entity_names_str)}"

        return query

    def _should_inject_entities(self, task: TaskDefinition, query: str) -> bool:
        """Determine if known entities should be injected into the query."""
        # Don't inject if query already mentions entities explicitly
        entity_keywords = ["实体", "entity", "公司", "企业", "集团"]
        for keyword in entity_keywords:
            if keyword in query.lower():
                return False
        # Don't inject for relationship or guarantee queries (they handle entities differently)
        if task.skill_type in ("relationship_query", "guarantee_analysis"):
            return False
        return True

    def _resolve_variable(
        self,
        path: str,
        context: SessionContext,
        upstream_results: dict[str, TaskResult],
    ) -> Any:
        """Resolve a variable path like 'task_1.output.entities.0.canonical_name'."""
        parts = path.split(".")

        # Determine the root object
        if parts[0] in upstream_results:
            value = upstream_results[parts[0]].output
            parts = parts[1:]
        elif parts[0] == "context":
            value = context.variables
            parts = parts[1:]
        elif parts[0] == "session":
            value = {
                "known_entities": context.known_entities,
                "known_clusters": context.known_clusters,
                "variables": context.variables,
            }
            parts = parts[1:]
        else:
            return None

        # Traverse the path
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                idx = int(part)
                if 0 <= idx < len(value):
                    value = value[idx]
                else:
                    return None
            else:
                return None

            if value is None:
                return None

        return value

    def _topological_sort(self, tasks: list[TaskDefinition]) -> list[str]:
        """Perform topological sort on tasks based on dependencies."""
        task_ids = {t.task_id for t in tasks}
        in_degree: dict[str, int] = {t.task_id: 0 for t in tasks}

        # Calculate in-degrees
        for task in tasks:
            for dep in task.depends_on:
                if dep in task_ids:
                    in_degree[task.task_id] += 1

        # Find tasks with no dependencies (use deque for O(1) popleft)
        queue: deque[str] = deque(tid for tid, degree in in_degree.items() if degree == 0)
        result: list[str] = []

        while queue:
            current = queue.popleft()
            result.append(current)

            # Reduce in-degree for dependent tasks
            for task in tasks:
                if current in task.depends_on:
                    in_degree[task.task_id] -= 1
                    if in_degree[task.task_id] == 0:
                        queue.append(task.task_id)

        # Check for cycles
        if len(result) != len(tasks):
            # There's a cycle, return tasks in original order
            return [t.task_id for t in tasks]

        return result

    def shutdown(self) -> None:
        """Shutdown the thread pool."""
        self._pool.shutdown(wait=True)
