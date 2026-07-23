from __future__ import annotations

import json
import re
from hashlib import sha1
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.clients.github_client import load_github_repository, parse_repo_full_name
from backend.services.concurrency_guard import ConcurrencyGuard
from backend.security import SecurityValidationError, normalize_github_repo_url


DEPTH_FILE_LIMITS = {
    "快速": 300,
    "标准": 800,
    "深度": 2000,
    "fast": 300,
    "standard": 800,
    "deep": 2000,
}
DEPTH_KEY_LIMITS = {
    "快速": 8,
    "标准": 15,
    "深度": 30,
    "fast": 8,
    "standard": 15,
    "deep": 30,
}
MAX_FILE_READ_CHARS = 12000
MAX_MERGED_CONTEXT_CHARS = 50000
MAX_DEPENDENCIES = 10
MAX_DEFINITIONS = 12

IGNORED_PATH_PARTS = {
    ".git",
    ".github",
    ".idea",
    ".vscode",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}
IGNORED_SUFFIXES = {
    ".7z",
    ".apk",
    ".class",
    ".dll",
    ".exe",
    ".gif",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lock",
    ".mp4",
    ".pdf",
    ".png",
    ".so",
    ".webp",
    ".zip",
}
LANGUAGE_BY_EXTENSION = {
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}
SOURCE_EXTENSIONS = set(LANGUAGE_BY_EXTENSION)
ENTRY_FILE_NAMES = {
    "app.py",
    "main.py",
    "server.py",
    "manage.py",
    "index.js",
    "index.ts",
    "main.js",
    "main.ts",
    "main.tsx",
    "app.tsx",
    "app.jsx",
    "mainactivity.java",
    "mainactivity.kt",
}
CONFIG_FILE_NAMES = {
    "docker-compose.yml",
    "dockerfile",
    "gradle.properties",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "settings.gradle.kts",
    "vite.config.ts",
}


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

    def _build_workflow_lock_key(self, repo_url: str, depth: str, intent: Optional[str]) -> str:
        digest = sha1(f"{repo_url}|{depth}|{intent or ''}".encode("utf-8")).hexdigest()[:12]
        return f"workflow-analysis:generate:{digest}"

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

    def generate_workflow_analysis(
        self,
        *,
        token: Optional[str],
        repo_url: str,
        depth: str = "标准",
        intent: Optional[str] = None,
        focus_areas: Optional[str] = None,
        queries: Optional[str] = None,
    ) -> Dict[str, object]:
        normalized_depth = str(depth or "标准").strip() or "标准"
        normalized_repo_url = normalize_github_repo_url(repo_url)
        lock_key = self._build_workflow_lock_key(
            repo_url=normalized_repo_url,
            depth=normalized_depth,
            intent=intent,
        )
        with self.concurrency_guard.acquire(lock_key=lock_key, ttl_seconds=240, wait_timeout_seconds=25.0):
            repo_full_name = parse_repo_full_name(normalized_repo_url)
            repo, _auth_mode = load_github_repository(token=token, repo_full_name=repo_full_name)
            default_branch = str(getattr(repo, "default_branch", "") or "main")

            file_limit = DEPTH_FILE_LIMITS.get(normalized_depth, 800)
            key_limit = DEPTH_KEY_LIMITS.get(normalized_depth, 15)
            files = self._fetch_file_tree(repo=repo, branch=default_branch, limit=file_limit)

            languages = self._detect_languages(files)
            frameworks = self._detect_frameworks(files)
            build_tools = self._detect_build_tools(files)
            entry_files = self._detect_entry_files(files)
            key_files = self._select_key_files(
                files=files,
                entry_files=entry_files,
                focus_areas=focus_areas,
                queries=queries,
                limit=key_limit,
            )
            details = self._analyze_key_files(
                repo=repo,
                branch=default_branch,
                selected_files=key_files,
            )
            merged_files, merged_context = self._merge_key_file_details(details)

            file_tree_text = json.dumps(files, ensure_ascii=False)
            key_file_paths = ",".join(item["path"] for item in key_files)
            language_text = ",".join(languages)
            read_plan = f"按优先级读取 {len(key_files)} 个关键文件：{key_file_paths}"

            return {
                "repository": repo_full_name,
                "default_branch": default_branch,
                "file_tree": files,
                "file_tree_text": file_tree_text,
                "language": language_text,
                "languages": language_text,
                "frameworks": ",".join(frameworks),
                "build_tools": ",".join(build_tools),
                "entry_files": ",".join(entry_files),
                "total_files": str(len(files)),
                "key_files": [item["path"] for item in key_files],
                "key_file_details": json.dumps(details, ensure_ascii=False),
                "key_file_paths": key_file_paths,
                "read_plan": read_plan,
                "total_key_files": str(len(key_files)),
                "merged_files": merged_files,
                "merged_context": merged_context,
                "file_count": str(len(details)),
            }

    def _fetch_file_tree(self, *, repo, branch: str, limit: int) -> List[Dict[str, object]]:
        try:
            tree = repo.get_git_tree(branch, recursive=True)
        except Exception as exc:
            try:
                branch_ref = repo.get_branch(branch)
                commit_sha = str(getattr(getattr(branch_ref, "commit", None), "sha", "") or "").strip()
                tree = repo.get_git_tree(commit_sha, recursive=True)
            except Exception:
                raise ConnectionError(f"读取仓库文件树失败: {exc}") from exc

        files: List[Dict[str, object]] = []
        for item in list(getattr(tree, "tree", []) or []):
            if len(files) >= limit:
                break
            if str(getattr(item, "type", "") or "") != "blob":
                continue
            path = str(getattr(item, "path", "") or "").strip()
            if not path or self._should_ignore_path(path):
                continue
            size = self._to_int(getattr(item, "size", 0))
            files.append(
                {
                    "path": path,
                    "type": "file",
                    "size": size,
                    "language": self._language_for_path(path),
                }
            )
        return files

    def _select_key_files(
        self,
        *,
        files: List[Dict[str, object]],
        entry_files: List[str],
        focus_areas: Optional[str],
        queries: Optional[str],
        limit: int,
    ) -> List[Dict[str, object]]:
        entry_set = set(entry_files)
        focus_terms = self._split_terms(focus_areas) + self._split_terms(queries)
        scored: List[Dict[str, object]] = []
        for file_item in files:
            path = str(file_item.get("path", ""))
            score = self._score_file(path=path, entry_set=entry_set, focus_terms=focus_terms)
            if score <= 0:
                continue
            item = dict(file_item)
            item["score"] = score
            scored.append(item)

        scored.sort(
            key=lambda item: (
                -self._to_int(item.get("score")),
                str(item.get("path", "")).count("/"),
                str(item.get("path", "")),
            )
        )
        return scored[:limit]

    def _score_file(self, *, path: str, entry_set: set[str], focus_terms: List[str]) -> int:
        lowered = path.lower()
        name = lowered.rsplit("/", 1)[-1]
        extension = self._extension_for_path(path)
        score = 0

        if path in entry_set:
            score += 100
        if name in CONFIG_FILE_NAMES:
            score += 70
        if name in {"readme.md", "dockerfile", "androidmanifest.xml"}:
            score += 60
        if extension in SOURCE_EXTENSIONS:
            score += 35
        if any(part in lowered.split("/") for part in ["api", "routes", "services", "clients", "models"]):
            score += 30
        if any(part in lowered.split("/") for part in ["src", "app", "backend"]):
            score += 15
        if any(term and term in lowered for term in focus_terms):
            score += 25
        if "/test" in lowered or "tests/" in lowered or name.startswith("test_"):
            score -= 20
        if extension not in SOURCE_EXTENSIONS and name not in CONFIG_FILE_NAMES and name != "readme.md":
            score -= 10
        return score

    def _analyze_key_files(self, *, repo, branch: str, selected_files: List[Dict[str, object]]) -> List[Dict[str, object]]:
        details: List[Dict[str, object]] = []
        for item in selected_files:
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            content = self._read_file_text(repo=repo, branch=branch, path=path)
            summary = self._summarize_file(path=path, content=content)
            details.append(
                {
                    "path": path,
                    "language": str(item.get("language", "")),
                    "size": self._to_int(item.get("size")),
                    "score": self._to_int(item.get("score")),
                    **summary,
                }
            )
        return details

    def _read_file_text(self, *, repo, branch: str, path: str) -> str:
        try:
            content_file = repo.get_contents(path, ref=branch)
        except Exception:
            return ""
        if isinstance(content_file, list):
            return ""
        try:
            raw = getattr(content_file, "decoded_content", b"") or b""
            text = raw.decode("utf-8", errors="ignore")
        except Exception:
            return ""
        return text[:MAX_FILE_READ_CHARS]

    def _summarize_file(self, *, path: str, content: str) -> Dict[str, object]:
        definitions = self._extract_definitions(path=path, content=content)
        dependencies = self._extract_dependencies(path=path, content=content)
        issues = self._extract_issues(content)
        purpose = self._infer_file_purpose(path)

        if definitions:
            summary = f"{path} 是{purpose}，核心定义包括 {', '.join(definitions[:5])}。"
        else:
            summary = f"{path} 是{purpose}。"
        if not content:
            summary += " 当前未读取到可解析文本内容。"

        return {
            "summary": summary,
            "definitions": definitions,
            "dependencies": dependencies,
            "issues": issues,
        }

    def _merge_key_file_details(self, details: List[Dict[str, object]]) -> Tuple[str, str]:
        merged_files = "\n".join(
            f"- {item.get('path', '')}: {item.get('summary', '')}"
            for item in details
            if item.get("path")
        )

        blocks: List[str] = []
        total_chars = 0
        for item in details:
            block = "\n".join(
                [
                    f"### {item.get('path', '')}",
                    f"用途：{item.get('summary', '')}",
                    f"关键定义：{', '.join(item.get('definitions', []) or []) or '无'}",
                    f"依赖：{', '.join(item.get('dependencies', []) or []) or '无'}",
                    f"潜在问题：{', '.join(item.get('issues', []) or []) or '无'}",
                ]
            )
            if total_chars + len(block) > MAX_MERGED_CONTEXT_CHARS:
                break
            blocks.append(block)
            total_chars += len(block)
        return merged_files, "\n\n".join(blocks)

    def _detect_languages(self, files: List[Dict[str, object]]) -> List[str]:
        counts: Dict[str, int] = {}
        for item in files:
            language = str(item.get("language", "")).strip()
            if not language:
                continue
            counts[language] = counts.get(language, 0) + 1
        return [name for name, _count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:5]]

    def _detect_frameworks(self, files: List[Dict[str, object]]) -> List[str]:
        paths = {str(item.get("path", "")).lower() for item in files}
        frameworks: List[str] = []
        if any(path.endswith("main.py") for path in paths) and any("/api/routes/" in f"/{path}" for path in paths):
            frameworks.append("FastAPI")
        if any(path.endswith("app.tsx") or path.endswith("main.tsx") for path in paths):
            frameworks.append("React")
        if any(path.endswith("vite.config.ts") or path.endswith("vite.config.js") for path in paths):
            frameworks.append("Vite")
        if any(path.endswith("androidmanifest.xml") for path in paths):
            frameworks.append("Android")
        if any(path.endswith("build.gradle.kts") or path.endswith("settings.gradle.kts") for path in paths):
            frameworks.append("Gradle")
        if any(path.endswith("docker-compose.yml") for path in paths):
            frameworks.append("Docker Compose")
        return frameworks

    def _detect_build_tools(self, files: List[Dict[str, object]]) -> List[str]:
        paths = {str(item.get("path", "")).lower() for item in files}
        tools: List[str] = []
        if "package.json" in {path.rsplit("/", 1)[-1] for path in paths}:
            tools.append("npm")
        if any(path.endswith("requirements.txt") for path in paths):
            tools.append("pip")
        if any(path.endswith("pyproject.toml") for path in paths):
            tools.append("pyproject")
        if any(path.endswith("build.gradle.kts") or path.endswith("settings.gradle.kts") for path in paths):
            tools.append("Gradle")
        if any(path.endswith("dockerfile") for path in paths):
            tools.append("Docker")
        return tools

    def _detect_entry_files(self, files: List[Dict[str, object]]) -> List[str]:
        entry_files: List[str] = []
        for item in files:
            path = str(item.get("path", ""))
            name = path.lower().rsplit("/", 1)[-1]
            if name in ENTRY_FILE_NAMES or name in {"androidmanifest.xml", "docker-compose.yml"}:
                entry_files.append(path)
        return entry_files[:20]

    def _extract_definitions(self, *, path: str, content: str) -> List[str]:
        extension = self._extension_for_path(path)
        patterns = {
            ".py": r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][\w]*)",
            ".ts": r"^\s*(?:export\s+)?(?:class|function|interface|type|const)\s+([A-Za-z_][\w]*)",
            ".tsx": r"^\s*(?:export\s+)?(?:class|function|interface|type|const)\s+([A-Za-z_][\w]*)",
            ".js": r"^\s*(?:export\s+)?(?:class|function|const)\s+([A-Za-z_][\w]*)",
            ".jsx": r"^\s*(?:export\s+)?(?:class|function|const)\s+([A-Za-z_][\w]*)",
            ".java": r"^\s*(?:public|private|protected)?\s*(?:class|interface|enum|void|[\w<>]+)\s+([A-Za-z_][\w]*)",
            ".kt": r"^\s*(?:class|interface|object|fun)\s+([A-Za-z_][\w]*)",
            ".kts": r"^\s*(?:class|interface|object|fun)\s+([A-Za-z_][\w]*)",
        }
        pattern = patterns.get(extension)
        if not pattern:
            return []
        matches: List[str] = []
        for line in content.splitlines():
            match = re.search(pattern, line)
            if match and match.group(1) not in matches:
                matches.append(match.group(1))
            if len(matches) >= MAX_DEFINITIONS:
                break
        return matches

    def _extract_dependencies(self, *, path: str, content: str) -> List[str]:
        extension = self._extension_for_path(path)
        dependencies: List[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            dependency = ""
            if extension == ".py":
                match = re.match(r"(?:from|import)\s+([A-Za-z0-9_.]+)", stripped)
                dependency = match.group(1) if match else ""
            elif extension in {".js", ".jsx", ".ts", ".tsx"}:
                match = re.search(r"from\s+['\"]([^'\"]+)['\"]|import\s+['\"]([^'\"]+)['\"]", stripped)
                dependency = (match.group(1) or match.group(2)) if match else ""
            elif extension == ".java":
                match = re.match(r"import\s+([A-Za-z0-9_.]+)", stripped)
                dependency = match.group(1) if match else ""
            elif extension in {".kt", ".kts"}:
                match = re.match(r"import\s+([A-Za-z0-9_.]+)", stripped)
                dependency = match.group(1) if match else ""
            if dependency and dependency not in dependencies:
                dependencies.append(dependency)
            if len(dependencies) >= MAX_DEPENDENCIES:
                break
        return dependencies

    def _extract_issues(self, content: str) -> List[str]:
        if not content:
            return []
        lowered = content.lower()
        issues: List[str] = []
        if "todo" in lowered or "fixme" in lowered:
            issues.append("存在 TODO/FIXME")
        if "eval(" in lowered or "exec(" in lowered:
            issues.append("存在动态执行调用")
        if re.search(r"(api[_-]?key|secret|token|password)\s*=\s*['\"][^'\"]{8,}", lowered):
            issues.append("疑似硬编码敏感配置")
        return issues

    def _infer_file_purpose(self, path: str) -> str:
        lowered = path.lower()
        name = lowered.rsplit("/", 1)[-1]
        if "/api/" in f"/{lowered}" or "/routes/" in f"/{lowered}":
            return "接口路由文件"
        if "/services/" in f"/{lowered}":
            return "业务服务文件"
        if "/clients/" in f"/{lowered}":
            return "外部服务客户端文件"
        if "/models/" in f"/{lowered}" or "/schemas" in f"/{lowered}":
            return "数据模型契约文件"
        if name in CONFIG_FILE_NAMES:
            return "项目配置或构建配置文件"
        if name in ENTRY_FILE_NAMES:
            return "应用入口文件"
        return "项目关键源码文件"

    def _should_ignore_path(self, path: str) -> bool:
        lowered = path.lower()
        parts = lowered.split("/")
        if any(part in IGNORED_PATH_PARTS for part in parts):
            return True
        return any(lowered.endswith(suffix) for suffix in IGNORED_SUFFIXES)

    def _language_for_path(self, path: str) -> str:
        return LANGUAGE_BY_EXTENSION.get(self._extension_for_path(path), "")

    def _extension_for_path(self, path: str) -> str:
        lowered = path.lower()
        if "." not in lowered.rsplit("/", 1)[-1]:
            return ""
        return "." + lowered.rsplit(".", 1)[-1]

    def _split_terms(self, value: Optional[str]) -> List[str]:
        if not value:
            return []
        terms = re.split(r"[，,；;\s]+", str(value).lower())
        return [term for term in terms if len(term) >= 2]

    def _to_int(self, value: object, default: int = 0) -> int:
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default
