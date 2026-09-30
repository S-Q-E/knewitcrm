from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .db import create_engine, create_session_factory
from .deps import get_settings
from .errors import ApiError, api_error_handler, error_payload
from .logging_utils import setup_logging
from .middleware import BasicAuthMiddleware, RequestIdMiddleware
from .routers import health, legacy_bot

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FRONTEND_DIR = (
    BASE_DIR / "frontend-legacy"
    if (BASE_DIR / "frontend-legacy").exists()
    else BASE_DIR / "frontend"
)

# /api/health and /api/ready stay public for orchestrator probes.
PUBLIC_PATHS = {"/api/health", "/api/ready"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="KnewIT CRM", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        BasicAuthMiddleware,
        username=settings.basic_user,
        password=settings.basic_pass,
        public_paths=PUBLIC_PATHS,
    )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router)
    app.include_router(legacy_bot.router)

    @app.get("/")
    async def root_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    logger.info("app created (env=%s)", settings.app_env)
    return app


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "")


async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_payload("VALIDATION_ERROR", "Invalid request", exc.errors()),
        headers={"X-Request-ID": _request_id(request)},
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload("HTTP_ERROR", str(exc.detail)),
        headers={"X-Request-ID": _request_id(request)},
    )


async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content=error_payload("INTERNAL_ERROR", "Internal server error"),
        headers={"X-Request-ID": _request_id(request)},
    )


app = create_app()
