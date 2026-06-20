from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from src.admin.config import AdminSettings
from src.admin.dependencies import get_db, get_settings
from src.admin.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/api/v1/health", response_model=HealthResponse)
def health_check(settings: AdminSettings = Depends(get_settings)) -> HealthResponse:
    db_connected = False
    try:
        conn = sqlite3.connect(settings.db_path)
        conn.execute("SELECT 1")
        conn.close()
        db_connected = True
    except Exception:
        pass

    neo4j_connected = None
    if settings.neo4j_password:
        try:
            # 统一走加锁工厂，避免绕过 get_connection 的并发构造 race。
            from src.graph.connection import get_connection

            neo4j_connected = get_connection().health_check()
        except Exception:
            neo4j_connected = False

    return HealthResponse(
        status="ok" if db_connected else "degraded",
        db_connected=db_connected,
        neo4j_connected=neo4j_connected,
    )
