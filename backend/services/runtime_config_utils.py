from __future__ import annotations

from typing import Dict, Optional

from backend.clients.email_client import DEFAULT_DM_ENDPOINT, DEFAULT_DM_REGION_ID, EmailClientConfig
from backend.security import (
    SecurityValidationError,
    normalize_email,
    normalize_email_endpoint,
    normalize_llm_base_url,
    normalize_llm_model_name,
    normalize_runtime_region,
    normalize_runtime_secret,
)


DEFAULT_LLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_LLM_MODEL = "glm-4-flash"
LEGACY_LLM_MODEL_ALIASES = {
    "glm-4.5-flash": DEFAULT_LLM_MODEL,
}

LLM_RUNTIME_KEYS = (
    "github_token",
    "llm_api_key",
    "llm_base_url",
    "llm_model",
    "llm_temperature",
    "llm_top_p",
    "llm_max_tokens",
    "llm_timeout_seconds",
    "llm_max_retries",
)

EMAIL_RUNTIME_KEYS = (
    "email_access_key_id",
    "email_access_key_secret",
    "email_account_name",
    "email_region_id",
    "email_endpoint",
    "email_address_type",
    "email_reply_to_address",
    "email_from_alias",
    "email_connect_timeout_ms",
    "email_read_timeout_ms",
)

RUNTIME_CONFIG_MUTABLE_KEYS = LLM_RUNTIME_KEYS + EMAIL_RUNTIME_KEYS

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


def build_effective_runtime_config(raw: Dict[str, str]) -> Dict[str, object]:
    return {
        "github_token_configured": bool(_safe_runtime_secret(raw.get("github_token"), field_name="github_token")),
        "llm_api_key_configured": bool(_safe_runtime_secret(raw.get("llm_api_key"), field_name="llm_api_key")),
        "llm_base_url": _safe_llm_base_url(raw.get("llm_base_url")),
        "llm_model": _safe_llm_model(raw.get("llm_model")),
        "llm_temperature": _to_float_or_none(raw.get("llm_temperature"), min_value=0.0, max_value=2.0),
        "llm_top_p": _to_float_or_none(raw.get("llm_top_p"), min_value=0.0, max_value=1.0),
        "llm_max_tokens": _to_int_or_none(raw.get("llm_max_tokens"), min_value=1, max_value=32000),
        "llm_timeout_seconds": _to_float(
            raw.get("llm_timeout_seconds"),
            PERSISTED_LLM_DEFAULTS["llm_timeout_seconds"],
            min_value=1.0,
            max_value=120.0,
        ),
        "llm_max_retries": _to_int(
            raw.get("llm_max_retries"),
            PERSISTED_LLM_DEFAULTS["llm_max_retries"],
            min_value=0,
            max_value=5,
        ),
        "email_access_key_id_configured": bool(
            _safe_runtime_secret(raw.get("email_access_key_id"), field_name="email_access_key_id")
        ),
        "email_access_key_secret_configured": bool(
            _safe_runtime_secret(raw.get("email_access_key_secret"), field_name="email_access_key_secret")
        ),
        "email_account_name": _safe_email_account_name(raw.get("email_account_name")),
        "email_region_id": _safe_email_region(raw.get("email_region_id")),
        "email_endpoint": _safe_email_endpoint(raw.get("email_endpoint")),
        "email_address_type": _to_int(
            raw.get("email_address_type"),
            PERSISTED_EMAIL_DEFAULTS["email_address_type"],
            min_value=0,
            max_value=1,
        ),
        "email_reply_to_address": _to_bool(
            raw.get("email_reply_to_address"),
            PERSISTED_EMAIL_DEFAULTS["email_reply_to_address"],
        ),
        "email_from_alias": _clean_string(raw.get("email_from_alias")),
        "email_connect_timeout_ms": _to_int(
            raw.get("email_connect_timeout_ms"),
            PERSISTED_EMAIL_DEFAULTS["email_connect_timeout_ms"],
            min_value=1000,
            max_value=60000,
        ),
        "email_read_timeout_ms": _to_int(
            raw.get("email_read_timeout_ms"),
            PERSISTED_EMAIL_DEFAULTS["email_read_timeout_ms"],
            min_value=1000,
            max_value=120000,
        ),
    }


def build_llm_config_overrides(raw: Dict[str, str]) -> Dict[str, object]:
    return {
        "api_key": _safe_runtime_secret(raw.get("llm_api_key"), field_name="llm_api_key"),
        "base_url": _safe_llm_base_url(raw.get("llm_base_url")),
        "model": _safe_llm_model(raw.get("llm_model")),
        "temperature": _to_float_or_none(raw.get("llm_temperature"), min_value=0.0, max_value=2.0),
        "top_p": _to_float_or_none(raw.get("llm_top_p"), min_value=0.0, max_value=1.0),
        "max_tokens": _to_int_or_none(raw.get("llm_max_tokens"), min_value=1, max_value=32000),
        "timeout_seconds": _to_float(
            raw.get("llm_timeout_seconds"),
            PERSISTED_LLM_DEFAULTS["llm_timeout_seconds"],
            min_value=1.0,
            max_value=120.0,
        ),
        "max_retries": _to_int(
            raw.get("llm_max_retries"),
            PERSISTED_LLM_DEFAULTS["llm_max_retries"],
            min_value=0,
            max_value=5,
        ),
    }


def build_email_config(raw: Dict[str, str]) -> Optional[EmailClientConfig]:
    access_key_id = _safe_runtime_secret(raw.get("email_access_key_id"), field_name="email_access_key_id")
    access_key_secret = _safe_runtime_secret(raw.get("email_access_key_secret"), field_name="email_access_key_secret")
    account_name = _safe_email_account_name(raw.get("email_account_name"))
    if not access_key_id or not access_key_secret or not account_name:
        return None

    return EmailClientConfig(
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        account_name=account_name,
        region_id=_safe_email_region(raw.get("email_region_id")),
        endpoint=_safe_email_endpoint(raw.get("email_endpoint")),
        address_type=_to_int(
            raw.get("email_address_type"),
            PERSISTED_EMAIL_DEFAULTS["email_address_type"],
            min_value=0,
            max_value=1,
        ),
        reply_to_address=_to_bool(raw.get("email_reply_to_address"), PERSISTED_EMAIL_DEFAULTS["email_reply_to_address"]),
        from_alias=_clean_string(raw.get("email_from_alias")),
        connect_timeout_ms=_to_int(
            raw.get("email_connect_timeout_ms"),
            PERSISTED_EMAIL_DEFAULTS["email_connect_timeout_ms"],
            min_value=1000,
            max_value=60000,
        ),
        read_timeout_ms=_to_int(
            raw.get("email_read_timeout_ms"),
            PERSISTED_EMAIL_DEFAULTS["email_read_timeout_ms"],
            min_value=1000,
            max_value=120000,
        ),
    )


def _clean_string(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _normalize_llm_model(value: object) -> str:
    normalized = _clean_string(value)
    if not normalized:
        return PERSISTED_LLM_DEFAULTS["llm_model"]
    return LEGACY_LLM_MODEL_ALIASES.get(normalized.lower(), normalized)


def _to_int(value: object, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    try:
        parsed = int(value) if value is not None and value != "" else default
    except (TypeError, ValueError):
        return default
    if min_value is not None and parsed < min_value:
        return default
    if max_value is not None and parsed > max_value:
        return default
    return parsed


def _to_float(
    value: object,
    default: float,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> float:
    try:
        parsed = float(value) if value is not None and value != "" else default
    except (TypeError, ValueError):
        return default
    if min_value is not None and parsed < min_value:
        return default
    if max_value is not None and parsed > max_value:
        return default
    return parsed


def _to_int_or_none(value: object, min_value: Optional[int] = None, max_value: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if min_value is not None and parsed < min_value:
        return None
    if max_value is not None and parsed > max_value:
        return None
    return parsed


def _to_float_or_none(
    value: object,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if min_value is not None and parsed < min_value:
        return None
    if max_value is not None and parsed > max_value:
        return None
    return parsed


def _to_bool(value: object, default: bool) -> bool:
    if value is None or value == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _safe_runtime_secret(value: object, *, field_name: str) -> str:
    try:
        return normalize_runtime_secret(value, field_name=field_name, allow_empty=True)
    except SecurityValidationError:
        return ""


def _safe_llm_base_url(value: object) -> str:
    try:
        return normalize_llm_base_url(value, allow_empty=True) or PERSISTED_LLM_DEFAULTS["llm_base_url"]
    except SecurityValidationError:
        return PERSISTED_LLM_DEFAULTS["llm_base_url"]


def _safe_llm_model(value: object) -> str:
    try:
        normalized = normalize_llm_model_name(value, allow_empty=True)
    except SecurityValidationError:
        normalized = ""
    if not normalized:
        return PERSISTED_LLM_DEFAULTS["llm_model"]
    return LEGACY_LLM_MODEL_ALIASES.get(normalized.lower(), normalized)


def _safe_email_account_name(value: object) -> str:
    try:
        return normalize_email(value, allow_empty=True)
    except SecurityValidationError:
        return ""


def _safe_email_region(value: object) -> str:
    try:
        return normalize_runtime_region(value, allow_empty=True) or PERSISTED_EMAIL_DEFAULTS["email_region_id"]
    except SecurityValidationError:
        return PERSISTED_EMAIL_DEFAULTS["email_region_id"]


def _safe_email_endpoint(value: object) -> str:
    try:
        return normalize_email_endpoint(value, allow_empty=True) or PERSISTED_EMAIL_DEFAULTS["email_endpoint"]
    except SecurityValidationError:
        return PERSISTED_EMAIL_DEFAULTS["email_endpoint"]
