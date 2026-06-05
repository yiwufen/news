"""MCP call logger — records every tool invocation for usage statistics."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path


class MCPCallLogger:
    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_table(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_call_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    intent TEXT,
                    entity_count INTEGER,
                    success INTEGER NOT NULL DEFAULT 1,
                    duration_ms INTEGER,
                    error_message TEXT,
                    client_info TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_mcp_call_created_at
                ON mcp_call_log(created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_mcp_call_tool
                ON mcp_call_log(tool_name, created_at)
                """
            )

    def log(
        self,
        tool_name: str,
        intent: str | None = None,
        entity_count: int = 0,
        success: bool = True,
        duration_ms: int = 0,
        error_message: str | None = None,
        client_info: str | None = None,
    ) -> None:
        """Fire-and-forget write. Uses a thread to avoid blocking the caller."""

        def _write():
            with self._lock:
                try:
                    with self._connect() as conn:
                        conn.execute(
                            """
                            INSERT INTO mcp_call_log
                                (tool_name, intent, entity_count, success,
                                 duration_ms, error_message, client_info, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                tool_name,
                                intent,
                                entity_count,
                                1 if success else 0,
                                duration_ms,
                                error_message,
                                client_info,
                                datetime.now(UTC).isoformat(),
                            ),
                        )
                except Exception:
                    pass  # never let logging failure affect the caller

        threading.Thread(target=_write, daemon=True).start()
