from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List

import requests


LOGGER = logging.getLogger(__name__)


def fetch_trending_repositories(
    min_stars: int = 100,
    min_forks: int = 5,
    created_within_weeks: int = 3,
    per_page: int = 10,
) -> List[Dict[str, object]]:
    """从 GitHub Search API 拉取近期热点仓库。"""
    created_after = (datetime.now() - timedelta(weeks=created_within_weeks)).strftime("%Y-%m-%d")
    query = f"created:>{created_after} stars:>={min_stars} forks:>={min_forks}"
    url = "https://api.github.com/search/repositories"

    base_headers = {"User-Agent": "NightShift-Trending-Client"}
    token = (os.getenv("GITHUB_TOKEN") or "").strip()

    start = time.perf_counter()
    response = _request_trending(url=url, query=query, per_page=per_page, headers=base_headers, token=token)
    items = response.json().get("items", [])
    latency_ms = int((time.perf_counter() - start) * 1000)
    LOGGER.info("trending fetched: count=%s latency_ms=%s auth=%s", len(items), latency_ms, "token" if token else "anonymous")
    return items


def _request_trending(url: str, query: str, per_page: int, headers: Dict[str, str], token: str) -> requests.Response:
    auth_headers = dict(headers)
    if token:
        auth_headers["Authorization"] = f"token {token}"

    try:
        response = requests.get(
            url,
            headers=auth_headers,
            params={"q": query, "sort": "stars", "order": "desc", "per_page": per_page},
            timeout=25,
        )
    except requests.RequestException as exc:
        raise ConnectionError(f"请求 GitHub 热点失败: {exc}") from exc

    if response.status_code in {401, 403} and token:
        text = response.text.lower()
        if "bad credentials" in text or "requires authentication" in text or "invalid" in text:
            LOGGER.warning("github token invalid for trending, fallback to anonymous request")
            return _request_trending(url=url, query=query, per_page=per_page, headers=headers, token="")

    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ConnectionError(f"请求 GitHub 热点失败: {exc}") from exc
    return response
