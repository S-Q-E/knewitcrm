from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import CrmEntityTag, CrmTag
from ..schemas.meta import TagOut


async def entity_tags_map(
    session: AsyncSession, entity: str, entity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[TagOut]]:
    """Batch-load tags for listed objects (avoids N+1)."""
    out: dict[uuid.UUID, list[TagOut]] = {eid: [] for eid in entity_ids}
    if not entity_ids:
        return out
    rows = (
        await session.execute(
            select(CrmEntityTag.entity_id, CrmTag)
            .join(CrmTag, CrmTag.id == CrmEntityTag.tag_id)
            .where(CrmEntityTag.entity == entity, CrmEntityTag.entity_id.in_(entity_ids))
            .order_by(CrmTag.name)
        )
    ).all()
    for entity_id, tag in rows:
        out.setdefault(entity_id, []).append(TagOut.model_validate(tag))
    return out


async def replace_entity_tags(
    session: AsyncSession, entity: str, entity_id: uuid.UUID, tag_ids: list[uuid.UUID]
) -> list[TagOut]:
    """Replace the tag set of one object. Unknown tag ids are rejected."""
    unique_ids = list(dict.fromkeys(tag_ids))
    if unique_ids:
        existing = (
            (await session.execute(select(CrmTag.id).where(CrmTag.id.in_(unique_ids))))
            .scalars()
            .all()
        )
        unknown = set(unique_ids) - set(existing)
        if unknown:
            raise ApiError(
                "UNKNOWN_TAG", "Unknown tag ids", 422, {"ids": [str(i) for i in unknown]}
            )
    await session.execute(
        delete(CrmEntityTag).where(
            CrmEntityTag.entity == entity, CrmEntityTag.entity_id == entity_id
        )
    )
    for tag_id in unique_ids:
        session.add(CrmEntityTag(tag_id=tag_id, entity=entity, entity_id=entity_id))
    await session.flush()
    return (await entity_tags_map(session, entity, [entity_id]))[entity_id]


async def detach_entity_tags(session: AsyncSession, entity: str, entity_id: uuid.UUID) -> None:
    await session.execute(
        delete(CrmEntityTag).where(
            CrmEntityTag.entity == entity, CrmEntityTag.entity_id == entity_id
        )
    )
