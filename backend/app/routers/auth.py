from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..cookies import clear_session_cookies, session_expiry, set_session_cookies
from ..deps import get_session
from ..errors import ApiError
from ..models import CrmSession, CrmUser
from ..schemas.settings import ProfileUpdate, SessionListOut, SessionOut
from ..schemas.users import ChangePasswordIn, LoginIn, UserOut
from ..security import (
    MIN_PASSWORD_LENGTH,
    csrf_hash,
    hash_password,
    needs_rehash,
    new_csrf_token,
    new_session_token,
    normalize_email,
    token_cookie_value,
    token_hash,
    verify_password,
)
from ..services.activity import log_activity
from ..services.ratelimit import login_limiter
from ..session_middleware import client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
async def login(
    payload: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    email = normalize_email(payload.email)
    ip = client_ip(request)
    if login_limiter.is_blocked(ip, email):
        logger.warning("login rate-limited email=%s ip=%s", email, ip)
        raise ApiError("RATE_LIMITED", "Too many failed attempts, try again later", 429)

    user = (
        await session.execute(select(CrmUser).where(CrmUser.email == email))
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_password(user.password_hash, payload.password)
    ):
        login_limiter.record_failure(ip, email)
        logger.warning("login failed email=%s ip=%s", email, ip)
        raise ApiError("INVALID_CREDENTIALS", "Invalid email or password", 401)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    raw_token = new_session_token()
    csrf_token = new_csrf_token()
    db_session = CrmSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        csrf_hash=csrf_hash(csrf_token),
        expires_at=session_expiry(),
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    session.add(db_session)
    user.last_login_at = datetime.now(UTC)
    await session.commit()

    login_limiter.record_success(ip, email)
    await log_activity(session, user.id, "user", user.id, "auth_login", {"ip": ip})
    await session.commit()
    set_session_cookies(
        response, request.app.state.settings, token_cookie_value(raw_token), csrf_token
    )
    return user


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    session_id = getattr(request.state, "crm_session_id", None)
    if session_id is not None:
        await session.execute(
            update(CrmSession)
            .where(CrmSession.id == session_id, CrmSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    clear_session_cookies(response, request.app.state.settings)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(CrmUser, user.id)
    if row is None or not row.is_active:
        raise ApiError("UNAUTHORIZED", "Authentication required", 401)
    return row


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordIn,
    request: Request,
    response: Response,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise ApiError("WEAK_PASSWORD", "Password must be at least 10 characters", 400)
    row = await session.get(CrmUser, user.id)
    if row is None or not row.is_active:
        raise ApiError("UNAUTHORIZED", "Authentication required", 401)
    if not verify_password(row.password_hash, payload.current_password):
        raise ApiError("INVALID_CREDENTIALS", "Current password is incorrect", 400)

    row.password_hash = hash_password(payload.new_password)
    # Full rotation: every session (including this one) dies, then a fresh
    # session is issued transparently so the caller stays logged in.
    await session.execute(
        update(CrmSession)
        .where(CrmSession.user_id == row.id, CrmSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    raw_token = new_session_token()
    csrf_token = new_csrf_token()
    session.add(
        CrmSession(
            user_id=row.id,
            token_hash=token_hash(raw_token),
            csrf_hash=csrf_hash(csrf_token),
            expires_at=session_expiry(),
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    )
    await session.commit()
    set_session_cookies(
        response, request.app.state.settings, token_cookie_value(raw_token), csrf_token
    )
    await log_activity(session, row.id, "user", row.id, "password_changed", None)
    await session.commit()
    return {"ok": True}


@router.patch("/profile", response_model=UserOut)
async def update_profile(
    payload: ProfileUpdate,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Self-service display name change (email stays the login key)."""
    row = await session.get(CrmUser, user.id)
    if row is None or not row.is_active:
        raise ApiError("UNAUTHORIZED", "Authentication required", 401)
    row.name = payload.name.strip()
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/sessions", response_model=SessionListOut)
async def list_sessions(
    request: Request,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Own active sessions (devices), newest first, with the current one marked."""
    current_id = getattr(request.state, "crm_session_id", None)
    rows = (
        await session.execute(
            select(CrmSession)
            .where(CrmSession.user_id == user.id, CrmSession.revoked_at.is_(None))
            .order_by(CrmSession.created_at.desc(), CrmSession.id.desc())
        )
    ).scalars()
    return SessionListOut(
        items=[
            SessionOut(
                id=row.id,
                ip=row.ip,
                user_agent=row.user_agent,
                created_at=row.created_at,
                expires_at=row.expires_at,
                is_current=row.id == current_id,
            )
            for row in rows
        ]
    )


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    row = await session.get(CrmSession, session_id)
    if row is None or row.user_id != user.id or row.revoked_at is not None:
        raise ApiError("NOT_FOUND", "Session not found", 404)
    if row.id == getattr(request.state, "crm_session_id", None):
        raise ApiError("CANNOT_REVOKE_CURRENT", "Log out instead of revoking this session", 422)
    row.revoked_at = datetime.now(UTC)
    await session.commit()
    return {"ok": True}


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(
    request: Request,
    user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
):
    """Log out on all other devices; the current session stays alive."""
    current_id = getattr(request.state, "crm_session_id", None)
    result = await session.execute(
        update(CrmSession)
        .where(
            CrmSession.user_id == user.id,
            CrmSession.revoked_at.is_(None),
            CrmSession.id != current_id,
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return {"ok": True, "revoked": result.rowcount or 0}
