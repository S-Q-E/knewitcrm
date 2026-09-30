from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser, require_role, require_user
from ..deps import get_session, pagination
from ..errors import ApiError
from ..models import ROLE_ADMIN, CrmSession, CrmUser
from ..schemas.users import (
    UserCreate,
    UserListOut,
    UserLite,
    UserLiteListOut,
    UserOut,
    UserUpdate,
)
from ..security import hash_password, normalize_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])

require_admin = require_role("admin")


@router.get("")
async def list_users(
    request_user: CurrentUser = Depends(require_user),
    session: AsyncSession = Depends(get_session),
    page: dict = Depends(pagination),
):
    """Admins get the full paginated list; managers get id+name of active users."""
    if not request_user.is_admin:
        rows = (
            await session.execute(
                select(CrmUser).where(CrmUser.is_active.is_(True)).order_by(CrmUser.name)
            )
        ).scalars()
        return UserLiteListOut(items=[UserLite.model_validate(u) for u in rows])
    total = (await session.execute(select(func.count()).select_from(CrmUser))).scalar() or 0
    rows = (
        await session.execute(
            select(CrmUser)
            .order_by(CrmUser.created_at.desc())
            .limit(page["limit"])
            .offset(page["offset"])
        )
    ).scalars()
    return UserListOut(items=[UserOut.model_validate(u) for u in rows], total=total)


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    payload: UserCreate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = CrmUser(
        email=normalize_email(payload.email),
        name=payload.name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("EMAIL_TAKEN", "A user with this email already exists", 409) from exc
    await session.refresh(user)
    logger.info("user created email=%s role=%s by=%s", user.email, user.role, admin.email)
    return user


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(CrmUser, user_id)
    if user is None:
        raise ApiError("NOT_FOUND", "User not found", 404)
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    admin: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    user = await session.get(CrmUser, user_id)
    if user is None:
        raise ApiError("NOT_FOUND", "User not found", 404)

    if payload.name is not None:
        user.name = payload.name.strip()
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.role is not None and payload.role != user.role:
        if user.role == ROLE_ADMIN and not await _another_active_admin(session, user.id):
            raise ApiError("LAST_ADMIN", "Cannot demote the last active admin", 409)
        user.role = payload.role
    if payload.is_active is not None and payload.is_active != user.is_active:
        if not payload.is_active and user.role == ROLE_ADMIN:
            if not await _another_active_admin(session, user.id):
                raise ApiError("LAST_ADMIN", "Cannot deactivate the last active admin", 409)
        user.is_active = payload.is_active
        if not payload.is_active:
            await _revoke_sessions(session, user.id)

    await session.commit()
    await session.refresh(user)
    logger.info("user updated email=%s by=%s", user.email, admin.email)
    return user


async def _another_active_admin(session: AsyncSession, exclude_id: uuid.UUID) -> bool:
    row = (
        await session.execute(
            select(func.count())
            .select_from(CrmUser)
            .where(
                CrmUser.role == ROLE_ADMIN,
                CrmUser.is_active.is_(True),
                CrmUser.id != exclude_id,
            )
        )
    ).scalar()
    return bool(row)


async def _revoke_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(CrmSession)
        .where(CrmSession.user_id == user_id, CrmSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
