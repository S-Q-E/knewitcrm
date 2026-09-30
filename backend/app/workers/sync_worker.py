from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..models import (
    CONTACT_SOURCE_BOT,
    DEAL_STATUS_LOST,
    DEAL_STATUS_OPEN,
    DEAL_STATUS_WON,
    HISTORY_SOURCE_BOT,
    HISTORY_SOURCE_SYSTEM,
    STATUS_CLIENT,
    STATUS_LOST,
    STATUS_MANAGER,
    CrmActivityLog,
    CrmContact,
    CrmConversationState,
    CrmDeal,
    CrmDealStageHistory,
    CrmPipeline,
    CrmStage,
    CrmTask,
)
from ..services.notifications import active_managers, notify

logger = logging.getLogger(__name__)

# Advisory-lock key for the sync worker (bigint). Transaction-scoped variant
# is used so the lock is always released on commit/rollback, even with pooling.
SYNC_LOCK_KEY = 91030001
SETTINGS_KEY_LAST_SYNCED = "sync_worker.last_synced_at"
BATCH_SIZE = 500

# knewit_leads columns mirrored into contact/deal custom payloads.
CUSTOM_FIELDS = (
    "direction",
    "goal",
    "experience_level",
    "preferred_format",
    "preferred_time",
    "last_objection",
)


class SyncConfigError(RuntimeError):
    """Raised when the funnel is not seeded (no default pipeline/stages)."""


@dataclass
class SyncStats:
    leads_seen: int = 0
    contacts_created: int = 0
    deals_created: int = 0
    moved: int = 0
    blocked: int = 0
    won: int = 0
    lost: int = 0
    states_created: int = 0


@dataclass
class _Funnel:
    pipeline_id: uuid.UUID
    by_stage_key: dict[str, CrmStage] = field(default_factory=dict)
    by_status_key: dict[str, CrmStage] = field(default_factory=dict)
    first_open: CrmStage | None = None


async def run_sync_cycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> SyncStats | None:
    """Run one sync pass. Returns None when another instance holds the lock."""
    async with session_factory() as session:
        async with session.begin():
            got_lock = (
                await session.execute(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": SYNC_LOCK_KEY}
                )
            ).scalar()
            if not got_lock:
                logger.debug("sync skipped: lock held by another instance")
                return None
            stats = await sync_all(session)
    logger.info(
        "sync cycle done leads=%d contacts+=%d deals+=%d moved=%d blocked=%d",
        stats.leads_seen,
        stats.contacts_created,
        stats.deals_created,
        stats.moved,
        stats.blocked,
    )
    return stats


async def sync_all(session: AsyncSession) -> SyncStats:
    """Sync every bot lead into contacts/deals. Caller owns the transaction."""
    funnel = await _load_funnel(session)
    stats = SyncStats()
    last_id = ""
    while True:
        batch = (
            await session.execute(
                text(
                    "SELECT whatsapp_id, name, current_stage, previous_stage, status,"
                    " direction, goal, experience_level, preferred_format,"
                    " preferred_time, trial_datetime, last_objection"
                    " FROM knewit_leads WHERE whatsapp_id > :last"
                    " ORDER BY whatsapp_id LIMIT :limit"
                ),
                {"last": last_id, "limit": BATCH_SIZE},
            )
        ).mappings()
        rows = list(batch)
        if not rows:
            break
        for lead in rows:
            await _sync_lead(session, funnel, dict(lead), stats)
        last_id = rows[-1]["whatsapp_id"]
    await _store_last_synced(session)
    return stats


async def _load_funnel(session: AsyncSession) -> _Funnel:
    pipeline = (
        (
            await session.execute(
                select(CrmPipeline).order_by(CrmPipeline.is_default.desc(), CrmPipeline.sort)
            )
        )
        .scalars()
        .first()
    )
    if pipeline is None:
        raise SyncConfigError("No pipeline found; run migrations to seed the funnel")
    stages = (
        await session.execute(
            select(CrmStage).where(CrmStage.pipeline_id == pipeline.id).order_by(CrmStage.sort)
        )
    ).scalars()
    funnel = _Funnel(pipeline_id=pipeline.id)
    for stage in stages:
        if stage.bot_stage_key:
            funnel.by_stage_key.setdefault(stage.bot_stage_key, stage)
        if stage.bot_status_key:
            funnel.by_status_key.setdefault(stage.bot_status_key, stage)
        if funnel.first_open is None and stage.kind == DEAL_STATUS_OPEN:
            funnel.first_open = stage
    if funnel.first_open is None:
        raise SyncConfigError("Default pipeline has no open stage")
    return funnel


async def _sync_lead(
    session: AsyncSession, funnel: _Funnel, lead: dict[str, Any], stats: SyncStats
) -> None:
    whatsapp_id: str = lead["whatsapp_id"]
    stats.leads_seen += 1

    state = await session.get(CrmConversationState, whatsapp_id)
    if state is None:
        # Fresh rows start as read; unread counts from here forward (D14).
        state = CrmConversationState(
            whatsapp_id=whatsapp_id, unread_count=0, last_read_at=datetime.now(UTC)
        )
        session.add(state)
        stats.states_created += 1
        unread_before = 0
    else:
        if state.last_read_at is None:
            state.last_read_at = datetime.now(UTC)
            state.unread_count = 0
            unread_before = 0
        else:
            unread_before = state.unread_count
            state.unread_count = (
                await session.execute(
                    text(
                        "SELECT COUNT(*) FROM knewit_messages WHERE whatsapp_id = :wa"
                        " AND direction = 'in' AND created_at > :since"
                    ),
                    {"wa": whatsapp_id, "since": state.last_read_at},
                )
            ).scalar() or 0
    if unread_before == 0 and state.unread_count > 0 and state.assigned_to is not None:
        await notify(
            session,
            [state.assigned_to],
            "dialog_message",
            {"whatsapp_id": whatsapp_id, "unread": state.unread_count},
        )

    contact = (
        await session.execute(select(CrmContact).where(CrmContact.whatsapp_id == whatsapp_id))
    ).scalar_one_or_none()
    custom = {name: lead.get(name) for name in CUSTOM_FIELDS}
    if contact is None:
        contact = CrmContact(
            whatsapp_id=whatsapp_id,
            name=lead.get("name"),
            source=CONTACT_SOURCE_BOT,
            custom=custom,
        )
        session.add(contact)
        await session.flush()
        stats.contacts_created += 1
    elif contact.deleted_at is None:
        if lead.get("name") is not None and contact.name != lead["name"]:
            contact.name = lead["name"]
        contact.custom = custom

    if contact.deleted_at is not None:
        return

    target_stage, target_status = _resolve_target(
        funnel, lead.get("status"), lead.get("current_stage")
    )
    deal = await _managed_deal(session, contact.id)
    if deal is None:
        position = await _next_position(session, target_stage.id)
        deal = CrmDeal(
            contact_id=contact.id,
            pipeline_id=funnel.pipeline_id,
            stage_id=target_stage.id,
            title=lead.get("name") or whatsapp_id,
            status=target_status,
            trial_at=lead.get("trial_datetime"),
            closed_at=datetime.now(UTC) if target_status != DEAL_STATUS_OPEN else None,
            position=position,
            custom=custom,
        )
        session.add(deal)
        await session.flush()
        session.add(
            CrmDealStageHistory(
                deal_id=deal.id,
                from_stage_id=None,
                to_stage_id=target_stage.id,
                changed_by=None,
                source=HISTORY_SOURCE_SYSTEM,
            )
        )
        stats.deals_created += 1
        _count_terminal(stats, target_status)
        await _maybe_handover(session, lead, deal, state)
        return

    deal.custom = custom
    deal.trial_at = lead.get("trial_datetime")
    if deal.stage_id == target_stage.id and deal.status == target_status:
        await _maybe_handover(session, lead, deal, state)
        return
    if deal.stage_locked:
        session.add(
            CrmActivityLog(
                actor_id=None,
                entity="deal",
                entity_id=deal.id,
                action="bot_stage_blocked",
                diff={
                    "lead_status": lead.get("status"),
                    "lead_stage": lead.get("current_stage"),
                    "target_stage_id": str(target_stage.id),
                    "deal_stage_id": str(deal.stage_id),
                },
            )
        )
        stats.blocked += 1
        await _notify_locked(session, deal, target_stage.id)
        await _maybe_handover(session, lead, deal, state)
        return

    from_stage_id = deal.stage_id
    deal.stage_id = target_stage.id
    deal.status = target_status
    deal.closed_at = datetime.now(UTC) if target_status != DEAL_STATUS_OPEN else None
    session.add(
        CrmDealStageHistory(
            deal_id=deal.id,
            from_stage_id=from_stage_id,
            to_stage_id=target_stage.id,
            changed_by=None,
            source=HISTORY_SOURCE_BOT,
        )
    )
    stats.moved += 1
    _count_terminal(stats, target_status)
    await _maybe_handover(session, lead, deal, state)


def _resolve_target(
    funnel: _Funnel, status: str | None, current_stage: str | None
) -> tuple[CrmStage, str]:
    """Bot status wins (client/lost finals); otherwise map the bot stage key."""
    if status == STATUS_CLIENT and STATUS_CLIENT in funnel.by_status_key:
        stage = funnel.by_status_key[STATUS_CLIENT]
        return stage, DEAL_STATUS_WON
    if status == STATUS_LOST and STATUS_LOST in funnel.by_status_key:
        stage = funnel.by_status_key[STATUS_LOST]
        return stage, DEAL_STATUS_LOST
    stage = funnel.by_stage_key.get(current_stage or "")
    if stage is None:
        stage = funnel.first_open
        assert stage is not None
    deal_status = {
        "open": DEAL_STATUS_OPEN,
        "won": DEAL_STATUS_WON,
        "lost": DEAL_STATUS_LOST,
    }[stage.kind]
    return stage, deal_status


async def _managed_deal(session: AsyncSession, contact_id: uuid.UUID) -> CrmDeal | None:
    """The sync-managed deal: most recently updated non-deleted deal (D2)."""
    return (
        (
            await session.execute(
                select(CrmDeal)
                .where(CrmDeal.contact_id == contact_id, CrmDeal.deleted_at.is_(None))
                .order_by(CrmDeal.updated_at.desc())
            )
        )
        .scalars()
        .first()
    )


async def _next_position(session: AsyncSession, stage_id: uuid.UUID) -> int:
    top = (
        await session.execute(
            select(func.max(CrmDeal.position)).where(
                CrmDeal.stage_id == stage_id, CrmDeal.deleted_at.is_(None)
            )
        )
    ).scalar()
    return (top or 0) + 1


def _count_terminal(stats: SyncStats, status: str) -> None:
    if status == DEAL_STATUS_WON:
        stats.won += 1
    elif status == DEAL_STATUS_LOST:
        stats.lost += 1


async def _get_setting(session: AsyncSession, key: str) -> Any:
    return (
        await session.execute(text("SELECT value FROM crm_settings WHERE key = :key"), {"key": key})
    ).scalar_one_or_none()


async def _notify_locked(session: AsyncSession, deal: CrmDeal, target_stage_id: uuid.UUID) -> None:
    """Tell the owner (or all managers) that the bot hit a locked deal."""
    if deal.owner_id is not None:
        targets = [deal.owner_id]
    else:
        targets = [user_id for user_id, _ in await active_managers(session)]
    await notify(
        session,
        targets,
        "locked_stage",
        {
            "deal_id": str(deal.id),
            "target_stage_id": str(target_stage_id),
            "dedupe_key": f"locked-stage:{deal.id}:{target_stage_id}",
        },
    )


async def _maybe_handover(
    session: AsyncSession,
    lead: dict[str, Any],
    deal: CrmDeal,
    state: CrmConversationState,
) -> None:
    """D5: on МЕНЕДЖЕР status create an urgent task + notify; pause only if set."""
    if lead.get("status") != STATUS_MANAGER:
        return
    existing = (
        await session.execute(
            select(CrmTask.id).where(
                CrmTask.deal_id == deal.id,
                CrmTask.done_at.is_(None),
                CrmTask.title == "Ответить клиенту",
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            CrmTask(
                deal_id=deal.id,
                contact_id=deal.contact_id,
                assignee_id=deal.owner_id,
                type="message",
                title="Ответить клиенту",
                due_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
    if deal.owner_id is not None:
        targets = [deal.owner_id]
    else:
        targets = [user_id for user_id, _ in await active_managers(session)]
    await notify(
        session,
        targets,
        "manager_handover",
        {
            "deal_id": str(deal.id),
            "whatsapp_id": lead["whatsapp_id"],
            "dedupe_key": f"handover:{deal.id}",
        },
    )
    auto_pause = await _get_setting(session, "auto_pause_on_manager")
    if auto_pause is True and not state.bot_paused:
        state.bot_paused = True
        state.paused_at = datetime.now(UTC)
        state.paused_by = None


async def _store_last_synced(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO crm_settings (key, value) VALUES (:key, CAST(:value AS jsonb))"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {
            "key": SETTINGS_KEY_LAST_SYNCED,
            "value": json.dumps(datetime.now(UTC).isoformat()),
        },
    )


async def sync_loop(
    session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = 5
) -> None:
    """Background loop for lifespan. Never raises; failures are logged."""
    while True:
        try:
            await run_sync_cycle(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("sync cycle failed")
        await asyncio.sleep(interval_seconds)
