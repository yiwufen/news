from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.admin.config import AdminSettings
from src.admin.dependencies import get_settings, verify_token
from src.admin import queries
from src.admin.schemas import ArticleSummary, EntitySummary, KUSummary, PaginatedResponse

router = APIRouter(dependencies=[Depends(verify_token)], tags=["articles"])


@router.get("/articles", response_model=PaginatedResponse[ArticleSummary])
def list_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    category: str = Query(""),
    source_name: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
    settings: AdminSettings = Depends(get_settings),
) -> PaginatedResponse[ArticleSummary]:
    total, rows = queries.paginated_articles(
        settings.db_path, page, page_size, search, category, source_name, date_from, date_to
    )
    return PaginatedResponse(
        total=total,
        items=[ArticleSummary(**r) for r in rows],
        page=page,
        page_size=page_size,
    )


@router.get("/articles/{doc_id}")
def get_article(doc_id: str, settings: AdminSettings = Depends(get_settings)) -> dict:
    result = queries.get_article_detail(settings.db_path, doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Article not found")
    return result


@router.get("/articles/{doc_id}/knowledge-units", response_model=PaginatedResponse[KUSummary])
def article_related_knowledge_units(
    doc_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    settings: AdminSettings = Depends(get_settings),
) -> PaginatedResponse[KUSummary]:
    result = queries.get_article_detail(settings.db_path, doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Article not found")
    total, rows = queries.get_article_related_kus(settings.db_path, doc_id, page, page_size)
    return PaginatedResponse(
        total=total,
        items=[KUSummary(**r) for r in rows],
        page=page,
        page_size=page_size,
    )


@router.get("/articles/{doc_id}/entities", response_model=list[EntitySummary])
def article_related_entities(doc_id: str, settings: AdminSettings = Depends(get_settings)) -> list[EntitySummary]:
    result = queries.get_article_detail(settings.db_path, doc_id)
    if not result:
        raise HTTPException(status_code=404, detail="Article not found")
    rows = queries.get_article_related_entities(settings.db_path, doc_id)
    return [EntitySummary(**r) for r in rows]
