from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from backend.repositories.paths import NIGHTSHIFT_DB


AUTH_SESSIONS_TABLE = "oauth_sessions"


class AuthSessionRepository:
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
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {AUTH_SESSIONS_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    state_token TEXT NOT NULL UNIQUE,
                    poll_token TEXT NOT NULL UNIQUE,
                    requested_by_user_id INTEGER,
                    flow_type TEXT NOT NULL DEFAULT 'login',
                    redirect_uri TEXT NOT NULL DEFAULT '',
                    authorization_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    result_access_token TEXT NOT NULL DEFAULT '',
                    result_token_type TEXT NOT NULL DEFAULT 'bearer',
                    result_expires_in INTEGER NOT NULL DEFAULT 0,
                    result_user_json TEXT NOT NULL DEFAULT '',
                    result_repo_sync_json TEXT NOT NULL DEFAULT '',
                    result_message TEXT NOT NULL DEFAULT '',
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{AUTH_SESSIONS_TABLE}_expires_at ON {AUTH_SESSIONS_TABLE}(expires_at)"
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{AUTH_SESSIONS_TABLE}_status ON {AUTH_SESSIONS_TABLE}(status)"
            )
            connection.commit()
        finally:
            connection.close()

    def create_session(
        self,
        *,
        state_token: str,
        poll_token: str,
        requested_by_user_id: Optional[int],
        flow_type: str,
        redirect_uri: str,
        authorization_url: str,
        expires_at: str,
    ) -> Dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"""
                INSERT INTO {AUTH_SESSIONS_TABLE} (
                    state_token,
                    poll_token,
                    requested_by_user_id,
                    flow_type,
                    redirect_uri,
                    authorization_url,
                    status,
                    expires_at,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (
                    state_token,
                    poll_token,
                    requested_by_user_id,
                    flow_type,
                    redirect_uri,
                    authorization_url,
                    expires_at,
                    now,
                    now,
                ),
            )
            connection.commit()
            session_id = int(cursor.lastrowid)
        finally:
            connection.close()

        session = self.get_session_by_id(session_id)
        if not session:
            raise RuntimeError("oauth session created but cannot be loaded")
        return session

    def get_session_by_id(self, session_id: int) -> Optional[Dict[str, object]]:
        return self._get_one("SELECT * FROM oauth_sessions WHERE id = ?", (session_id,))

    def get_session_by_state(self, state_token: str) -> Optional[Dict[str, object]]:
        return self._get_one("SELECT * FROM oauth_sessions WHERE state_token = ?", (state_token,))

    def get_session_by_poll_token(self, poll_token: str) -> Optional[Dict[str, object]]:
        return self._get_one("SELECT * FROM oauth_sessions WHERE poll_token = ?", (poll_token,))

    def mark_completed(
        self,
        session_id: int,
        *,
        auth_payload: Dict[str, object],
        repo_sync: Optional[Dict[str, object]],
        message: str,
    ) -> Optional[Dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"""
                UPDATE {AUTH_SESSIONS_TABLE}
                SET status = 'completed',
                    result_access_token = ?,
                    result_token_type = ?,
                    result_expires_in = ?,
                    result_user_json = ?,
                    result_repo_sync_json = ?,
                    result_message = ?,
                    error_code = '',
                    error_message = '',
                    completed_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(auth_payload.get("access_token", "")),
                    str(auth_payload.get("token_type", "bearer")),
                    int(auth_payload.get("expires_in", 0) or 0),
                    json.dumps(auth_payload.get("user", {}), ensure_ascii=True),
                    json.dumps(repo_sync or {}, ensure_ascii=True),
                    message.strip(),
                    now,
                    now,
                    session_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_session_by_id(session_id)

    def mark_failed(self, session_id: int, *, error_code: str, error_message: str) -> Optional[Dict[str, object]]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"""
                UPDATE {AUTH_SESSIONS_TABLE}
                SET status = 'failed',
                    error_code = ?,
                    error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    error_code.strip(),
                    error_message.strip(),
                    now,
                    session_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get_session_by_id(session_id)

    def delete_expired_sessions(self, *, now_iso: Optional[str] = None) -> int:
        threshold = now_iso or datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"DELETE FROM {AUTH_SESSIONS_TABLE} WHERE expires_at <= ?",
                (threshold,),
            )
            connection.commit()
            return cursor.rowcount
        finally:
            connection.close()

    def delete_session(self, session_id: int) -> bool:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(f"DELETE FROM {AUTH_SESSIONS_TABLE} WHERE id = ?", (int(session_id),))
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def _get_one(self, query: str, params: tuple[object, ...]) -> Optional[Dict[str, object]]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            connection.close()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, object]:
        return {
            "id": int(row["id"]),
            "state_token": str(row["state_token"]),
            "poll_token": str(row["poll_token"]),
            "requested_by_user_id": row["requested_by_user_id"],
            "flow_type": str(row["flow_type"]),
            "redirect_uri": str(row["redirect_uri"]),
            "authorization_url": str(row["authorization_url"]),
            "status": str(row["status"]),
            "result_access_token": str(row["result_access_token"]),
            "result_token_type": str(row["result_token_type"]),
            "result_expires_in": int(row["result_expires_in"] or 0),
            "result_user": self._load_json(row["result_user_json"]),
            "result_repo_sync": self._load_json(row["result_repo_sync_json"]),
            "result_message": str(row["result_message"]),
            "error_code": str(row["error_code"]),
            "error_message": str(row["error_message"]),
            "expires_at": str(row["expires_at"]),
            "completed_at": row["completed_at"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def _load_json(self, raw: object) -> Dict[str, object]:
        value = str(raw or "").strip()
        if not value:
            return {}
        try:
            payload = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
