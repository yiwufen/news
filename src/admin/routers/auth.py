from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.admin.auth import (
    TokenPayload,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
)
from src.admin.dependencies import get_current_user, get_user_repo
from src.admin.users import UserRepository

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4, max_length=128)


@router.post("/api/v1/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, repo: UserRepository = Depends(get_user_repo)) -> TokenResponse:
    user = repo.authenticate(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    payload = TokenPayload(user_id=user.id, username=user.username, role=user.role)
    return TokenResponse(
        access_token=create_access_token(payload),
        refresh_token=create_refresh_token(user.id),
        user=user.to_dict(),
    )


@router.post("/api/v1/auth/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, repo: UserRepository = Depends(get_user_repo)) -> TokenResponse:
    import jwt

    try:
        user_id = decode_refresh_token(body.refresh_token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = repo.get_by_id(user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")

    payload = TokenPayload(user_id=user.id, username=user.username, role=user.role)
    return TokenResponse(
        access_token=create_access_token(payload),
        refresh_token=create_refresh_token(user.id),
        user=user.to_dict(),
    )


@router.get("/api/v1/auth/me")
def me(user: TokenPayload = Depends(get_current_user), repo: UserRepository = Depends(get_user_repo)) -> dict:
    u = repo.get_by_id(user.user_id)
    if user.user_id == 0:  # ADMIN_TOKEN super-admin
        return {"id": 0, "username": "admin", "display_name": "Admin", "role": "admin"}
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return u.to_dict()


@router.post("/api/v1/auth/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: TokenPayload = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repo),
) -> dict:
    if user.user_id == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change password for ADMIN_TOKEN user")
    if not repo.change_password(user.user_id, body.current_password, body.new_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    return {"message": "Password changed successfully"}
