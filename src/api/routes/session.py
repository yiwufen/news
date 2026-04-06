"""Session management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_orchestrator
from src.api.helpers import build_session_response
from src.api.models.requests import CreateSessionRequest, ExtendTTLRequest
from src.api.models.responses import SessionResponse
from src.session import SessionOrchestrator

router = APIRouter(prefix="/sessions", tags=["Session"])


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    request: CreateSessionRequest,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    """Create a new session."""
    session = orchestrator.create_session(
        user_id=request.user_id,
        ttl_seconds=request.ttl_seconds,
        initial_context=request.initial_context,
    )
    return build_session_response(session)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    """Get session details."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return build_session_response(session)


@router.post("/{session_id}/close", response_model=SessionResponse)
async def close_session(
    session_id: str,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    """Close a session."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    orchestrator.close_session(session_id)
    updated = orchestrator.get_session(session_id)

    if not updated:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return build_session_response(updated)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> None:
    """Delete a session."""
    if not orchestrator.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.patch("/{session_id}/ttl", response_model=SessionResponse)
async def extend_session_ttl(
    session_id: str,
    request: ExtendTTLRequest,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionResponse:
    """Extend session TTL."""
    if not orchestrator.extend_session_ttl(session_id, request.ttl_seconds):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return build_session_response(session)
