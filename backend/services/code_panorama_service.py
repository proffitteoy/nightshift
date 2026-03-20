from __future__ import annotations

from hashlib import sha1
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.services.concurrency_guard import ConcurrencyGuard
from backend.security import SecurityValidationError, normalize_github_repo_url


class CodePanoramaService:
    def __init__(self, concurrency_guard: Optional[ConcurrencyGuard] = None) -> None:
        self.concurrency_guard = concurrency_guard or ConcurrencyGuard()

    def _parse_repo(self, repo_url: str) -> Tuple[str, str]:
        try:
            normalized_repo_url = normalize_github_repo_url(repo_url)
        except SecurityValidationError as exc:
            raise ValueError(str(exc)) from exc
        from urllib.parse import urlparse

        parsed = urlparse(normalized_repo_url)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) < 2:
            raise ValueError("repo_url must be a valid GitHub repository URL")
        return parts[0], parts[1].replace(".git", "")

    def _build_lock_key(self, repo_url: str, depth: int, entry_hint: Optional[str]) -> str:
        digest = sha1(f"{repo_url}|{depth}|{entry_hint or ''}".encode("utf-8")).hexdigest()[:12]
        return f"panorama:generate:{digest}"

    def generate_panorama(
        self,
        repo_url: str,
        depth: int = 2,
        entry_hint: Optional[str] = None,
    ) -> Dict[str, object]:
        lock_key = self._build_lock_key(repo_url=repo_url, depth=depth, entry_hint=entry_hint)
        with self.concurrency_guard.acquire(lock_key=lock_key, ttl_seconds=180, wait_timeout_seconds=20.0):
            owner, repo = self._parse_repo(repo_url)
            anchor = entry_hint or "entrypoint"

            nodes: List[Dict[str, object]] = [
                {
                    "id": "n0",
                    "file_path": "/",
                    "function_name": anchor,
                    "summary": f"Repository anchor for {owner}/{repo}",
                    "signature": f"{anchor}()",
                    "line_start": 1,
                    "line_end": 10,
                }
            ]
            edges: List[Dict[str, str]] = []

            for level in range(1, depth + 2):
                node_id = f"n{level}"
                parent_id = f"n{level - 1}"
                nodes.append(
                    {
                        "id": node_id,
                        "file_path": f"src/module_{level}.py",
                        "function_name": f"{anchor}_layer_{level}",
                        "summary": f"Generated panorama node at depth {level}",
                        "signature": f"{anchor}_layer_{level}(ctx)",
                        "line_start": level * 10,
                        "line_end": level * 10 + 8,
                    }
                )
                edges.append(
                    {
                        "from": parent_id,
                        "to": node_id,
                        "type": "calls",
                    }
                )

            return {
                "nodes": nodes,
                "edges": edges,
                "meta": {
                    "source_repo": f"{owner}/{repo}",
                    "language": "unknown",
                    "commit_sha": "mvp-generated",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "drilldown_supported": True,
                },
            }
