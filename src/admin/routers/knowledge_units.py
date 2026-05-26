from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.admin.config import AdminSettings
from src.admin.dependencies import get_settings, verify_token
from src.admin import queries
from src.admin.schemas import EntitySummary, KUSummary, PaginatedResponse

router = APIRouter(dependencies=[Depends(verify_token)], tags=["knowledge-units"])


@router.get("/knowledge-units", response_model=PaginatedResponse[KUSummary])
def list_knowledge_units(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    unit_type: str = Query(""),
    entity_id: str = Query(""),
    settings: AdminSettings = Depends(get_settings),
) -> PaginatedResponse[KUSummary]:
    total, rows = queries.paginated_knowledge_units(
        settings.db_path, page, page_size, search, unit_type, entity_id
    )
    return PaginatedResponse(
        total=total,
        items=[KUSummary(**r) for r in rows],
        page=page,
        page_size=page_size,
    )


@router.get("/knowledge-units/{ku_id}")
def get_knowledge_unit(ku_id: str, settings: AdminSettings = Depends(get_settings)) -> dict:
    result = queries.get_ku_detail(settings.db_path, ku_id)
    if not result:
        raise HTTPException(status_code=404, detail="Knowledge unit not found")
    return result


@router.get("/knowledge-units/{ku_id}/entities", response_model=list[EntitySummary])
def ku_related_entities(ku_id: str, settings: AdminSettings = Depends(get_settings)) -> list[EntitySummary]:
    result = queries.get_ku_detail(settings.db_path, ku_id)
    if not result:
        raise HTTPException(status_code=404, detail="Knowledge unit not found")
    rows = queries.get_ku_related_entities(settings.db_path, ku_id)
    return [EntitySummary(**r) for r in rows]
