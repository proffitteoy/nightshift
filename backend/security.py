from __future__ import annotations

import hashlib
import os
import re
from typing import Iterable
from urllib.parse import urlparse, urlunparse


PUBLIC_BASE_URL_ENV = "NIGHTSHIFT_PUBLIC_BASE_URL"
ALLOWED_LLM_HOSTS_ENV = "NIGHTSHIFT_ALLOWED_LLM_HOSTS"
ALLOWED_EMAIL_ENDPOINTS_ENV = "NIGHTSHIFT_ALLOWED_EMAIL_ENDPOINTS"
ALLOWED_PROXY_HOSTS_ENV = "NIGHTSHIFT_PROXY_ALLOWED_HOSTS"

DEFAULT_ALLOWED_LLM_HOSTS = ("open.bigmodel.cn",)
DEFAULT_ALLOWED_EMAIL_ENDPOINTS = ("dm.aliyuncs.com",)
DEFAULT_ALLOWED_PROXY_HOSTS = ("github.com", "raw.githubusercontent.com", "codeload.github.com")

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
REPO_FULL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
GITHUB_LOGIN_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,39}$")
RUNTIME_REGION_PATTERN = re.compile(r"^[A-Za-z0-9-]{2,40}$")
CONTROL_CHARS_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SecurityValidationError(ValueError):
    pass


def normalize_email(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("email is required")
    if len(normalized) > 320 or not EMAIL_PATTERN.match(normalized):
        raise SecurityValidationError("email must be a valid email address")
    return normalized.lower()


def normalize_display_name(value: object, *, fallback: str = "", allow_empty: bool = False) -> str:
    normalized = sanitize_untrusted_text(value, max_length=60, allow_empty=True)
    if normalized:
        return normalized
    fallback_value = sanitize_untrusted_text(fallback, max_length=60, allow_empty=True)
    if fallback_value:
        return fallback_value
    if allow_empty:
        return ""
    raise SecurityValidationError("display_name is required")


def normalize_github_login(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("github_login is required")
    if not GITHUB_LOGIN_PATTERN.match(normalized):
        raise SecurityValidationError("github_login is invalid")
    return normalized


def normalize_avatar_url(value: object, *, allow_empty: bool = True) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("avatar_url is required")
    parsed = _parse_url(normalized, field_name="avatar_url")
    if parsed.scheme not in {"http", "https"}:
        raise SecurityValidationError("avatar_url must use http or https")
    if parsed.username or parsed.password or parsed.fragment:
        raise SecurityValidationError("avatar_url contains unsupported components")
    if len(normalized) > 500:
        raise SecurityValidationError("avatar_url is too long")
    return normalized


def normalize_repo_full_name(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("repo_full_name is required")
    if not REPO_FULL_NAME_PATTERN.match(normalized):
        raise SecurityValidationError("repo_full_name must use owner/repo format")
    return normalized


def normalize_github_repo_url(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("repo_url is required")
    parsed = _parse_url(normalized, field_name="repo_url")
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        raise SecurityValidationError("repo_url must use http or https")
    if host not in {"github.com", "www.github.com"}:
        raise SecurityValidationError("repo_url must point to github.com")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise SecurityValidationError("repo_url contains unsupported components")
    repo_full_name = normalize_repo_full_name(parsed.path.strip("/").replace(".git", ""))
    return f"https://github.com/{repo_full_name}"


def normalize_runtime_secret(value: object, *, field_name: str, allow_empty: bool = False, max_length: int = 512) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError(f"{field_name} is required")
    if len(normalized) > max_length:
        raise SecurityValidationError(f"{field_name} is too long")
    return normalized


def normalize_llm_model_name(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("llm_model is required")
    if not MODEL_NAME_PATTERN.match(normalized):
        raise SecurityValidationError("llm_model contains unsupported characters")
    return normalized


def normalize_llm_base_url(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("llm_base_url is required")
    parsed = _parse_url(normalized, field_name="llm_base_url")
    if parsed.scheme != "https":
        raise SecurityValidationError("llm_base_url must use https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SecurityValidationError("llm_base_url contains unsupported components")
    allowed_hosts = _load_allowed_hosts(ALLOWED_LLM_HOSTS_ENV, DEFAULT_ALLOWED_LLM_HOSTS)
    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts:
        raise SecurityValidationError("llm_base_url host is not allowed")
    normalized_path = parsed.path or "/"
    if not normalized_path.endswith("/"):
        normalized_path += "/"
    return urlunparse((parsed.scheme, host, normalized_path, "", "", ""))


def normalize_email_endpoint(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("email_endpoint is required")
    allowed_hosts = _load_allowed_hosts(ALLOWED_EMAIL_ENDPOINTS_ENV, DEFAULT_ALLOWED_EMAIL_ENDPOINTS)
    if "://" not in normalized:
        host = normalized.lower()
        if "/" in host or "?" in host or "#" in host or "@" in host or ":" in host:
            raise SecurityValidationError("email_endpoint must be a plain hostname")
        if host not in allowed_hosts:
            raise SecurityValidationError("email_endpoint host is not allowed")
        return host

    parsed = _parse_url(normalized, field_name="email_endpoint")
    if parsed.scheme != "https":
        raise SecurityValidationError("email_endpoint must use https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port:
        raise SecurityValidationError("email_endpoint contains unsupported components")
    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts:
        raise SecurityValidationError("email_endpoint host is not allowed")
    if parsed.path not in {"", "/"}:
        raise SecurityValidationError("email_endpoint must not include a path")
    return host


def normalize_runtime_region(value: object, *, allow_empty: bool = False) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("region_id is required")
    if not RUNTIME_REGION_PATTERN.match(normalized):
        raise SecurityValidationError("region_id is invalid")
    return normalized


def normalize_public_base_url(value: object) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        raise SecurityValidationError("public base URL is required")
    parsed = _parse_url(normalized, field_name="public base URL")
    if parsed.scheme not in {"http", "https"}:
        raise SecurityValidationError("public base URL must use http or https")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SecurityValidationError("public base URL contains unsupported components")
    normalized_path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc.lower(), normalized_path, "", "", ""))


def normalize_proxy_target_url(value: object) -> str:
    normalized = _strip_and_reject_controls(value)
    if not normalized:
        raise SecurityValidationError("proxy url is required")
    parsed = _parse_url(normalized, field_name="proxy url")
    if parsed.scheme != "https":
        raise SecurityValidationError("proxy target must use https")
    if parsed.username or parsed.password or parsed.fragment or parsed.port:
        raise SecurityValidationError("proxy target contains unsupported components")
    allowed_hosts = _load_allowed_hosts(ALLOWED_PROXY_HOSTS_ENV, DEFAULT_ALLOWED_PROXY_HOSTS)
    host = (parsed.hostname or "").lower()
    if host not in allowed_hosts:
        raise SecurityValidationError("proxy target host is not allowed")
    return urlunparse((parsed.scheme, host, parsed.path or "/", "", parsed.query, ""))


def sanitize_untrusted_text(
    value: object,
    *,
    max_length: int,
    allow_empty: bool = False,
    preserve_newlines: bool = False,
) -> str:
    text = str(value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_CHARS_PATTERN.sub("", text)
    if not preserve_newlines:
        text = text.replace("\n", " ").replace("\t", " ")
        text = re.sub(r"\s+", " ", text)
    else:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
    normalized = text.strip()
    if not normalized:
        if allow_empty:
            return ""
        raise SecurityValidationError("text value is required")
    return normalized[:max_length]


def fingerprint_secret(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "anonymous"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _strip_and_reject_controls(value: object) -> str:
    normalized = str(value or "").strip()
    if CONTROL_CHARS_PATTERN.search(normalized):
        raise SecurityValidationError("value contains unsupported control characters")
    return normalized


def _parse_url(value: str, *, field_name: str):
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        raise SecurityValidationError(f"{field_name} is invalid")
    if not parsed.hostname:
        raise SecurityValidationError(f"{field_name} is invalid")
    return parsed


def _load_allowed_hosts(env_name: str, defaults: Iterable[str]) -> set[str]:
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return {item.strip().lower() for item in defaults if item.strip()}
    return {item.strip().lower() for item in raw.split(",") if item.strip()}
