from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CrmAutomation, CrmDeal
from .activity import log_activity
from .notifications import active_managers, notify

logger = logging.getLogger(__name__)

AUTOMATION_FIRED_ACTION = "automation_fired"


@dataclass
class AutomationStats:
    evaluated: int = 0
    fired: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)


async def evaluate_automations(session: AsyncSession) -> AutomationStats:
    """Run all active automations once. Each fires at most once per deal."""
    stats = AutomationStats()
    automations = (
        await session.execute(select(CrmAutomation).where(CrmAutomation.is_active.is_(True)))
    ).scalars()
    for automation in automations:
        stats.evaluated += 1
        try:
            fired, events = await _evaluate(session, automation)
            stats.fired += fired
            stats.events.extend(events)
        except Exception:
            logger.exception("automation failed id=%s", automation.id)
    return stats


async def _evaluate(
    session: AsyncSession, automation: CrmAutomation
) -> tuple[int, list[dict[str, Any]]]:
    deals = await _matching_deals(session, automation)
    fired = 0
    events: list[dict[str, Any]] = []
    for deal_id in deals:
        if await _already_fired(session, automation.id, deal_id):
            continue
        events.extend(await _apply_actions(session, automation, deal_id))
        await log_activity(
            session,
            None,
            "deal",
            deal_id,
            AUTOMATION_FIRED_ACTION,
            {"automation_id": str(automation.id)},
        )
        fired += 1
    if fired:
        logger.info("automation fired id=%s deals=%d", automation.id, fired)
    return fired, events


async def _matching_deals(session: AsyncSession, automation: CrmAutomation) -> list[uuid.UUID]:
    config = automation.trigger_config or {}
    base = select(CrmDeal.id).where(CrmDeal.deleted_at.is_(None), CrmDeal.status == "open")
    pipeline_raw = config.get("pipeline_id")
    if pipeline_raw is not None:
        try:
            base = base.where(CrmDeal.pipeline_id == uuid.UUID(str(pipeline_raw)))
        except (ValueError, TypeError):
            return []
    if automation.trigger_type == "deal_entered_stage":
        stage_id = config.get("stage_id")
        if not stage_id:
            return []
        try:
            wanted = uuid.UUID(str(stage_id))
        except ValueError:
            return []
        rows = (await session.execute(base.where(CrmDeal.stage_id == wanted))).scalars()
        return list(rows)
    if automation.trigger_type == "no_activity_hours":
        try:
            hours = float(config.get("hours", 0))
        except (TypeError, ValueError):
            return []
        if hours <= 0:
            return []
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        rows = (await session.execute(base.where(CrmDeal.updated_at < cutoff))).scalars()
        return list(rows)
    return []


async def _already_fired(
    session: AsyncSession, automation_id: uuid.UUID, deal_id: uuid.UUID
) -> bool:
    row = (
        await session.execute(
            text(
                "SELECT id FROM crm_activity_log WHERE entity = 'deal' AND entity_id = :deal"
                " AND action = :action AND diff->>'automation_id' = :automation LIMIT 1"
            ),
            {"deal": deal_id, "action": AUTOMATION_FIRED_ACTION, "automation": str(automation_id)},
        )
    ).first()
    return row is not None


async def _apply_actions(
    session: AsyncSession, automation: CrmAutomation, deal_id: uuid.UUID
) -> list[dict[str, Any]]:
    from ..models import CrmEntityTag, CrmTag, CrmTask

    events: list[dict[str, Any]] = []
    actions = automation.actions or []
    if not isinstance(actions, list):
        return events
    deal = await session.get(CrmDeal, deal_id)
    if deal is None:
        return events
    for action in actions:
        if not isinstance(action, dict):
            continue
        kind = action.get("type")
        if kind == "create_task":
            title = str(action.get("title") or automation.name)
            due_in = action.get("due_in_hours")
            due_at = None
            if isinstance(due_in, int | float) and due_in >= 0:
                due_at = datetime.now(UTC) + timedelta(hours=due_in)
            session.add(
                CrmTask(
                    deal_id=deal.id,
                    contact_id=deal.contact_id,
                    assignee_id=deal.owner_id,
                    type=str(action.get("task_type") or "other"),
                    title=title[:255],
                    due_at=due_at,
                )
            )
        elif kind == "assign_owner":
            try:
                new_owner = uuid.UUID(str(action.get("user_id")))
            except (ValueError, TypeError):
                continue
            deal.owner_id = new_owner
        elif kind == "add_tag":
            try:
                tag_id = uuid.UUID(str(action.get("tag_id")))
            except (ValueError, TypeError):
                continue
            exists = (
                await session.execute(select(CrmTag.id).where(CrmTag.id == tag_id))
            ).scalar_one_or_none()
            if exists is None:
                continue
            session.add(CrmEntityTag(tag_id=tag_id, entity="deal", entity_id=deal.id))
        elif kind == "notify":
            text_body = str(action.get("text") or automation.name)
            targets = await _notify_targets(session, action, deal)
            events.extend(
                await notify(
                    session,
                    targets,
                    "automation",
                    {
                        "text": text_body,
                        "deal_id": str(deal.id),
                        "dedupe_key": f"automation:{automation.id}:{deal.id}",
                    },
                )
            )
    return events


async def _notify_targets(
    session: AsyncSession, action: dict[str, Any], deal: CrmDeal
) -> list[uuid.UUID]:
    scope = action.get("to", "owner")
    if scope == "owner" and deal.owner_id is not None:
        return [deal.owner_id]
    if isinstance(action.get("user_ids"), list):
        out = []
        for raw in action["user_ids"]:
            try:
                out.append(uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        return out
    managers = await active_managers(session)
    return [user_id for user_id, _ in managers]
