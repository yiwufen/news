from __future__ import annotations

import sqlite3
from collections.abc import Generator

import jwt
from fastapi import Depends, HTTPException, Request, status

from src.admin.auth import TokenPayload, decode_token
from src.admin.config import AdminSettings
from src.admin.users import UserRepository

_settings = AdminSettings()


def get_settings() -> AdminSettings:
    return _settings


def get_user_repo(settings: AdminSettings = Depends(get_settings)) -> UserRepository:
    return UserRepository(settings.db_path)


def get_current_user(
    request: Request,
    settings: AdminSettings = Depends(get_settings),
) -> TokenPayload:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = auth[len("Bearer "):]

    # Backward compat: ADMIN_TOKEN works as super-admin bypass
    if settings.admin_token and token == settings.admin_token:
        return TokenPayload(user_id=0, username="admin", role="admin")

    try:
        return decode_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def require_admin(
    user: TokenPayload = Depends(get_current_user),
) -> TokenPayload:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


def get_db(settings: AdminSettings = Depends(get_settings)) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


verify_token = get_current_user  # backward compat alias
