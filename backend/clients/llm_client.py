from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from hashlib import sha1
from pathlib import Path
from typing import Dict, List, Optional

from backend.clients.github_client import fetch_repo_question_context
from backend.prompts import get_prompt, render_prompt
from backend.repositories.llm_evaluation_repository import LLMEvaluationRepository
from backend.repositories.paths import COMMIT_DATA_DIR
from backend.security import fingerprint_secret


LOGGER = logging.getLogger(__name__)
REPORT_QA_CONTEXT_CACHE_TTL_SECONDS = 300
REPORT_QA_RESULT_CACHE_TTL_SECONDS = 300
REPORT_QA_RESULT_CACHE_MAX_ENTRIES = 64
OPENAI_CLIENT_CACHE_MAX_ENTRIES = 8
DEFAULT_LLM_REQUEST_MIN_INTERVAL_SECONDS = 1.2
DEFAULT_LLM_RATE_LIMIT_COOLDOWN_SECONDS = 8.0
DEFAULT_LLM_RATE_LIMIT_RETRIES = 2
LEGACY_LLM_MODEL_ALIASES = {
    "glm-4.5-flash": "glm-4-flash",
}


class LLMClient:
    _rate_limit_lock = threading.Lock()
    _next_request_at_by_key: Dict[str, float] = {}
    """晨报生成客户端：摘要走规则，问答优先走模型。"""

    def __init__(
        self,
        evaluation_repository: Optional[LLMEvaluationRepository] = None,
        config_overrides: Optional[Dict[str, object]] = None,
        commit_data_dir: Optional[Path] = None,
        use_env_overrides: bool = True,
    ) -> None:
        self.config_overrides = dict(config_overrides or {})
        self.commit_data_dir = commit_data_dir or COMMIT_DATA_DIR
        self.use_env_overrides = use_env_overrides
        self.config = self._load_generator_config()
        self.evaluation_repository = evaluation_repository or LLMEvaluationRepository()
        self._repo_context_cache: Dict[str, Dict[str, object]] = {}
        self._repo_context_cache_expire_at: Dict[str, float] = {}
        self._report_qa_cache: Dict[str, Dict[str, object]] = {}
        self._report_qa_cache_lock = threading.Lock()
        self._openai_client_cache: Dict[str, object] = {}
        self._openai_client_cache_lock = threading.Lock()

    def generate_report(self, repo_name: Optional[str] = None) -> Dict[str, object]:
        snapshot = self._load_latest_snapshot(repo_name=repo_name)
        if not snapshot:
            return self._build_missing_snapshot_report(repo_name)

        stats = self._build_stats(snapshot)
        summary = self._build_summary(stats)
        todo_list = self._build_todo_list(stats)

        return {
            "repository": stats["repository"],
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "time_range": self._build_time_range(stats),
            "stats": {
                "pr_count": stats["pr_count"],
                "commit_count": stats["commit_count"],
            },
            "summary": summary,
            "todo_list": todo_list,
            "details": {
                "top_prs": stats["pr_details"],
                "top_commits": stats["commit_details"],
            },
        }

    def _load_generator_config(self) -> Dict[str, object]:
        config_path = Path(__file__).resolve().parent.parent / "config" / "generator.json"
        if not config_path.exists():
            return {}
        try:
            with config_path.open("r", encoding="utf-8") as file:
                config = json.load(file)
        except Exception:
            return {}

        provider = config.get("provider")
        provider_config = config.get(provider, {}) if isinstance(provider, str) else {}
        resolved: Dict[str, object] = dict(provider_config) if isinstance(provider_config, dict) else {}
        resolved["provider"] = provider

        if self.use_env_overrides:
            if os.getenv("NIGHTSHIFT_GENERATOR_API_KEY"):
                resolved["api_key"] = os.getenv("NIGHTSHIFT_GENERATOR_API_KEY")
            if os.getenv("NIGHTSHIFT_GENERATOR_BASE_URL"):
                resolved["base_url"] = os.getenv("NIGHTSHIFT_GENERATOR_BASE_URL")
            if os.getenv("NIGHTSHIFT_GENERATOR_MODEL"):
                resolved["model"] = os.getenv("NIGHTSHIFT_GENERATOR_MODEL")
            if os.getenv("NIGHTSHIFT_GENERATOR_TEMPERATURE"):
                resolved["temperature"] = self._safe_float(os.getenv("NIGHTSHIFT_GENERATOR_TEMPERATURE"), 0.7)
            if os.getenv("NIGHTSHIFT_GENERATOR_TOP_P"):
                resolved["top_p"] = self._safe_float(os.getenv("NIGHTSHIFT_GENERATOR_TOP_P"), 1.0)
            if os.getenv("NIGHTSHIFT_GENERATOR_MAX_TOKENS"):
                resolved["max_tokens"] = self._safe_int(os.getenv("NIGHTSHIFT_GENERATOR_MAX_TOKENS"), 2000)
            if os.getenv("NIGHTSHIFT_GENERATOR_TIMEOUT_SECONDS"):
                resolved["timeout_seconds"] = self._safe_float(os.getenv("NIGHTSHIFT_GENERATOR_TIMEOUT_SECONDS"), 25.0)
            if os.getenv("NIGHTSHIFT_GENERATOR_MAX_RETRIES"):
                resolved["max_retries"] = self._safe_int(os.getenv("NIGHTSHIFT_GENERATOR_MAX_RETRIES"), 1)
        for key, value in self.config_overrides.items():
            resolved[key] = value
        resolved["model"] = self._normalize_llm_model_name(resolved.get("model"))
        return resolved

    def _resolve_call_config(self, prompt_name: str) -> Dict[str, object]:
        config = dict(self._load_generator_config())

        if prompt_name == "email_digest_v1":
            config["temperature"] = min(max(self._safe_float(config.get("temperature"), 0.55), 0.45), 0.75)
            config["top_p"] = min(max(self._safe_float(config.get("top_p"), 0.9), 0.85), 1.0)
            config["max_tokens"] = min(self._safe_int(config.get("max_tokens"), 360), 360)
            config["timeout_seconds"] = min(self._safe_float(config.get("timeout_seconds"), 18.0), 18.0)
            config["max_retries"] = min(self._safe_int(config.get("max_retries"), 1), 1)

        if prompt_name == "trending_detail_summary_v2":
            config["temperature"] = min(max(self._safe_float(config.get("temperature"), 0.82), 0.72), 0.9)
            config["top_p"] = min(max(self._safe_float(config.get("top_p"), 0.92), 0.88), 1.0)
            config["max_tokens"] = min(self._safe_int(config.get("max_tokens"), 320), 320)
            config["timeout_seconds"] = min(self._safe_float(config.get("timeout_seconds"), 14.0), 14.0)
            config["max_retries"] = 0

        return config

    def _load_latest_snapshot(self, repo_name: Optional[str]) -> Optional[Dict[str, object]]:
        if not self.commit_data_dir.exists():
            return None
        json_files = sorted(self.commit_data_dir.glob("*.json"), reverse=True)
        for file_path in json_files:
            try:
                with file_path.open("r", encoding="utf-8") as file:
                    data = json.load(file)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            repository = str(data.get("repository", "")).lower()
            if repo_name and repository != repo_name.lower():
                continue
            return data
        return None

    def _build_missing_snapshot_report(self, repo_name: Optional[str]) -> Dict[str, object]:
        repository = repo_name or "unknown"
        return {
            "repository": repository,
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "time_range": "latest commit diff unavailable",
            "stats": {"pr_count": 0, "commit_count": 0},
            "summary": (
                f"仓库 {repository} 暂未读取到可分析的提交快照，本次晨报未能完成最近两次提交差异分析。"
                "建议先检查仓库地址、访问权限或 GITHUB_TOKEN 配置。"
            ),
            "todo_list": [
                "[HIGH] 检查仓库地址、访问权限和 GITHUB_TOKEN，恢复最近两次提交的可读快照",
            ],
            "details": {"top_prs": [], "top_commits": []},
        }

    def _build_stats(self, snapshot: Dict[str, object]) -> Dict[str, object]:
        commits = snapshot.get("commits", [])
        if not isinstance(commits, list):
            commits = []

        pull_requests = snapshot.get("pull_requests", [])
        if not isinstance(pull_requests, list):
            pull_requests = []

        latest_commit = snapshot.get("latest_commit")
        previous_commit = snapshot.get("previous_commit")
        comparison = snapshot.get("comparison")

        if not isinstance(latest_commit, dict):
            latest_commit = commits[0] if commits and isinstance(commits[0], dict) else {}
        if not isinstance(previous_commit, dict):
            previous_commit = commits[1] if len(commits) > 1 and isinstance(commits[1], dict) else {}
        if not isinstance(comparison, dict):
            comparison = {}

        changed_files = []
        for item in comparison.get("changed_files", []) if isinstance(comparison.get("changed_files"), list) else []:
            if not isinstance(item, dict):
                continue
            changed_files.append(
                {
                    "filename": str(item.get("filename", "")),
                    "status": str(item.get("status", "")),
                    "additions": self._safe_int(item.get("additions"), 0),
                    "deletions": self._safe_int(item.get("deletions"), 0),
                    "changes": self._safe_int(item.get("changes"), 0),
                }
            )

        commit_details: List[Dict[str, object]] = []
        seen_shas = set()
        for commit in (latest_commit, previous_commit):
            if not isinstance(commit, dict):
                continue
            sha = str(commit.get("sha", "")).strip()
            if not sha or sha in seen_shas:
                continue
            seen_shas.add(sha)
            commit_details.append(
                {
                    "sha": sha[:7],
                    "author": str(commit.get("author", "")),
                    "message": str(commit.get("message", "")),
                }
            )

        pr_details_all: List[Dict[str, object]] = []
        seen_pr_numbers = set()
        for item in pull_requests:
            if not isinstance(item, dict):
                continue
            number = self._safe_int(item.get("number"), 0)
            if number <= 0 or number in seen_pr_numbers:
                continue
            seen_pr_numbers.add(number)
            pr_details_all.append(
                {
                    "number": number,
                    "title": str(item.get("title", "")).strip(),
                    "user": str(item.get("user", "")).strip(),
                    "files_count": self._safe_int(item.get("files_count"), 0),
                }
            )

        return {
            "analysis_mode": str(snapshot.get("analysis_mode", "latest-commit-diff")),
            "repository": str(snapshot.get("repository", "unknown")),
            "fetch_time_utc": str(snapshot.get("fetch_time_utc", "")),
            "latest_commit": latest_commit if isinstance(latest_commit, dict) else {},
            "previous_commit": previous_commit if isinstance(previous_commit, dict) else {},
            "comparison": comparison,
            "changed_files": changed_files,
            "files_changed_count": self._safe_int(comparison.get("files_changed"), len(changed_files)),
            "additions": self._safe_int(comparison.get("additions"), 0),
            "deletions": self._safe_int(comparison.get("deletions"), 0),
            "pr_count": len(pr_details_all),
            "pr_details": pr_details_all[:5],
            "commit_count": len(commit_details),
            "commit_details": commit_details,
        }

    def _build_time_range(self, stats: Dict[str, object]) -> str:
        latest_sha = self._short_sha(stats.get("latest_commit"))
        previous_sha = self._short_sha(stats.get("previous_commit"))
        if latest_sha and previous_sha:
            return f"commit diff {previous_sha} -> {latest_sha}"
        if latest_sha:
            return f"latest commit {latest_sha}"
        return "latest commit diff unavailable"

    def _build_summary(self, stats: Dict[str, object]) -> str:
        repository = str(stats.get("repository", "unknown"))
        latest_commit = stats.get("latest_commit", {})
        previous_commit = stats.get("previous_commit", {})
        if not isinstance(latest_commit, dict) or not latest_commit.get("sha"):
            return (
                f"仓库 {repository} 暂未读取到可分析的提交快照，本次晨报未能完成最近两次提交差异分析。"
                "建议先检查仓库地址、访问权限或 GITHUB_TOKEN 配置。"
            )
        if not isinstance(previous_commit, dict) or not previous_commit.get("sha"):
            return (
                f"仓库 {repository} 只拿到最近一次提交 {self._short_sha(latest_commit)}，缺少上一提交作为基线，"
                "本次晨报未能完成差异分析。建议补齐仓库访问权限后重试。"
            )

        files_changed = self._safe_int(stats.get("files_changed_count"), 0)
        additions = self._safe_int(stats.get("additions"), 0)
        deletions = self._safe_int(stats.get("deletions"), 0)
        top_files = self._format_top_files(stats)
        latest_message = str(latest_commit.get("message", "")).strip() or "无提交说明"
        latest_author = str(latest_commit.get("author", "")).strip() or "unknown"

        if files_changed <= 0 and additions == 0 and deletions == 0:
            return (
                f"仓库 {repository} 已定位到最近两次提交 {self._short_sha(previous_commit)} -> {self._short_sha(latest_commit)}，"
                "但还没有拿到可靠的文件级差异明细，本次晨报暂无法给出有效分析结论。"
                f"最近一次提交为“{latest_message}”，建议先补齐 compare 结果后再继续分析。"
            )

        risk_label = self._estimate_risk_label(stats)
        return (
            f"仓库 {repository} 本次晨报基于最近两次提交差异生成："
            f"{self._short_sha(previous_commit)} -> {self._short_sha(latest_commit)} 共变更 {files_changed} 个文件，"
            f"新增 {additions} 行、删除 {deletions} 行。最近一次提交“{latest_message}”由 {latest_author} 提交，"
            f"当前判断为{risk_label}风险，优先复核 {top_files}。"
        )

    def _build_todo_list(self, stats: Dict[str, object]) -> List[str]:
        repository = str(stats.get("repository", "unknown"))
        latest_commit = stats.get("latest_commit", {})
        previous_commit = stats.get("previous_commit", {})
        if not isinstance(latest_commit, dict) or not latest_commit.get("sha"):
            return [
                "[HIGH] 检查仓库地址、访问权限和 GITHUB_TOKEN，恢复最近两次提交的可读快照",
            ]
        if not isinstance(previous_commit, dict) or not previous_commit.get("sha"):
            return [
                f"[HIGH] 补齐仓库 {repository} 的上一提交基线，恢复最近两次提交差异分析",
                "[LOW] 更新交接记录，注明当前只拿到单次提交，暂不输出项目结论",
            ]

        files_changed = self._safe_int(stats.get("files_changed_count"), 0)
        additions = self._safe_int(stats.get("additions"), 0)
        deletions = self._safe_int(stats.get("deletions"), 0)
        latest_sha = self._short_sha(latest_commit)
        top_files = self._format_top_files(stats)
        critical_files = self._pick_critical_files(stats)

        if files_changed <= 0 and additions == 0 and deletions == 0:
            return [
                f"[HIGH] 重新拉取提交 {self._short_sha(previous_commit)} -> {latest_sha} 的 compare 结果，补齐文件级差异",
                f"[MEDIUM] 复核最近一次提交 {latest_sha} 的提交说明与实际影响范围",
                "[LOW] 更新交接记录，说明本次晨报因差异明细缺失而分析未完成",
            ]

        risk_label = self._estimate_risk_label(stats)
        lead_priority = "[HIGH]" if risk_label == "高" else "[MEDIUM]"
        todos = [
            f"{lead_priority} 复核最近提交 {latest_sha} 对 {top_files} 的直接影响",
            f"[MEDIUM] 回归验证本次差异涉及的 {files_changed} 个文件及相关调用链",
        ]
        if critical_files:
            todos.append(f"[HIGH] 检查关键配置或发布文件 {critical_files} 是否引入部署或依赖变更")
        todos.append("[LOW] 更新交接记录，补充差异结论、验证结果和后续观察点")
        return todos[:5]

    def _estimate_risk_label(self, stats: Dict[str, object]) -> str:
        files_changed = self._safe_int(stats.get("files_changed_count"), 0)
        churn = self._safe_int(stats.get("additions"), 0) + self._safe_int(stats.get("deletions"), 0)
        critical_files = self._pick_critical_file_names(stats)
        pr_count = self._safe_int(stats.get("pr_count"), 0)
        pr_files_changed = max(
            [self._safe_int(item.get("files_count"), 0) for item in stats.get("pr_details", []) if isinstance(item, dict)] or [0]
        )

        score = 0
        if files_changed >= 10:
            score += 2
        elif files_changed >= 5:
            score += 1

        if churn >= 400:
            score += 2
        elif churn >= 120:
            score += 1

        if critical_files:
            score += 2

        if pr_count >= 3:
            score += 1

        if pr_files_changed >= 8:
            score += 1

        if score >= 4:
            return "高"
        if score >= 2:
            return "中"
        return "低"

    def _pick_critical_file_names(self, stats: Dict[str, object]) -> List[str]:
        keywords = (
            "dockerfile",
            "package.json",
            "requirements",
            "pom.xml",
            "build.gradle",
            "go.mod",
            ".github/",
            "deploy",
            "infra",
            "config",
            "settings",
            "migration",
            "schema",
            "workflow",
        )
        result = []
        for item in stats.get("changed_files", []):
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", "")).strip()
            lowered = filename.lower()
            if filename and any(keyword in lowered for keyword in keywords):
                result.append(filename)
        return result[:3]

    def _pick_critical_files(self, stats: Dict[str, object]) -> str:
        files = self._pick_critical_file_names(stats)
        return "、".join(files)

    def _format_top_files(self, stats: Dict[str, object]) -> str:
        files = []
        for item in stats.get("changed_files", []):
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", "")).strip()
            if filename:
                files.append(filename)
        if not files:
            return "最近一次提交影响范围"
        return "、".join(files[:3])

    def _format_report_todos(self, report: Dict[str, object]) -> str:
        items = report.get("todo_list", [])
        if not isinstance(items, list) or not items:
            return "- 无"
        return "\n".join(f"- {str(item).strip()}" for item in items[:5] if str(item).strip()) or "- 无"

    def _format_report_prs(self, report: Dict[str, object]) -> str:
        handover = report.get("sections", {}) if isinstance(report.get("sections"), dict) else {}
        records = handover.get("handover_records", {}) if isinstance(handover.get("handover_records"), dict) else {}
        top_prs = records.get("top_prs", [])
        if not isinstance(top_prs, list) or not top_prs:
            return "- 无"
        lines: List[str] = []
        for item in top_prs[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- PR #{self._safe_int(item.get('number'), 0)} {str(item.get('title', '')).strip()} ({str(item.get('user', '')).strip()})"
            )
        return "\n".join(lines) or "- 无"

    def _format_report_commits(self, report: Dict[str, object]) -> str:
        handover = report.get("sections", {}) if isinstance(report.get("sections"), dict) else {}
        records = handover.get("handover_records", {}) if isinstance(handover.get("handover_records"), dict) else {}
        top_commits = records.get("top_commits", [])
        if not isinstance(top_commits, list) or not top_commits:
            return "- 无"
        lines: List[str] = []
        for item in top_commits[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('sha', '')).strip()} {str(item.get('author', '')).strip()}: {str(item.get('message', '')).strip()}"
            )
        return "\n".join(lines) or "- 无"

    def _fetch_report_repo_context(self, token: Optional[str], repo_url: Optional[str]) -> Dict[str, object]:
        normalized_repo_url = str(repo_url or "").strip()
        if not normalized_repo_url:
            return {}
        auth_scope = fingerprint_secret(token)
        cache_key = f"{auth_scope}:{str(self.commit_data_dir).lower()}:{normalized_repo_url.lower()}"
        expires_at = self._repo_context_cache_expire_at.get(cache_key, 0.0)
        if expires_at > time.time():
            cached = self._repo_context_cache.get(cache_key, {})
            return dict(cached) if isinstance(cached, dict) else {}
        try:
            context = fetch_repo_question_context(
                token=token,
                repo_url=normalized_repo_url,
                commit_data_dir=self.commit_data_dir,
            )
            self._repo_context_cache[cache_key] = context
            self._repo_context_cache_expire_at[cache_key] = time.time() + REPORT_QA_CONTEXT_CACHE_TTL_SECONDS
            return dict(context)
        except Exception as exc:
            LOGGER.warning("failed to fetch repo QA context: repo=%s error=%s", normalized_repo_url, exc)
            return {}

    def _format_repo_topics(self, repo_context: Dict[str, object]) -> str:
        topics = repo_context.get("topics", [])
        if not isinstance(topics, list) or not topics:
            return "- 当前未获取到 topics"
        return "\n".join(f"- {str(item).strip()}" for item in topics[:6] if str(item).strip()) or "- 当前未获取到 topics"

    def _format_repo_root_entries(self, repo_context: Dict[str, object]) -> str:
        entries = repo_context.get("root_entries", [])
        if not isinstance(entries, list) or not entries:
            return "- 当前未获取到仓库根目录结构"
        return "\n".join(f"- {str(item).strip()}" for item in entries[:12] if str(item).strip()) or "- 当前未获取到仓库根目录结构"

    def _format_repo_readme_excerpt(self, repo_context: Dict[str, object]) -> str:
        readme_excerpt = str(repo_context.get("readme_excerpt", "") or "").strip()
        return readme_excerpt or "当前未获取到 README 摘要。"

    def _format_repo_changed_files(self, repo_context: Dict[str, object]) -> str:
        changed_files = repo_context.get("changed_files", [])
        if not isinstance(changed_files, list) or not changed_files:
            return "- 当前未获取到最近变更文件"
        lines: List[str] = []
        for item in changed_files[:8]:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename", "")).strip()
            if not filename:
                continue
            summary = (
                f"- {filename} | {str(item.get('status', '')).strip()} | "
                f"+{self._safe_int(item.get('additions'), 0)} / -{self._safe_int(item.get('deletions'), 0)}"
            )
            patch_excerpt = str(item.get("patch_excerpt", "") or "").strip()
            if patch_excerpt:
                summary += f" | patch: {patch_excerpt}"
            lines.append(summary)
        return "\n".join(lines) or "- 当前未获取到最近变更文件"

    def _format_repo_pull_requests(self, repo_context: Dict[str, object]) -> str:
        pull_requests = repo_context.get("recent_pull_requests", [])
        if not isinstance(pull_requests, list) or not pull_requests:
            return "- 当前未获取到最近 PR"
        lines: List[str] = []
        for item in pull_requests[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- PR #{self._safe_int(item.get('number'), 0)} {str(item.get('title', '')).strip()} "
                f"({str(item.get('user', '')).strip()})"
            )
        return "\n".join(lines) or "- 当前未获取到最近 PR"

    def _format_repo_commits(self, repo_context: Dict[str, object]) -> str:
        commits = repo_context.get("recent_commits", [])
        if not isinstance(commits, list) or not commits:
            return "- 当前未获取到最近提交"
        lines: List[str] = []
        for item in commits[:5]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {str(item.get('sha', '')).strip()[:7]} {str(item.get('author', '')).strip()}: "
                f"{str(item.get('message', '')).strip()}"
            )
        return "\n".join(lines) or "- 当前未获取到最近提交"

    def _build_trending_detail_paragraphs(self, project: Dict[str, object]) -> List[str]:
        repo_full_name = str(project.get("repo_full_name", "unknown/unknown") or "unknown/unknown").strip()
        description = str(project.get("description", "") or "").strip()
        language = str(project.get("language", "") or "").strip()
        stars_total = self._safe_int(project.get("stars_total"), 0)
        trend = project.get("trend_7d", [])
        if not isinstance(trend, list):
            trend = []
        start_value = self._safe_int(trend[0], stars_total) if trend else stars_total
        end_value = self._safe_int(trend[-1], stars_total) if trend else stars_total
        delta = end_value - start_value

        paragraph_one = (
            f"{repo_full_name} 是一个{language or '近期上榜的'}开源项目。"
            f"{description or '当前公开描述有限，但从榜单表现看，它具备持续被关注的基础。'}"
        )
        paragraph_two = (
            f"近 7 日星标从 {start_value} 变化到 {end_value}，净变化 "
            f"{'+' if delta >= 0 else ''}{delta}，当前累计星标 {stars_total}。"
            "后续更适合继续观察它的真实使用场景、版本节奏，以及是否出现新的集成或生态信号。"
        )
        return [paragraph_one.strip(), paragraph_two.strip()]

    def _normalize_trending_detail_summary(self, summary: str, project: Dict[str, object]) -> str:
        paragraphs = [item.strip() for item in str(summary or "").replace("\r\n", "\n").split("\n\n") if item.strip()]
        fallback = self._build_trending_detail_paragraphs(project)
        if len(paragraphs) >= 2:
            return "\n\n".join(paragraphs[:2])
        if len(paragraphs) == 1:
            return f"{paragraphs[0]}\n\n{fallback[1]}"
        return "\n\n".join(fallback)

    def answer_report_question(
        self,
        report: Dict[str, object],
        question: str,
        repo_url: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, str]:
        normalized_question = str(question or "").strip()
        if not normalized_question:
            return {"answer": "请输入要追问的问题。", "source": "rules"}

        prompt_name = "report_qa_v1"
        prompt = render_prompt(
            prompt_name,
            repository=str(report.get("repository", "unknown")),
            report_date=str(report.get("report_date", datetime.now().strftime("%Y-%m-%d"))),
            time_range=str(report.get("time_range", "latest commit diff unavailable")),
            summary_text=str(report.get("summary_text", "")).strip() or "当前晨报没有可用摘要。",
            todo_list=self._format_report_todos(report),
            top_prs=self._format_report_prs(report),
            top_commits=self._format_report_commits(report),
            question=normalized_question,
        )
        resolved_config = self._resolve_call_config(prompt_name)
        cache_key = self._build_report_qa_cache_key(
            prompt_name=prompt_name,
            prompt=prompt,
            config=resolved_config,
        )
        cached_answer = self._get_cached_report_qa_answer(cache_key)
        if cached_answer:
            return {"answer": cached_answer, "source": "llm"}

        answer = self._call_openai_compatible(
            prompt_name=prompt_name,
            prompt=prompt,
            resolved_config=resolved_config,
        )
        if answer:
            self._store_cached_report_qa_answer(cache_key=cache_key, answer=answer)
            return {"answer": answer, "source": "llm"}
        return {
            "answer": self._build_rule_based_report_answer(report, normalized_question),
            "source": "rules",
        }

    def answer_repo_context_question(
        self,
        repo_context: Dict[str, object],
        question: str,
    ) -> Dict[str, str]:
        normalized_question = str(question or "").strip()
        if not normalized_question:
            return {"answer": "请输入要追问的问题。", "source": "rules"}

        prompt_name = "repo_context_qa_v1"
        prompt = render_prompt(
            prompt_name,
            repository=str(repo_context.get("repository", "unknown")),
            repo_url=str(repo_context.get("repo_url", "")),
            repo_description=str(repo_context.get("description", "") or "当前未获取到仓库描述。"),
            default_branch=str(repo_context.get("default_branch", "") or "unknown"),
            repo_topics=self._format_repo_topics(repo_context),
            root_entries=self._format_repo_root_entries(repo_context),
            readme_excerpt=self._format_repo_readme_excerpt(repo_context),
            changed_files=self._format_repo_changed_files(repo_context),
            recent_repo_prs=self._format_repo_pull_requests(repo_context),
            recent_repo_commits=self._format_repo_commits(repo_context),
            question=normalized_question,
        )
        resolved_config = self._resolve_call_config(prompt_name)
        cache_key = self._build_report_qa_cache_key(
            prompt_name=prompt_name,
            prompt=prompt,
            config=resolved_config,
        )
        cached_answer = self._get_cached_report_qa_answer(cache_key)
        if cached_answer:
            return {"answer": cached_answer, "source": "llm"}

        answer = self._call_openai_compatible(
            prompt_name=prompt_name,
            prompt=prompt,
            resolved_config=resolved_config,
        )
        if answer:
            self._store_cached_report_qa_answer(cache_key=cache_key, answer=answer)
            return {"answer": answer, "source": "llm"}

        return {
            "answer": self._build_rule_based_repo_context_answer(repo_context, normalized_question),
            "source": "rules",
        }

    def summarize_trending_project(self, project: Dict[str, object]) -> str:
        prompt_name = "trending_detail_summary_v2"
        trend = project.get("trend_7d", [])
        if not isinstance(trend, list):
            trend = []

        prompt = render_prompt(
            prompt_name,
            repo_full_name=str(project.get("repo_full_name", "unknown/unknown")),
            description=str(project.get("description", "")).strip() or "无公开描述",
            language=str(project.get("language", "")).strip() or "unknown",
            stars_total=self._safe_int(project.get("stars_total"), 0),
            trend_7d=", ".join(str(self._safe_int(value, 0)) for value in trend[:7]) or "0, 0, 0, 0, 0, 0, 0",
            link=str(project.get("link", "")).strip() or "N/A",
        )
        return self._normalize_trending_detail_summary(
            self._call_openai_compatible(prompt_name=prompt_name, prompt=prompt).strip(),
            project,
        )

    def generate_email_digest(self, report: Dict[str, object]) -> str:
        prompt_name = "email_digest_v1"
        prompt = render_prompt(
            prompt_name,
            repository=str(report.get("repository", "unknown")),
            report_date=str(report.get("report_date", datetime.now().strftime("%Y-%m-%d"))),
            time_range=str(report.get("time_range", "latest commit diff unavailable")),
            summary_text=str(report.get("summary_text", "")).strip() or "当前可用信息有限。",
            todo_list=self._format_report_todos(report),
            top_prs=self._format_report_prs(report),
            top_commits=self._format_report_commits(report),
        )
        summary = self._call_openai_compatible(prompt_name=prompt_name, prompt=prompt).strip()
        return self._normalize_email_digest(summary=summary, report=report)

    def _normalize_email_digest(self, summary: str, report: Dict[str, object]) -> str:
        paragraphs = [item.strip() for item in str(summary or "").replace("\r\n", "\n").split("\n\n") if item.strip()]
        fallback = self._build_rule_based_email_digest_paragraphs(report)
        if len(paragraphs) >= 2:
            return "\n\n".join(paragraphs[:2])
        if len(paragraphs) == 1:
            return f"{paragraphs[0]}\n\n{fallback[1]}"
        return "\n\n".join(fallback)

    def _build_rule_based_email_digest_paragraphs(self, report: Dict[str, object]) -> List[str]:
        repository = str(report.get("repository", "unknown")).strip() or "unknown"
        time_range = str(report.get("time_range", "")).strip() or "latest commit diff unavailable"
        summary_text = str(report.get("summary_text", "")).strip() or "当前可用信息有限，尚未生成完整摘要。"
        todo_list = report.get("todo_list", [])
        todos = [str(item).strip() for item in todo_list if str(item).strip()] if isinstance(todo_list, list) else []
        top_commits = self._extract_top_commit_messages(report)

        first_paragraph = summary_text
        if top_commits:
            first_paragraph = f"{repository} 本次晨报覆盖 {time_range}。{summary_text} 主要变更包括：{top_commits}。"
        elif repository and time_range:
            first_paragraph = f"{repository} 本次晨报覆盖 {time_range}。{summary_text}"

        if todos:
            action_text = "；".join(todos[:3])
            second_paragraph = f"建议优先处理这些事项：{action_text}。如果需要继续跟进，可先从影响范围最大的变更点开始复核。"
        else:
            second_paragraph = "建议继续关注主要变更点的实际影响，并结合后续提交与相关 PR 观察风险是否扩大。"

        return [first_paragraph.strip(), second_paragraph.strip()]

    def _extract_top_commit_messages(self, report: Dict[str, object]) -> str:
        handover = report.get("sections", {}) if isinstance(report.get("sections"), dict) else {}
        records = handover.get("handover_records", {}) if isinstance(handover.get("handover_records"), dict) else {}
        top_commits = records.get("top_commits", []) if isinstance(records.get("top_commits"), list) else []
        messages = []
        for item in top_commits[:3]:
            if not isinstance(item, dict):
                continue
            message = str(item.get("message", "")).strip()
            if message:
                messages.append(message)
        return "；".join(messages)

    def _build_rule_based_report_answer(self, report: Dict[str, object], question: str) -> str:
        lowered = question.lower()
        repository = str(report.get("repository", "unknown"))
        time_range = str(report.get("time_range", "")).strip() or "latest commit diff unavailable"
        summary_text = str(report.get("summary_text", "")).strip() or "当前晨报没有足够信息。"

        todo_list = report.get("todo_list", [])
        todos = [str(item).strip() for item in todo_list if str(item).strip()] if isinstance(todo_list, list) else []

        sections = report.get("sections", {}) if isinstance(report.get("sections"), dict) else {}
        handover = sections.get("handover_records", {}) if isinstance(sections.get("handover_records"), dict) else {}
        top_prs = handover.get("top_prs", []) if isinstance(handover.get("top_prs"), list) else []
        top_commits = handover.get("top_commits", []) if isinstance(handover.get("top_commits"), list) else []

        if any(word in lowered for word in ("仓库", "项目", "repo", "repository")):
            return f"当前晨报对应仓库是 {repository}，分析范围是 {time_range}。{summary_text}"

        if any(word in lowered for word in ("风险", "结论", "总结", "概括", "summary")):
            return summary_text

        if any(word in lowered for word in ("待办", "下一步", "todo", "action")):
            if todos:
                return "当前建议优先处理这些动作：" + "；".join(todos[:3])
            return "当前晨报里没有待办项，说明这次快照没有产出需要继续跟进的动作。"

        if "pr" in lowered or "pull request" in lowered or "合并请求" in lowered:
            if top_prs:
                first = top_prs[0] if isinstance(top_prs[0], dict) else {}
                return (
                    f"当前晨报记录了 {len(top_prs)} 条重点 PR。"
                    f" 最靠前的是 PR #{self._safe_int(first.get('number'), 0)} {str(first.get('title', '')).strip()}。"
                )
            return "这次晨报没有记录重点 PR，当前分析主要基于最近两次提交差异。"

        if "commit" in lowered or "提交" in lowered or "diff" in lowered:
            if top_commits:
                first = top_commits[0] if isinstance(top_commits[0], dict) else {}
                second = top_commits[1] if len(top_commits) > 1 and isinstance(top_commits[1], dict) else {}
                if second:
                    return (
                        f"这次晨报主要比较 {str(second.get('sha', '')).strip()} -> {str(first.get('sha', '')).strip()}，"
                        f"最近一次提交是 {str(first.get('message', '')).strip()}。"
                    )
                return f"当前只记录到一次提交：{str(first.get('sha', '')).strip()} {str(first.get('message', '')).strip()}。"
            return "当前晨报没有拿到可展示的提交差异信息。"

        if todos:
            return f"{summary_text} 你可以继续追问待办、提交差异、重点文件或回归建议；当前优先动作包括：{'；'.join(todos[:2])}。"
        return f"{summary_text} 你可以继续追问提交差异、重点文件或下一步动作。"

    def _build_rule_based_repo_context_answer(self, repo_context: Dict[str, object], question: str) -> str:
        lowered = question.lower()
        repository = str(repo_context.get("repository", "unknown")).strip() or "unknown"
        description = str(repo_context.get("description", "") or "").strip()
        default_branch = str(repo_context.get("default_branch", "") or "").strip() or "unknown"
        root_entries = self._format_repo_root_entries(repo_context)
        changed_files = self._format_repo_changed_files(repo_context)
        recent_prs = self._format_repo_pull_requests(repo_context)
        recent_commits = self._format_repo_commits(repo_context)

        asks_recent = any(term in lowered for term in ["最近", "更新", "commit", "commits", "pr", "change", "changes"])
        asks_identity = any(term in lowered for term in ["是什么", "what", "用途", "项目", "readme"])

        if asks_recent and asks_identity:
            return (
                f"{repository} 的默认分支是 {default_branch}。"
                f"{description or '当前未获取到仓库描述。'}"
                f"最近可见变更文件包括：{changed_files}；最近 PR 包括：{recent_prs}；最近 Commit 包括：{recent_commits}。"
            )
        if asks_recent:
            return f"{repository} 最近可见变更文件包括：{changed_files}；最近 PR 包括：{recent_prs}；最近 Commit 包括：{recent_commits}。"
        if asks_identity:
            return f"{repository} 的默认分支是 {default_branch}。{description or '当前未获取到仓库描述。'} 根目录结构包括：{root_entries}。"
        return f"{repository} 当前可用上下文包括 README 摘要、根目录结构、最近变更文件、PR 和 Commit；请进一步说明要分析的方向。"

    def _call_openai_compatible(
        self,
        prompt_name: str,
        prompt: str,
        resolved_config: Optional[Dict[str, object]] = None,
    ) -> str:
        config = dict(resolved_config) if resolved_config is not None else self._resolve_call_config(prompt_name)
        self.config = config

        provider = str(config.get("provider", "") or "")
        api_key = str(config.get("api_key", "") or "")
        base_url = str(config.get("base_url", "") or "")
        model = str(config.get("model", "") or "")
        temperature = self._safe_float(config.get("temperature"), 0.7)
        top_p = self._safe_float(config.get("top_p"), 1.0)
        max_tokens = self._safe_int(config.get("max_tokens"), 800)
        timeout_seconds = self._safe_float(config.get("timeout_seconds"), 25.0)
        max_retries = self._safe_int(config.get("max_retries"), 1)
        rate_limit_guard_enabled = "open.bigmodel.cn" in base_url.lower()
        min_interval_seconds = (
            max(
                self._safe_float(
                    os.getenv("NIGHTSHIFT_LLM_MIN_INTERVAL_SECONDS"),
                    DEFAULT_LLM_REQUEST_MIN_INTERVAL_SECONDS,
                ),
                0.0,
            )
            if rate_limit_guard_enabled
            else 0.0
        )
        rate_limit_cooldown_seconds = (
            max(
                self._safe_float(
                    os.getenv("NIGHTSHIFT_LLM_RATE_LIMIT_COOLDOWN_SECONDS"),
                    DEFAULT_LLM_RATE_LIMIT_COOLDOWN_SECONDS,
                ),
                0.5,
            )
            if rate_limit_guard_enabled
            else 0.0
        )
        rate_limit_retries = (
            max(
                self._safe_int(
                    os.getenv("NIGHTSHIFT_LLM_RATE_LIMIT_RETRIES"),
                    DEFAULT_LLM_RATE_LIMIT_RETRIES,
                ),
                0,
            )
            if rate_limit_guard_enabled
            else 0
        )
        rate_limit_key = self._build_rate_limit_key(base_url=base_url, model=model)

        prompt_version = get_prompt(prompt_name).name
        start = time.perf_counter()
        success = False
        fallback_used = False
        error_message = ""
        output = ""

        if not api_key or api_key.startswith("YOUR_") or not base_url or not model:
            fallback_used = True
            error_message = "missing_model_config"
            self._record_eval(
                provider=provider,
                model=model,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                success=success,
                fallback_used=fallback_used,
                latency_ms=self._latency_ms(start),
                output_preview=output,
                error_message=error_message,
            )
            return ""

        try:
            from openai import OpenAI  # noqa: F401
        except Exception:
            fallback_used = True
            error_message = "openai_sdk_not_installed"
            self._record_eval(
                provider=provider,
                model=model,
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                success=success,
                fallback_used=fallback_used,
                latency_ms=self._latency_ms(start),
                output_preview=output,
                error_message=error_message,
            )
            return ""

        try:
            sdk_max_retries = 0 if rate_limit_guard_enabled else max_retries
            client = self._get_openai_client(
                api_key=api_key,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                max_retries=sdk_max_retries,
            )
            attempts = rate_limit_retries + 1
            for attempt_index in range(attempts):
                self._wait_for_rate_limit_slot(
                    rate_limit_key=rate_limit_key,
                    min_interval_seconds=min_interval_seconds,
                )
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are NightShift's handover assistant. Be clear, actionable, and avoid fabrication.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                    )
                    output = (response.choices[0].message.content or "").strip()
                    success = bool(output)
                    if not success:
                        fallback_used = True
                        error_message = "empty_model_output"
                    break
                except Exception as exc:
                    retry_after_seconds = self._extract_rate_limit_delay_seconds(
                        exc,
                        default_seconds=rate_limit_cooldown_seconds,
                    )
                    if retry_after_seconds is not None and attempt_index + 1 < attempts:
                        self._mark_rate_limit_cooldown(
                            rate_limit_key=rate_limit_key,
                            cooldown_seconds=retry_after_seconds,
                        )
                        LOGGER.warning(
                            "llm rate limited: model=%s base_url=%s attempt=%s/%s retry_in=%.2fs",
                            model,
                            base_url,
                            attempt_index + 1,
                            attempts,
                            retry_after_seconds,
                        )
                        time.sleep(retry_after_seconds)
                        continue
                    raise
        except Exception as exc:
            fallback_used = True
            error_message = str(exc)
            output = ""

        self._record_eval(
            provider=provider,
            model=model,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            success=success,
            fallback_used=fallback_used,
            latency_ms=self._latency_ms(start),
            output_preview=output,
            error_message=error_message,
        )
        return output if success else ""

    def _build_report_qa_cache_key(
        self,
        prompt_name: str,
        prompt: str,
        config: Dict[str, object],
    ) -> str:
        payload = {
            "prompt_name": prompt_name,
            "prompt": prompt,
            "provider": str(config.get("provider", "") or ""),
            "base_url": str(config.get("base_url", "") or ""),
            "model": str(config.get("model", "") or ""),
            "temperature": self._safe_float(config.get("temperature"), 0.7),
            "top_p": self._safe_float(config.get("top_p"), 1.0),
            "max_tokens": self._safe_int(config.get("max_tokens"), 800),
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return sha1(serialized.encode("utf-8")).hexdigest()

    def _get_cached_report_qa_answer(self, cache_key: str) -> str:
        now = time.time()
        with self._report_qa_cache_lock:
            cached = self._report_qa_cache.get(cache_key)
            if not isinstance(cached, dict):
                return ""
            if float(cached.get("expires_at", 0.0) or 0.0) <= now:
                self._report_qa_cache.pop(cache_key, None)
                return ""
            return str(cached.get("answer", "") or "")

    def _store_cached_report_qa_answer(self, cache_key: str, answer: str) -> None:
        if not answer:
            return
        now = time.time()
        with self._report_qa_cache_lock:
            self._prune_report_qa_cache(now)
            self._report_qa_cache[cache_key] = {
                "answer": answer,
                "expires_at": now + REPORT_QA_RESULT_CACHE_TTL_SECONDS,
            }

    def _prune_report_qa_cache(self, now: float) -> None:
        expired_keys = [
            key
            for key, payload in self._report_qa_cache.items()
            if float(payload.get("expires_at", 0.0) or 0.0) <= now
        ]
        for key in expired_keys:
            self._report_qa_cache.pop(key, None)

        overflow = len(self._report_qa_cache) - REPORT_QA_RESULT_CACHE_MAX_ENTRIES + 1
        if overflow <= 0:
            return

        oldest_keys = sorted(
            self._report_qa_cache,
            key=lambda key: float(self._report_qa_cache[key].get("expires_at", 0.0) or 0.0),
        )[:overflow]
        for key in oldest_keys:
            self._report_qa_cache.pop(key, None)

    def _get_openai_client(
        self,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
    ):
        cache_material = {
            "api_key_sha1": sha1(api_key.encode("utf-8")).hexdigest(),
            "base_url": base_url,
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
        }
        cache_key = json.dumps(cache_material, sort_keys=True)

        with self._openai_client_cache_lock:
            cached = self._openai_client_cache.get(cache_key)
            if cached is not None:
                return cached

            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=max_retries)
            self._openai_client_cache[cache_key] = client

            overflow = len(self._openai_client_cache) - OPENAI_CLIENT_CACHE_MAX_ENTRIES
            if overflow > 0:
                oldest_keys = list(self._openai_client_cache.keys())[:overflow]
                for key in oldest_keys:
                    if key != cache_key:
                        self._openai_client_cache.pop(key, None)
            return client

    def _build_rate_limit_key(self, *, base_url: str, model: str) -> str:
        normalized_base_url = base_url.strip().rstrip("/").lower()
        normalized_model = model.strip().lower()
        return f"{normalized_base_url}|{normalized_model}"

    def _normalize_llm_model_name(self, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            return ""
        return LEGACY_LLM_MODEL_ALIASES.get(normalized.lower(), normalized)

    def _wait_for_rate_limit_slot(self, *, rate_limit_key: str, min_interval_seconds: float) -> None:
        if not rate_limit_key or min_interval_seconds <= 0:
            return

        while True:
            with self._rate_limit_lock:
                now = time.monotonic()
                next_allowed_at = self._next_request_at_by_key.get(rate_limit_key, 0.0)
                if next_allowed_at <= now:
                    self._next_request_at_by_key[rate_limit_key] = now + min_interval_seconds
                    return
                sleep_seconds = next_allowed_at - now
            time.sleep(min(max(sleep_seconds, 0.01), 0.25))

    def _mark_rate_limit_cooldown(self, *, rate_limit_key: str, cooldown_seconds: float) -> None:
        if not rate_limit_key or cooldown_seconds <= 0:
            return
        with self._rate_limit_lock:
            next_allowed_at = time.monotonic() + cooldown_seconds
            current_next_allowed_at = self._next_request_at_by_key.get(rate_limit_key, 0.0)
            self._next_request_at_by_key[rate_limit_key] = max(current_next_allowed_at, next_allowed_at)

    def _extract_rate_limit_delay_seconds(
        self,
        exc: Exception,
        *,
        default_seconds: float,
    ) -> Optional[float]:
        status_code = getattr(exc, "status_code", None)
        response = getattr(exc, "response", None)
        if status_code is None and response is not None:
            status_code = getattr(response, "status_code", None)

        lowered_message = str(exc).lower()
        if status_code != 429 and "429" not in lowered_message and "rate limit" not in lowered_message and "too many requests" not in lowered_message:
            return None

        headers = getattr(response, "headers", {}) if response is not None else {}
        retry_after_value = headers.get("retry-after") if hasattr(headers, "get") else None
        retry_after_seconds = self._parse_retry_after_seconds(retry_after_value)
        if retry_after_seconds is not None:
            return max(retry_after_seconds, 0.5)
        return max(default_seconds, 0.5)

    def _parse_retry_after_seconds(self, value: object) -> Optional[float]:
        if value is None:
            return None
        try:
            parsed = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    def _record_eval(
        self,
        provider: str,
        model: str,
        prompt_name: str,
        prompt_version: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        success: bool,
        fallback_used: bool,
        latency_ms: int,
        output_preview: str,
        error_message: str,
    ) -> None:
        try:
            self.evaluation_repository.record(
                {
                    "provider": provider,
                    "model": model,
                    "prompt_name": prompt_name,
                    "prompt_version": prompt_version,
                    "temperature": temperature,
                    "top_p": top_p,
                    "max_tokens": max_tokens,
                    "success": success,
                    "fallback_used": fallback_used,
                    "latency_ms": latency_ms,
                    "output_preview": output_preview,
                    "error_message": error_message,
                }
            )
        except Exception as exc:
            LOGGER.warning("failed to record llm evaluation: %s", exc)

    def _latency_ms(self, start: float) -> int:
        return int((time.perf_counter() - start) * 1000)

    def _short_sha(self, commit: object) -> str:
        if not isinstance(commit, dict):
            return ""
        return str(commit.get("sha", "")).strip()[:7]

    def _safe_int(self, value: object, default: int = 0) -> int:
        try:
            return default if value is None else int(value)
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value: object, default: float = 0.0) -> float:
        try:
            return default if value is None else float(value)
        except (TypeError, ValueError):
            return default
