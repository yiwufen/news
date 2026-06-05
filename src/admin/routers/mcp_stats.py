from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.admin.config import AdminSettings
from src.admin.dependencies import get_settings, verify_token
from src.admin.queries import (
    get_mcp_call_stats,
    get_mcp_intent_breakdown,
    get_mcp_tool_breakdown,
)
from src.admin.schemas import MCPDailyStats, MCPStatsResponse

router = APIRouter(dependencies=[Depends(verify_token)], tags=["mcp"])


@router.get("/mcp/stats", response_model=MCPStatsResponse)
def mcp_stats(
    days: int = Query(default=7, ge=1, le=90),
    settings: AdminSettings = Depends(get_settings),
) -> MCPStatsResponse:
    db = settings.db_path

    daily_rows = get_mcp_call_stats(db, days=days)
    tool_rows = get_mcp_tool_breakdown(db, days=days)
    intent_rows = get_mcp_intent_breakdown(db, days=days)

    tool_map = {r["tool_name"]: r["cnt"] for r in tool_rows}
    intent_map = {r["intent"]: r["cnt"] for r in intent_rows if r["intent"]}

    daily = [
        MCPDailyStats(
            date=r["date"],
            total=r["total"],
            success=r["success"],
            failed=r["failed"],
            avg_duration_ms=float(r["avg_duration_ms"] or 0),
            by_tool=tool_map,
            by_intent=intent_map,
        )
        for r in daily_rows
    ]

    total_calls = sum(r["total"] for r in daily_rows)

    return MCPStatsResponse(
        daily=daily,
        total_calls=total_calls,
        period_days=days,
    )
