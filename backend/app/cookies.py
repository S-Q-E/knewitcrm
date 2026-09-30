from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import Response

from .config import Settings
from .security import CSRF_COOKIE, SESSION_COOKIE, SESSION_TTL_DAYS


def session_cookie_max_age() -> int:
    return SESSION_TTL_DAYS * 24 * 3600


def set_session_cookies(
    response: Response,
    settings: Settings,
    token_value: str,
    csrf_value: str,
) -> None:
    max_age = session_cookie_max_age()
    response.set_cookie(
        SESSION_COOKIE,
        token_value,
        max_age=max_age,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_value,
        max_age=max_age,
        path="/",
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(
            name,
            path="/",
            httponly=httponly,
            secure=settings.cookie_secure,
            samesite="lax",
        )


def session_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)
