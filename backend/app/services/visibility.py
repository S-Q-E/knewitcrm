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


async def lead_owner(session: AsyncSession, whatsapp_id: str):
    """Responsible user for a bot lead: the managed deal owner.

    The managed deal is the most recently updated live deal of the linked
    contact; without one the contact owner applies; without a contact the
    lead counts as unassigned (visible to all). Returns the owner id or None.
    """
    from ..models import CrmContact, CrmDeal

    contact = (
        await session.execute(
            select(CrmContact.id, CrmContact.owner_id).where(CrmContact.whatsapp_id == whatsapp_id)
        )
    ).one_or_none()
    if contact is None:
        return None
    deal = (
        await session.execute(
            select(CrmDeal.id, CrmDeal.owner_id)
            .where(CrmDeal.contact_id == contact.id, CrmDeal.deleted_at.is_(None))
            .order_by(CrmDeal.updated_at.desc(), CrmDeal.id)
            .limit(1)
        )
    ).one_or_none()
    if deal is None:
        return contact.owner_id
    return deal.owner_id


async def ensure_lead_visible(session: AsyncSession, whatsapp_id: str, user: CurrentUser) -> None:
    """Scope check for dialog/chat/stream objects behind a bot lead."""
    restricted = await restrict_managers_to_own(session)
    ensure_visible(is_visible(await lead_owner(session, whatsapp_id), user, restricted))
