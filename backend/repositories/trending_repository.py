from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

from backend.repositories.paths import TRENDING_DB
from backend.security import SecurityValidationError, normalize_github_repo_url, sanitize_untrusted_text


class TrendingRepository:
    """热点仓库数据仓储。"""

    def __init__(self, db_path: Path = TRENDING_DB) -> None:
        self.db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS weekly_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    author TEXT,
                    language TEXT,
                    stars_total INTEGER,
                    forks_total INTEGER,
                    issues_total INTEGER,
                    date TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS project_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    author TEXT,
                    link TEXT,
                    creation_date TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def has_daily_records(self, date_str: str) -> bool:
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM weekly_data WHERE date = ? LIMIT 1", (date_str,))
            return cur.fetchone() is not None
        finally:
            conn.close()

    def save_trending_repositories(self, repos: List[Dict[str, object]], date_str: str) -> int:
        conn = self._connect()
        inserted = 0
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM weekly_data WHERE date = ?", (date_str,))
            for repo in repos:
                try:
                    link = normalize_github_repo_url(repo.get("html_url", ""))
                    path_parts = link.rstrip("/").split("/")[-2:]
                    if len(path_parts) != 2:
                        continue
                    author, name = path_parts
                    language = sanitize_untrusted_text(repo.get("language") or "N/A", max_length=60, allow_empty=True) or "N/A"
                    stars_total = int(repo.get("stargazers_count", 0))
                    forks_total = int(repo.get("forks_count", 0))
                    issues_total = int(repo.get("open_issues_count", 0))
                    creation_date = sanitize_untrusted_text(repo.get("created_at", ""), max_length=40, allow_empty=True)
                except (SecurityValidationError, TypeError, ValueError):
                    continue

                cur.execute(
                    """
                    INSERT INTO weekly_data (name, author, language, stars_total, forks_total, issues_total, date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (name, author, language, stars_total, forks_total, issues_total, date_str),
                )
                cur.execute(
                    """
                    INSERT OR REPLACE INTO project_data (id, name, author, link, creation_date)
                    VALUES ((SELECT id FROM project_data WHERE name = ?), ?, ?, ?, ?)
                    """,
                    (name, name, author, link, creation_date),
                )
                inserted += 1

            conn.commit()
            return inserted
        finally:
            conn.close()

    def list_weekly_records(self, days: int = 7) -> List[Dict[str, object]]:
        safe_days = max(days, 1)
        threshold = (datetime.now() - timedelta(days=safe_days - 1)).strftime("%Y-%m-%d")
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM weekly_data
                WHERE date >= ?
                ORDER BY date DESC, stars_total DESC
                """,
                (threshold,),
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
