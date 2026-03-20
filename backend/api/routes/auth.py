from __future__ import annotations

import html

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from backend.api.dependencies import get_auth_service, get_current_user, get_optional_current_user
from backend.models.schemas import (
    AuthChangePasswordRequest,
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthTokenResponse,
    GitHubOAuthPollResponse,
    GitHubOAuthStartResponse,
    MessageResponse,
    UserProfileResponse,
)
from backend.services.auth_service import (
    AuthService,
    EmailAlreadyExistsError,
    GitHubAccountConflictError,
    InvalidCredentialsError,
    OAuthConfigurationError,
    OAuthSessionNotFoundError,
    PasswordChangeNotAllowedError,
)


router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=AuthTokenResponse)
def register(
    request: AuthRegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        return auth_service.register_user(
            email=request.email,
            password=request.password,
            display_name=request.display_name,
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "EMAIL_ALREADY_EXISTS", "message": str(exc)},
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_REGISTER_REQUEST", "message": str(exc)},
        ) from exc


@router.post("/auth/login", response_model=AuthTokenResponse)
def login(
    request: AuthLoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthTokenResponse:
    try:
        return auth_service.login_user(email=request.email, password=request.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_CREDENTIALS", "message": str(exc)},
        ) from exc


@router.post("/auth/change-password", response_model=MessageResponse)
def change_password(
    request: AuthChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> MessageResponse:
    try:
        auth_service.change_password(
            user_id=int(current_user["id"]),
            current_password=request.current_password,
            new_password=request.new_password,
        )
    except PasswordChangeNotAllowedError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "PASSWORD_CHANGE_NOT_ALLOWED", "message": str(exc)},
        ) from exc
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_PASSWORD_CHANGE_REQUEST", "message": str(exc)},
        ) from exc
    return {"message": "password updated"}


@router.post("/auth/github/start", response_model=GitHubOAuthStartResponse)
def start_github_oauth(
    current_user: dict | None = Depends(get_optional_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> GitHubOAuthStartResponse:
    try:
        return auth_service.start_github_oauth(current_user=current_user)
    except OAuthConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "GITHUB_OAUTH_NOT_CONFIGURED", "message": str(exc)},
        ) from exc


@router.get("/auth/github/poll/{poll_token}", response_model=GitHubOAuthPollResponse)
def poll_github_oauth(
    poll_token: str,
    auth_service: AuthService = Depends(get_auth_service),
) -> GitHubOAuthPollResponse:
    try:
        return auth_service.poll_github_oauth(poll_token=poll_token)
    except OAuthSessionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "GITHUB_OAUTH_SESSION_NOT_FOUND", "message": str(exc)},
        ) from exc


@router.get("/auth/github/callback", response_class=HTMLResponse)
def github_oauth_callback(
    state: str = Query(default=""),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    auth_service: AuthService = Depends(get_auth_service),
) -> HTMLResponse:
    result = auth_service.complete_github_oauth(
        state_token=state,
        code=code,
        error=error,
        error_description=error_description,
    )
    return HTMLResponse(_build_callback_page(result.get("status") == "completed", str(result.get("message", ""))))


@router.get("/me", response_model=UserProfileResponse)
def read_me(current_user: dict = Depends(get_current_user)) -> UserProfileResponse:
    return current_user


def _build_callback_page(success: bool, message: str) -> str:
    escaped_message = html.escape(message)
    title = "GitHub 授权已完成" if success else "GitHub 授权失败"
    accent = "#2f7d32" if success else "#b42318"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", sans-serif;
      background: #f6f8fb;
      color: #111827;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 24px;
    }}
    .card {{
      width: min(480px, 100%);
      background: #ffffff;
      border-radius: 18px;
      box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12);
      padding: 28px;
      border-top: 6px solid {accent};
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 22px;
    }}
    p {{
      margin: 0 0 20px;
      line-height: 1.6;
      color: #475467;
    }}
    button {{
      border: none;
      border-radius: 999px;
      padding: 12px 18px;
      background: #111827;
      color: white;
      font-size: 14px;
      cursor: pointer;
    }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{title}</h1>
    <p>{escaped_message}</p>
    <button type="button" onclick="window.close()">关闭此页</button>
  </div>
</body>
</html>"""
