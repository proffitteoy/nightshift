from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from backend.api.dependencies import (
    AUTH_SESSION_COOKIE_NAME,
    get_auth_service,
    get_current_user,
    get_optional_current_user,
    get_project_service,
    get_subscription_service,
    get_trending_service,
)
from backend.models.schemas import GitHubTokenRequest, LLMRuntimeConfigRequest, MessageResponse, RootResponse
from backend.security import (
    SecurityValidationError,
    normalize_proxy_target_url,
    normalize_runtime_secret,
    sanitize_untrusted_text,
)
from backend.services.auth_service import AuthService, InvalidTokenError
from backend.services.project_service import ProjectService
from backend.services.subscription_service import SubscriptionService


router = APIRouter(tags=["general"])
MAX_PROXY_BODY_BYTES = 2 * 1024 * 1024
SHOWCASE_ACCESS_TOKEN_QUERY = "access_token"
SHOWCASE_TAB3_DEFAULT_GITHUB_TOKEN_ENV = "TAB3_DEFAULT_GITHUB_TOKEN"


@router.get("/", response_model=RootResponse)
def read_root() -> RootResponse:
    return {"message": "Welcome to NightShift API"}


@router.get("/api/health", response_model=MessageResponse)
def read_health() -> MessageResponse:
    return {"message": "ok"}


@router.get("/favicon.ico", include_in_schema=False)
def read_favicon() -> FileResponse:
    assets_dir = Path(__file__).resolve().parents[2] / "static" / "showcase" / "atlas" / "assets"
    png_favicon = assets_dir / "nightshift.png"
    if png_favicon.exists():
        return FileResponse(path=png_favicon, media_type="image/png")

    svg_favicon = assets_dir / "panorama-favicon.svg"
    if svg_favicon.exists():
        return FileResponse(path=svg_favicon, media_type="image/svg+xml")

    raise HTTPException(status_code=404, detail={"code": "FAVICON_NOT_FOUND", "message": "favicon asset is missing"})


@router.get("/showcase/atlas", include_in_schema=False)
def redirect_showcase_atlas(request: Request) -> RedirectResponse:
    return RedirectResponse(url=str(request.url.replace(path="/showcase/atlas/")), status_code=307)


@router.get("/showcase/atlas/", include_in_schema=False)
def read_showcase_atlas(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    index_file = Path(__file__).resolve().parents[2] / "static" / "showcase" / "atlas" / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail={"code": "SHOWCASE_NOT_FOUND", "message": "atlas showcase index is missing"},
        )

    bootstrap_token = _extract_showcase_bootstrap_token(request)
    validated_token = _validate_showcase_bootstrap_token(bootstrap_token, auth_service=auth_service)

    if SHOWCASE_ACCESS_TOKEN_QUERY in request.query_params:
        response = RedirectResponse(url=str(request.url.replace(query="")), status_code=307)
    else:
        response = HTMLResponse(_inject_showcase_runtime_config(index_file))

    _set_showcase_bootstrap_headers(response)
    if validated_token:
        _set_showcase_auth_cookie(
            response,
            token=validated_token,
            secure=request.url.scheme == "https",
        )
    elif SHOWCASE_ACCESS_TOKEN_QUERY in request.query_params:
        response.delete_cookie(AUTH_SESSION_COOKIE_NAME, path="/", samesite="lax")
    return response


@router.api_route("/api/proxy", methods=["GET", "POST", "OPTIONS"])
async def proxy_github_request(
    request: Request,
    current_user: dict | None = Depends(get_optional_current_user),
    project_service: ProjectService = Depends(get_project_service),
) -> Response:
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, Git-Protocol, Accept",
            },
        )

    url = str(request.query_params.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=400, detail={"code": "MISSING_PROXY_URL", "message": "url query parameter is required"})

    try:
        normalized_url = normalize_proxy_target_url(url)
    except SecurityValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PROXY_URL", "message": str(exc)}) from exc

    forward_headers = {"User-Agent": "git/isomorphic-git"}
    header_mapping = {
        "content-type": "Content-Type",
        "git-protocol": "Git-Protocol",
        "accept": "Accept",
    }
    for source_name, target_name in header_mapping.items():
        if source_name in request.headers:
            forward_headers[target_name] = sanitize_untrusted_text(
                request.headers[source_name],
                max_length=200,
            )

    runtime_authorizations = _build_runtime_proxy_authorizations(
        token=project_service.get_runtime_token(
            user_id=int(current_user["id"]) if current_user else None,
        ),
    )
    body = await request.body() if request.method == "POST" else None
    if body and len(body) > MAX_PROXY_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "PROXY_BODY_TOO_LARGE", "message": "proxy request body exceeds 2MB"},
        )

    try:
        upstream = None
        authorization_attempts = runtime_authorizations if runtime_authorizations else [None]
        for authorization in authorization_attempts:
            retry_headers = dict(forward_headers)
            if authorization:
                retry_headers["Authorization"] = authorization
            upstream = requests.request(
                method=request.method,
                url=normalized_url,
                headers=retry_headers,
                data=body if body else None,
                timeout=60,
            )
            if upstream.status_code != 401 or authorization is None:
                break
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail={"code": "PROXY_REQUEST_FAILED", "message": str(exc)}) from exc

    if upstream is None:
        raise HTTPException(status_code=502, detail={"code": "PROXY_REQUEST_FAILED", "message": "upstream request failed"})

    skip_headers = {"content-encoding", "transfer-encoding", "connection", "www-authenticate"}
    response_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "*",
    }
    for key, value in upstream.headers.items():
        if key.lower() not in skip_headers:
            response_headers[key] = value

    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


def _build_runtime_proxy_authorizations(token: str | None) -> list[str]:
    normalized = token.strip() if token else ""
    if not normalized:
        return []

    candidates = [
        f"x-access-token:{normalized}",
        f"{normalized}:x-oauth-basic",
    ]
    authorizations: list[str] = []
    for candidate in candidates:
        encoded = base64.b64encode(candidate.encode("utf-8")).decode("ascii")
        authorizations.append(f"Basic {encoded}")
    return authorizations


def _extract_showcase_bootstrap_token(request: Request) -> str:
    authorization = str(request.headers.get("authorization", "")).strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return str(request.query_params.get(SHOWCASE_ACCESS_TOKEN_QUERY, "")).strip()


def _validate_showcase_bootstrap_token(
    token: str,
    *,
    auth_service: AuthService,
) -> str | None:
    normalized = token.strip()
    if not normalized:
        return None
    try:
        normalized = normalize_runtime_secret(
            normalized,
            field_name="access token",
            max_length=4096,
        )
        auth_service.get_user_from_token(normalized)
    except (InvalidTokenError, SecurityValidationError):
        return None
    return normalized


def _set_showcase_bootstrap_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Vary"] = "Authorization, Cookie"


def _set_showcase_auth_cookie(response: Response, *, token: str, secure: bool) -> None:
    response.set_cookie(
        key=AUTH_SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def _inject_showcase_runtime_config(index_file: Path) -> str:
    html = index_file.read_text(encoding="utf-8")
    config_payload = {
        "embedded": True,
        "disableLocalProject": True,
        "defaultGithubToken": os.getenv(SHOWCASE_TAB3_DEFAULT_GITHUB_TOKEN_ENV, "").strip(),
    }
    config_json = json.dumps(config_payload, ensure_ascii=False).replace("</", "<\\/")
    config_script = (
        "<script>"
        "window.__NIGHTSHIFT_TAB3_CONFIG__ = Object.assign({}, "
        "window.__NIGHTSHIFT_TAB3_CONFIG__ || {}, "
        f"{config_json}"
        ");"
        "</script>"
    )
    if "</head>" in html:
        return html.replace("</head>", f"  {config_script}\n</head>", 1)
    return f"{config_script}\n{html}"


@router.post("/api/config/token", response_model=MessageResponse)
def set_github_token(
    request: GitHubTokenRequest,
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> MessageResponse:
    token = request.token.strip()
    if not token:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_TOKEN", "message": "token cannot be empty"},
        )

    subscription_service.update_runtime_config(
        user_id=int(current_user["id"]),
        payload={"github_token": token},
    )
    return {"message": "GitHub token saved for current user"}


@router.post("/api/config/llm", response_model=MessageResponse)
def set_llm_runtime_config(
    request: LLMRuntimeConfigRequest,
    current_user: dict = Depends(get_current_user),
    subscription_service: SubscriptionService = Depends(get_subscription_service),
) -> MessageResponse:
    api_key = request.api_key.strip()
    base_url = request.base_url.strip()
    model = request.model.strip()
    if not api_key or not base_url or not model:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_LLM_CONFIG", "message": "api_key, base_url, model are required"},
        )

    subscription_service.update_runtime_config(
        user_id=int(current_user["id"]),
        payload={
            "llm_api_key": api_key,
            "llm_base_url": base_url,
            "llm_model": model,
            "llm_temperature": request.temperature,
            "llm_top_p": request.top_p,
            "llm_max_tokens": request.max_tokens,
            "llm_timeout_seconds": request.timeout_seconds,
            "llm_max_retries": request.max_retries,
        },
    )
    get_trending_service.cache_clear()
    return {"message": f"LLM runtime config saved for current user: model={model}"}
