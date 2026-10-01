from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ENTITY_DEAL
from ..schemas.deals import DealOut
from .tags import entity_tags_map


async def deals_out(session: AsyncSession, deals: list) -> list[DealOut]:
    tags = await entity_tags_map(session, ENTITY_DEAL, [d.id for d in deals])
    out: list[DealOut] = []
    for deal in deals:
        row = DealOut.model_validate(deal)
        row.tags = tags.get(deal.id, [])
        out.append(row)
    return out
