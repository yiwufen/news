"""Health check routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from src.api.config import get_config
from src.api.models.responses import HealthResponse, ReadyResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    config = get_config()
    return HealthResponse(
        status="healthy",
        version=config.api_version,
        timestamp=datetime.now(),
    )


@router.get("/ready", response_model=ReadyResponse)
async def readiness_check() -> ReadyResponse:
    """Readiness check endpoint."""
    # Can be extended to check database connections, etc.
    checks = {
        "api": True,
        "session_store": True,
    }

    return ReadyResponse(
        status="ready" if all(checks.values()) else "not_ready",
        checks=checks,
    )
