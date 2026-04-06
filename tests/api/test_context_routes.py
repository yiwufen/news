"""Tests for context routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestContextRoutes:
    """Context routes tests."""

    def test_get_context_summary(self, client: TestClient) -> None:
        """Test getting context summary."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.get(f"/api/v1/sessions/{session_id}/context")
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert data["state"] == "active"
        assert "known_entities" in data
        assert "variables" in data

    def test_get_context_session_not_found(self, client: TestClient) -> None:
        """Test getting context for non-existent session."""
        response = client.get("/api/v1/sessions/nonexistent/context")
        assert response.status_code == 404

    def test_get_all_variables(self, client: TestClient) -> None:
        """Test getting all variables."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.get(f"/api/v1/sessions/{session_id}/context/variables")
        assert response.status_code == 200
        data = response.json()
        assert "variables" in data

    def test_get_variable(self, client: TestClient) -> None:
        """Test getting a single variable."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        # Set a variable first
        client.put(
            f"/api/v1/sessions/{session_id}/context/variables/test_key",
            json={"value": "test_value"},
        )

        response = client.get(
            f"/api/v1/sessions/{session_id}/context/variables/test_key"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "test_key"
        assert data["value"] == "test_value"

    def test_get_variable_not_found(self, client: TestClient) -> None:
        """Test getting a non-existent variable."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.get(
            f"/api/v1/sessions/{session_id}/context/variables/nonexistent_key"
        )
        assert response.status_code == 404

    def test_set_variable(self, client: TestClient) -> None:
        """Test setting a variable."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        response = client.put(
            f"/api/v1/sessions/{session_id}/context/variables/my_key",
            json={"value": "my_value"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "my_key"
        assert data["value"] == "my_value"

    def test_set_variable_session_not_found(self, client: TestClient) -> None:
        """Test setting a variable for non-existent session."""
        response = client.put(
            "/api/v1/sessions/nonexistent/context/variables/key",
            json={"value": "value"},
        )
        assert response.status_code == 404

    def test_set_variable_with_complex_value(self, client: TestClient) -> None:
        """Test setting a variable with complex value."""
        create_response = client.post("/api/v1/sessions", json={})
        session_id = create_response.json()["session_id"]

        complex_value = {"nested": {"key": "value"}, "list": [1, 2, 3]}

        response = client.put(
            f"/api/v1/sessions/{session_id}/context/variables/complex",
            json={"value": complex_value},
        )
        assert response.status_code == 200

        # Verify the value was stored correctly
        get_response = client.get(
            f"/api/v1/sessions/{session_id}/context/variables/complex"
        )
        assert get_response.json()["value"] == complex_value
