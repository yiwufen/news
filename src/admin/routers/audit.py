from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.admin.audit import AuditLogRepository
from src.admin.auth import TokenPayload
from src.admin.dependencies import get_settings, require_admin, verify_token
from src.admin.schemas import AuditLogEntry, PaginatedResponse

router = APIRouter(tags=["audit"])


@router.get(
    "/audit-log",
    response_model=PaginatedResponse[AuditLogEntry],
    dependencies=[Depends(verify_token)],
)
def list_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = None,
    resource_type: str | None = None,
) -> PaginatedResponse[AuditLogEntry]:
    repo = AuditLogRepository(get_settings().db_path)
    total, items = repo.get_paginated(page, page_size, action=action, resource_type=resource_type)
    return PaginatedResponse(
        total=total,
        items=[AuditLogEntry(**r) for r in items],
        page=page,
        page_size=page_size,
    )


@router.get(
    "/audit-log/{log_id}",
    response_model=AuditLogEntry,
    dependencies=[Depends(verify_token)],
)
def get_audit_entry(log_id: int) -> AuditLogEntry:
    repo = AuditLogRepository(get_settings().db_path)
    entry = repo.get_by_id(log_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log entry not found")
    return AuditLogEntry(**entry)


@router.post(
    "/audit-log/{log_id}/undo",
    dependencies=[Depends(require_admin)],
)
def undo_audit_entry(
    log_id: int,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    from src.admin.service import AdminWriteService

    service = AdminWriteService(get_settings().db_path, user)
    try:
        return service.undo(log_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
