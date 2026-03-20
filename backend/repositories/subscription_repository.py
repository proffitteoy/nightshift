from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from backend.repositories.paths import NIGHTSHIFT_DB


SUBSCRIPTIONS_TABLE = "subscriptions"
RUNTIME_CONFIGS_TABLE = "runtime_configs"


class SubscriptionRepository:
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
            self._ensure_subscriptions_schema(cursor)
            self._ensure_runtime_configs_schema(cursor)
            connection.commit()
        finally:
            connection.close()

    def _ensure_subscriptions_schema(self, cursor: sqlite3.Cursor) -> None:
        if not self._table_exists(cursor, SUBSCRIPTIONS_TABLE):
            self._create_subscriptions_table(cursor, SUBSCRIPTIONS_TABLE)
            self._ensure_subscription_indexes(cursor)
            return

        columns = self._get_table_columns(cursor, SUBSCRIPTIONS_TABLE)
        needs_rebuild = "user_id" not in columns or self._has_legacy_unique_index(
            cursor,
            SUBSCRIPTIONS_TABLE,
            ("repo_url",),
        )
        if needs_rebuild:
            self._rebuild_subscriptions_table(cursor, columns)
            return

        self._ensure_subscription_indexes(cursor)

    def _ensure_runtime_configs_schema(self, cursor: sqlite3.Cursor) -> None:
        if not self._table_exists(cursor, RUNTIME_CONFIGS_TABLE):
            self._create_runtime_configs_table(cursor, RUNTIME_CONFIGS_TABLE)
            self._ensure_runtime_config_indexes(cursor)
            return

        columns = self._get_table_columns(cursor, RUNTIME_CONFIGS_TABLE)
        needs_rebuild = "user_id" not in columns or self._has_legacy_unique_index(
            cursor,
            RUNTIME_CONFIGS_TABLE,
            ("key",),
        )
        if needs_rebuild:
            self._rebuild_runtime_configs_table(cursor, columns)
            return

        self._ensure_runtime_config_indexes(cursor)

    def _rebuild_subscriptions_table(self, cursor: sqlite3.Cursor, columns: Sequence[str]) -> None:
        temp_table = f"{SUBSCRIPTIONS_TABLE}__new"
        self._drop_table_if_exists(cursor, temp_table)
        self._create_subscriptions_table(cursor, temp_table)
        now = datetime.now(timezone.utc).isoformat()
        select_parts = [
            "id",
            "user_id" if "user_id" in columns else "NULL AS user_id",
            "repo_url",
            "morning_report_enabled" if "morning_report_enabled" in columns else "1 AS morning_report_enabled",
            "code_panorama_enabled" if "code_panorama_enabled" in columns else "1 AS code_panorama_enabled",
            "recipient_email" if "recipient_email" in columns else "'' AS recipient_email",
            "delivery_mode" if "delivery_mode" in columns else "'scheduled' AS delivery_mode",
            "frequency" if "frequency" in columns else "'daily' AS frequency",
            "delivery_time" if "delivery_time" in columns else "'09:00' AS delivery_time",
            "update_strategy" if "update_strategy" in columns else "'incremental' AS update_strategy",
            "last_delivery_at" if "last_delivery_at" in columns else "NULL AS last_delivery_at",
            "last_delivery_attempt_at"
            if "last_delivery_attempt_at" in columns
            else "NULL AS last_delivery_attempt_at",
            "last_delivery_error" if "last_delivery_error" in columns else "'' AS last_delivery_error",
            "created_at" if "created_at" in columns else f"'{now}' AS created_at",
            "updated_at" if "updated_at" in columns else f"'{now}' AS updated_at",
        ]
        cursor.execute(
            f"""
            INSERT INTO {temp_table} (
                id,
                user_id,
                repo_url,
                morning_report_enabled,
                code_panorama_enabled,
                recipient_email,
                delivery_mode,
                frequency,
                delivery_time,
                update_strategy,
                last_delivery_at,
                last_delivery_attempt_at,
                last_delivery_error,
                created_at,
                updated_at
            )
            SELECT {", ".join(select_parts)}
            FROM {SUBSCRIPTIONS_TABLE}
            """
        )
        cursor.execute(f"DROP TABLE {SUBSCRIPTIONS_TABLE}")
        cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {SUBSCRIPTIONS_TABLE}")
        self._ensure_subscription_indexes(cursor)

    def _rebuild_runtime_configs_table(self, cursor: sqlite3.Cursor, columns: Sequence[str]) -> None:
        temp_table = f"{RUNTIME_CONFIGS_TABLE}__new"
        self._drop_table_if_exists(cursor, temp_table)
        self._create_runtime_configs_table(cursor, temp_table)
        now = datetime.now(timezone.utc).isoformat()
        select_parts = [
            "user_id" if "user_id" in columns else "NULL AS user_id",
            "key",
            "value",
            "updated_at" if "updated_at" in columns else f"'{now}' AS updated_at",
        ]
        cursor.execute(
            f"""
            INSERT INTO {temp_table} (
                user_id,
                key,
                value,
                updated_at
            )
            SELECT {", ".join(select_parts)}
            FROM {RUNTIME_CONFIGS_TABLE}
            """
        )
        cursor.execute(f"DROP TABLE {RUNTIME_CONFIGS_TABLE}")
        cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {RUNTIME_CONFIGS_TABLE}")
        self._ensure_runtime_config_indexes(cursor)

    def _create_subscriptions_table(self, cursor: sqlite3.Cursor, table_name: str) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                repo_url TEXT NOT NULL,
                morning_report_enabled INTEGER NOT NULL DEFAULT 1,
                code_panorama_enabled INTEGER NOT NULL DEFAULT 1,
                recipient_email TEXT NOT NULL DEFAULT '',
                delivery_mode TEXT NOT NULL DEFAULT 'scheduled',
                frequency TEXT NOT NULL DEFAULT 'daily',
                delivery_time TEXT NOT NULL DEFAULT '09:00',
                update_strategy TEXT NOT NULL DEFAULT 'incremental',
                last_delivery_at TEXT,
                last_delivery_attempt_at TEXT,
                last_delivery_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def _create_runtime_configs_table(self, cursor: sqlite3.Cursor, table_name: str) -> None:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    def _ensure_subscription_indexes(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user_id ON subscriptions(user_id)")
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_subscriptions_user_repo
            ON subscriptions(IFNULL(user_id, 0), repo_url)
            """
        )

    def _ensure_runtime_config_indexes(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runtime_configs_user_id ON runtime_configs(user_id)")
        cursor.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_configs_user_key
            ON runtime_configs(IFNULL(user_id, 0), key)
            """
        )

    def _table_exists(self, cursor: sqlite3.Cursor, table_name: str) -> bool:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return cursor.fetchone() is not None

    def _drop_table_if_exists(self, cursor: sqlite3.Cursor, table_name: str) -> None:
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")

    def _get_table_columns(self, cursor: sqlite3.Cursor, table_name: str) -> List[str]:
        cursor.execute(f"PRAGMA table_info({table_name})")
        return [str(row["name"]) for row in cursor.fetchall()]

    def _has_legacy_unique_index(
        self,
        cursor: sqlite3.Cursor,
        table_name: str,
        expected_columns: Tuple[str, ...],
    ) -> bool:
        cursor.execute(f"PRAGMA index_list({table_name})")
        indexes = cursor.fetchall()
        for row in indexes:
            if not int(row["unique"]):
                continue
            index_name = str(row["name"])
            cursor.execute(f"PRAGMA index_info({index_name})")
            columns = tuple(item["name"] for item in cursor.fetchall())
            if columns == expected_columns:
                return True
        return False

    def _subscription_scope_clause(self, user_id: Optional[int]) -> Tuple[str, Tuple[object, ...]]:
        if user_id is None:
            return "user_id IS NULL", ()
        return "user_id = ?", (int(user_id),)

    def _runtime_scope_clause(self, user_id: Optional[int]) -> Tuple[str, Tuple[object, ...]]:
        if user_id is None:
            return "user_id IS NULL", ()
        return "user_id = ?", (int(user_id),)

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, object]:
        frequency = row["frequency"]
        if frequency not in {"daily", "weekly", "weekday"}:
            frequency = "daily"

        update_strategy = row["update_strategy"]
        if update_strategy not in {"incremental", "full"}:
            update_strategy = "incremental"

        delivery_mode = row["delivery_mode"]
        if delivery_mode not in {"instant", "scheduled"}:
            delivery_mode = "scheduled"

        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "repo_url": row["repo_url"],
            "morning_report_enabled": bool(row["morning_report_enabled"]),
            "code_panorama_enabled": bool(row["code_panorama_enabled"]),
            "recipient_email": row["recipient_email"],
            "delivery_mode": delivery_mode,
            "frequency": frequency,
            "delivery_time": row["delivery_time"],
            "update_strategy": update_strategy,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _row_to_delivery_dict(self, row: sqlite3.Row) -> Dict[str, object]:
        payload = self._row_to_dict(row)
        row_keys = set(row.keys())
        payload["last_delivery_at"] = row["last_delivery_at"] if "last_delivery_at" in row_keys else None
        payload["last_delivery_attempt_at"] = (
            row["last_delivery_attempt_at"] if "last_delivery_attempt_at" in row_keys else None
        )
        payload["last_delivery_error"] = row["last_delivery_error"] if "last_delivery_error" in row_keys else ""
        return payload

    def list_subscriptions(self, user_id: Optional[int]) -> List[Dict[str, object]]:
        where_clause, params = self._subscription_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT * FROM subscriptions WHERE {where_clause} ORDER BY id ASC",
                params,
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(row) for row in rows]
        finally:
            connection.close()

    def get_subscription(self, subscription_id: int, user_id: Optional[int]) -> Optional[Dict[str, object]]:
        where_clause, params = self._subscription_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT * FROM subscriptions WHERE id = ? AND {where_clause}",
                (subscription_id, *params),
            )
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            connection.close()

    def get_any_subscription(self, subscription_id: int) -> Optional[Dict[str, object]]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
            row = cursor.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            connection.close()

    def get_subscription_with_delivery_state(
        self,
        subscription_id: int,
        user_id: Optional[int],
    ) -> Optional[Dict[str, object]]:
        where_clause, params = self._subscription_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT * FROM subscriptions WHERE id = ? AND {where_clause}",
                (subscription_id, *params),
            )
            row = cursor.fetchone()
            return self._row_to_delivery_dict(row) if row else None
        finally:
            connection.close()

    def get_any_subscription_with_delivery_state(self, subscription_id: int) -> Optional[Dict[str, object]]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM subscriptions WHERE id = ?", (subscription_id,))
            row = cursor.fetchone()
            return self._row_to_delivery_dict(row) if row else None
        finally:
            connection.close()

    def list_all_subscriptions_with_delivery_state(self) -> List[Dict[str, object]]:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT * FROM subscriptions ORDER BY id ASC")
            rows = cursor.fetchall()
            return [self._row_to_delivery_dict(row) for row in rows]
        finally:
            connection.close()

    def create_subscription(self, user_id: Optional[int], payload: Dict[str, object]) -> Dict[str, object]:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO subscriptions (
                    user_id,
                    repo_url,
                    morning_report_enabled,
                    code_panorama_enabled,
                    recipient_email,
                    delivery_mode,
                    frequency,
                    delivery_time,
                    update_strategy,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    payload["repo_url"],
                    int(bool(payload.get("morning_report_enabled", True))),
                    int(bool(payload.get("code_panorama_enabled", True))),
                    payload.get("recipient_email", ""),
                    payload.get("delivery_mode", "scheduled"),
                    payload.get("frequency", "daily"),
                    payload.get("delivery_time", "09:00"),
                    payload.get("update_strategy", "incremental"),
                    now,
                    now,
                ),
            )
            connection.commit()
            created_id = int(cursor.lastrowid)
        finally:
            connection.close()

        created = self.get_subscription(created_id, user_id)
        if not created:
            raise RuntimeError("subscription created but cannot be loaded")
        return created

    def update_subscription(
        self,
        user_id: Optional[int],
        subscription_id: int,
        payload: Dict[str, object],
    ) -> Optional[Dict[str, object]]:
        existing = self.get_subscription(subscription_id, user_id)
        if not existing:
            return None

        if not payload:
            return existing

        fields = []
        values: List[object] = []
        for key in (
            "repo_url",
            "morning_report_enabled",
            "code_panorama_enabled",
            "recipient_email",
            "delivery_mode",
            "frequency",
            "delivery_time",
            "update_strategy",
        ):
            if key not in payload:
                continue
            fields.append(f"{key} = ?")
            value = payload[key]
            if key in ("morning_report_enabled", "code_panorama_enabled"):
                value = int(bool(value))
            values.append(value)

        if fields:
            fields.append("last_delivery_attempt_at = ?")
            values.append(None)
            fields.append("last_delivery_error = ?")
            values.append("")

        now = datetime.now(timezone.utc).isoformat()
        fields.append("updated_at = ?")
        values.append(now)
        values.append(subscription_id)

        where_clause, params = self._subscription_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"UPDATE subscriptions SET {', '.join(fields)} WHERE id = ? AND {where_clause}",
                tuple(values) + params,
            )
            connection.commit()
        finally:
            connection.close()

        return self.get_subscription(subscription_id, user_id)

    def record_delivery_attempt(
        self,
        subscription_id: int,
        attempted_at: str,
        delivered_at: Optional[str],
        error_message: str,
    ) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                UPDATE subscriptions
                SET last_delivery_attempt_at = ?,
                    last_delivery_at = COALESCE(?, last_delivery_at),
                    last_delivery_error = ?
                WHERE id = ?
                """,
                (
                    attempted_at,
                    delivered_at,
                    error_message,
                    subscription_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

    def delete_subscription(self, user_id: Optional[int], subscription_id: int) -> bool:
        where_clause, params = self._subscription_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"DELETE FROM subscriptions WHERE id = ? AND {where_clause}",
                (subscription_id, *params),
            )
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()

    def get_runtime_configs(self, user_id: Optional[int]) -> Dict[str, str]:
        where_clause, params = self._runtime_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                f"SELECT key, value FROM runtime_configs WHERE {where_clause}",
                params,
            )
            rows = cursor.fetchall()
            return {str(row["key"]): str(row["value"]) for row in rows}
        finally:
            connection.close()

    def upsert_runtime_configs(self, user_id: Optional[int], payload: Dict[str, str]) -> None:
        if not payload:
            return

        now = datetime.now(timezone.utc).isoformat()
        where_clause, scope_params = self._runtime_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            for key, value in payload.items():
                cursor.execute(
                    f"""
                    UPDATE runtime_configs
                    SET value = ?, updated_at = ?
                    WHERE {where_clause} AND key = ?
                    """,
                    (value, now, *scope_params, key),
                )
                if cursor.rowcount > 0:
                    continue
                cursor.execute(
                    """
                    INSERT INTO runtime_configs (user_id, key, value, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, key, value, now),
                )
            connection.commit()
        finally:
            connection.close()

    def delete_runtime_config_keys(self, user_id: Optional[int], keys: List[str]) -> None:
        clean_keys = [key for key in keys if key]
        if not clean_keys:
            return

        where_clause, params = self._runtime_scope_clause(user_id)
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.executemany(
                f"DELETE FROM runtime_configs WHERE {where_clause} AND key = ?",
                [params + (key,) for key in clean_keys],
            )
            connection.commit()
        finally:
            connection.close()
