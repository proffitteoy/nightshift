from __future__ import annotations

import logging
import os
import re
from hashlib import sha1
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from backend.clients.email_client import DEFAULT_DM_ENDPOINT, DEFAULT_DM_REGION_ID
from backend.clients.github_client import fetch_repo_activity, parse_repo_full_name
from backend.clients.llm_client import LLMClient
from backend.models.schemas import DailyReport
from backend.repositories.json_repository import read_json, save_json
from backend.repositories.paths import COMMIT_DATA_DIR, REPORTS_DIR
from backend.repositories.subscription_repository import SubscriptionRepository
from backend.security import SecurityValidationError, normalize_github_repo_url, normalize_repo_full_name
from backend.services.concurrency_guard import ConcurrencyGuard
from backend.services.runtime_config_utils import DEFAULT_LLM_BASE_URL, DEFAULT_LLM_MODEL, build_llm_config_overrides


LOGGER = logging.getLogger(__name__)

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
LLM_ENV_MAPPING = {
    "llm_api_key": "NIGHTSHIFT_GENERATOR_API_KEY",
    "llm_base_url": "NIGHTSHIFT_GENERATOR_BASE_URL",
    "llm_model": "NIGHTSHIFT_GENERATOR_MODEL",
    "llm_temperature": "NIGHTSHIFT_GENERATOR_TEMPERATURE",
    "llm_top_p": "NIGHTSHIFT_GENERATOR_TOP_P",
    "llm_max_tokens": "NIGHTSHIFT_GENERATOR_MAX_TOKENS",
    "llm_timeout_seconds": "NIGHTSHIFT_GENERATOR_TIMEOUT_SECONDS",
    "llm_max_retries": "NIGHTSHIFT_GENERATOR_MAX_RETRIES",
}
EMAIL_ENV_MAPPING = {
    "email_access_key_id": "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "email_access_key_secret": "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "email_account_name": "ALIBABA_CLOUD_DM_ACCOUNT_NAME",
    "email_region_id": "ALIBABA_CLOUD_DM_REGION_ID",
    "email_endpoint": "ALIBABA_CLOUD_DM_ENDPOINT",
    "email_address_type": "ALIBABA_CLOUD_DM_ADDRESS_TYPE",
    "email_reply_to_address": "ALIBABA_CLOUD_DM_REPLY_TO_ADDRESS",
    "email_from_alias": "ALIBABA_CLOUD_DM_FROM_ALIAS",
    "email_connect_timeout_ms": "ALIBABA_CLOUD_DM_CONNECT_TIMEOUT_MS",
    "email_read_timeout_ms": "ALIBABA_CLOUD_DM_READ_TIMEOUT_MS",
}
PERSISTED_LLM_DEFAULTS = {
    "llm_base_url": DEFAULT_LLM_BASE_URL,
    "llm_model": DEFAULT_LLM_MODEL,
    "llm_timeout_seconds": 25.0,
    "llm_max_retries": 1,
}
PERSISTED_EMAIL_DEFAULTS = {
    "email_region_id": DEFAULT_DM_REGION_ID,
    "email_endpoint": DEFAULT_DM_ENDPOINT,
    "email_address_type": 1,
    "email_reply_to_address": False,
    "email_connect_timeout_ms": 5000,
    "email_read_timeout_ms": 10000,
}
DEFAULT_EMAIL_REPORT_CACHE_TTL_MINUTES = 180


class ProjectService:
    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        subscription_repository: Optional[SubscriptionRepository] = None,
        concurrency_guard: Optional[ConcurrencyGuard] = None,
    ) -> None:
        self.llm_client = llm_client
        self.subscription_repository = subscription_repository or SubscriptionRepository()
        self.concurrency_guard = concurrency_guard or ConcurrencyGuard()

    def set_github_token(self, token: str) -> None:
        raise RuntimeError("set_github_token is disabled; persist runtime config via SubscriptionService instead")

    def set_llm_runtime_config(
        self,
        api_key: str,
        base_url: str,
        model: str,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> None:
        raise RuntimeError("set_llm_runtime_config is disabled; persist runtime config via SubscriptionService instead")

    def sync_persisted_runtime_config(
        self,
        raw_config: Dict[str, object],
        effective_config: Dict[str, object],
    ) -> None:
        raise RuntimeError("sync_persisted_runtime_config is disabled; read runtime config per request instead")

    def get_runtime_token(self, user_id: Optional[int] = None) -> Optional[str]:
        raw_config = self._get_user_runtime_config(user_id)
        if user_id is None and not raw_config:
            return os.getenv(GITHUB_TOKEN_ENV)
        token = str(raw_config.get("github_token", "")).strip()
        return token or None

    def subscribe_project(
        self,
        token: Optional[str],
        repo_url: str,
        hours: int = 24,
        user_id: Optional[int] = None,
    ) -> Dict[str, object]:
        normalized_repo_url = self._normalize_repo_url(repo_url)
        lock_key = self._build_repo_lock_key(scope="repo-work", repo_url=normalized_repo_url, user_id=user_id)
        with self.concurrency_guard.acquire(lock_key=lock_key):
            return self._subscribe_project_without_lock(
                token=token,
                repo_url=normalized_repo_url,
                hours=hours,
                user_id=user_id,
            )

    def _subscribe_project_without_lock(
        self,
        token: Optional[str],
        repo_url: str,
        hours: int = 24,
        user_id: Optional[int] = None,
    ) -> Dict[str, object]:
        used_fallback_snapshot = False
        try:
            data = fetch_repo_activity(token=token, repo_url=repo_url, hours=hours)
        except ConnectionError as exc:
            if self._is_repo_not_found_error(exc):
                raise
            LOGGER.warning("github fetch failed, fallback to empty snapshot: %s", exc)
            data = self._build_empty_snapshot(repo_url=repo_url, hours=hours)
            used_fallback_snapshot = True

        target_file = self._save_repo_snapshot(data, user_id=user_id)
        return {
            "repository": data.get("repository", "unknown"),
            "data_file": str(target_file),
            "snapshot": data,
            "used_fallback_snapshot": used_fallback_snapshot,
        }

    def _legacy_generate_daily_report(self) -> Dict[str, object]:
        raw_report = self._get_llm_client(user_id=None).generate_report()
        report = self._normalize_report_contract(raw_report)

        # 没有本地快照时，尝试从订阅仓库补一次数据，避免页面2长期停留在 unknown。
        if self._is_empty_report(report):
            bootstrap_repo_url = self._pick_bootstrap_repo_url()
            if bootstrap_repo_url:
                LOGGER.info("daily-report bootstrap from subscription repo: %s", bootstrap_repo_url)
                try:
                    generated = self.generate_report_by_user(
                        token=self.get_runtime_token(user_id=None),
                        repo_url=bootstrap_repo_url,
                        user_id=None,
                    )
                    report = generated["report"]
                except Exception as exc:
                    LOGGER.warning("daily-report bootstrap failed: %s", exc)

        report_path = self._save_report_artifact(report, user_id=None)
        LOGGER.info("daily report generated: %s", report_path.name)
        return report

    def _legacy_generate_report_by_user(self, token: Optional[str], repo_url: str, hours: int = 24) -> Dict[str, object]:
        snapshot_result = self.subscribe_project(token=token, repo_url=repo_url, hours=hours, user_id=None)
        raw_report = self._get_llm_client(user_id=None).generate_report(repo_name=str(snapshot_result["repository"]))
        report = self._normalize_report_contract(raw_report)
        report_path = self._save_report_artifact(report, user_id=None)
        LOGGER.info("user report generated: %s", report_path.name)
        return {
            "report": report,
            "data_file": snapshot_result["data_file"],
            "used_fallback_snapshot": bool(snapshot_result.get("used_fallback_snapshot", False)),
        }

    def answer_report_question(
        self,
        report: Dict[str, object],
        question: str,
        repo_url: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, str]:
        normalized_report = DailyReport.model_validate(report).model_dump(by_alias=True)
        resolved_repo_url = self._resolve_report_repo_url(report=normalized_report, repo_url=repo_url)
        return self._get_llm_client(user_id=user_id).answer_report_question(
            normalized_report,
            question,
            repo_url=resolved_repo_url,
            token=self.get_runtime_token(user_id=user_id),
        )

    def generate_email_digest(self, report: Dict[str, object], user_id: Optional[int] = None) -> str:
        normalized_report = DailyReport.model_validate(report).model_dump(by_alias=True)
        return self._get_llm_client(user_id=user_id).generate_email_digest(normalized_report)

    def _get_llm_client(self, user_id: Optional[int] = None) -> LLMClient:
        raw_config = self._get_user_runtime_config(user_id)
        if user_id is not None and raw_config:
            return LLMClient(
                config_overrides=build_llm_config_overrides(raw_config),
                commit_data_dir=self._resolve_commit_data_dir(user_id),
                use_env_overrides=False,
            )

        if self.llm_client is None:
            self.llm_client = LLMClient(commit_data_dir=self._resolve_commit_data_dir(None))
        return self.llm_client

    def _get_user_runtime_config(self, user_id: Optional[int]) -> Dict[str, str]:
        if user_id is None:
            return {}
        return self.subscription_repository.get_runtime_configs(user_id=user_id)

    def _resolve_commit_data_dir(self, user_id: Optional[int]) -> Path:
        if user_id is None:
            return COMMIT_DATA_DIR
        return COMMIT_DATA_DIR / f"user_{int(user_id)}"

    def _resolve_reports_dir(self, user_id: Optional[int]) -> Path:
        if user_id is None:
            return REPORTS_DIR
        return REPORTS_DIR / f"user_{int(user_id)}"

    def _build_daily_commit_file(self, repository: str, user_id: Optional[int]) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        safe_repo = self._build_safe_repo_segment(repository)
        return self._resolve_commit_data_dir(user_id) / f"{date_str}_{safe_repo}.json"

    def _build_report_file(self, repository: str, user_id: Optional[int]) -> Path:
        date_str = datetime.now().strftime("%Y-%m-%d")
        stamp = datetime.now().strftime("%H%M%S")
        safe_repo = self._build_safe_repo_segment(repository)
        return self._resolve_reports_dir(user_id) / f"{date_str}_{safe_repo}_{stamp}.json"

    def _save_repo_snapshot(self, data: Dict[str, object], user_id: Optional[int]) -> Path:
        repository = str(data.get("repository", "unknown"))
        target_file = self._build_daily_commit_file(repository, user_id=user_id)
        return save_json(data, target_file)

    def _save_report_artifact(self, report: Dict[str, object], user_id: Optional[int]) -> Path:
        repository = str(report.get("repository", "unknown"))
        target_file = self._build_report_file(repository, user_id=user_id)
        return save_json(report, target_file)

    def _build_empty_snapshot(self, repo_url: str, hours: int) -> Dict[str, object]:
        repository = self._repo_name_from_url(repo_url)
        return {
            "repository": repository,
            "fetch_time_utc": datetime.now().astimezone().isoformat(),
            "timespan_hours": hours,
            "analysis_mode": "latest-commit-diff",
            "latest_commit": {},
            "previous_commit": {},
            "comparison": {},
            "pull_requests": [],
            "commits": [],
        }

    def _repo_name_from_url(self, repo_url: str) -> str:
        try:
            return parse_repo_full_name(repo_url)
        except ValueError:
            parsed = urlparse(repo_url)
            path = parsed.path.strip("/").replace(".git", "")
            if path.count("/") == 1:
                return path
            return "unknown/unknown"

    def _build_repo_lock_key(self, scope: str, repo_url: str, user_id: Optional[int] = None) -> str:
        repo_name = self._repo_name_from_url(repo_url).strip().lower()
        safe_repo = re.sub(r"[^a-z0-9_.-]+", "_", repo_name).strip("_") or "unknown_unknown"
        digest = sha1(repo_url.strip().encode("utf-8")).hexdigest()[:12]
        scope_user = f"user_{int(user_id)}" if user_id is not None else "user_0"
        return f"project:{scope}:{scope_user}:{safe_repo}:{digest}"

    def generate_daily_report(self, user_id: Optional[int] = None) -> Dict[str, object]:
        daily_lock_key = f"project:daily-report:user:{int(user_id) if user_id is not None else 0}"
        with self.concurrency_guard.acquire(lock_key=daily_lock_key):
            raw_report = self._get_llm_client(user_id=user_id).generate_report()
            report = self._normalize_report_contract(raw_report)

            # No local snapshot: bootstrap from subscription list to keep tab2 usable.
            if self._is_empty_report(report):
                bootstrap_repo_url = self._pick_bootstrap_repo_url(user_id=user_id)
                if bootstrap_repo_url:
                    LOGGER.info("daily-report bootstrap from subscription repo: %s", bootstrap_repo_url)
                    try:
                        generated = self.generate_report_by_user(
                            token=self.get_runtime_token(user_id=user_id),
                            repo_url=bootstrap_repo_url,
                            user_id=user_id,
                        )
                        report = generated["report"]
                    except Exception as exc:
                        LOGGER.warning("daily-report bootstrap failed: %s", exc)

            report_path = self._save_report_artifact(report, user_id=user_id)
            LOGGER.info("daily report generated: %s", report_path.name)
            return report

    def generate_report_by_user(
        self,
        token: Optional[str],
        repo_url: str,
        hours: int = 24,
        user_id: Optional[int] = None,
    ) -> Dict[str, object]:
        normalized_repo_url = self._normalize_repo_url(repo_url)
        lock_key = self._build_repo_lock_key(scope="repo-work", repo_url=normalized_repo_url, user_id=user_id)
        with self.concurrency_guard.acquire(lock_key=lock_key):
            snapshot_result = self._subscribe_project_without_lock(
                token=token,
                repo_url=normalized_repo_url,
                hours=hours,
                user_id=user_id,
            )
            raw_report = self._get_llm_client(user_id=user_id).generate_report(
                repo_name=str(snapshot_result["repository"])
            )
            report = self._normalize_report_contract(raw_report)
            report_path = self._save_report_artifact(report, user_id=user_id)
            LOGGER.info("user report generated: %s", report_path.name)
            return {
                "report": report,
                "data_file": snapshot_result["data_file"],
                "used_fallback_snapshot": bool(snapshot_result.get("used_fallback_snapshot", False)),
            }

    def generate_email_report_by_user(
        self,
        token: Optional[str],
        repo_url: str,
        hours: int = 24,
        user_id: Optional[int] = None,
        max_age_minutes: Optional[int] = None,
    ) -> Dict[str, object]:
        normalized_repo_url = self._normalize_repo_url(repo_url)
        cached_report = self.load_recent_report_by_repo(
            repo_url=normalized_repo_url,
            user_id=user_id,
            max_age_minutes=max_age_minutes,
            require_usable_snapshot=bool(str(token or "").strip()),
        )
        if cached_report is not None:
            LOGGER.info(
                "email report reused local artifact: user_id=%s repo=%s report_file=%s",
                user_id,
                self._repo_name_from_url(normalized_repo_url),
                cached_report["report_file"],
            )
            return cached_report

        result = self.generate_report_by_user(
            token=token,
            repo_url=normalized_repo_url,
            hours=hours,
            user_id=user_id,
        )
        result["report_source"] = "realtime"
        return result

    def load_recent_report_by_repo(
        self,
        repo_url: str,
        user_id: Optional[int] = None,
        max_age_minutes: Optional[int] = None,
        require_usable_snapshot: bool = False,
    ) -> Optional[Dict[str, object]]:
        normalized_repo_url = self._normalize_repo_url(repo_url)
        repository = normalize_repo_full_name(self._repo_name_from_url(normalized_repo_url))
        reports_dir = self._resolve_reports_dir(user_id)
        if not reports_dir.exists():
            return None

        cutoff_at = datetime.now(timezone.utc) - timedelta(
            minutes=self._resolve_email_report_cache_ttl_minutes(max_age_minutes)
        )
        safe_repo = self._build_safe_repo_segment(repository)
        candidates = sorted(
            reports_dir.glob(f"*_{safe_repo}_*.json"),
            key=lambda file_path: file_path.stat().st_mtime,
            reverse=True,
        )
        for report_file in candidates:
            try:
                modified_at = datetime.fromtimestamp(report_file.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified_at < cutoff_at:
                break

            report = self._load_report_artifact(report_file)
            if report is None:
                continue
            try:
                self._resolve_report_repo_url(report=report, repo_url=normalized_repo_url)
            except ValueError:
                continue
            if require_usable_snapshot:
                snapshot = self._load_recent_snapshot_by_repo(
                    repo_url=normalized_repo_url,
                    user_id=user_id,
                    max_age_minutes=max_age_minutes,
                )
                if not self._has_usable_snapshot(snapshot):
                    LOGGER.info(
                        "email report cache bypassed: user_id=%s repo=%s reason=missing_usable_snapshot",
                        user_id,
                        repository,
                    )
                    continue
            return {
                "report": report,
                "report_source": "cache",
                "report_file": str(report_file),
                "used_fallback_snapshot": False,
            }
        return None

    def _normalize_report_contract(self, raw_report: Dict[str, object]) -> Dict[str, object]:
        summary_text = str(raw_report.get("summary", "")).strip()
        todo_list = self._normalize_todo_list(raw_report.get("todo_list", []))
        details = self._normalize_details(raw_report.get("details", {}))
        stats = self._normalize_stats(raw_report.get("stats", {}), details)

        high_priority = [item for item in todo_list if self._is_high_priority(item)]
        medium_priority = [item for item in todo_list if self._is_medium_priority(item)]
        low_priority = [item for item in todo_list if item not in high_priority and item not in medium_priority]

        unresolved_count = len(todo_list)
        high_risk_count = len(high_priority)
        overdue_count = len(
            [
                item
                for item in todo_list
                if self._contains_any(item.lower(), ["overdue", "past due", "late", "expired"])
            ]
        )

        structured_summary = {
            "unresolved_count": unresolved_count,
            "high_risk_count": high_risk_count,
            "overdue_count": overdue_count,
            "key_conclusion": summary_text[:160] if summary_text else "No summary generated.",
        }

        structured_sections = {
            "key_risk_summary": {
                "text": summary_text,
                "high_priority_items": high_priority[:10],
            },
            "handover_records": {
                "top_prs": details["top_prs"],
                "top_commits": details["top_commits"],
            },
            "onboarding_summary": {
                "repository": raw_report.get("repository", "unknown"),
                "entry_context": "Generated from latest-vs-previous commit diff.",
                "next_actions": todo_list[:5],
            },
            "charts": {
                "risk_trend": self._build_risk_trend(high_risk_count),
                "task_priority_distribution": {
                    "high": len(high_priority),
                    "medium": len(medium_priority),
                    "low": len(low_priority),
                },
            },
        }

        payload = {
            "repository": raw_report.get("repository", "unknown"),
            "report_date": raw_report.get("report_date", datetime.now().strftime("%Y-%m-%d")),
            "time_range": raw_report.get("time_range", ""),
            "stats": stats,
            "summary_text": summary_text,
            "todo_list": todo_list,
            "details": details,
            "summary": structured_summary,
            "sections": structured_sections,
        }

        validated = DailyReport.model_validate(payload)
        return validated.model_dump(by_alias=True)

    def _normalize_stats(self, raw_stats: object, details: Dict[str, object]) -> Dict[str, int]:
        stats = raw_stats if isinstance(raw_stats, dict) else {}
        pr_count = self._to_int(stats.get("pr_count"), default=len(details.get("top_prs", [])))
        commit_count = self._to_int(stats.get("commit_count"), default=len(details.get("top_commits", [])))
        return {
            "pr_count": pr_count,
            "commit_count": commit_count,
        }

    def _normalize_details(self, raw_details: object) -> Dict[str, List[Dict[str, object]]]:
        details = raw_details if isinstance(raw_details, dict) else {}
        top_prs_raw = details.get("top_prs")
        top_commits_raw = details.get("top_commits")
        top_prs: List[Dict[str, object]] = []
        top_commits: List[Dict[str, object]] = []

        if isinstance(top_prs_raw, list):
            for item in top_prs_raw:
                if not isinstance(item, dict):
                    continue
                top_prs.append(
                    {
                        "number": self._to_int(item.get("number")),
                        "title": str(item.get("title", "")),
                        "user": str(item.get("user", "")),
                        "files_count": self._to_int(item.get("files_count")),
                    }
                )

        if isinstance(top_commits_raw, list):
            for item in top_commits_raw:
                if not isinstance(item, dict):
                    continue
                top_commits.append(
                    {
                        "sha": str(item.get("sha", "")),
                        "author": str(item.get("author", "")),
                        "message": str(item.get("message", "")),
                    }
                )

        return {"top_prs": top_prs, "top_commits": top_commits}

    def _normalize_todo_list(self, raw_todo_list: object) -> List[str]:
        if not isinstance(raw_todo_list, list):
            return []
        return [str(item).strip() for item in raw_todo_list if str(item).strip()]

    def _is_high_priority(self, item: str) -> bool:
        lowered = item.lower()
        return self._contains_any(
            lowered,
            ["[high]", " high", "critical", "blocker", "sev-1", "p0", "urgent", "high priority"],
        )

    def _is_medium_priority(self, item: str) -> bool:
        lowered = item.lower()
        return self._contains_any(
            lowered,
            ["[medium]", " medium", "important", "p1", "normal priority"],
        )

    def _contains_any(self, text: str, keywords: List[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _build_risk_trend(self, high_risk_count: int) -> List[Dict[str, object]]:
        if high_risk_count <= 0:
            labels = ["D-6", "D-5", "D-4", "D-3", "D-2", "D-1", "D0"]
            return [{"day": label, "high_risk_count": 0} for label in labels]

        base = max(high_risk_count - 2, 0)
        values = [
            base,
            max(base + 1, 0),
            max(base + 1, 0),
            high_risk_count,
            high_risk_count,
            high_risk_count,
            high_risk_count,
        ]
        labels = ["D-6", "D-5", "D-4", "D-3", "D-2", "D-1", "D0"]
        return [{"day": label, "high_risk_count": values[index]} for index, label in enumerate(labels)]

    def _to_int(self, value: object, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def _is_empty_report(self, report: Dict[str, object]) -> bool:
        repository = str(report.get("repository", "unknown")).strip().lower()
        stats = report.get("stats", {})
        if not isinstance(stats, dict):
            stats = {}
        pr_count = self._to_int(stats.get("pr_count"), 0)
        commit_count = self._to_int(stats.get("commit_count"), 0)
        return repository in {"", "unknown", "unknown/unknown"} and pr_count == 0 and commit_count == 0

    def _pick_bootstrap_repo_url(self, user_id: Optional[int] = None) -> Optional[str]:
        subscriptions = self.subscription_repository.list_subscriptions(user_id=user_id)
        if not subscriptions:
            return None

        for item in subscriptions:
            if not isinstance(item, dict):
                continue
            if item.get("morning_report_enabled", True):
                repo_url = str(item.get("repo_url", "")).strip()
                if repo_url:
                    return repo_url

        for item in subscriptions:
            if not isinstance(item, dict):
                continue
            repo_url = str(item.get("repo_url", "")).strip()
            if repo_url:
                return repo_url
        return None

    def _load_report_artifact(self, report_file: Path) -> Optional[Dict[str, object]]:
        try:
            payload = read_json(report_file)
            if not isinstance(payload, dict):
                return None
            return DailyReport.model_validate(payload).model_dump(by_alias=True)
        except Exception:
            return None

    def _load_recent_snapshot_by_repo(
        self,
        repo_url: str,
        user_id: Optional[int] = None,
        max_age_minutes: Optional[int] = None,
    ) -> Optional[Dict[str, object]]:
        normalized_repo_url = self._normalize_repo_url(repo_url)
        repository = normalize_repo_full_name(self._repo_name_from_url(normalized_repo_url))
        commit_data_dir = self._resolve_commit_data_dir(user_id)
        if not commit_data_dir.exists():
            return None

        cutoff_at = datetime.now(timezone.utc) - timedelta(
            minutes=self._resolve_email_report_cache_ttl_minutes(max_age_minutes)
        )
        safe_repo = self._build_safe_repo_segment(repository)
        candidates = sorted(
            commit_data_dir.glob(f"*_{safe_repo}.json"),
            key=lambda file_path: file_path.stat().st_mtime,
            reverse=True,
        )
        for snapshot_file in candidates:
            try:
                modified_at = datetime.fromtimestamp(snapshot_file.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified_at < cutoff_at:
                break
            try:
                payload = read_json(snapshot_file)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if normalize_repo_full_name(str(payload.get("repository", ""))) != repository:
                continue
            return payload
        return None

    def _has_usable_snapshot(self, snapshot: Optional[Dict[str, object]]) -> bool:
        if not isinstance(snapshot, dict) or not snapshot:
            return False

        latest_commit = snapshot.get("latest_commit")
        if isinstance(latest_commit, dict) and str(latest_commit.get("sha", "")).strip():
            return True

        commits = snapshot.get("commits")
        if isinstance(commits, list) and any(
            isinstance(item, dict) and str(item.get("sha", "")).strip()
            for item in commits
        ):
            return True

        comparison = snapshot.get("comparison")
        if isinstance(comparison, dict):
            if str(comparison.get("base_sha", "")).strip() and str(comparison.get("head_sha", "")).strip():
                return True

        pull_requests = snapshot.get("pull_requests")
        if isinstance(pull_requests, list) and any(isinstance(item, dict) for item in pull_requests):
            return True

        return False

    def _build_repo_url_from_report(self, report: Dict[str, object]) -> Optional[str]:
        repository = str(report.get("repository", "")).strip()
        if repository.count("/") != 1:
            return None
        return f"https://github.com/{repository}"

    def _resolve_report_repo_url(self, report: Dict[str, object], repo_url: Optional[str]) -> Optional[str]:
        resolved_repo_url = self._normalize_repo_url(repo_url) if repo_url else self._build_repo_url_from_report(report)
        if resolved_repo_url is None:
            return None
        report_repository = str(report.get("repository", "")).strip()
        if report_repository and report_repository not in {"unknown", "unknown/unknown"}:
            try:
                expected_repo = normalize_repo_full_name(report_repository)
                actual_repo = normalize_repo_full_name(self._repo_name_from_url(resolved_repo_url))
            except SecurityValidationError as exc:
                raise ValueError(str(exc)) from exc
            if expected_repo.lower() != actual_repo.lower():
                raise ValueError("repo_url does not match the report repository")
        return resolved_repo_url

    def _is_repo_not_found_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        keywords = [
            "仓库不存在",
            "无访问权限",
            "repo not found",
            "not found",
            "invalid github",
        ]
        return any(keyword in text for keyword in keywords)

    def _set_or_clear_env(self, env_name: str, value: object) -> None:
        if value is None:
            self._clear_env(env_name)
            return
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                self._clear_env(env_name)
                return
            os.environ[env_name] = normalized
            return
        os.environ[env_name] = str(value)

    def _clear_env(self, env_name: str) -> None:
        os.environ.pop(env_name, None)

    def _clean_string(self, value: object) -> str:
        return str(value).strip() if value is not None else ""

    def _build_safe_repo_segment(self, repository: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_.-]+", "_", repository).strip("_") or "unknown"

    def _resolve_email_report_cache_ttl_minutes(self, requested_ttl_minutes: Optional[int]) -> int:
        if requested_ttl_minutes is not None:
            return max(int(requested_ttl_minutes), 1)
        return self._parse_positive_int(
            os.getenv("NIGHTSHIFT_EMAIL_REPORT_CACHE_TTL_MINUTES"),
            default=DEFAULT_EMAIL_REPORT_CACHE_TTL_MINUTES,
        )

    def _parse_positive_int(self, value: object, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _reset_llm_client(self) -> None:
        self.llm_client = None

    def _normalize_repo_url(self, repo_url: str) -> str:
        try:
            return normalize_github_repo_url(repo_url)
        except SecurityValidationError as exc:
            raise ValueError(str(exc)) from exc
