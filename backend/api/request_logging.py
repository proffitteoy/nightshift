from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


LOGGER = logging.getLogger("nightshift.api")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            latency_ms = int((time.perf_counter() - start) * 1000)
            LOGGER.exception(
                "request failed: id=%s method=%s path=%s latency_ms=%s",
                request_id,
                request.method,
                request.url.path,
                latency_ms,
            )
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)
        LOGGER.info(
            "request handled: id=%s method=%s path=%s status=%s latency_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
        )
        response.headers["X-Request-Id"] = request_id
        if request.url.path.startswith("/showcase"):
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
            response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response
