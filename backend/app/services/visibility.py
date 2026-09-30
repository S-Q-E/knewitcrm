from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_deps import CurrentUser
from ..errors import ApiError
from ..models import CrmSetting

SETTING_RESTRICT_MANAGERS_TO_OWN = "restrict_managers_to_own"


async def restrict_managers_to_own(session: AsyncSession) -> bool:
    """True when managers may only see their own and unassigned records."""
    row = (
        await session.execute(
            select(CrmSetting.value).where(CrmSetting.key == SETTING_RESTRICT_MANAGERS_TO_OWN)
        )
    ).scalar_one_or_none()
    return row is True


def owner_condition(owner_column, user: CurrentUser, restricted: bool):
    """Visibility condition, or None when the user has full access."""
    if user.is_admin or not restricted:
        return None
    return or_(owner_column == user.id, owner_column.is_(None))


def is_visible(owner_id, user: CurrentUser, restricted: bool) -> bool:
    """Row-level check for single-object endpoints."""
    if user.is_admin or not restricted:
        return True
    return owner_id is None or owner_id == user.id


def ensure_visible(has_access: bool) -> None:
    """Hide scoped-out objects as NOT_FOUND so their existence does not leak."""
    if not has_access:
        raise ApiError("NOT_FOUND", "Not found", 404)
