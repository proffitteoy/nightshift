from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.security import SecurityValidationError, normalize_runtime_secret
from backend.services.auth_service import AuthService, InvalidTokenError


bearer_scheme = HTTPBearer(auto_error=False)
AUTH_SESSION_COOKIE_NAME = "nightshift_access_token"


@lru_cache
def get_project_service():
    from backend.services.project_service import ProjectService

    return ProjectService()


@lru_cache
def get_trending_service():
    from backend.services.trending_service import TrendingService

    return TrendingService()


@lru_cache
def get_code_panorama_service():
    from backend.services.code_panorama_service import CodePanoramaService

    return CodePanoramaService()


@lru_cache
def get_subscription_repository():
    from backend.repositories.subscription_repository import SubscriptionRepository

    return SubscriptionRepository()


@lru_cache
def get_user_repository():
    from backend.repositories.user_repository import UserRepository

    return UserRepository()


@lru_cache
def get_auth_session_repository():
    from backend.repositories.auth_session_repository import AuthSessionRepository

    return AuthSessionRepository()


@lru_cache
def get_auth_service():
    return AuthService(
        repository=get_user_repository(),
        auth_session_repository=get_auth_session_repository(),
        subscription_service=get_subscription_service(),
    )


@lru_cache
def get_subscription_service():
    from backend.services.subscription_service import SubscriptionService

    return SubscriptionService(repository=get_subscription_repository())


@lru_cache
def get_subscription_delivery_service():
    from backend.services.subscription_delivery_service import SubscriptionDeliveryService

    return SubscriptionDeliveryService(
        repository=get_subscription_repository(),
        project_service=get_project_service(),
    )


def _authenticate_access_token(
    token: str,
    *,
    auth_service: AuthService,
    strict: bool,
):
    try:
        normalized = normalize_runtime_secret(
            token,
            field_name="access token",
            max_length=4096,
        )
        return auth_service.get_user_from_token(normalized)
    except (InvalidTokenError, SecurityValidationError) as exc:
        if not strict:
            return None
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_AUTH_TOKEN", "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
):
    if credentials is not None:
        return _authenticate_access_token(
            credentials.credentials,
            auth_service=auth_service,
            strict=True,
        )

    cookie_token = str(request.cookies.get(AUTH_SESSION_COOKIE_NAME, "")).strip()
    if not cookie_token:
        return None
    return _authenticate_access_token(
        cookie_token,
        auth_service=auth_service,
        strict=False,
    )


def get_current_user(current_user=Depends(get_optional_current_user)):
    if current_user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "authentication is required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
