from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_deps import CurrentUser
from .cookies import set_session_cookies
from .errors import error_payload
from .models import CrmSession, CrmUser
from .security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    SESSION_RENEW_THRESHOLD_DAYS,
    SESSION_TTL_DAYS,
)

logger = logging.getLogger(__name__)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# API paths that never require a session. Everything else under /api/* does.
# /api/metrics is guarded by its own Bearer token (routers/metrics.py), not by sessions.
PUBLIC_API_PATHS = frozenset({"/api/health", "/api/ready", "/api/auth/login", "/api/metrics"})
# Login cannot present a CSRF token yet (no session); SameSite=Lax covers it.
CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})


def client_ip(request: Request, trusted_proxy_hops: int | None = None) -> str:
    """Best-effort client IP behind trusted proxies.

    Each proxy appends the peer it received the request from, so with
    ``hops`` trusted proxies the client IP is the entry just before the
    last ``hops`` values (outermost last). Taking the last value (hops=1)
    instead of the first one is what makes a spoofed prefix harmless: the
    attacker-controlled entries sit to the left of it. When the chain is
    shorter than ``hops`` (or hops is 0) nothing in the header is
    trustworthy, so fall back to the direct peer.
    """
    hops = trusted_proxy_hops
    if hops is None:
        try:
            hops = int(request.app.state.settings.trusted_proxy_hops)
        except (AttributeError, TypeError, ValueError):
            hops = 1
    hops = max(0, hops)
    peer = request.client.host if request.client else "unknown"
    if hops <= 0:
        return peer
    parts = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",")]
    parts = [part for part in parts if part]
    if len(parts) >= hops:
        return parts[len(parts) - hops] or "unknown"
    return peer


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """Cookie session auth for all /api/* except the public probes and login."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        if request.url.path in PUBLIC_API_PATHS:
            return await call_next(request)

        token_value = request.cookies.get(SESSION_COOKIE, "")
        session, user = await self._load(token_value, request)
        if session is None or user is None:
            return self._error(401, "UNAUTHORIZED", "Authentication required")

        csrf_error = self._check_csrf(request, session)
        if csrf_error is not None:
            return csrf_error

        request.state.current_user = CurrentUser(
            id=user.id, email=user.email, name=user.name, role=user.role
        )
        request.state.crm_session_id = session.id

        response = await call_next(request)

        if self._needs_renewal(session):
            await self._renew(session, request, response)
        return response

    async def _load(self, token_value: str, request: Request):
        try:
            raw = bytes.fromhex(token_value)
        except (ValueError, TypeError):
            return None, None
        if len(raw) != 32:
            return None, None
        token_hash = hashlib.sha256(raw).hexdigest()
        factory = request.app.state.session_factory
        async with factory() as db:
            row = (
                await db.execute(
                    select(CrmSession, CrmUser)
                    .join(CrmUser, CrmSession.user_id == CrmUser.id)
                    .where(
                        CrmSession.token_hash == token_hash,
                        CrmSession.revoked_at.is_(None),
                        CrmSession.expires_at > datetime.now(UTC),
                        CrmUser.is_active.is_(True),
                    )
                )
            ).one_or_none()
            if row is None:
                return None, None
            session, user = row
            db.expunge(session)
            db.expunge(user)
            return session, user

    def _check_csrf(self, request: Request, session: CrmSession):
        if request.method not in UNSAFE_METHODS:
            return None
        if request.url.path in CSRF_EXEMPT_PATHS:
            return None
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not header or not cookie:
            return self._error(403, "CSRF_REQUIRED", "CSRF token is required")
        if not hmac.compare_digest(header, cookie):
            return self._error(403, "CSRF_MISMATCH", "CSRF token mismatch")
        expected = hashlib.sha256(header.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected, session.csrf_hash):
            return self._error(403, "CSRF_MISMATCH", "CSRF token mismatch")
        return None

    @staticmethod
    def _needs_renewal(session: CrmSession) -> bool:
        remaining = session.expires_at - datetime.now(UTC)
        return remaining < timedelta(days=SESSION_RENEW_THRESHOLD_DAYS)

    async def _renew(self, session: CrmSession, request: Request, response) -> None:
        factory = request.app.state.session_factory
        async with factory() as db:
            row = await db.get(CrmSession, session.id)
            if row is None or row.revoked_at is not None:
                return
            row.expires_at = datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)
            await db.commit()
        settings = request.app.state.settings
        set_session_cookies(
            response,
            settings,
            request.cookies.get(SESSION_COOKIE, ""),
            request.cookies.get(CSRF_COOKIE, ""),
        )
        logger.debug("session renewed")

    @staticmethod
    def _error(status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(status_code=status, content=error_payload(code, message))
