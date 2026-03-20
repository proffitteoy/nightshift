from __future__ import annotations

import os
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
RUNTIME_ROOT_ENV = "NIGHTSHIFT_RUNTIME_ROOT"


def _resolve_runtime_root() -> Path:
    raw = os.getenv(RUNTIME_ROOT_ENV, "").strip()
    if not raw:
        return PROJECT_ROOT

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


RUNTIME_ROOT = _resolve_runtime_root()

COMMIT_DATA_DIR = RUNTIME_ROOT / "commit_data"
ANALYSIS_DATA_DIR = RUNTIME_ROOT / "analysis_data"
REPORTS_DIR = RUNTIME_ROOT / "reports"
SQLITE_DIR = RUNTIME_ROOT / "sqlite_data"

TRENDING_DB = SQLITE_DIR / "github_trending.db"
NIGHTSHIFT_DB = SQLITE_DIR / "nightshift.db"


def ensure_runtime_dirs() -> None:
    for runtime_dir in (COMMIT_DATA_DIR, ANALYSIS_DATA_DIR, REPORTS_DIR, SQLITE_DIR):
        runtime_dir.mkdir(parents=True, exist_ok=True)
