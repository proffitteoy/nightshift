from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from backend.repositories.paths import COMMIT_DATA_DIR
from backend.security import SecurityValidationError, normalize_github_repo_url


LOGGER = logging.getLogger(__name__)
GITHUB_TIMEOUT_SECONDS = 12
MAX_COMPARE_FILES = 20
MAX_PULL_REQUESTS = 5
MAX_PULL_REQUEST_SCAN = 24
MAX_README_EXCERPT_CHARS = 2400
MAX_ROOT_ENTRIES = 20
MAX_QA_CHANGED_FILES = 8


def parse_repo_full_name(repo_url: str) -> str:
    """Parse a GitHub repository URL into owner/repo."""
    try:
        normalized_repo_url = normalize_github_repo_url(repo_url)
    except SecurityValidationError as exc:
        raise ValueError(str(exc)) from exc
    parsed = urlparse(normalized_repo_url)
    if parsed.netloc and parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValueError(f"无效的 GitHub 仓库地址: {repo_url}")
    path = parsed.path.strip("/")
    repo_full_name = path.replace(".git", "")
    if repo_full_name.count("/") != 1:
        raise ValueError(f"无效的 GitHub 仓库地址: {repo_url}")
    return repo_full_name


def _to_int(value: object, default: int = 0) -> int:
    try:
        return default if value is None else int(value)
    except (TypeError, ValueError):
        return default


def _to_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _truncate_text(text: object, limit: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(limit - 3, 0)].rstrip() + "..."


def _load_saved_repo_activity(repo_full_name: str, commit_data_dir: Optional[Path] = None) -> Dict[str, object]:
    resolved_commit_data_dir = commit_data_dir or COMMIT_DATA_DIR
    if not resolved_commit_data_dir.exists():
        return {}

    for file_path in sorted(resolved_commit_data_dir.glob("*.json"), reverse=True):
        try:
            with file_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        repository = str(payload.get("repository", "")).strip().lower()
        if repository == repo_full_name.lower():
            return payload
    return {}


def _has_saved_repo_activity(activity: Dict[str, object]) -> bool:
    if not isinstance(activity, dict) or not activity:
        return False

    commits = activity.get("commits", [])
    if isinstance(commits, list) and commits:
        return True

    pull_requests = activity.get("pull_requests", [])
    if isinstance(pull_requests, list) and pull_requests:
        return True

    comparison = activity.get("comparison", {})
    changed_files = comparison.get("changed_files", []) if isinstance(comparison, dict) else []
    return isinstance(changed_files, list) and bool(changed_files)


def _load_github_repo(token: Optional[str], repo_full_name: str):
    try:
        from github import Github, GithubException
    except Exception as exc:
        raise RuntimeError("缺少 PyGithub 依赖，请先安装 backend/requirements.txt") from exc

    auth_token = token.strip() if isinstance(token, str) else ""

    def new_client(auth_value: Optional[str]):
        return Github(
            auth_value if auth_value else None,
            timeout=GITHUB_TIMEOUT_SECONDS,
            retry=0,
            seconds_between_requests=0.0,
            seconds_between_writes=0.0,
        )

    client = new_client(auth_token)
    auth_mode = "token" if auth_token else "anonymous"

    try:
        repo = client.get_repo(repo_full_name)
        return repo, auth_mode
    except GithubException as exc:
        status = int(getattr(exc, "status", 0) or 0)
        message = str(exc)
        if auth_token and status == 401 and "bad credentials" in message.lower():
            LOGGER.warning("github token invalid, fallback to anonymous: repo=%s", repo_full_name)
            client = new_client(None)
            auth_mode = "token->anonymous"
            try:
                repo = client.get_repo(repo_full_name)
                return repo, auth_mode
            except GithubException as fallback_exc:
                status = int(getattr(fallback_exc, "status", 0) or 0)
                message = str(fallback_exc)
                exc = fallback_exc

        if status == 403 and "rate limit" in message.lower():
            raise ConnectionError("GitHub API 匿名额度已耗尽，请配置 GITHUB_TOKEN 后重试") from exc
        if status == 404:
            raise ConnectionError(f"仓库不存在或无访问权限: {repo_full_name}") from exc
        raise ConnectionError(
            f"无法访问仓库 {repo_full_name}，请检查仓库地址、访问权限或 GITHUB_TOKEN 配置"
        ) from exc


def load_github_repository(token: Optional[str], repo_full_name: str):
    return _load_github_repo(token=token, repo_full_name=repo_full_name)


def _extract_commit_summary(commit) -> Dict[str, object]:
    stats = getattr(commit, "stats", None)
    commit_time = ""
    if commit.commit and commit.commit.author and commit.commit.author.date:
        commit_time = commit.commit.author.date.isoformat()

    message = ""
    if commit.commit and commit.commit.message:
        message = commit.commit.message.splitlines()[0]

    return {
        "sha": getattr(commit, "sha", ""),
        "author": commit.author.login if getattr(commit, "author", None) else "N/A",
        "message": message,
        "date": commit_time,
        "html_url": getattr(commit, "html_url", ""),
        "stats": {
            "additions": _to_int(getattr(stats, "additions", 0)),
            "deletions": _to_int(getattr(stats, "deletions", 0)),
            "total": _to_int(getattr(stats, "total", 0)),
        },
    }


def _extract_comparison_summary(comparison, base_sha: str, head_sha: str) -> Dict[str, object]:
    changed_files: List[Dict[str, object]] = []
    additions = 0
    deletions = 0

    for file in list(getattr(comparison, "files", []) or []):
        file_additions = _to_int(getattr(file, "additions", 0))
        file_deletions = _to_int(getattr(file, "deletions", 0))
        additions += file_additions
        deletions += file_deletions
        if len(changed_files) < MAX_COMPARE_FILES:
            changed_files.append(
                {
                    "filename": getattr(file, "filename", ""),
                    "status": getattr(file, "status", ""),
                    "additions": file_additions,
                    "deletions": file_deletions,
                    "changes": _to_int(getattr(file, "changes", 0)),
                    "patch_excerpt": _truncate_text(getattr(file, "patch", ""), 600),
                }
            )

    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "ahead_by": _to_int(getattr(comparison, "ahead_by", 0)),
        "total_commits": _to_int(getattr(comparison, "total_commits", 0)),
        "files_changed": len(list(getattr(comparison, "files", []) or [])),
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
    }


def _extract_pull_request_summary(pull_request) -> Dict[str, object]:
    created_at = getattr(pull_request, "created_at", None)
    updated_at = getattr(pull_request, "updated_at", None)
    merged_at = getattr(pull_request, "merged_at", None)
    return {
        "number": _to_int(getattr(pull_request, "number", 0)),
        "title": str(getattr(pull_request, "title", "") or "").strip(),
        "user": pull_request.user.login if getattr(pull_request, "user", None) else "N/A",
        "files_count": _to_int(getattr(pull_request, "changed_files", 0)),
        "state": str(getattr(pull_request, "state", "") or ""),
        "created_at": created_at.isoformat() if created_at else "",
        "updated_at": updated_at.isoformat() if updated_at else "",
        "merged_at": merged_at.isoformat() if merged_at else "",
        "html_url": str(getattr(pull_request, "html_url", "") or ""),
        "merge_commit_sha": str(getattr(pull_request, "merge_commit_sha", "") or ""),
    }


def _build_pull_request_window_start(latest_commit: Dict[str, object], previous_commit: Dict[str, object]) -> Optional[datetime]:
    previous_time = _to_datetime(previous_commit.get("date"))
    if previous_time:
        return previous_time - timedelta(hours=12)

    latest_time = _to_datetime(latest_commit.get("date"))
    if latest_time:
        return latest_time - timedelta(days=3)
    return None


def _select_recent_pull_requests(repo, window_start: Optional[datetime]) -> List[Dict[str, object]]:
    collected: List[Dict[str, object]] = []
    fallback: List[Dict[str, object]] = []

    for index, pull_request in enumerate(repo.get_pulls(state="all", sort="updated", direction="desc")):
        if index >= MAX_PULL_REQUEST_SCAN:
            break

        summary = _extract_pull_request_summary(pull_request)
        if summary["number"] <= 0:
            continue

        if len(fallback) < MAX_PULL_REQUESTS:
            fallback.append(summary)

        pr_time = (
            _to_datetime(summary.get("merged_at"))
            or _to_datetime(summary.get("updated_at"))
            or _to_datetime(summary.get("created_at"))
        )
        if window_start and pr_time and pr_time < window_start:
            if collected:
                break
            continue

        collected.append(summary)
        if len(collected) >= MAX_PULL_REQUESTS:
            break

    return collected if collected else fallback[:MAX_PULL_REQUESTS]


def fetch_repo_activity(token: Optional[str], repo_url: str, hours: int = 24) -> Dict[str, object]:
    """Fetch the latest comparable commits and related pull requests for a repository."""
    start = time.perf_counter()
    repo_full_name = parse_repo_full_name(repo_url)

    try:
        from github import GithubException
    except Exception as exc:
        raise RuntimeError("缺少 PyGithub 依赖，请先安装 backend/requirements.txt") from exc

    repo, auth_mode = _load_github_repo(token=token, repo_full_name=repo_full_name)

    try:
        recent_commits = []
        for commit in repo.get_commits():
            recent_commits.append(commit)
            if len(recent_commits) >= 2:
                break
    except GithubException as exc:
        status = int(getattr(exc, "status", 0) or 0)
        if status == 403 and "rate limit" in str(exc).lower():
            raise ConnectionError("GitHub API 匿名额度已耗尽，请配置 GITHUB_TOKEN 后重试") from exc
        raise ConnectionError(f"读取 Commit 数据失败: {exc}") from exc

    latest_commit = _extract_commit_summary(recent_commits[0]) if recent_commits else {}
    previous_commit = _extract_commit_summary(recent_commits[1]) if len(recent_commits) > 1 else {}
    comparison: Dict[str, object] = {}
    pull_requests: List[Dict[str, object]] = []

    if latest_commit and previous_commit:
        try:
            raw_comparison = repo.compare(previous_commit["sha"], latest_commit["sha"])
            comparison = _extract_comparison_summary(
                raw_comparison,
                str(previous_commit["sha"]),
                str(latest_commit["sha"]),
            )
        except GithubException as exc:
            status = int(getattr(exc, "status", 0) or 0)
            if status == 403 and "rate limit" in str(exc).lower():
                raise ConnectionError("GitHub API 匿名额度已耗尽，请配置 GITHUB_TOKEN 后重试") from exc
            LOGGER.warning("github compare failed, continue with commit-only snapshot: repo=%s error=%s", repo.full_name, exc)

    try:
        window_start = _build_pull_request_window_start(latest_commit, previous_commit)
        pull_requests = _select_recent_pull_requests(repo, window_start)
    except GithubException as exc:
        status = int(getattr(exc, "status", 0) or 0)
        if status == 403 and "rate limit" in str(exc).lower():
            LOGGER.warning("github pull request fetch hit rate limit, continue without PR data: repo=%s", repo.full_name)
        else:
            LOGGER.warning("github pull request fetch failed, continue without PR data: repo=%s error=%s", repo.full_name, exc)

    result = {
        "repository": repo.full_name,
        "fetch_time_utc": datetime.now(timezone.utc).isoformat(),
        "timespan_hours": hours,
        "analysis_mode": "latest-commit-diff",
        "latest_commit": latest_commit,
        "previous_commit": previous_commit,
        "comparison": comparison,
        "pull_requests": pull_requests,
        "commits": [item for item in (latest_commit, previous_commit) if item],
    }

    latency_ms = int((time.perf_counter() - start) * 1000)
    LOGGER.info(
        "github activity fetched: repo=%s latest=%s previous=%s prs=%s files_changed=%s latency_ms=%s auth=%s",
        repo.full_name,
        bool(latest_commit),
        bool(previous_commit),
        len(pull_requests),
        _to_int(comparison.get("files_changed"), 0),
        latency_ms,
        auth_mode,
    )
    return result


def fetch_repo_question_context(
    token: Optional[str],
    repo_url: str,
    *,
    commit_data_dir: Optional[Path] = None,
    hours: int = 72,
) -> Dict[str, object]:
    """Fetch lightweight repository context for report QA."""
    repo_full_name = parse_repo_full_name(repo_url)

    try:
        from github import GithubException
    except Exception as exc:
        raise RuntimeError("缺少 PyGithub 依赖，请先安装 backend/requirements.txt") from exc

    repo, auth_mode = _load_github_repo(token=token, repo_full_name=repo_full_name)

    readme_excerpt = ""
    try:
        readme = repo.get_readme()
        readme_excerpt = _truncate_text(readme.decoded_content.decode("utf-8", errors="ignore"), MAX_README_EXCERPT_CHARS)
    except GithubException:
        readme_excerpt = ""

    root_entries: List[str] = []
    try:
        contents = repo.get_contents("")
        if not isinstance(contents, list):
            contents = [contents]
        for item in contents:
            root_entries.append(f"{getattr(item, 'type', 'unknown')}:{getattr(item, 'path', '')}")
            if len(root_entries) >= MAX_ROOT_ENTRIES:
                break
    except GithubException:
        root_entries = []

    topics: List[str] = []
    try:
        topics = list(getattr(repo, "get_topics", lambda: [])() or [])[:6]
    except Exception:
        topics = []

    activity = _load_saved_repo_activity(repo_full_name, commit_data_dir=commit_data_dir)
    if not _has_saved_repo_activity(activity):
        try:
            activity = fetch_repo_activity(token=token, repo_url=repo_url, hours=hours)
        except Exception as exc:
            LOGGER.warning("repo QA activity context fallback to metadata only: repo=%s error=%s", repo_full_name, exc)

    comparison = activity.get("comparison", {}) if isinstance(activity, dict) else {}
    changed_files = comparison.get("changed_files", []) if isinstance(comparison, dict) else []
    if not isinstance(changed_files, list):
        changed_files = []

    commits = activity.get("commits", []) if isinstance(activity, dict) else []
    if not isinstance(commits, list):
        commits = []

    pull_requests = activity.get("pull_requests", []) if isinstance(activity, dict) else []
    if not isinstance(pull_requests, list):
        pull_requests = []

    return {
        "repo_url": repo_url,
        "repository": repo.full_name,
        "description": str(getattr(repo, "description", "") or "").strip(),
        "default_branch": str(getattr(repo, "default_branch", "") or "").strip(),
        "topics": topics,
        "readme_excerpt": readme_excerpt,
        "root_entries": root_entries,
        "changed_files": changed_files[:MAX_QA_CHANGED_FILES],
        "recent_commits": commits[:5],
        "recent_pull_requests": pull_requests[:5],
        "auth_mode": auth_mode,
    }
