from __future__ import annotations

import sqlite3
from typing import Literal

from src.admin.auth import Role, hash_password, verify_password

_SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'viewer' CHECK(role IN ('admin', 'viewer')),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);
"""


class UserRow:
    __slots__ = ("id", "username", "password_hash", "display_name", "role", "is_active", "created_at", "last_login_at")

    def __init__(self, row: sqlite3.Row) -> None:
        self.id: int = row["id"]
        self.username: str = row["username"]
        self.password_hash: str = row["password_hash"]
        self.display_name: str = row["display_name"]
        self.role: Role = row["role"]
        self.is_active: bool = bool(row["is_active"])
        self.created_at: str = row["created_at"]
        self.last_login_at: str | None = row["last_login_at"]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


class UserRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def create_default_admin(self, admin_token: str) -> bool:
        """Create default admin user from ADMIN_TOKEN if no users exist. Returns True if created."""
        with self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
            if count > 0:
                return False
            conn.execute(
                "INSERT INTO admin_users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
                ("admin", hash_password(admin_token), "Admin", "admin"),
            )
            conn.commit()
            return True

    def authenticate(self, username: str, password: str) -> UserRow | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM admin_users WHERE username = ? AND is_active = 1", (username,)
            ).fetchone()
            if row is None:
                return None
            user = UserRow(row)
            if not verify_password(password, user.password_hash):
                return None
            conn.execute("UPDATE admin_users SET last_login_at = datetime('now') WHERE id = ?", (user.id,))
            conn.commit()
            return user

    def get_by_id(self, user_id: int) -> UserRow | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM admin_users WHERE id = ?", (user_id,)).fetchone()
            return UserRow(row) if row else None

    def list_all(self) -> list[UserRow]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM admin_users ORDER BY id").fetchall()
            return [UserRow(r) for r in rows]

    def create(self, username: str, password: str, display_name: str = "", role: Role = "viewer") -> UserRow:
        with self._connect() as conn:
            try:
                cursor = conn.execute(
                    "INSERT INTO admin_users (username, password_hash, display_name, role) VALUES (?, ?, ?, ?)",
                    (username, hash_password(password), display_name, role),
                )
                conn.commit()
                row = conn.execute("SELECT * FROM admin_users WHERE id = ?", (cursor.lastrowid,)).fetchone()
                return UserRow(row)
            except sqlite3.IntegrityError:
                raise ValueError(f"Username '{username}' already exists")

    def update(self, user_id: int, **kwargs) -> UserRow | None:
        allowed = {"username", "display_name", "role", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if "password" in kwargs:
            updates["password_hash"] = hash_password(kwargs["password"])
        if not updates:
            return self.get_by_id(user_id)
        with self._connect() as conn:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [user_id]
            conn.execute(f"UPDATE admin_users SET {set_clause} WHERE id = ?", values)
            conn.commit()
            return self.get_by_id(user_id)

    def change_password(self, user_id: int, current_password: str, new_password: str) -> bool:
        user = self.get_by_id(user_id)
        if user is None or not verify_password(current_password, user.password_hash):
            return False
        self.update(user_id, password=new_password)
        return True

    def delete(self, user_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM admin_users WHERE id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM admin_users").fetchone()[0]
