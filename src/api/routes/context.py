"""Context management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_orchestrator
from src.api.models.requests import SetVariableRequest
from src.api.models.responses import (
    ContextSummaryResponse,
    VariableResponse,
    VariablesResponse,
)
from src.session import SessionOrchestrator

router = APIRouter(prefix="/sessions/{session_id}/context", tags=["Context"])


@router.get("", response_model=ContextSummaryResponse)
async def get_context_summary(
    session_id: str,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> ContextSummaryResponse:
    """Get session context summary."""
    summary = orchestrator.get_context_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return ContextSummaryResponse(**summary)


@router.get("/variables", response_model=VariablesResponse)
async def get_all_variables(
    session_id: str,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> VariablesResponse:
    """Get all session variables."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return VariablesResponse(variables=session.variables)


@router.get("/variables/{key}", response_model=VariableResponse)
async def get_variable(
    session_id: str,
    key: str,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> VariableResponse:
    """Get a single session variable."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if key not in session.variables:
        raise HTTPException(status_code=404, detail=f"Variable not found: {key}")

    return VariableResponse(key=key, value=session.variables[key])


@router.put("/variables/{key}", response_model=VariableResponse)
async def set_variable(
    session_id: str,
    key: str,
    request: SetVariableRequest,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> VariableResponse:
    """Set a session variable."""
    if not orchestrator.set_variable(session_id, key, request.value):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    return VariableResponse(key=key, value=request.value)
