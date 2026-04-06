"""API helper functions and dependencies."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException

from src.api.dependencies import get_orchestrator
from src.api.models.responses import SessionResponse
from src.session import SessionContext, SessionOrchestrator, SessionState


def build_session_response(session: SessionContext) -> SessionResponse:
    """Build SessionResponse from SessionContext."""
    remaining_seconds = max(
        0,
        math.ceil(
            session.ttl_seconds - (datetime.now() - session.updated_at).total_seconds()
        ),
    )
    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        state=session.state.value,
        created_at=session.created_at,
        updated_at=session.updated_at,
        ttl_seconds=session.ttl_seconds,
        expires_in=remaining_seconds,
    )


async def get_active_session(
    session_id: str,
    orchestrator: SessionOrchestrator = Depends(get_orchestrator),
) -> SessionContext:
    """Dependency that validates session exists and is active."""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    if session.state != SessionState.ACTIVE:
        raise HTTPException(
            status_code=400,
            detail=f"Session is not active (state: {session.state.value})",
        )
    return session


ActiveSession = Annotated[SessionContext, Depends(get_active_session)]
