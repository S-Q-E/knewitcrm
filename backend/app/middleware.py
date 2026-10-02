from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .errors import error_payload
from .logging_utils import request_id_ctx
from .services.metrics import note_request
from .services.ratelimit import api_limiter
from .session_middleware import client_ip

# No 'unsafe-inline' for scripts. Inline styles stay allowed: React sets them
# through CSSOM (not governed by style-src) and several UI libs rely on
# style attributes, which blocking would break silently.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        request_id_ctx.set(request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers on every response (API and SPA)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Ignored by browsers over plain HTTP; enforced once behind HTTPS.
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


class MetricsMiddleware(BaseHTTPMiddleware):
    """Count every request (including 401/429) with route-template labels."""

    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            note_request(request.method, _route_template(request), 500, _elapsed(started))
            raise
        note_request(
            request.method,
            _route_template(request),
            response.status_code,
            _elapsed(started),
        )
        return response


def _elapsed(started: float) -> float:
    return time.perf_counter() - started


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None) or "unknown"
    if template in ("/", "/{full_path:path}"):
        return "spa"
    return template[:120]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding window over all /api traffic (login keeps its own rules)."""

    async def dispatch(self, request: Request, call_next):
        settings = getattr(request.app.state, "settings", None)
        enabled = getattr(settings, "rate_limit_enabled", True)
        if enabled and request.url.path.startswith("/api/"):
            limit = getattr(settings, "rate_limit_per_minute", 600)
            ip = client_ip(request)
            if not api_limiter.check(ip, max_hits=limit, window=60):
                retry_after = api_limiter.retry_after(ip)
                return JSONResponse(
                    status_code=429,
                    content=error_payload("RATE_LIMITED", "Too many requests, slow down"),
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)


class BodyTooLargeError(Exception):
    pass


class BodyLimitMiddleware:
    """Pure-ASGI cap on request bodies (also covers chunked uploads)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = scope["app"].state.settings
        limit = getattr(settings, "max_request_body_bytes", 10 * 1024 * 1024)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10 * 1024 * 1024
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        try:
            declared = int(headers.get("content-length", "0") or "0")
        except ValueError:
            declared = 0
        if declared > limit:
            await _too_large(send)
            return
        consumed = 0

        async def capped_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise BodyTooLargeError
            return message

        try:
            await self.app(scope, capped_receive, send)
        except BodyTooLargeError:
            await _too_large(send)


async def _too_large(send) -> None:
    import json

    body = json.dumps(error_payload("REQUEST_TOO_LARGE", "Request body is too large")).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
