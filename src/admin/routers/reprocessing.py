from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.admin.auth import TokenPayload
from src.admin.dependencies import get_settings, require_admin
from src.admin.service import AdminWriteService

router = APIRouter(dependencies=[Depends(require_admin)], tags=["reprocessing"])


class BatchReprocessRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=50)


@router.post("/reprocessing/{doc_id}")
def reprocess_document(
    doc_id: str,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        return service.reprocess_document(doc_id)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/reprocessing/batch")
def reprocess_batch(
    body: BatchReprocessRequest,
    user: TokenPayload = Depends(require_admin),
) -> list[dict]:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        return service.reprocess_batch(body.doc_ids)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
