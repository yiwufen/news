from __future__ import annotations

from fastapi import APIRouter, Depends

from src.admin.config import AdminSettings
from src.admin.dependencies import get_settings, verify_token
from src.admin import queries
from src.admin.container_status import get_pipeline_status
from src.admin.schemas import DashboardStats, ProcessingSummary

router = APIRouter(dependencies=[Depends(verify_token)], tags=["dashboard"])


@router.get("/dashboard/stats", response_model=DashboardStats)
def dashboard_stats(settings: AdminSettings = Depends(get_settings)) -> DashboardStats:
    db = settings.db_path

    entity_type_counts = queries.get_entity_type_counts(db)
    ku_kind_counts = queries.get_ku_kind_counts(db)
    category_counts = queries.get_article_category_counts(db)
    time_range = queries.get_article_time_range(db)
    proc_summary = queries.get_processing_summary(db)

    entities_data = {
        "total": queries.count_entities(db),
        "by_type": {r["entity_type"]: r["cnt"] for r in entity_type_counts},
    }
    ku_data = {
        "total": queries.count_knowledge_units(db),
        "by_kind": {r["unit_kind"]: r["cnt"] for r in ku_kind_counts},
    }
    clusters_data = {
        "total": queries.count_event_clusters(db),
    }
    articles_data = {
        "total": queries.count_articles(db),
        "by_category": {r["category"]: r["cnt"] for r in category_counts},
        "time_range": time_range,
    }

    return DashboardStats(
        entities=entities_data,
        knowledge_units=ku_data,
        event_clusters=clusters_data,
        articles=articles_data,
        processing=ProcessingSummary(**proc_summary),
        pipeline=get_pipeline_status(),
    )
