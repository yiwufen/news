"""MCP call logger — records every tool invocation for usage statistics.

并发模型：
- 旧实现每次 ``log()`` 新建一个 daemon Thread 写库，高 QPS 下线程数无界且都
  争抢同一把锁，退化为串行但线程开销照付（线程风暴）。
- 现在改为单条常驻后台写线程 + ``queue.SimpleQueue``：``log()`` 只做一次
  非阻塞 ``put``，写线程循环批量消费并串行写库。单写线程天然串行，无需
  额外锁。
- 进程退出时 daemon 写线程随之结束，可接受少量尾部丢失（与旧语义一致）。
"""

from __future__ import annotations

import queue
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

# 批量消费：写线程一次最多 flush 的记录数。
_FLUSH_BATCH = 64
# 哨兵对象：put 到队列后唤醒写线程退出。
_SHUTDOWN = object()


class MCPCallLogger:
    def __init__(self, db_path: str = "data/news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._init_table()
        self._writer = threading.Thread(
            target=self._run_writer, name="mcp-call-log-writer", daemon=True
        )
        self._writer.start()

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
        """Fire-and-forget write. Enqueues a record; never blocks the caller.

        Records are consumed by a single background writer thread, so there is
        exactly one writer (no per-call thread) and writes are serialized.
        """
        record = (
            tool_name,
            intent,
            entity_count,
            1 if success else 0,
            duration_ms,
            error_message,
            client_info,
            datetime.now(UTC).isoformat(),
        )
        try:
            self._queue.put_nowait(record)
        except queue.Full:  # SimpleQueue is unbounded, but keep the guard
            pass  # never let logging failure affect the caller

    def _run_writer(self) -> None:
        """Background loop: drain the queue in batches and persist."""
        while True:
            try:
                first = self._queue.get()
            except Exception:  # pragma: no cover - defensive
                return
            if first is _SHUTDOWN:
                return
            batch: list[tuple] = [first]
            # Drain up to _FLUSH_BATCH-1 more without blocking.
            for _ in range(_FLUSH_BATCH - 1):
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is _SHUTDOWN:
                    # Flush what we have, then stop.
                    self._write_batch(batch)
                    return
                batch.append(item)
            self._write_batch(batch)

    def _write_batch(self, batch: list[tuple]) -> None:
        """Persist a batch of records. Swallows errors to protect the caller."""
        if not batch:
            return
        try:
            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO mcp_call_log
                        (tool_name, intent, entity_count, success,
                         duration_ms, error_message, client_info, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
        except Exception:
            pass  # never let logging failure affect the caller

    def stop(self) -> None:
        """Signal the writer thread to flush and exit (for tests / shutdown)."""
        try:
            self._queue.put_nowait(_SHUTDOWN)
        except Exception:  # pragma: no cover - defensive
            pass
        # Don't block forever; writer should exit shortly.
        self._writer.join(timeout=5.0)
