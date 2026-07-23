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
from backend.clients.github_client import fetch_repo_activity, fetch_repo_question_context, parse_repo_full_name
from backend.clients.llm_client import LLMClient
from backend.models.schemas import DailyReport
from backend.repositories.json_repository import read_json, save_json
from backend.repositories.paths import ANALYSIS_DATA_DIR, COMMIT_DATA_DIR, REPORTS_DIR
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
DEFAULT_REPO_CONTEXT_MAX_CHARS = 12000
REPO_CONTEXT_BLOCK_CHAR_LIMIT = 900


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

    def generate_repo_context(
        self,
        token: Optional[str],
        repo_url: str,
        question: Optional[str] = None,
        intent: Optional[str] = None,
        hours: int = 72,
        context_mode: str = "standard",
        max_context_chars: int = DEFAULT_REPO_CONTEXT_MAX_CHARS,
        max_evidence_items: int = 12,
        include_raw: bool = False,
        cache_ttl_seconds: int = 1800,
        force_refresh: bool = False,
        user_id: Optional[int] = None,
    ) -> Dict[str, object]:
        normalized_repo_url = self._normalize_repo_url(repo_url)
        lock_key = self._build_repo_context_lock_key(
            repo_url=normalized_repo_url,
            user_id=user_id,
            hours=hours,
        )
        with self.concurrency_guard.acquire(lock_key=lock_key):
            cached = None if force_refresh else self._load_repo_context_artifact(
                repo_url=normalized_repo_url,
                user_id=user_id,
                hours=hours,
                cache_ttl_seconds=cache_ttl_seconds,
            )
            if cached is not None:
                return self._normalize_repo_context_payload(
                    cached,
                    repo_url=normalized_repo_url,
                    source="cache",
                    hours=hours,
                    question=question,
                    intent=intent,
                    context_mode=context_mode,
                    max_context_chars=max_context_chars,
                    max_evidence_items=max_evidence_items,
                    include_raw=include_raw,
                )

            context = fetch_repo_question_context(
                token=token,
                repo_url=normalized_repo_url,
                commit_data_dir=self._resolve_commit_data_dir(user_id),
                hours=hours,
            )
            payload = self._normalize_repo_context_payload(
                context,
                repo_url=normalized_repo_url,
                source="github",
                hours=hours,
                question=question,
                intent=intent,
                context_mode=context_mode,
                max_context_chars=max_context_chars,
                max_evidence_items=max_evidence_items,
                include_raw=include_raw,
            )
            self._save_repo_context_artifact(
                context,
                repo_url=normalized_repo_url,
                user_id=user_id,
                hours=hours,
            )
            return payload

    def answer_repo_context_question(
        self,
        token: Optional[str],
        repo_url: str,
        question: str,
        hours: int = 72,
        context_mode: str = "standard",
        max_context_chars: int = DEFAULT_REPO_CONTEXT_MAX_CHARS,
        max_evidence_items: int = 12,
        include_raw: bool = False,
        cache_ttl_seconds: int = 1800,
        force_refresh: bool = False,
        user_id: Optional[int] = None,
    ) -> Dict[str, object]:
        context = self.generate_repo_context(
            token=token,
            repo_url=repo_url,
            question=question,
            hours=hours,
            context_mode=context_mode,
            max_context_chars=max_context_chars,
            max_evidence_items=max_evidence_items,
            include_raw=include_raw,
            cache_ttl_seconds=cache_ttl_seconds,
            force_refresh=force_refresh,
            user_id=user_id,
        )
        answer_result = self._get_llm_client(user_id=user_id).answer_repo_context_question(
            context,
            question,
        )
        return {
            **context,
            "answer": answer_result["answer"],
            "answer_source": answer_result["source"],
            "message": "repo context question answered",
        }

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

    def _resolve_repo_context_dir(self, user_id: Optional[int]) -> Path:
        base_dir = ANALYSIS_DATA_DIR / "repo_context"
        if user_id is None:
            return base_dir
        return base_dir / f"user_{int(user_id)}"

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

    def _build_repo_context_file(self, repo_url: str, user_id: Optional[int], hours: int) -> Path:
        repo_name = self._repo_name_from_url(repo_url)
        safe_repo = self._build_safe_repo_segment(repo_name)
        scope_user = f"user_{int(user_id)}" if user_id is not None else "user_0"
        digest = sha1(f"{repo_url.strip()}|{hours}|{scope_user}".encode("utf-8")).hexdigest()[:12]
        return self._resolve_repo_context_dir(user_id) / f"{safe_repo}_{hours}h_{digest}.json"

    def _build_repo_context_lock_key(self, repo_url: str, user_id: Optional[int], hours: int) -> str:
        repo_name = self._repo_name_from_url(repo_url).strip().lower()
        safe_repo = re.sub(r"[^a-z0-9_.-]+", "_", repo_name).strip("_") or "unknown_unknown"
        scope_user = f"user_{int(user_id)}" if user_id is not None else "user_0"
        digest = sha1(f"{repo_url.strip()}|{hours}|{scope_user}".encode("utf-8")).hexdigest()[:12]
        return f"repo-context:{scope_user}:{safe_repo}:{hours}:{digest}"

    def _load_repo_context_artifact(
        self,
        *,
        repo_url: str,
        user_id: Optional[int],
        hours: int,
        cache_ttl_seconds: int,
    ) -> Optional[Dict[str, object]]:
        if cache_ttl_seconds <= 0:
            return None
        target_file = self._build_repo_context_file(repo_url, user_id=user_id, hours=hours)
        if not target_file.exists():
            return None
        modified_at = datetime.fromtimestamp(target_file.stat().st_mtime, tz=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - modified_at).total_seconds()
        if age_seconds > cache_ttl_seconds:
            return None
        try:
            payload = read_json(target_file)
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _save_repo_context_artifact(
        self,
        payload: Dict[str, object],
        *,
        repo_url: str,
        user_id: Optional[int],
        hours: int,
    ) -> Path:
        target_file = self._build_repo_context_file(repo_url, user_id=user_id, hours=hours)
        return save_json(payload, target_file)

    def _normalize_repo_context_payload(
        self,
        context: Dict[str, object],
        *,
        repo_url: str,
        source: str,
        hours: int,
        question: Optional[str],
        intent: Optional[str],
        context_mode: str,
        max_context_chars: int,
        max_evidence_items: int,
        include_raw: bool,
    ) -> Dict[str, object]:
        repository = str(context.get("repository", "unknown/unknown") or "unknown/unknown").strip()
        payload = dict(context)
        package = self._build_repo_analysis_context_package(
            context,
            repo_url=repo_url,
            question=question,
            intent=intent,
            context_mode=context_mode,
            max_context_chars=max_context_chars,
            max_evidence_items=max_evidence_items,
        )
        payload.update(
            {
                "repo_url": repo_url,
                "repository": repository,
                "source": source,
                "hours": hours,
                "question": str(question or ""),
                "intent": str(intent or ""),
                "context_mode": context_mode,
                "max_context_chars": max_context_chars,
                "max_evidence_items": max_evidence_items,
                "include_raw": include_raw,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "repo_summary_text": self._build_repo_summary_text(context),
                "recent_changes_text": self._build_recent_changes_text(context),
                **package,
                "readme_text": self._format_repo_readme_excerpt(context),
                "root_entries_text": self._format_repo_root_entries(context),
                "changed_files_text": self._format_repo_changed_files(context),
                "recent_prs_text": self._format_repo_pull_requests(context),
                "recent_commits_text": self._format_repo_commits(context),
                "merged_context": package["analysis_prompt_context"],
            }
        )
        return payload

    def _build_repo_analysis_context_package(
        self,
        context: Dict[str, object],
        *,
        repo_url: str,
        question: Optional[str],
        intent: Optional[str],
        context_mode: str,
        max_context_chars: int,
        max_evidence_items: int,
    ) -> Dict[str, object]:
        safe_max_chars = max(1000, min(int(max_context_chars or DEFAULT_REPO_CONTEXT_MAX_CHARS), 60000))
        safe_max_items = max(3, min(int(max_evidence_items or 12), 30))
        mode = str(context_mode or "standard").lower()
        if mode == "compact":
            safe_max_chars = min(safe_max_chars, 6000)
            safe_max_items = min(safe_max_items, 8)
        elif mode == "deep":
            safe_max_chars = max(safe_max_chars, DEFAULT_REPO_CONTEXT_MAX_CHARS)

        all_blocks = self._build_evidence_blocks(
            context,
            question=question,
            intent=intent,
        )
        missing_context = self._build_missing_context(context)
        selected_blocks, omitted = self._select_evidence_blocks(
            all_blocks=all_blocks,
            max_context_chars=safe_max_chars,
            max_evidence_items=safe_max_items,
        )
        prompt = self._render_analysis_prompt_context(
            context,
            repo_url=repo_url,
            question=question,
            intent=intent,
            context_quality=self._resolve_context_quality(missing_context),
            missing_context=missing_context,
            evidence_blocks=selected_blocks,
            max_context_chars=safe_max_chars,
        )
        return {
            "context_quality": self._resolve_context_quality(missing_context),
            "analysis_prompt_context": prompt,
            "evidence_blocks": selected_blocks,
            "omitted_evidence_count": omitted,
            "missing_context": missing_context,
        }

    def _build_evidence_blocks(
        self,
        context: Dict[str, object],
        *,
        question: Optional[str],
        intent: Optional[str],
    ) -> List[Dict[str, object]]:
        intent_bucket = self._resolve_context_intent_bucket(question=question, intent=intent)
        blocks: List[Dict[str, object]] = []

        def add_block(block_type: str, title: str, content: str, priority: int) -> None:
            normalized_content = self._truncate_text(content, REPO_CONTEXT_BLOCK_CHAR_LIMIT)
            if normalized_content:
                blocks.append(
                    {
                        "type": block_type,
                        "title": title,
                        "content": normalized_content,
                        "priority": priority,
                    }
                )

        description = str(context.get("description", "") or "").strip()
        topics = self._format_repo_topics(context)
        readme = self._format_repo_readme_excerpt(context)
        root_entries = self._format_repo_root_entries(context, limit=20)
        changed_files = context.get("changed_files", []) if isinstance(context.get("changed_files"), list) else []
        pull_requests = (
            context.get("recent_pull_requests", [])
            if isinstance(context.get("recent_pull_requests"), list)
            else []
        )
        commits = context.get("recent_commits", []) if isinstance(context.get("recent_commits"), list) else []

        identity_boost = 30 if intent_bucket == "identity" else 0
        change_boost = 35 if intent_bucket == "recent" else 0
        risk_boost = 25 if intent_bucket == "risk" else 0
        refactor_boost = 20 if intent_bucket == "refactor" else 0

        add_block("summary", "仓库基础信息", self._build_repo_summary_text(context), 100 + identity_boost)
        add_block("topics", "仓库 Topics", topics, 80 + identity_boost)
        add_block("readme", "README 摘要", readme, 90 + identity_boost + refactor_boost)
        add_block("root", "根目录结构", root_entries, 85 + identity_boost + refactor_boost)

        for index, item in enumerate(changed_files[:8]):
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", "") or "").strip()
            if not filename:
                continue
            patch_excerpt = str(item.get("patch_excerpt", "") or "").strip()
            content = (
                f"{filename} | {str(item.get('status', '')).strip()} | "
                f"+{self._to_int(item.get('additions'))} / -{self._to_int(item.get('deletions'))}"
            )
            if patch_excerpt:
                content += f"\npatch excerpt:\n{patch_excerpt}"
            add_block("changed_file", f"近期变更文件 {index + 1}: {filename}", content, 75 + change_boost + risk_boost - index)

        for index, item in enumerate(pull_requests[:5]):
            if not isinstance(item, dict):
                continue
            number = self._to_int(item.get("number"))
            title = str(item.get("title", "") or "").strip()
            if number <= 0 and not title:
                continue
            content = (
                f"PR #{number} {title}\n"
                f"state={str(item.get('state', '')).strip()}, user={str(item.get('user', '')).strip()}, "
                f"files={self._to_int(item.get('files_count'))}, updated_at={str(item.get('updated_at', '')).strip()}"
            )
            add_block("pull_request", f"近期 PR {index + 1}", content, 70 + change_boost - index)

        for index, item in enumerate(commits[:5]):
            if not isinstance(item, dict):
                continue
            sha = str(item.get("sha", "") or "").strip()[:7]
            message = str(item.get("message", "") or "").strip()
            if not sha and not message:
                continue
            stats = item.get("stats", {}) if isinstance(item.get("stats"), dict) else {}
            content = (
                f"{sha} {str(item.get('author', '')).strip()}: {message}\n"
                f"date={str(item.get('date', '')).strip()}, "
                f"+{self._to_int(stats.get('additions'))} / -{self._to_int(stats.get('deletions'))}"
            )
            add_block("commit", f"近期 Commit {index + 1}", content, 68 + change_boost - index)

        blocks.sort(key=lambda item: (-self._to_int(item.get("priority")), str(item.get("title", ""))))
        return blocks

    def _select_evidence_blocks(
        self,
        *,
        all_blocks: List[Dict[str, object]],
        max_context_chars: int,
        max_evidence_items: int,
    ) -> tuple[List[Dict[str, object]], int]:
        selected: List[Dict[str, object]] = []
        omitted = 0
        used_chars = 0
        budget_for_blocks = max(max_context_chars - 1200, 500)

        for block in all_blocks:
            if len(selected) >= max_evidence_items:
                omitted += 1
                continue
            block_size = len(str(block.get("title", ""))) + len(str(block.get("content", ""))) + 40
            if used_chars + block_size > budget_for_blocks and selected:
                omitted += 1
                continue
            selected.append(block)
            used_chars += block_size

        return selected, omitted

    def _render_analysis_prompt_context(
        self,
        context: Dict[str, object],
        *,
        repo_url: str,
        question: Optional[str],
        intent: Optional[str],
        context_quality: str,
        missing_context: List[str],
        evidence_blocks: List[Dict[str, object]],
        max_context_chars: int,
    ) -> str:
        repository = str(context.get("repository", "unknown/unknown") or "unknown/unknown").strip()
        header = [
            "你将基于以下 NightShift 已筛选的 GitHub 仓库上下文进行分析。",
            f"仓库：{repository}",
            f"仓库地址：{repo_url}",
            f"用户问题：{str(question or '').strip() or '未提供'}",
            f"识别意图：{str(intent or '').strip() or '未提供'}",
            f"上下文质量：{context_quality}",
            f"缺失上下文：{', '.join(missing_context) if missing_context else '无'}",
            "",
            "证据块：",
        ]
        block_lines: List[str] = []
        for index, block in enumerate(evidence_blocks, start=1):
            block_lines.extend(
                [
                    f"[{index}] {str(block.get('title', '')).strip()} ({str(block.get('type', '')).strip()})",
                    str(block.get("content", "")).strip(),
                    "",
                ]
            )

        footer = [
            "分析要求：",
            "- 只基于以上证据回答，不要编造未出现的信息。",
            "- 如果上下文质量不是 complete，说明不确定性和缺失信息。",
            "- 优先回答用户问题；涉及最近更新时引用 changed_file、pull_request 或 commit 证据。",
        ]
        prompt = "\n".join(header + block_lines + footer).strip()
        return self._truncate_text(prompt, max_context_chars)

    def _build_missing_context(self, context: Dict[str, object]) -> List[str]:
        missing: List[str] = []
        if not str(context.get("readme_excerpt", "") or "").strip():
            missing.append("README")
        if not isinstance(context.get("root_entries"), list) or not context.get("root_entries"):
            missing.append("根目录结构")
        if not isinstance(context.get("changed_files"), list) or not context.get("changed_files"):
            missing.append("近期变更文件")
        if not isinstance(context.get("recent_pull_requests"), list) or not context.get("recent_pull_requests"):
            missing.append("最近 PR")
        if not isinstance(context.get("recent_commits"), list) or not context.get("recent_commits"):
            missing.append("最近 Commit")
        return missing

    def _resolve_context_quality(self, missing_context: List[str]) -> str:
        if not missing_context:
            return "complete"
        if len(missing_context) <= 2:
            return "partial"
        return "weak"

    def _resolve_context_intent_bucket(self, *, question: Optional[str], intent: Optional[str]) -> str:
        text = f"{intent or ''} {question or ''}".lower()
        if any(term in text for term in ["最近", "更新", "commit", "commits", "pr", "change", "changes"]):
            return "recent"
        if any(term in text for term in ["找问题", "风险", "bug", "漏洞", "安全", "排查", "异常"]):
            return "risk"
        if any(term in text for term in ["改造", "优化", "重构", "规划", "新增", "实现"]):
            return "refactor"
        return "identity"

    def _build_recent_changes_text(self, context: Dict[str, object]) -> str:
        parts = [
            "近期变更文件：",
            self._format_repo_changed_files(context),
            "近期 PR：",
            self._format_repo_pull_requests(context),
            "近期 Commit：",
            self._format_repo_commits(context),
        ]
        return self._truncate_text("\n".join(parts), 5000)

    def _format_repo_topics(self, context: Dict[str, object]) -> str:
        topics = context.get("topics", [])
        if not isinstance(topics, list) or not topics:
            return "- 当前未获取到 topics"
        return "\n".join(f"- {str(item).strip()}" for item in topics[:8] if str(item).strip()) or "- 当前未获取到 topics"

    def _truncate_text(self, value: object, max_chars: int) -> str:
        text = str(value or "").strip()
        if len(text) <= max_chars:
            return text
        suffix = f"\n...[已截断，原始长度 {len(text)} 字符]"
        return text[: max(max_chars - len(suffix), 0)].rstrip() + suffix

    def _build_repo_context_merged_text(self, context: Dict[str, object]) -> str:
        parts = [
            f"仓库：{str(context.get('repository', '')).strip()}",
            f"描述：{str(context.get('description', '')).strip()}",
            f"默认分支：{str(context.get('default_branch', '')).strip()}",
            f"Topics：{', '.join(str(item).strip() for item in context.get('topics', []) if str(item).strip())}",
            f"README：{self._format_repo_readme_excerpt(context)}",
            f"根目录：{self._format_repo_root_entries(context)}",
            f"变更文件：{self._format_repo_changed_files(context)}",
            f"PR：{self._format_repo_pull_requests(context)}",
            f"Commit：{self._format_repo_commits(context)}",
        ]
        return "\n".join(part for part in parts if part and not part.endswith(": "))

    def _build_repo_summary_text(self, context: Dict[str, object]) -> str:
        repository = str(context.get("repository", "unknown/unknown")).strip() or "unknown/unknown"
        description = str(context.get("description", "") or "").strip()
        default_branch = str(context.get("default_branch", "") or "").strip() or "unknown"
        root_entries = self._format_repo_root_entries(context)
        if description:
            return f"{repository} 的默认分支是 {default_branch}，仓库描述为：{description}。根目录结构包括：{root_entries}。"
        return f"{repository} 的默认分支是 {default_branch}。根目录结构包括：{root_entries}。"

    def _format_repo_readme_excerpt(self, context: Dict[str, object]) -> str:
        readme_excerpt = str(context.get("readme_excerpt", "") or "").strip()
        return readme_excerpt or "当前未获取到 README 摘要。"

    def _format_repo_root_entries(self, context: Dict[str, object], limit: int = 20) -> str:
        entries = context.get("root_entries", [])
        if not isinstance(entries, list) or not entries:
            return "- 当前未获取到仓库根目录结构"
        safe_limit = max(1, min(int(limit or 20), 20))
        return "\n".join(f"- {str(item).strip()}" for item in entries[:safe_limit] if str(item).strip()) or "- 当前未获取到仓库根目录结构"

    def _format_repo_changed_files(self, context: Dict[str, object]) -> str:
        changed_files = context.get("changed_files", [])
        if not isinstance(changed_files, list) or not changed_files:
            return "- 当前未获取到最近变更文件"
        lines: List[str] = []
        for item in changed_files[:8]:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", "")).strip()
            if not filename:
                continue
            line = (
                f"- {filename} | {str(item.get('status', '')).strip()} | "
                f"+{self._to_int(item.get('additions'))} / -{self._to_int(item.get('deletions'))}"
            )
            patch_excerpt = str(item.get("patch_excerpt", "") or "").strip()
            if patch_excerpt:
                line += f" | patch: {patch_excerpt}"
            lines.append(line)
        return "\n".join(lines) or "- 当前未获取到最近变更文件"

    def _format_repo_pull_requests(self, context: Dict[str, object]) -> str:
        pull_requests = context.get("recent_pull_requests", [])
        if not isinstance(pull_requests, list) or not pull_requests:
            return "- 当前未获取到最近 PR"
        lines: List[str] = []
        for item in pull_requests[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- PR #{self._to_int(item.get('number'))} {str(item.get('title', '')).strip()} "
                f"({str(item.get('user', '')).strip()})"
            )
        return "\n".join(lines) or "- 当前未获取到最近 PR"

    def _format_repo_commits(self, context: Dict[str, object]) -> str:
        commits = context.get("recent_commits", [])
        if not isinstance(commits, list) or not commits:
            return "- 当前未获取到最近 Commit"
        lines: List[str] = []
        for item in commits[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('sha', '')).strip()[:7]} {str(item.get('author', '')).strip()}: "
                f"{str(item.get('message', '')).strip()}"
            )
        return "\n".join(lines) or "- 当前未获取到最近 Commit"

    def _to_int(self, value: object, default: int = 0) -> int:
        try:
            return default if value is None else int(value)
        except (TypeError, ValueError):
            return default

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
