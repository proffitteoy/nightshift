from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.repositories.paths import NIGHTSHIFT_DB


class JobLockRepository:
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
                """
                CREATE TABLE IF NOT EXISTS job_locks (
                    lock_key TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def try_acquire(self, lock_key: str, owner_id: str, ttl_seconds: int) -> bool:
        now_ts = time.time()
        expires_at = now_ts + max(ttl_seconds, 1)
        updated_at = datetime.now(timezone.utc).isoformat()

        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute(
                "DELETE FROM job_locks WHERE lock_key = ? AND expires_at <= ?",
                (lock_key, now_ts),
            )
            try:
                cursor.execute(
                    """
                    INSERT INTO job_locks (lock_key, owner_id, expires_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (lock_key, owner_id, expires_at, updated_at),
                )
                connection.commit()
                return True
            except sqlite3.IntegrityError:
                connection.rollback()
                return False
        finally:
            connection.close()

    def release(self, lock_key: str, owner_id: str) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "DELETE FROM job_locks WHERE lock_key = ? AND owner_id = ?",
                (lock_key, owner_id),
            )
            connection.commit()
        finally:
            connection.close()
