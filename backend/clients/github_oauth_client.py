from __future__ import annotations

import os
from typing import Dict, List, Optional
from urllib.parse import urlencode

import requests


GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_GITHUB_OAUTH_SCOPE = "read:user user:email"
DEFAULT_GITHUB_TIMEOUT_SECONDS = 15

GITHUB_OAUTH_CLIENT_ID_ENV = "NIGHTSHIFT_GITHUB_OAUTH_CLIENT_ID"
GITHUB_OAUTH_CLIENT_SECRET_ENV = "NIGHTSHIFT_GITHUB_OAUTH_CLIENT_SECRET"
GITHUB_OAUTH_SCOPE_ENV = "NIGHTSHIFT_GITHUB_OAUTH_SCOPE"
GITHUB_OAUTH_TIMEOUT_SECONDS_ENV = "NIGHTSHIFT_GITHUB_OAUTH_TIMEOUT_SECONDS"


class GitHubOAuthClientError(Exception):
    pass


class GitHubOAuthConfigurationError(GitHubOAuthClientError):
    pass


class GitHubOAuthClient:
    def __init__(self) -> None:
        self.client_id = os.getenv(GITHUB_OAUTH_CLIENT_ID_ENV, "").strip()
        self.client_secret = os.getenv(GITHUB_OAUTH_CLIENT_SECRET_ENV, "").strip()
        self.scope = os.getenv(GITHUB_OAUTH_SCOPE_ENV, "").strip() or DEFAULT_GITHUB_OAUTH_SCOPE
        self.timeout_seconds = self._parse_timeout_seconds(
            os.getenv(GITHUB_OAUTH_TIMEOUT_SECONDS_ENV),
            DEFAULT_GITHUB_TIMEOUT_SECONDS,
        )

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def ensure_configured(self) -> None:
        if self.is_configured():
            return
        raise GitHubOAuthConfigurationError(
            "GitHub OAuth is not configured. Set NIGHTSHIFT_GITHUB_OAUTH_CLIENT_ID and NIGHTSHIFT_GITHUB_OAUTH_CLIENT_SECRET."
        )

    def build_authorize_url(self, *, state: str, redirect_uri: str) -> str:
        self.ensure_configured()
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "scope": self.scope,
                "state": state,
                "allow_signup": "true",
            }
        )
        return f"{GITHUB_AUTHORIZE_URL}?{query}"

    def exchange_code_for_token(self, *, code: str, redirect_uri: str) -> str:
        self.ensure_configured()
        try:
            response = requests.post(
                GITHUB_ACCESS_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": "NightShift-OAuth",
                },
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GitHubOAuthClientError(f"failed to exchange GitHub code: {exc}") from exc

        payload = self._parse_json(response, fallback_message="invalid GitHub token response")
        access_token = str(payload.get("access_token", "")).strip()
        if not response.ok or not access_token:
            error_code = str(payload.get("error", "")).strip() or f"HTTP_{response.status_code}"
            error_description = str(payload.get("error_description", "")).strip() or "GitHub token exchange failed"
            raise GitHubOAuthClientError(f"{error_code}: {error_description}")
        return access_token

    def fetch_identity(self, *, access_token: str) -> Dict[str, object]:
        profile = self._github_json("GET", "/user", access_token=access_token)
        email = str(profile.get("email", "") or "").strip().lower()
        if not email:
            email = self._fetch_primary_email(access_token)

        display_name = str(profile.get("name", "") or "").strip()
        github_login = str(profile.get("login", "") or "").strip()
        if not display_name:
            display_name = github_login or f"github-{profile.get('id', 'user')}"

        private_repo_count = self._to_int(
            profile.get("owned_private_repos", profile.get("total_private_repos", 0)),
            0,
        )

        return {
            "github_id": str(profile.get("id", "") or "").strip(),
            "github_login": github_login,
            "display_name": display_name,
            "avatar_url": str(profile.get("avatar_url", "") or "").strip(),
            "email": email,
            "public_repo_count": self._to_int(profile.get("public_repos"), 0),
            "private_repo_count": max(private_repo_count, 0),
        }

    def list_public_repositories(
        self,
        *,
        github_login: str,
        access_token: Optional[str] = None,
    ) -> List[str]:
        normalized_login = github_login.strip()
        if not normalized_login:
            return []

        repositories: List[str] = []
        page = 1

        while True:
            if access_token:
                payload = self._github_json(
                    "GET",
                    "/user/repos",
                    access_token=access_token,
                    params={
                        "visibility": "public",
                        "affiliation": "owner",
                        "sort": "updated",
                        "per_page": 100,
                        "page": page,
                    },
                )
            else:
                payload = self._github_json(
                    "GET",
                    f"/users/{normalized_login}/repos",
                    access_token=None,
                    params={
                        "type": "owner",
                        "sort": "updated",
                        "per_page": 100,
                        "page": page,
                    },
                )

            if not isinstance(payload, list):
                break

            items = payload
            for item in items:
                if not isinstance(item, dict):
                    continue
                if bool(item.get("private", False)):
                    continue
                owner_login = str((item.get("owner") or {}).get("login", "")).strip()
                if owner_login and owner_login.lower() != normalized_login.lower():
                    continue
                repo_url = str(item.get("html_url", "")).strip()
                if repo_url:
                    repositories.append(repo_url)

            if len(items) < 100:
                break
            page += 1

        unique_repositories: List[str] = []
        seen = set()
        for repo_url in repositories:
            normalized_repo_url = repo_url.lower()
            if normalized_repo_url in seen:
                continue
            seen.add(normalized_repo_url)
            unique_repositories.append(repo_url)
        return unique_repositories

    def _fetch_primary_email(self, access_token: str) -> str:
        payload = self._github_json("GET", "/user/emails", access_token=access_token)
        if not isinstance(payload, list):
            return ""

        preferred = None
        fallback = None
        for item in payload:
            if not isinstance(item, dict):
                continue
            email = str(item.get("email", "") or "").strip().lower()
            if not email:
                continue
            if fallback is None:
                fallback = email
            if bool(item.get("verified")) and bool(item.get("primary")):
                preferred = email
                break
            if preferred is None and bool(item.get("verified")):
                preferred = email
        return preferred or fallback or ""

    def _github_json(
        self,
        method: str,
        path: str,
        *,
        access_token: Optional[str],
        params: Optional[Dict[str, object]] = None,
    ):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "NightShift-OAuth",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        url = f"{GITHUB_API_BASE_URL}{path}"
        try:
            response = requests.request(
                method,
                url,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise GitHubOAuthClientError(f"GitHub API request failed: {exc}") from exc

        payload = self._parse_json(response, fallback_message="invalid GitHub API response")
        if response.ok:
            return payload

        message = self._extract_error_message(payload) or f"GitHub API request failed with HTTP {response.status_code}"
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            message = "GitHub API rate limit exceeded"
        raise GitHubOAuthClientError(message)

    def _parse_json(self, response: requests.Response, *, fallback_message: str):
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubOAuthClientError(fallback_message) from exc

    def _extract_error_message(self, payload) -> str:
        if isinstance(payload, dict):
            return str(payload.get("error_description") or payload.get("message") or "").strip()
        return ""

    def _parse_timeout_seconds(self, value: Optional[str], default: int) -> int:
        try:
            parsed = int(str(value).strip()) if value is not None else default
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _to_int(self, value: object, default: int) -> int:
        try:
            return default if value is None else int(value)
        except (TypeError, ValueError):
            return default
