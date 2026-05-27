from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.admin.auth import TokenPayload
from src.admin.dependencies import get_settings, require_admin
from src.admin.service import AdminWriteService

router = APIRouter(dependencies=[Depends(require_admin)], tags=["entities-write"])


class EditEntityRequest(BaseModel):
    canonical_name: str | None = None
    entity_type: str | None = None
    description: str | None = None
    aliases: list[str] | None = None
    identifiers: dict[str, str] | None = None
    tags: list[str] | None = None


class MergeEntityRequest(BaseModel):
    source_id: str
    target_id: str


class NewEntitySpec(BaseModel):
    canonical_name: str
    entity_type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    ku_ids: list[str]


class SplitEntityRequest(BaseModel):
    new_entities: list[NewEntitySpec]


@router.put("/entities/{entity_id}")
def edit_entity(
    entity_id: str,
    body: EditEntityRequest,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        entity = service.entity_edit(entity_id, body.model_dump(exclude_none=True))
        return entity.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/entities/merge")
def merge_entities(
    body: MergeEntityRequest,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        entity = service.entity_merge(body.source_id, body.target_id)
        return entity.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/entities/{entity_id}/split")
def split_entity(
    entity_id: str,
    body: SplitEntityRequest,
    user: TokenPayload = Depends(require_admin),
) -> list[dict]:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        entities = service.entity_split(
            entity_id,
            [spec.model_dump() for spec in body.new_entities],
        )
        return [e.model_dump(mode="json") for e in entities]
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/entities/{entity_id}")
def delete_entity(
    entity_id: str,
    user: TokenPayload = Depends(require_admin),
) -> dict:
    service = AdminWriteService(get_settings().db_path, user)
    try:
        service.entity_delete(entity_id)
        return {"message": f"Entity {entity_id} deleted"}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
