from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import (
    ENTITY_CONTACT,
    CrmContact,
    CrmDeal,
    CrmEntityTag,
    CrmNote,
    CrmTask,
)
from .activity import log_activity, slim
from .normalize import contact_keys
from .tags import entity_tags_map
from .visibility import ensure_visible, is_visible, restrict_managers_to_own


async def find_duplicate_groups(
    session: AsyncSession,
    limit: int = 100,
    include_deleted: bool = False,
) -> list[dict]:
    """Group live contacts by normalized phone / whatsapp digits / email.

    Python-side grouping keeps the query portable and test-friendly;
    contact volumes in this CRM are small (hundreds, not millions).
    """
    stmt = select(CrmContact.id, CrmContact.phone, CrmContact.whatsapp_id, CrmContact.email)
    if not include_deleted:
        stmt = stmt.where(CrmContact.deleted_at.is_(None))
    rows = (await session.execute(stmt)).all()

    buckets: dict[str, list[uuid.UUID]] = {}
    for row in rows:
        keys = contact_keys(row.phone, row.whatsapp_id, row.email)
        if keys["phone"]:
            buckets.setdefault(f"phone:{keys['phone']}", []).append(row.id)
        if keys["email"]:
            buckets.setdefault(f"email:{keys['email']}", []).append(row.id)
    groups: list[dict] = []
    seen: set[frozenset] = set()
    for key, ids in buckets.items():
        unique = sorted(set(ids))
        if len(unique) < 2:
            continue
        marker = frozenset(unique)
        if marker in seen:
            continue
        seen.add(marker)
        kind, _, value = key.partition(":")
        groups.append(
            {
                "key": key,
                "kind": kind,
                "value": value,
                "contact_ids": [str(i) for i in unique],
            }
        )
        if len(groups) >= limit:
            break
    return groups


async def merge_contacts(
    session: AsyncSession,
    winner_id: uuid.UUID,
    loser_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    actor_is_admin: bool,
    restricted: bool,
    actor_user_id: uuid.UUID | None = None,
) -> CrmContact:
    """Merge loser into winner: deals/notes/tasks/tags move, loser soft-deleted."""
    if winner_id == loser_id:
        raise ApiError("SAME_CONTACT", "Cannot merge a contact into itself", 422)
    winner = await session.get(CrmContact, winner_id)
    loser = await session.get(CrmContact, loser_id)
    if winner is None or winner.deleted_at is not None:
        raise ApiError("NOT_FOUND", "Winner contact not found", 404)
    if loser is None or loser.deleted_at is not None:
        raise ApiError("NOT_FOUND", "Source contact not found", 404)
    if not actor_is_admin:
        w_visible = is_visible(winner.owner_id, _stub(actor_is_admin, actor_user_id), restricted)
        l_visible = is_visible(loser.owner_id, _stub(actor_is_admin, actor_user_id), restricted)
        ensure_visible(w_visible)
        ensure_visible(l_visible)
    if winner.whatsapp_id and loser.whatsapp_id and winner.whatsapp_id != loser.whatsapp_id:
        raise ApiError(
            "MERGE_WHATSAPP_CONFLICT",
            "Both contacts have different WhatsApp chats; merge is refused",
            409,
        )

    # Move deals
    deal_rows = await session.execute(select(CrmDeal).where(CrmDeal.contact_id == loser.id))
    deals = deal_rows.scalars().all()
    for deal in deals:
        deal.contact_id = winner.id
    # Move notes
    note_rows = await session.execute(select(CrmNote).where(CrmNote.contact_id == loser.id))
    notes = note_rows.scalars().all()
    for note in notes:
        note.contact_id = winner.id
    # Move tasks
    task_rows = await session.execute(select(CrmTask).where(CrmTask.contact_id == loser.id))
    tasks = task_rows.scalars().all()
    for task in tasks:
        task.contact_id = winner.id
    # Merge tags (union)
    winner_tags = {
        t.id for t in (await entity_tags_map(session, ENTITY_CONTACT, [winner.id]))[winner.id]
    }
    loser_map = await entity_tags_map(session, ENTITY_CONTACT, [loser.id])
    loser_tags = loser_map[loser.id]
    for tag in loser_tags:
        if tag.id not in winner_tags:
            session.add(CrmEntityTag(tag_id=tag.id, entity=ENTITY_CONTACT, entity_id=winner.id))
    # Fill empty winner fields from loser (name/phone/email/source/custom keys)
    for field in ("name", "phone", "email"):
        if getattr(winner, field) in (None, "") and getattr(loser, field) not in (None, ""):
            setattr(winner, field, getattr(loser, field))
    # whatsapp_id is unique: release it from the loser before the winner takes it.
    if not winner.whatsapp_id and loser.whatsapp_id:
        moved_wa = loser.whatsapp_id
        loser.whatsapp_id = None
        await session.flush()
        winner.whatsapp_id = moved_wa
    if winner.owner_id is None and loser.owner_id is not None:
        winner.owner_id = loser.owner_id
    merged_custom = dict(winner.custom or {})
    for key, value in (loser.custom or {}).items():
        if key not in merged_custom:
            merged_custom[key] = value
    winner.custom = merged_custom

    loser.deleted_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("MERGE_CONFLICT", "Contacts could not be merged", 409) from exc
    await log_activity(
        session,
        actor_id,
        "contact",
        winner.id,
        "contact_merged",
        {
            "merged_from": str(loser.id),
            "merged_from_name": loser.name,
            "deals_moved": len(deals),
            "notes_moved": len(notes),
            "tasks_moved": len(tasks),
        },
    )
    await log_activity(
        session,
        actor_id,
        "contact",
        loser.id,
        "contact_merged_from",
        {"merged_into": str(winner.id), **slim({"name": loser.name})},
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ApiError("MERGE_CONFLICT", "Contacts could not be merged", 409) from exc
    await session.refresh(winner)
    return winner


class _StubUser:
    def __init__(self, is_admin: bool, user_id: uuid.UUID | None):
        self.is_admin = is_admin
        self.id = user_id


def _stub(is_admin: bool, user_id: uuid.UUID | None) -> _StubUser:
    return _StubUser(is_admin, user_id)


async def visibility_restricted(session: AsyncSession) -> bool:
    return await restrict_managers_to_own(session)
