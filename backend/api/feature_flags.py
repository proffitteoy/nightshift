from __future__ import annotations

import os

from fastapi import HTTPException


FEATURE_ENV_MAPPING = {
    "code_panorama": "NIGHTSHIFT_FEATURE_CODE_PANORAMA",
    "subscriptions": "NIGHTSHIFT_FEATURE_SUBSCRIPTIONS",
}


def is_feature_enabled(feature_name: str) -> bool:
    env_name = FEATURE_ENV_MAPPING.get(feature_name)
    if not env_name:
        return True
    raw_value = os.getenv(env_name, "true").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def require_feature_enabled(feature_name: str) -> None:
    if is_feature_enabled(feature_name):
        return
    raise HTTPException(
        status_code=503,
        detail={"code": "FEATURE_DISABLED", "message": f"feature '{feature_name}' is disabled"},
    )
