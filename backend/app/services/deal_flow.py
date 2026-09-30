from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError
from ..models import (
    DEAL_STATUS_LOST,
    DEAL_STATUS_OPEN,
    DEAL_STATUS_WON,
    CrmDeal,
    CrmDealStageHistory,
    CrmStage,
)
from .bot_bridge import BotLeadNotFoundError, update_bot_stage

logger = logging.getLogger(__name__)

KIND_TO_STATUS = {"open": DEAL_STATUS_OPEN, "won": DEAL_STATUS_WON, "lost": DEAL_STATUS_LOST}


async def apply_deal_stage(
    session: AsyncSession,
    deal: CrmDeal,
    target: CrmStage,
    contact_whatsapp: str | None,
    *,
    actor_id: uuid.UUID | None,
    source: str,
    position: Decimal | float | None = None,
    lost_reason_id: uuid.UUID | None = None,
    use_bridge: bool = True,
) -> dict:
    """Move a deal to another stage (manager-driven).

    Same-stage calls only reorder. Cross-stage calls lock the deal (D3),
    record history, push the stage to the bot when the target has a
    ``bot_stage_key``, and maintain status/closed_at/lost_reason.
    """
    if deal.pipeline_id != target.pipeline_id:
        raise ApiError("STAGE_PIPELINE_MISMATCH", "Stage belongs to another pipeline", 422)
    if deal.stage_id == target.id:
        if position is not None:
            deal.position = Decimal(str(position))
        return {"moved": False, "bridged": False}

    target_status = KIND_TO_STATUS[target.kind]
    if target_status == DEAL_STATUS_LOST:
        reason = lost_reason_id if lost_reason_id is not None else deal.lost_reason_id
        if reason is None:
            raise ApiError("LOST_REASON_REQUIRED", "lost_reason_id is required to lose a deal", 422)
        deal.lost_reason_id = reason
    else:
        deal.lost_reason_id = None

    from_stage_id = deal.stage_id
    deal.stage_id = target.id
    deal.status = target_status
    deal.closed_at = datetime.now(UTC) if target_status != DEAL_STATUS_OPEN else None
    deal.position = (
        Decimal(str(position))
        if position is not None
        else await _append_position(session, target.id)
    )
    deal.stage_locked = True
    session.add(
        CrmDealStageHistory(
            deal_id=deal.id,
            from_stage_id=from_stage_id,
            to_stage_id=target.id,
            changed_by=actor_id,
            source=source,
        )
    )

    bridged = False
    if use_bridge and target.bot_stage_key and contact_whatsapp:
        try:
            bridged = await update_bot_stage(
                session, contact_whatsapp, target.bot_stage_key, actor_id
            )
        except BotLeadNotFoundError:
            logger.warning("bot lead gone, manager move kept whatsapp_id=%s", contact_whatsapp)
    return {"moved": True, "bridged": bridged}


async def _append_position(session: AsyncSession, stage_id: uuid.UUID) -> Decimal:
    top = (
        await session.execute(
            select(func.max(CrmDeal.position)).where(
                CrmDeal.stage_id == stage_id, CrmDeal.deleted_at.is_(None)
            )
        )
    ).scalar()
    return (top or Decimal(0)) + 1
