from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.dependencies import get_subscription_delivery_service
from backend.api.error_handlers import install_error_handlers
from backend.api.request_logging import RequestLoggingMiddleware
from backend.api.routes.auth import router as auth_router
from backend.api.routes.code_panorama import router as code_panorama_router
from backend.api.routes.general import router as general_router
from backend.api.routes.project import router as project_router
from backend.api.routes.subscriptions import router as subscriptions_router
from backend.api.routes.trending import router as trending_router
from backend.api.routes.llm_proxy import router as llm_proxy_router
from backend.repositories.paths import ensure_runtime_dirs
def _load_local_env_file() -> None:
    candidate_paths = [
        Path(__file__).resolve().parents[1] / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for env_path in candidate_paths:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key or not value:
                continue
            if key not in os.environ:
                os.environ[key] = value


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=os.getenv("NIGHTSHIFT_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
def create_app() -> FastAPI:
    _load_local_env_file()
    _configure_logging()
    app = FastAPI(
        title="NightShift API",
        description="Refactored backend aligned with the docs contract",
        version="2.0.0",
    )

    ensure_runtime_dirs()
    app.add_middleware(RequestLoggingMiddleware)
    install_error_handlers(app)

    app.include_router(auth_router)
    app.include_router(general_router)
    app.include_router(project_router)
    app.include_router(trending_router)
        app.include_router(llm_proxy_router)
    app.include_router(code_panorama_router)
    app.include_router(subscriptions_router)

    showcase_dir = Path(__file__).resolve().parents[1] / "static" / "showcase"
    if showcase_dir.exists():
        app.mount("/showcase", StaticFiles(directory=str(showcase_dir), html=True), name="showcase")
    else:
        logging.getLogger(__name__).warning("showcase directory not found: %s", showcase_dir)

    @app.on_event("startup")
    def _start_subscription_delivery() -> None:
        def _bootstrap_delivery_service() -> None:
            try:
                service = get_subscription_delivery_service()
                service.start()
                app.state.subscription_delivery_service = service
            except Exception as exc:
                logging.getLogger(__name__).warning("failed to start subscription delivery service: %s", exc)

        threading.Thread(
            target=_bootstrap_delivery_service,
            name="nightshift-startup-delivery-bootstrap",
            daemon=True,
        ).start()

    @app.on_event("shutdown")
    def _stop_subscription_delivery() -> None:
        service = getattr(app.state, "subscription_delivery_service", None)
        if service is None:
            return
        service.stop()

    return app
