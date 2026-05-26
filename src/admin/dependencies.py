from __future__ import annotations

import sqlite3
from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status

from src.admin.config import AdminSettings

_settings = AdminSettings()


def get_settings() -> AdminSettings:
    return _settings


def verify_token(request: Request, settings: AdminSettings = Depends(get_settings)) -> None:
    if not settings.admin_token:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    token = auth[len("Bearer "):]
    if token != settings.admin_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_db(settings: AdminSettings = Depends(get_settings)) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()
