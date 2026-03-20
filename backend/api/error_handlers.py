from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse


SERVER_ERROR_MESSAGES = {
    "GITHUB_OAUTH_NOT_CONFIGURED": "GitHub OAuth is not configured.",
    "PROXY_REQUEST_FAILED": "upstream request failed",
    "SUBSCRIBE_BUSY": "resource is busy, retry later",
    "SUBSCRIBE_FAILED": "project subscription failed",
    "REPORT_BUSY": "report generation is busy, retry later",
    "REPORT_FAILED": "report generation failed",
    "REPORT_QA_FAILED": "report question answering failed",
    "PANORAMA_BUSY": "code panorama generation is busy, retry later",
    "PANORAMA_FAILED": "code panorama generation failed",
    "TRENDING_FAILED": "trending fetch failed",
    "ANALYSIS_BUSY": "analysis generation is busy, retry later",
    "ANALYSIS_FAILED": "analysis generation failed",
    "TRENDING_DETAIL_SUMMARY_FAILED": "detail summary generation failed",
    "CREATE_SUBSCRIPTION_FAILED": "subscription creation failed",
    "UPDATE_SUBSCRIPTION_FAILED": "subscription update failed",
    "DELETE_SUBSCRIPTION_FAILED": "subscription deletion failed",
    "SUBSCRIPTION_DELIVERY_FAILED": "subscription delivery failed",
    "INTERNAL_ERROR": "internal server error",
}


def _normalize_http_error(detail: object) -> dict:
    if isinstance(detail, dict):
        if "success" in detail and "error" in detail:
            return detail
        if "code" in detail and "message" in detail:
            return {"success": False, "error": detail}
    return {
        "success": False,
        "error": {
            "code": "HTTP_ERROR",
            "message": str(detail),
        },
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
        payload = _normalize_http_error(exc.detail)
        if exc.status_code >= 500:
            code = str(payload.get("error", {}).get("code", "")).strip() or "INTERNAL_ERROR"
            payload["error"]["message"] = SERVER_ERROR_MESSAGES.get(code, SERVER_ERROR_MESSAGES["INTERNAL_ERROR"])
            request_id = getattr(getattr(request, "state", None), "request_id", "")
            if request_id:
                payload["error"]["request_id"] = request_id
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request, _: Exception) -> JSONResponse:
        request_id = getattr(getattr(request, "state", None), "request_id", "")
        payload = {
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": SERVER_ERROR_MESSAGES["INTERNAL_ERROR"],
            },
        }
        if request_id:
            payload["error"]["request_id"] = request_id
        return JSONResponse(
            status_code=500,
            content=payload,
        )
