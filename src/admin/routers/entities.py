from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.admin.config import AdminSettings
from src.admin.dependencies import get_settings, verify_token
from src.admin import queries
from src.admin.schemas import EntitySummary, PaginatedResponse

router = APIRouter(dependencies=[Depends(verify_token)], tags=["entities"])


@router.get("/entities", response_model=PaginatedResponse[EntitySummary])
def list_entities(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    settings: AdminSettings = Depends(get_settings),
) -> PaginatedResponse[EntitySummary]:
    total, rows = queries.paginated_entities(settings.db_path, page, page_size, search)
    return PaginatedResponse(
        total=total,
        items=[EntitySummary(**r) for r in rows],
        page=page,
        page_size=page_size,
    )


@router.get("/entities/{entity_id}")
def get_entity(entity_id: str, settings: AdminSettings = Depends(get_settings)) -> dict:
    result = queries.get_entity_detail(settings.db_path, entity_id)
    if not result:
        raise HTTPException(status_code=404, detail="Entity not found")
    return result
