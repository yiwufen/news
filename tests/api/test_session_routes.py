"""Tests for session routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestSessionRoutes:
    """Session routes tests."""

    def test_create_session(self, client: TestClient) -> None:
        """Test creating a session."""
        response = client.post("/api/v1/sessions", json={})
        assert response.status_code == 201
        data = response.json()
        assert "session_id" in data
        assert data["state"] == "active"

    def test_create_session_with_user(self, client: TestClient) -> None:
        """Test creating a session with user ID."""
        response = client.post(
            "/api/v1/sessions",
            json={"user_id": "test-user", "ttl_seconds": 7200},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == "test-user"
        assert data["ttl_seconds"] == 7200

    def test_create_session_with_initial_context(self, client: TestClient) -> None:
        """Test creating a session with initial context."""
        response = client.post(
            "/api/v1/sessions",
            json={"initial_context": {"key": "value"}},
        )
        assert response.status_code == 201

    def test_get_session(self, client: TestClient) -> None:
        """Test getting a session."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.get(f"/api/v1/sessions/{session_id}")
        assert response.status_code == 200
        assert response.json()["session_id"] == session_id

    def test_get_session_not_found(self, client: TestClient) -> None:
        """Test getting a non-existent session."""
        response = client.get("/api/v1/sessions/nonexistent")
        assert response.status_code == 404

    def test_close_session(self, client: TestClient) -> None:
        """Test closing a session."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.post(f"/api/v1/sessions/{session_id}/close")
        assert response.status_code == 200
        assert response.json()["state"] == "completed"

    def test_close_session_not_found(self, client: TestClient) -> None:
        """Test closing a non-existent session."""
        response = client.post("/api/v1/sessions/nonexistent/close")
        assert response.status_code == 404

    def test_delete_session(self, client: TestClient) -> None:
        """Test deleting a session."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.delete(f"/api/v1/sessions/{session_id}")
        assert response.status_code == 204

        get_response = client.get(f"/api/v1/sessions/{session_id}")
        assert get_response.status_code == 404

    def test_delete_session_not_found(self, client: TestClient) -> None:
        """Test deleting a non-existent session."""
        response = client.delete("/api/v1/sessions/nonexistent")
        assert response.status_code == 404

    def test_extend_session_ttl(self, client: TestClient) -> None:
        """Test extending session TTL."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.patch(
            f"/api/v1/sessions/{session_id}/ttl",
            json={"ttl_seconds": 7200},
        )
        assert response.status_code == 200
        assert response.json()["ttl_seconds"] == 7200

    def test_extend_ttl_session_not_found(self, client: TestClient) -> None:
        """Test extending TTL for non-existent session."""
        response = client.patch(
            "/api/v1/sessions/nonexistent/ttl",
            json={"ttl_seconds": 7200},
        )
        assert response.status_code == 404


class TestHealthRoutes:
    """Health routes tests."""

    def test_health_check(self, client: TestClient) -> None:
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_readiness_check(self, client: TestClient) -> None:
        """Test readiness check endpoint."""
        response = client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert "checks" in data
