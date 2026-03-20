from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from backend.repositories.paths import NIGHTSHIFT_DB


class LLMEvaluationRepository:
    def __init__(self, db_path: Path = NIGHTSHIFT_DB) -> None:
        self.db_path = Path(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_schema(self) -> None:
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_name TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    top_p REAL NOT NULL,
                    max_tokens INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    fallback_used INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    output_preview TEXT NOT NULL,
                    error_message TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def record(self, payload: Dict[str, object]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        connection = self._connect()
        try:
            cursor = connection.cursor()
            cursor.execute(
                """
                INSERT INTO llm_evaluations (
                    created_at,
                    provider,
                    model,
                    prompt_name,
                    prompt_version,
                    temperature,
                    top_p,
                    max_tokens,
                    success,
                    fallback_used,
                    latency_ms,
                    output_preview,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    str(payload.get("provider", "")),
                    str(payload.get("model", "")),
                    str(payload.get("prompt_name", "")),
                    str(payload.get("prompt_version", "")),
                    float(payload.get("temperature", 0.0)),
                    float(payload.get("top_p", 0.0)),
                    int(payload.get("max_tokens", 0)),
                    int(bool(payload.get("success", False))),
                    int(bool(payload.get("fallback_used", False))),
                    int(payload.get("latency_ms", 0)),
                    str(payload.get("output_preview", ""))[:300],
                    str(payload.get("error_message", ""))[:300],
                ),
            )
            connection.commit()
        finally:
            connection.close()
