from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from backend.repositories.paths import NIGHTSHIFT_DB


class UserRepository:
    def __init__(self, db_path: Path = NIGHTSHIFT_DB) -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_db(self) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            if not self._users_table_exists(cursor):
                self._create_users_table(cursor)
            elif self._needs_users_table_rebuild(cursor):
                self._rebuild_users_table(cursor)
            self._ensure_user_column(cursor, "display_name", "TEXT NOT NULL DEFAULT ''")
            self._ensure_user_column(cursor, "auth_source", "TEXT NOT NULL DEFAULT 'password'")
            self._ensure_user_column(cursor, "github_id", "TEXT")
            self._ensure_user_column(cursor, "github_login", "TEXT NOT NULL DEFAULT ''")
            self._ensure_user_column(cursor, "avatar_url", "TEXT NOT NULL DEFAULT ''")
            self._ensure_user_column(cursor, "is_active", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_user_column(cursor, "last_login_at", "TEXT")
            cursor.execute("DROP INDEX IF EXISTS idx_users_email")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email_lookup ON users(email)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_auth_source ON users(email, auth_source)")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id)")
            connection.commit()
        finally:
            connection.close()

    def _users_table_exists(self, cursor: sqlite3.Cursor) -> bool:
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'")
        return cursor.fetchone() is not None

    def _create_users_table(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                auth_source TEXT NOT NULL DEFAULT 'password',
                github_id TEXT,
                github_login TEXT NOT NULL DEFAULT '',
                avatar_url TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )

    def _needs_users_table_rebuild(self, cursor: sqlite3.Cursor) -> bool:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'")
        row = cursor.fetchone()
        create_sql = str(row["sql"] or "") if row else ""
        normalized_sql = re.sub(r"\s+", " ", create_sql.strip().lower())
        if "email text not null unique" in normalized_sql or "unique(email)" in normalized_sql:
            return True

        cursor.execute("PRAGMA index_list(users)")
        for index_row in cursor.fetchall():
            if str(index_row["name"]) == "idx_users_email":
                return True
        return False

    def _rebuild_users_table(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("ALTER TABLE users RENAME TO users_legacy")
        legacy_columns = self._table_columns(cursor, "users_legacy")
        self._create_users_table(cursor)
        cursor.execute(
            f"""
            INSERT INTO users (
                id,
                email,
                password_hash,
                display_name,
                auth_source,
                github_id,
                github_login,
                avatar_url,
                is_active,
                created_at,
                updated_at,
                last_login_at
            )
            SELECT
                {self._legacy_column_expr(legacy_columns, "id", "NULL")},
                {self._legacy_column_expr(legacy_columns, "email", "''")},
                {self._legacy_column_expr(legacy_columns, "password_hash", "''")},
                {self._legacy_column_expr(legacy_columns, "display_name", "''")},
                {self._legacy_column_expr(legacy_columns, "auth_source", "'password'")},
                {self._legacy_column_expr(legacy_columns, "github_id", "NULL")},
                {self._legacy_column_expr(legacy_columns, "github_login", "''")},
                {self._legacy_column_expr(legacy_columns, "avatar_url", "''")},
                {self._legacy_column_expr(legacy_columns, "is_active", "1")},
                {self._legacy_column_expr(legacy_columns, "created_at", "CURRENT_TIMESTAMP")},
                {self._legacy_column_expr(legacy_columns, "updated_at", "CURRENT_TIMESTAMP")},
                {self._legacy_column_expr(legacy_columns, "last_login_at", "NULL")}
            FROM users_legacy
            """
        )
        cursor.execute("DROP TABLE users_legacy")

    def _table_columns(self, cursor: sqlite3.Cursor, table_name: str) -> set[str]:
        cursor.execute(f"PRAGMA table_info({table_name})")
        return {str(row["name"]) for row in cursor.fetchall()}

    def _legacy_column_expr(self, columns: set[str], column_name: str, default_sql: str) -> str:
        if column_name in columns:
            return f"COALESCE({column_name}, {default_sql})"
        return default_sql

    def _ensure_user_column(self, cursor: sqlite3.Cursor, column_name: str, definition: str) -> None:
        cursor.execute("PRAGMA table_info(users)")
        columns = {str(row["name"]) for row in cursor.fetchall()}
        if column_name in columns:
            return
        cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {definition}")

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, object]:
        return {
            "id": row["id"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "display_name": row["display_name"],
            "auth_source": row["auth_source"],
            "github_id": row["github_id"],
            "github_login": row["github_login"],
            "avatar_url": row["avatar_url"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_login_at": row["last_login_at"],
        }

    def create_user(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        auth_source: str = "password",
        github_id: Optional[str] = None,
        github_login: str = "",
        avatar_url: str = "",
    ) -> Dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO users (
                    email,
                    password_hash,
                    display_name,
                    auth_source,
                    github_id,
                    github_login,
                    avatar_url,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email,
                    password_hash,
                    display_name,
                    auth_source,
                    github_id,
                    github_login,
                    avatar_url,
                    now,
                    now,
                ),
            )
            connection.commit()
            user_id = int(cursor.lastrowid)
        finally:
            connection.close()

        user = self.get_user_by_id(user_id)
        if not user:
            raise RuntimeError("user created but cannot be loaded")
        return user

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, object]]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            connection.close()

    def get_user_by_email(self, email: str, auth_source: Optional[str] = None) -> Optional[Dict[str, object]]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            if auth_source is None:
                cursor.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE email = ?
                    ORDER BY CASE WHEN auth_source = 'password' THEN 0 ELSE 1 END, id ASC
                    LIMIT 1
                    """,
                    (email,),
                )
            else:
                cursor.execute(
                    "SELECT * FROM users WHERE email = ? AND auth_source = ? ORDER BY id ASC LIMIT 1",
                    (email, auth_source),
                )
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            connection.close()

    def get_user_by_github_id(self, github_id: str) -> Optional[Dict[str, object]]:
        normalized_github_id = str(github_id or "").strip()
        if not normalized_github_id:
            return None
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM users WHERE github_id = ?", (normalized_github_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            connection.close()

    def link_github_account(
        self,
        *,
        user_id: int,
        github_id: str,
        github_login: str,
        avatar_url: str,
        display_name: Optional[str] = None,
        auth_source: Optional[str] = None,
    ) -> Optional[Dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            updates = [
                "github_id = ?",
                "github_login = ?",
                "avatar_url = ?",
                "updated_at = ?",
            ]
            values = [
                str(github_id or "").strip(),
                str(github_login or "").strip(),
                str(avatar_url or "").strip(),
                now,
            ]

            normalized_display_name = str(display_name or "").strip()
            if normalized_display_name:
                updates.append(
                    "display_name = CASE WHEN TRIM(COALESCE(display_name, '')) = '' THEN ? ELSE display_name END"
                )
                values.append(normalized_display_name[:60])

            normalized_auth_source = str(auth_source or "").strip()
            if normalized_auth_source:
                updates.append("auth_source = ?")
                values.append(normalized_auth_source)

            values.append(int(user_id))
            cursor.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
                tuple(values),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_user_by_id(user_id)

    def touch_last_login(self, user_id: int) -> Optional[Dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE users
                SET last_login_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    now,
                    now,
                    user_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_user_by_id(user_id)

    def update_password_hash(self, user_id: int, password_hash: str) -> Optional[Dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE users
                SET password_hash = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    password_hash,
                    now,
                    user_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_user_by_id(user_id)
