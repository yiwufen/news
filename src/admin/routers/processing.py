from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.admin.config import AdminSettings
from src.admin.dependencies import get_settings, verify_token
from src.admin import queries
from src.admin.schemas import PaginatedResponse, ProcessingLogEntry

router = APIRouter(dependencies=[Depends(verify_token)], tags=["processing"])


@router.get("/processing-log", response_model=PaginatedResponse[ProcessingLogEntry])
def list_processing_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    settings: AdminSettings = Depends(get_settings),
) -> PaginatedResponse[ProcessingLogEntry]:
    total, rows = queries.paginated_processing_log(settings.db_path, page, page_size)
    return PaginatedResponse(
        total=total,
        items=[ProcessingLogEntry(**r) for r in rows],
        page=page,
        page_size=page_size,
    )


@router.get("/pipeline/status")
def pipeline_status(settings: AdminSettings = Depends(get_settings)) -> dict:
    return {
        "fetch": {"running": False, "pid": None, "started_at": None, "command": None},
        "offline": {"running": False, "pid": None, "started_at": None, "command": None},
    }
