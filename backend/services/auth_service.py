from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from sqlite3 import IntegrityError
from typing import Dict, Optional

from backend.clients.github_oauth_client import (
    GitHubOAuthClient,
    GitHubOAuthClientError,
    GitHubOAuthConfigurationError,
)
from backend.repositories.auth_session_repository import AuthSessionRepository
from backend.repositories.user_repository import UserRepository
from backend.security import (
    PUBLIC_BASE_URL_ENV,
    SecurityValidationError,
    normalize_avatar_url,
    normalize_display_name,
    normalize_email,
    normalize_github_login,
    normalize_public_base_url,
    normalize_runtime_secret,
    sanitize_untrusted_text,
)
from backend.services.subscription_service import SubscriptionService


JWT_SECRET_ENV = "NIGHTSHIFT_JWT_SECRET"
JWT_EXPIRE_MINUTES_ENV = "NIGHTSHIFT_JWT_EXPIRE_MINUTES"
GITHUB_OAUTH_SESSION_TTL_ENV = "NIGHTSHIFT_GITHUB_OAUTH_SESSION_TTL_SECONDS"
GITHUB_OAUTH_REDIRECT_URI_ENV = "NIGHTSHIFT_GITHUB_OAUTH_REDIRECT_URI"

JWT_ALGORITHM = "HS256"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 390000
DEFAULT_GITHUB_OAUTH_SESSION_TTL_SECONDS = 600


class AuthServiceError(Exception):
    pass


class InvalidCredentialsError(AuthServiceError):
    pass


class EmailAlreadyExistsError(AuthServiceError):
    pass


class PasswordChangeNotAllowedError(AuthServiceError):
    pass


class InvalidTokenError(AuthServiceError):
    pass


class OAuthConfigurationError(AuthServiceError):
    pass


class OAuthSessionNotFoundError(AuthServiceError):
    pass


class GitHubOAuthError(AuthServiceError):
    pass


class GitHubAccountConflictError(AuthServiceError):
    pass


class AuthService:
    def __init__(
        self,
        repository: Optional[UserRepository] = None,
        auth_session_repository: Optional[AuthSessionRepository] = None,
        subscription_service: Optional[SubscriptionService] = None,
        github_oauth_client: Optional[GitHubOAuthClient] = None,
    ) -> None:
        self.repository = repository or UserRepository()
        self.auth_session_repository = auth_session_repository or AuthSessionRepository()
        self.subscription_service = subscription_service or SubscriptionService()
        self.github_oauth_client = github_oauth_client or GitHubOAuthClient()
        self._jwt_secret = os.getenv(JWT_SECRET_ENV, "").strip() or secrets.token_urlsafe(32)
        self._token_ttl = max(self._parse_positive_int(os.getenv(JWT_EXPIRE_MINUTES_ENV), 7 * 24 * 60), 15)
        self._oauth_session_ttl_seconds = max(
            self._parse_positive_int(os.getenv(GITHUB_OAUTH_SESSION_TTL_ENV), DEFAULT_GITHUB_OAUTH_SESSION_TTL_SECONDS),
            120,
        )

    def register_user(self, email: str, password: str, display_name: Optional[str] = None) -> Dict[str, object]:
        normalized_email = self._normalize_email(email)
        normalized_display_name = self._normalize_display_name(display_name, normalized_email)
        password_hash = self._hash_password(password)
        try:
            user = self.repository.create_user(
                email=normalized_email,
                password_hash=password_hash,
                display_name=normalized_display_name,
            )
        except IntegrityError as exc:
            raise EmailAlreadyExistsError("email already exists") from exc
        return self._build_auth_payload(user)

    def login_user(self, email: str, password: str) -> Dict[str, object]:
        normalized_email = self._normalize_email(email)
        user = self.repository.get_user_by_email(normalized_email, auth_source="password")
        if not user or not self._verify_password(password, str(user.get("password_hash", ""))):
            raise InvalidCredentialsError("invalid email or password")
        if not bool(user.get("is_active", True)):
            raise InvalidCredentialsError("account is disabled")
        refreshed = self.repository.touch_last_login(int(user["id"])) or user
        repo_sync = self._sync_public_repositories(user=refreshed, access_token=None, private_repo_count=None)
        return self._build_auth_payload(refreshed, repo_sync=repo_sync)

    def change_password(
        self,
        *,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> Dict[str, object]:
        user = self.repository.get_user_by_id(user_id)
        if not user or not bool(user.get("is_active", True)):
            raise InvalidCredentialsError("account is unavailable")
        if str(user.get("auth_source", "password")).strip().lower() != "password":
            raise PasswordChangeNotAllowedError("password can only be changed for password accounts")
        if not self._verify_password(current_password, str(user.get("password_hash", ""))):
            raise InvalidCredentialsError("current password is incorrect")
        if current_password.strip() == new_password.strip():
            raise InvalidCredentialsError("new password must be different from current password")

        updated = self.repository.update_password_hash(
            user_id=user_id,
            password_hash=self._hash_password(new_password),
        )
        if not updated:
            raise InvalidCredentialsError("account is unavailable")
        return self._public_user(updated)

    def get_user_from_token(self, token: str) -> Dict[str, object]:
        payload = self._decode_token(token)
        subject = str(payload.get("sub", "")).strip()
        if not subject.isdigit():
            raise InvalidTokenError("invalid token subject")
        user = self.repository.get_user_by_id(int(subject))
        if not user or not bool(user.get("is_active", True)):
            raise InvalidTokenError("user not found or inactive")
        return self._public_user(user)

    def start_github_oauth(self, *, current_user: Optional[Dict[str, object]]) -> Dict[str, object]:
        try:
            self.github_oauth_client.ensure_configured()
        except GitHubOAuthConfigurationError as exc:
            raise OAuthConfigurationError(str(exc)) from exc

        now = datetime.now(timezone.utc)
        self.auth_session_repository.delete_expired_sessions(now_iso=now.isoformat())

        state_token = secrets.token_urlsafe(24)
        poll_token = secrets.token_urlsafe(24)
        redirect_uri = self._resolve_github_redirect_uri()
        authorization_url = self.github_oauth_client.build_authorize_url(
            state=state_token,
            redirect_uri=redirect_uri,
        )
        expires_at = (now + timedelta(seconds=self._oauth_session_ttl_seconds)).isoformat()

        session = self.auth_session_repository.create_session(
            state_token=state_token,
            poll_token=poll_token,
            requested_by_user_id=int(current_user["id"]) if current_user else None,
            flow_type="connect" if current_user else "login",
            redirect_uri=redirect_uri,
            authorization_url=authorization_url,
            expires_at=expires_at,
        )

        return {
            "authorize_url": str(session["authorization_url"]),
            "poll_token": str(session["poll_token"]),
            "expires_in": self._oauth_session_ttl_seconds,
            "mode": str(session["flow_type"]),
        }

    def complete_github_oauth(
        self,
        *,
        state_token: str,
        code: Optional[str],
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ) -> Dict[str, object]:
        self.auth_session_repository.delete_expired_sessions()
        try:
            normalized_state_token = normalize_runtime_secret(
                state_token,
                field_name="state",
                max_length=256,
            )
        except SecurityValidationError:
            return {"status": "failed", "message": "GitHub authorization session is invalid."}
        session = self.auth_session_repository.get_session_by_state(normalized_state_token)
        if not session:
            return {
                "status": "failed",
                "message": "GitHub 授权会话不存在或已过期，请返回 NightShift 重新发起授权。",
            }
        if self._is_oauth_session_expired(session):
            self.auth_session_repository.mark_failed(
                int(session["id"]),
                error_code="OAUTH_SESSION_EXPIRED",
                error_message="GitHub authorization session expired",
            )
            return {
                "status": "failed",
                "message": "GitHub 授权会话已过期，请返回 NightShift 重新发起授权。",
            }
        if error:
            message = sanitize_untrusted_text(
                error_description or error or "GitHub authorization denied",
                max_length=200,
            )
            self.auth_session_repository.mark_failed(
                int(session["id"]),
                error_code="GITHUB_AUTH_DENIED",
                error_message=message,
            )
            return {
                "status": "failed",
                "message": f"GitHub 授权未完成：{message}",
            }
        if not code:
            self.auth_session_repository.mark_failed(
                int(session["id"]),
                error_code="GITHUB_AUTH_CODE_MISSING",
                error_message="GitHub authorization code is missing",
            )
            return {
                "status": "failed",
                "message": "GitHub 授权未返回 code，请返回 NightShift 重试。",
            }

        try:
            normalized_code = normalize_runtime_secret(
                code,
                field_name="code",
                max_length=512,
            )
            access_token = self.github_oauth_client.exchange_code_for_token(
                code=normalized_code,
                redirect_uri=str(session["redirect_uri"]),
            )
            identity = self.github_oauth_client.fetch_identity(access_token=access_token)
            user = self._resolve_github_user(session=session, identity=identity)
            repo_sync = self._sync_public_repositories(
                user=user,
                access_token=access_token,
                private_repo_count=identity.get("private_repo_count"),
            )
            auth_payload = self._build_auth_payload(user, repo_sync=repo_sync)
            completed_message = self._resolve_completed_message(
                flow_type=str(session["flow_type"]),
                repo_sync=repo_sync,
            )
            self.auth_session_repository.mark_completed(
                int(session["id"]),
                auth_payload=auth_payload,
                repo_sync=repo_sync,
                message=completed_message,
            )
            return {
                "status": "completed",
                "message": completed_message,
            }
        except GitHubAccountConflictError as exc:
            self.auth_session_repository.mark_failed(
                int(session["id"]),
                error_code="GITHUB_ACCOUNT_CONFLICT",
                error_message=str(exc),
            )
            return {
                "status": "failed",
                "message": str(exc),
            }
        except (GitHubOAuthClientError, InvalidCredentialsError, EmailAlreadyExistsError, SecurityValidationError) as exc:
            self.auth_session_repository.mark_failed(
                int(session["id"]),
                error_code="GITHUB_OAUTH_FAILED",
                error_message=str(exc),
            )
            return {
                "status": "failed",
                "message": f"GitHub 授权失败：{exc}",
            }

    def poll_github_oauth(self, *, poll_token: str) -> Dict[str, object]:
        self.auth_session_repository.delete_expired_sessions()
        try:
            normalized_poll_token = normalize_runtime_secret(
                poll_token,
                field_name="poll_token",
                max_length=256,
            )
        except SecurityValidationError as exc:
            raise OAuthSessionNotFoundError("GitHub authorization session not found or expired") from exc
        session = self.auth_session_repository.get_session_by_poll_token(normalized_poll_token)
        if not session:
            raise OAuthSessionNotFoundError("GitHub authorization session not found or expired")

        if session["status"] == "pending":
            return {
                "status": "pending",
                "message": "Waiting for GitHub authorization to finish.",
                "auth": None,
            }

        if session["status"] == "failed":
            return {
                "status": "failed",
                "message": str(session.get("error_message") or "GitHub authorization failed"),
                "auth": None,
            }

        auth_payload = {
            "access_token": str(session.get("result_access_token", "")),
            "token_type": str(session.get("result_token_type", "bearer")),
            "expires_in": int(session.get("result_expires_in", 0) or 0),
            "user": session.get("result_user", {}),
            "repo_sync": session.get("result_repo_sync") or None,
        }
        self.auth_session_repository.delete_session(int(session["id"]))
        return {
            "status": "completed",
            "message": str(session.get("result_message") or "GitHub authorization completed"),
            "auth": auth_payload,
        }

    def _build_auth_payload(
        self,
        user: Dict[str, object],
        *,
        repo_sync: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        public_user = self._public_user(user)
        access_token = self._encode_token(public_user)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": self._token_ttl * 60,
            "user": public_user,
            "repo_sync": repo_sync,
        }

    def _public_user(self, user: Dict[str, object]) -> Dict[str, object]:
        return {
            "id": int(user["id"]),
            "email": self._normalize_email(str(user.get("email", ""))),
            "display_name": self._normalize_display_name(
                str(user.get("display_name", "")),
                str(user.get("email", "")),
            ),
            "auth_source": sanitize_untrusted_text(
                str(user.get("auth_source", "password")),
                max_length=40,
                allow_empty=True,
            )
            or "password",
            "github_login": self._normalize_github_login(str(user.get("github_login", "")), allow_empty=True),
            "avatar_url": self._normalize_avatar_url(str(user.get("avatar_url", "")), allow_empty=True),
            "github_connected": bool(str(user.get("github_id", "")).strip()),
            "created_at": str(user.get("created_at", "")),
            "updated_at": str(user.get("updated_at", "")),
            "last_login_at": user.get("last_login_at"),
        }

    def _resolve_github_user(self, *, session: Dict[str, object], identity: Dict[str, object]) -> Dict[str, object]:
        github_id = str(identity.get("github_id", "")).strip()
        github_login = self._normalize_github_login(str(identity.get("github_login", "")))
        if not github_id or not github_login:
            raise InvalidCredentialsError("GitHub identity is incomplete")

        display_name = self._normalize_display_name(
            str(identity.get("display_name", "")).strip(),
            str(identity.get("email", "")).strip() or github_login,
        )
        avatar_url = self._normalize_avatar_url(str(identity.get("avatar_url", "")), allow_empty=True)
        requested_by_user_id = session.get("requested_by_user_id")

        if requested_by_user_id is not None:
            return self._link_github_account(
                user_id=int(requested_by_user_id),
                github_id=github_id,
                github_login=github_login,
                avatar_url=avatar_url,
                display_name=display_name,
            )

        existing_github_user = self.repository.get_user_by_github_id(github_id)
        if existing_github_user:
            linked_user = self.repository.link_github_account(
                user_id=int(existing_github_user["id"]),
                github_id=github_id,
                github_login=github_login,
                avatar_url=avatar_url,
                display_name=display_name,
            )
            if not linked_user:
                raise InvalidCredentialsError("linked GitHub user could not be refreshed")
            return self.repository.touch_last_login(int(linked_user["id"])) or linked_user

        email = self._normalize_email(str(identity.get("email", "")), allow_empty=True)
        if email:
            existing_github_email_user = self.repository.get_user_by_email(email, auth_source="github")
            if existing_github_email_user:
                existing_email_github_id = str(existing_github_email_user.get("github_id", "")).strip()
                if existing_email_github_id and existing_email_github_id != github_id:
                    raise GitHubAccountConflictError(
                        "This GitHub email is already used by another GitHub login."
                    )

        fallback_email = email or self._build_github_fallback_email(github_id=github_id)
        try:
            created_user = self.repository.create_user(
                email=fallback_email,
                password_hash="",
                display_name=display_name,
                auth_source="github",
                github_id=github_id,
                github_login=github_login,
                avatar_url=avatar_url,
            )
        except IntegrityError as exc:
            raise EmailAlreadyExistsError("GitHub login email already exists for the same auth source") from exc
        return self.repository.touch_last_login(int(created_user["id"])) or created_user

    def _link_github_account(
        self,
        *,
        user_id: int,
        github_id: str,
        github_login: str,
        avatar_url: str,
        display_name: str,
    ) -> Dict[str, object]:
        current_user = self.repository.get_user_by_id(user_id)
        if not current_user or not bool(current_user.get("is_active", True)):
            raise InvalidCredentialsError("account does not exist or is disabled")

        linked_user = self.repository.get_user_by_github_id(github_id)
        if linked_user and int(linked_user["id"]) != user_id:
            raise GitHubAccountConflictError("This GitHub account is already linked to another NightShift account.")

        updated_user = self.repository.link_github_account(
            user_id=user_id,
            github_id=github_id,
            github_login=github_login,
            avatar_url=avatar_url,
            display_name=display_name,
        )
        if not updated_user:
            raise InvalidCredentialsError("failed to update GitHub account binding")
        return self.repository.touch_last_login(user_id) or updated_user

    def _sync_public_repositories(
        self,
        *,
        user: Dict[str, object],
        access_token: Optional[str],
        private_repo_count: Optional[object],
    ) -> Optional[Dict[str, object]]:
        github_login = str(user.get("github_login", "")).strip()
        if not github_login:
            return None

        normalized_private_repo_count = max(self._parse_positive_or_zero_int(private_repo_count), 0)

        try:
            repo_urls = self.github_oauth_client.list_public_repositories(
                github_login=github_login,
                access_token=access_token,
            )
            summary = self.subscription_service.sync_public_repositories(
                user_id=int(user["id"]),
                repo_urls=repo_urls,
                recipient_email=str(user.get("email", "")),
            )
            summary["private_repo_count"] = normalized_private_repo_count
            summary["message"] = self._build_repo_sync_message(summary)
            return summary
        except GitHubOAuthClientError as exc:
            return {
                "added_count": 0,
                "skipped_existing_count": 0,
                "public_repo_count": 0,
                "private_repo_count": normalized_private_repo_count,
                "message": f"GitHub 公开仓库自动添加未完成：{exc}；私有仓库不会自动添加。",
            }

    def _build_repo_sync_message(self, summary: Dict[str, object]) -> str:
        public_repo_count = max(int(summary.get("public_repo_count", 0) or 0), 0)
        added_count = max(int(summary.get("added_count", 0) or 0), 0)
        skipped_existing_count = max(int(summary.get("skipped_existing_count", 0) or 0), 0)
        private_repo_count = max(int(summary.get("private_repo_count", 0) or 0), 0)

        if public_repo_count > 0:
            message = f"已自动同步 {added_count} 个公开仓库"
            if skipped_existing_count > 0:
                message += f"，{skipped_existing_count} 个已存在"
        else:
            message = "未发现可自动导入的公开仓库"

        if private_repo_count > 0:
            return f"{message}；{private_repo_count} 个私有仓库未自动添加。"
        return f"{message}；私有仓库不会自动添加。"

    def _resolve_completed_message(self, *, flow_type: str, repo_sync: Optional[Dict[str, object]]) -> str:
        if repo_sync and str(repo_sync.get("message", "")).strip():
            return str(repo_sync["message"]).strip()
        if flow_type == "connect":
            return "GitHub 账号已连接，请返回 NightShift 继续操作。"
        return "GitHub 登录成功，请返回 NightShift 继续操作。"

    def _resolve_github_redirect_uri(self) -> str:
        explicit_redirect_uri = os.getenv(GITHUB_OAUTH_REDIRECT_URI_ENV, "").strip()
        if explicit_redirect_uri:
            try:
                return normalize_public_base_url(explicit_redirect_uri)
            except SecurityValidationError as exc:
                raise OAuthConfigurationError(str(exc)) from exc
        public_base_url = os.getenv(PUBLIC_BASE_URL_ENV, "").strip()
        if not public_base_url:
            raise OAuthConfigurationError(
                "GitHub OAuth requires NIGHTSHIFT_GITHUB_OAUTH_REDIRECT_URI or NIGHTSHIFT_PUBLIC_BASE_URL."
            )
        try:
            return normalize_public_base_url(public_base_url) + "/auth/github/callback"
        except SecurityValidationError as exc:
            raise OAuthConfigurationError(str(exc)) from exc

    def _build_github_fallback_email(self, *, github_id: str) -> str:
        normalized_id = str(github_id or "").strip() or "user"
        return f"github-{normalized_id}@users.nightshift.local"

    def _normalize_email(self, value: str, allow_empty: bool = False) -> str:
        try:
            return normalize_email(value, allow_empty=allow_empty)
        except SecurityValidationError as exc:
            raise InvalidCredentialsError(str(exc)) from exc

    def _normalize_display_name(self, value: Optional[str], email: str) -> str:
        fallback = str(email or "").split("@", 1)[0][:60]
        try:
            return normalize_display_name(value, fallback=fallback, allow_empty=False)
        except SecurityValidationError as exc:
            raise InvalidCredentialsError(str(exc)) from exc

    def _normalize_github_login(self, value: str, allow_empty: bool = False) -> str:
        try:
            return normalize_github_login(value, allow_empty=allow_empty)
        except SecurityValidationError as exc:
            raise InvalidCredentialsError(str(exc)) from exc

    def _normalize_avatar_url(self, value: str, allow_empty: bool = True) -> str:
        try:
            return normalize_avatar_url(value, allow_empty=allow_empty)
        except SecurityValidationError as exc:
            raise InvalidCredentialsError(str(exc)) from exc

    def _hash_password(self, password: str) -> str:
        normalized = password.strip()
        if len(normalized) < 8:
            raise InvalidCredentialsError("password must be at least 8 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            normalized.encode("utf-8"),
            salt,
            PASSWORD_HASH_ITERATIONS,
        )
        return "$".join(
            [
                PASSWORD_HASH_ALGORITHM,
                str(PASSWORD_HASH_ITERATIONS),
                self._b64url_encode(salt),
                self._b64url_encode(digest),
            ]
        )

    def _verify_password(self, password: str, password_hash: str) -> bool:
        try:
            algorithm, iterations_text, salt_text, digest_text = password_hash.split("$", 3)
        except ValueError:
            return False
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        try:
            iterations = int(iterations_text)
            salt = self._b64url_decode(salt_text)
            expected = self._b64url_decode(digest_text)
        except (TypeError, ValueError):
            return False
        calculated = hashlib.pbkdf2_hmac(
            "sha256",
            password.strip().encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(calculated, expected)

    def _encode_token(self, user: Dict[str, object]) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user["id"]),
            "email": str(user["email"]),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self._token_ttl)).timestamp()),
        }
        header_segment = self._b64url_encode(
            json.dumps({"alg": JWT_ALGORITHM, "typ": "JWT"}, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        payload_segment = self._b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
        signature = hmac.new(self._jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{header_segment}.{payload_segment}.{self._b64url_encode(signature)}"

    def _decode_token(self, token: str) -> Dict[str, object]:
        parts = token.strip().split(".")
        if len(parts) != 3:
            raise InvalidTokenError("invalid token format")
        header_segment, payload_segment, signature_segment = parts
        signing_input = f"{header_segment}.{payload_segment}".encode("utf-8")
        expected_signature = hmac.new(self._jwt_secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        provided_signature = self._b64url_decode(signature_segment)
        if not hmac.compare_digest(expected_signature, provided_signature):
            raise InvalidTokenError("invalid token signature")

        payload_raw = self._b64url_decode(payload_segment)
        try:
            payload = json.loads(payload_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidTokenError("invalid token payload") from exc

        exp = payload.get("exp")
        if not isinstance(exp, int):
            raise InvalidTokenError("invalid token expiration")
        if exp <= int(datetime.now(timezone.utc).timestamp()):
            raise InvalidTokenError("token expired")
        return payload

    def _b64url_encode(self, value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    def _b64url_decode(self, value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))

    def _is_oauth_session_expired(self, session: Dict[str, object]) -> bool:
        raw_expires_at = str(session.get("expires_at", "")).strip()
        if not raw_expires_at:
            return True
        normalized = raw_expires_at.replace("Z", "+00:00")
        try:
            expires_at = datetime.fromisoformat(normalized)
        except ValueError:
            return True
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at = expires_at.astimezone(timezone.utc)
        return expires_at <= datetime.now(timezone.utc)

    def _parse_positive_int(self, value: Optional[str], default: int) -> int:
        try:
            parsed = int(str(value).strip()) if value is not None else default
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _parse_positive_or_zero_int(self, value: Optional[object]) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed >= 0 else 0
