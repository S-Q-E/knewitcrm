from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .db import create_engine, create_session_factory
from .deps import get_settings
from .errors import ApiError, api_error_handler, error_payload
from .logging_utils import setup_logging
from .middleware import RequestIdMiddleware
from .routers import (
    auth,
    automations,
    chats,
    contacts,
    custom_fields,
    deals,
    dialogs,
    health,
    legacy_bot,
    lost_reasons,
    notes,
    notifications,
    pipelines,
    tags,
    tasks,
    users,
    views,
)
from .services.bootstrap import try_bootstrap
from .session_middleware import SessionAuthMiddleware
from .workers.notify_worker import NOTIFY_INTERVAL_SECONDS, notify_loop
from .workers.outbox_worker import outbox_loop
from .workers.sync_worker import sync_loop

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def resolve_frontend_dir() -> Path:
    """Serve the built SPA bundle."""
    dist = BASE_DIR / "frontend" / "dist"
    if (dist / "index.html").is_file():
        return dist
    return BASE_DIR / "frontend"


FRONTEND_DIR = resolve_frontend_dir()

NO_CACHE = {"Cache-Control": "no-cache"}
IMMUTABLE_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}


def frontend_response(path: str) -> FileResponse:
    """SPA fallback: existing files as-is, everything else serves index.html.

    Anything under /api is left to the API routers (JSON 404 there).
    """
    if path.startswith("api/"):
        raise StarletteHTTPException(status_code=404, detail="Not found")
    if path:
        candidate = (FRONTEND_DIR / path).resolve()
        root = FRONTEND_DIR.resolve()
        if candidate.is_file() and (candidate == root or root in candidate.parents):
            headers = IMMUTABLE_CACHE if path.startswith("assets/") else NO_CACHE
            return FileResponse(str(candidate), headers=headers)
    return FileResponse(str(FRONTEND_DIR / "index.html"), headers=dict(NO_CACHE))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    await try_bootstrap(app.state.session_factory, settings.admin_email, settings.admin_password)
    sync_task = None
    if settings.sync_enabled:
        sync_task = asyncio.create_task(
            sync_loop(app.state.session_factory, settings.sync_interval_seconds)
        )
        app.state.sync_task = sync_task
    notify_task = None
    if settings.sync_enabled:
        notify_task = asyncio.create_task(
            notify_loop(app.state.session_factory, NOTIFY_INTERVAL_SECONDS)
        )
        app.state.notify_task = notify_task
    outbox_task = None
    if settings.sync_enabled:
        outbox_task = asyncio.create_task(
            outbox_loop(app.state.session_factory, settings, settings.outbox_interval_seconds)
        )
        app.state.outbox_task = outbox_task
    try:
        yield
    finally:
        for task in (sync_task, notify_task, outbox_task):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    app = FastAPI(title="KnewIT CRM", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(SessionAuthMiddleware)
    app.add_middleware(RequestIdMiddleware)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(automations.router)
    app.include_router(users.router)
    app.include_router(pipelines.router)
    app.include_router(pipelines.stages_router)
    app.include_router(contacts.router)
    app.include_router(deals.router)
    app.include_router(notes.router)
    app.include_router(tags.router)
    app.include_router(custom_fields.router)
    app.include_router(lost_reasons.router)
    app.include_router(views.router)
    app.include_router(tasks.router)
    app.include_router(dialogs.router)
    app.include_router(chats.router)
    app.include_router(notifications.router)
    app.include_router(legacy_bot.router)

    @app.get("/")
    async def root_index():
        return FileResponse(str(FRONTEND_DIR / "index.html"), headers=dict(NO_CACHE))

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        return frontend_response(full_path)

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
