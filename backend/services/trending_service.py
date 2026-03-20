from __future__ import annotations

import logging
from hashlib import sha1
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse

from backend.clients.llm_client import LLMClient
from backend.clients.trending_client import fetch_trending_repositories
from backend.models.schemas import TrendingItem
from backend.repositories.json_repository import save_json
from backend.repositories.paths import ANALYSIS_DATA_DIR
from backend.repositories.subscription_repository import SubscriptionRepository
from backend.repositories.trending_repository import TrendingRepository
from backend.security import SecurityValidationError, normalize_github_repo_url, normalize_repo_full_name, sanitize_untrusted_text
from backend.services.concurrency_guard import ConcurrencyGuard
from backend.services.runtime_config_utils import build_llm_config_overrides


LOGGER = logging.getLogger(__name__)


class TrendingService:
    """Page1 trending service: fetch, normalize, persist, and enrich summaries."""

    def __init__(
        self,
        repository: Optional[TrendingRepository] = None,
        subscription_repository: Optional[SubscriptionRepository] = None,
        llm_client: Optional[LLMClient] = None,
        concurrency_guard: Optional[ConcurrencyGuard] = None,
    ) -> None:
        self.repository = repository or TrendingRepository()
        self.subscription_repository = subscription_repository or SubscriptionRepository()
        self.llm_client = llm_client or LLMClient()
        self.concurrency_guard = concurrency_guard or ConcurrencyGuard()
        self.detail_summary_cache: Dict[str, str] = {}

    def get_weekly_trending(self) -> List[Dict[str, object]]:
        today = datetime.now().strftime("%Y-%m-%d")
        if not self.repository.has_daily_records(today):
            try:
                repos = fetch_trending_repositories()
            except Exception as exc:
                LOGGER.warning("fetch trending failed, fallback to empty list: %s", exc)
                repos = []

            self.repository.save_trending_repositories(repos, today)
            LOGGER.info("trending repositories fetched and stored: date=%s count=%s", today, len(repos))

        raw_records = self.repository.list_weekly_records()
        adapted = [self._adapt_trending_item(item) for item in raw_records]
        return [TrendingItem.model_validate(item).model_dump() for item in adapted]

    def generate_analysis(self) -> Dict[str, object]:
        lock_key = f"trending:generate-analysis:{datetime.now().strftime('%Y-%m-%d')}"
        with self.concurrency_guard.acquire(lock_key=lock_key, ttl_seconds=120, wait_timeout_seconds=12.0):
            adapted_data = self.get_weekly_trending()
            analysis_data = [self._attach_project_summary(item) for item in adapted_data]

            filename = f"{datetime.now().strftime('%Y-%m-%d')}.json"
            file_path = ANALYSIS_DATA_DIR / filename
            save_json(analysis_data, file_path)
            LOGGER.info("trending analysis generated: %s", file_path.name)

            return {
                "message": f"analysis generated: {file_path.name}",
                "file_path": str(file_path),
                "data": analysis_data,
            }

    def generate_detail_summary(self, item: Dict[str, object], user_id: Optional[int] = None) -> Dict[str, object]:
        normalized = self._adapt_trending_item(item)
        repo_full_name = str(normalized.get("repo_full_name", "unknown/unknown")).strip() or "unknown/unknown"
        cache_key = self._build_detail_summary_cache_key(normalized, user_id=user_id)

        cached_summary = self.detail_summary_cache.get(cache_key)
        if cached_summary:
            return {"repo_full_name": repo_full_name, "summary": cached_summary, "source": "llm"}

        summary = self._get_llm_client(user_id=user_id).summarize_trending_project(normalized).strip()
        if summary:
            self._store_detail_summary_cache(cache_key, summary)
            return {"repo_full_name": repo_full_name, "summary": summary, "source": "llm"}

        return {
            "repo_full_name": repo_full_name,
            "summary": self._build_rule_based_project_detail_summary(normalized),
            "source": "rules",
        }

    def _attach_project_summary(self, item: Dict[str, object]) -> Dict[str, object]:
        return {**item, "project_summary": self._build_rule_based_project_summary(item)}

    def _get_llm_client(self, user_id: Optional[int] = None) -> LLMClient:
        if user_id is not None:
            raw_config = self.subscription_repository.get_runtime_configs(user_id=user_id)
            if raw_config:
                return LLMClient(
                    config_overrides=build_llm_config_overrides(raw_config),
                    use_env_overrides=False,
                )
        return self.llm_client

    def _build_detail_summary_cache_key(self, item: Dict[str, object], user_id: Optional[int]) -> str:
        trend = item.get("trend_7d", [])
        if not isinstance(trend, list):
            trend = []

        fingerprint = "|".join(
            [
                str(user_id or 0),
                str(item.get("repo_full_name", "")).strip(),
                str(item.get("description", "")).strip(),
                str(item.get("language", "")).strip(),
                str(self._to_int(item.get("stars_total"))),
                ",".join(str(self._to_int(value)) for value in trend[:7]),
                str(item.get("link", "")).strip(),
            ]
        )
        return sha1(fingerprint.encode("utf-8")).hexdigest()

    def _store_detail_summary_cache(self, cache_key: str, summary: str) -> None:
        if cache_key in self.detail_summary_cache:
            self.detail_summary_cache[cache_key] = summary
            return
        if len(self.detail_summary_cache) >= 128:
            self.detail_summary_cache.pop(next(iter(self.detail_summary_cache)))
        self.detail_summary_cache[cache_key] = summary

    def _adapt_trending_item(self, item: Dict[str, object]) -> Dict[str, object]:
        stars_total = self._to_int(item.get("stars_total"))
        trend_7d = self._build_trend_series(stars_total)
        description = self._to_description(item.get("description"), item.get("project_summary"))
        repo_full_name = self._resolve_repo_full_name(item)

        return {
            **item,
            "repo_full_name": repo_full_name,
            "description": description,
            "stars_total": stars_total,
            "trend_7d": trend_7d,
        }

    def _to_int(self, value: object) -> int:
        try:
            return int(value) if value is not None else 0
        except (TypeError, ValueError):
            return 0

    def _build_trend_series(self, stars_total: int) -> List[int]:
        if stars_total <= 0:
            return [0, 0, 0, 0, 0, 0, 0]

        baseline = max(stars_total - max(stars_total // 10, 6), 0)
        step = (stars_total - baseline) / 6
        series = [int(round(baseline + step * index)) for index in range(7)]
        series[-1] = stars_total
        return series

    def _to_description(self, description: Optional[object], project_summary: Optional[object]) -> str:
        for value in (description, project_summary):
            if isinstance(value, str) and value.strip():
                return sanitize_untrusted_text(value, max_length=500, allow_empty=True)
        return ""

    def _resolve_repo_full_name(self, item: Dict[str, object]) -> str:
        author = item.get("author")
        name = item.get("name")
        if isinstance(author, str) and isinstance(name, str) and author and name:
            try:
                return normalize_repo_full_name(f"{author}/{name}")
            except SecurityValidationError:
                pass

        link = item.get("link")
        if isinstance(link, str) and link:
            try:
                parsed = urlparse(normalize_github_repo_url(link))
            except SecurityValidationError:
                return "unknown/unknown"
            parts = [part for part in parsed.path.strip("/").split("/") if part]
            if len(parts) >= 2:
                try:
                    return normalize_repo_full_name(f"{parts[0]}/{parts[1].replace('.git', '')}")
                except SecurityValidationError:
                    return "unknown/unknown"
        return "unknown/unknown"

    def _build_rule_based_project_summary(self, item: Dict[str, object]) -> str:
        description = str(item.get("description", "")).strip()
        repo_full_name = str(item.get("repo_full_name", "unknown/unknown")).strip() or "unknown/unknown"
        stars_total = self._to_int(item.get("stars_total"))
        language = str(item.get("language", "")).strip()

        if description and language:
            return f"{repo_full_name} 是一个 {language} 项目。{description} 当前累计星标 {stars_total}，值得继续关注后续走势。"
        if description:
            return f"{repo_full_name}：{description} 当前累计星标 {stars_total}。"
        return f"{repo_full_name} 是一个值得持续关注的开源项目，当前累计星标 {stars_total}。"

    def _build_rule_based_project_detail_summary(self, item: Dict[str, object]) -> str:
        repo_full_name = str(item.get("repo_full_name", "unknown/unknown")).strip() or "unknown/unknown"
        description = str(item.get("description", "")).strip()
        language = str(item.get("language", "")).strip()
        stars_total = self._to_int(item.get("stars_total"))
        trend = item.get("trend_7d", [])
        if not isinstance(trend, list):
            trend = []

        start_value = self._to_int(trend[0]) if trend else stars_total
        end_value = self._to_int(trend[-1]) if trend else stars_total
        delta = end_value - start_value

        paragraph_one = (
            f"{repo_full_name} 是一个{language or '近期上榜的'}开源项目。"
            f"{description or '当前公开信息有限，但从本周热度表现看，它处在持续被关注的区间。'}"
        )
        paragraph_two = (
            f"近 7 日星标从 {start_value} 变化到 {end_value}，净变化 "
            f"{'+' if delta >= 0 else ''}{delta}，当前累计星标 {stars_total}。"
            "后续更适合继续观察它的真实应用场景、版本迭代节奏，以及是否出现新的生态协同信号。"
        )
        return f"{paragraph_one}\n\n{paragraph_two}"
