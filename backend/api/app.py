"""FastAPI application factory.

Serves the JSON API under ``/api`` and the static research terminal at ``/``.

CORS is permissive by default *because this is a single-user local research
application*, but it is configurable through ``BTI_CORS_ORIGINS``. There are no
sessions, no users and no credential endpoints: the app holds no broker
credentials for trading and exposes no write capability against a broker.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.core.config import get_settings
from backend.core.errors import BTIError
from backend.core.logging import configure_logging, get_logger, new_request_id
from backend.core.provenance import utcnow

log = get_logger("api")
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=(
            "Personal Indian equity research platform. Research, backtesting and "
            "paper trading only. Live ordering is not implemented."
        ),
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def timing_and_context(request: Request, call_next):
        start = time.perf_counter()
        rid = new_request_id()
        try:
            response = await call_next(request)
        except BTIError as exc:
            log.warning("handled error: %s", exc.message)
            return JSONResponse(status_code=exc.http_status, content=exc.to_payload())
        duration = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-Id"] = rid
        response.headers["X-Response-Time-ms"] = str(duration)
        response.headers["X-Data-Policy"] = (
            f"data-mode={settings.data_mode}; research-only; no order routing"
        )
        return response

    @app.exception_handler(BTIError)
    async def bti_error_handler(request: Request, exc: BTIError):
        return JSONResponse(status_code=exc.http_status, content=exc.to_payload())

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=422,
            content={"error": "VALIDATION_ERROR", "message": str(exc), "details": {}},
        )

    app.include_router(router)

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="terminal")

    log.info("application ready", extra={"status": "ready"})
    return app


app = create_app()
