from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.admin.auth import TokenPayload
from src.admin.dependencies import get_settings, require_admin
from src.admin.service import AdminWriteService

router = APIRouter(dependencies=[Depends(require_admin)], tags=["clusters-write"])


class EditClusterRequest(BaseModel):
    title: str | None = None
    summary: str | None = None
    primary_entity_id: str | None = None
    conflict_status: Literal["none", "possible", "confirmed"] | None = None


class MergeClusterRequest(BaseModel):
    cluster_ids: list[str] = Field(min_length=2)


class SplitClusterRequest(BaseModel):
    remove_ku_ids: list[str] = Field(min_length=1)


@router.put("/event-clusters/{cluster_id}")
def edit_cluster(
    cluster_id: str,
    body: EditClusterRequest,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        cluster = service.cluster_edit(cluster_id, body.model_dump(exclude_none=True))
        return cluster.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/event-clusters/merge")
def merge_clusters(
    body: MergeClusterRequest,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        cluster = service.cluster_merge(body.cluster_ids)
        return cluster.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/event-clusters/{cluster_id}/split")
def split_cluster(
    cluster_id: str,
    body: SplitClusterRequest,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        cluster = service.cluster_split(cluster_id, body.remove_ku_ids)
        return cluster.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/event-clusters/{cluster_id}")
def delete_cluster(
    cluster_id: str,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        service.cluster_delete(cluster_id)
        return {"message": f"Cluster {cluster_id} deleted"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
