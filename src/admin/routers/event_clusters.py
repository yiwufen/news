from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.admin.config import AdminSettings
from src.admin.dependencies import get_settings, verify_token
from src.admin import queries
from src.admin.schemas import ClusterSummary, PaginatedResponse

router = APIRouter(dependencies=[Depends(verify_token)], tags=["event-clusters"])


@router.get("/event-clusters", response_model=PaginatedResponse[ClusterSummary])
def list_event_clusters(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    cluster_type: str = Query(""),
    entity_id: str = Query(""),
    settings: AdminSettings = Depends(get_settings),
) -> PaginatedResponse[ClusterSummary]:
    total, rows = queries.paginated_event_clusters(
        settings.db_path, page, page_size, cluster_type, entity_id
    )
    return PaginatedResponse(
        total=total,
        items=[ClusterSummary(**r) for r in rows],
        page=page,
        page_size=page_size,
    )


@router.get("/event-clusters/{cluster_id}")
def get_event_cluster(cluster_id: str, settings: AdminSettings = Depends(get_settings)) -> dict:
    result = queries.get_cluster_detail(settings.db_path, cluster_id)
    if not result:
        raise HTTPException(status_code=404, detail="Event cluster not found")
    return result
