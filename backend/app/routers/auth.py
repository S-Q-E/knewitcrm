from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_user
from ..cookies import clear_session_cookies, session_expiry, set_session_cookies
from ..deps import get_session
from ..errors import ApiError
from ..models import CrmSession, CrmUser
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
    # Revoke every other session; the current one stays alive.
    session_id = getattr(request.state, "crm_session_id", None)
    await session.execute(
        update(CrmSession)
        .where(
            CrmSession.user_id == row.id,
            CrmSession.revoked_at.is_(None),
            CrmSession.id != session_id,
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return {"ok": True}
