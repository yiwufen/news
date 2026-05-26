from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.admin.auth import Role
from src.admin.dependencies import get_user_repo, require_admin
from src.admin.users import UserRepository

router = APIRouter(dependencies=[Depends(require_admin)], tags=["users"])


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    display_name: str = Field(default="", max_length=128)
    role: Role = Field(default="viewer")


class UpdateUserRequest(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, min_length=4, max_length=128)
    role: Role | None = None
    is_active: bool | None = None


@router.get("/api/v1/users")
def list_users(repo: UserRepository = Depends(get_user_repo)) -> list[dict]:
    return [u.to_dict() for u in repo.list_all()]


@router.post("/api/v1/users", status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserRequest, repo: UserRepository = Depends(get_user_repo)) -> dict:
    try:
        user = repo.create(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
        )
        return user.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.put("/api/v1/users/{user_id}")
def update_user(user_id: int, body: UpdateUserRequest, repo: UserRepository = Depends(get_user_repo)) -> dict:
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    user = repo.update(user_id, **updates)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user.to_dict()


@router.delete("/api/v1/users/{user_id}")
def delete_user(user_id: int, repo: UserRepository = Depends(get_user_repo)) -> dict:
    if repo.count() <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the last user")
    if not repo.delete(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {"message": "User deleted"}
