"""Tests for task routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestTaskRoutes:
    """Task routes tests."""

    def test_execute_task_session_not_found(self, client: TestClient) -> None:
        """Test executing task on non-existent session."""
        response = client.post(
            "/api/v1/sessions/nonexistent/tasks",
            json={"skill_type": "entity_overview", "query": "test query"},
        )
        assert response.status_code == 404

    def test_execute_task_on_closed_session(self, client: TestClient) -> None:
        """Test executing task on closed session."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        client.post(f"/api/v1/sessions/{session_id}/close")

        response = client.post(
            f"/api/v1/sessions/{session_id}/tasks",
            json={"skill_type": "entity_overview", "query": "test query"},
        )
        assert response.status_code == 400
        assert "not active" in response.json()["error"]["message"]

    def test_execute_chain_session_not_found(self, client: TestClient) -> None:
        """Test executing chain on non-existent session."""
        response = client.post(
            "/api/v1/sessions/nonexistent/tasks/chain",
            json={
                "tasks": [
                    {"task_id": "task-1", "skill_type": "entity_overview", "query": "test"}
                ]
            },
        )
        assert response.status_code == 404

    def test_execute_chain_on_closed_session(self, client: TestClient) -> None:
        """Test executing chain on closed session."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        client.post(f"/api/v1/sessions/{session_id}/close")

        response = client.post(
            f"/api/v1/sessions/{session_id}/tasks/chain",
            json={
                "tasks": [
                    {"task_id": "task-1", "skill_type": "entity_overview", "query": "test"}
                ]
            },
        )
        assert response.status_code == 400

    def test_execute_chain_empty_tasks(self, client: TestClient) -> None:
        """Test executing chain with empty tasks list."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.post(
            f"/api/v1/sessions/{session_id}/tasks/chain",
            json={"tasks": []},
        )
        assert response.status_code == 422  # Validation error

    def test_execute_chain_too_many_tasks(self, client: TestClient) -> None:
        """Test executing chain with too many tasks."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        tasks = [
            {"task_id": f"task-{i}", "skill_type": "entity_overview", "query": "test"}
            for i in range(25)
        ]

        response = client.post(
            f"/api/v1/sessions/{session_id}/tasks/chain",
            json={"tasks": tasks},
        )
        assert response.status_code == 422  # Validation error
