"""审计日志 Repository — 记录所有管理员写入操作。"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class AuditLogRepository:
    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    old_state TEXT,
                    new_state TEXT,
                    metadata TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def log(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        user_id: int,
        username: str,
        old_state: dict | None = None,
        new_state: dict | None = None,
        metadata: dict | None = None,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO admin_audit_log
                    (action, resource_type, resource_id, user_id, username,
                     old_state, new_state, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action,
                    resource_type,
                    resource_id,
                    user_id,
                    username,
                    json.dumps(old_state, ensure_ascii=False) if old_state else None,
                    json.dumps(new_state, ensure_ascii=False) if new_state else None,
                    json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    datetime.now(UTC).isoformat(),
                ),
            )
            return cursor.lastrowid or 0

    def get_by_id(self, log_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM admin_audit_log WHERE id = ?", (log_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def get_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> tuple[int, list[dict]]:
        conditions: list[str] = []
        params: list[object] = []
        if action:
            conditions.append("action = ?")
            params.append(action)
        if resource_type:
            conditions.append("resource_type = ?")
            params.append(resource_type)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        offset = (page - 1) * page_size

        with self._connect() as conn:
            total = conn.execute(
                f"SELECT count(*) FROM admin_audit_log {where}", params
            ).fetchone()[0]

            rows = conn.execute(
                f"SELECT * FROM admin_audit_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()

        items = [self._row_to_dict(r) for r in rows]
        return total, items

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        for key in ("old_state", "new_state", "metadata"):
            if d.get(key):
                d[key] = json.loads(d[key])
        return d
