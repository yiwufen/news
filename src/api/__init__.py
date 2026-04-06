"""
API module for exposing session and skill services as REST endpoints.

This module provides a FastAPI application with the following endpoints:

Session Management:
    POST   /api/v1/sessions                - Create a new session
    GET    /api/v1/sessions/{session_id}   - Get session details
    POST   /api/v1/sessions/{session_id}/close - Close a session
    DELETE /api/v1/sessions/{session_id}   - Delete a session
    PATCH  /api/v1/sessions/{session_id}/ttl - Extend session TTL

Task Execution:
    POST   /api/v1/sessions/{session_id}/tasks - Execute a single task
    POST   /api/v1/sessions/{session_id}/tasks/chain - Execute a task chain

Context Management:
    GET    /api/v1/sessions/{session_id}/context - Get context summary
    GET    /api/v1/sessions/{session_id}/context/variables - Get all variables
    GET    /api/v1/sessions/{session_id}/context/variables/{key} - Get variable
    PUT    /api/v1/sessions/{session_id}/context/variables/{key} - Set variable

Health Check:
    GET    /health - Health check
    GET    /ready  - Readiness check

Example usage:

    # Start the server
    uv run uvicorn src.api.app:app --reload

    # Create a session and execute a task
    curl -X POST http://localhost:8000/api/v1/sessions \\
        -H "Content-Type: application/json" \\
        -d '{"user_id": "test-user"}'

    curl -X POST http://localhost:8000/api/v1/sessions/{session_id}/tasks \\
        -H "Content-Type: application/json" \\
        -d '{"skill_type": "entity_overview", "query": "查看小米集团最新动态"}'
"""

from src.api.app import app, create_app
from src.api.config import APIConfig, get_config
from src.api.dependencies import get_orchestrator, get_session_store

__all__ = [
    "app",
    "create_app",
    "APIConfig",
    "get_config",
    "get_orchestrator",
    "get_session_store",
]
