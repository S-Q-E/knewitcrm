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
    CrmNotification,
    CrmPipeline,
    CrmStage,
    CrmTask,
)
from ..services.activity import log_activity
from ..services.event_bus import bus
from ..services.notifications import active_managers, notify

logger = logging.getLogger(__name__)

# Advisory-lock key for the sync worker (bigint). The session-scoped variant
# is held for the whole cycle while every lead batch commits independently,
# so a crash never rolls back completed batches and never blocks bot tables.
SYNC_LOCK_KEY = 91030001
SETTINGS_KEY_LAST_SYNCED = "sync_worker.last_synced_at"
SETTINGS_KEY_LAST_FULL = "sync_worker.last_full_synced_at"
BATCH_SIZE = 500
# Incremental cycles only fetch leads active after (last_synced - overlap);
# a full reconciliation runs when the last full pass is older than this.
OVERLAP_WINDOW = timedelta(minutes=2)
FULL_RESCAN_INTERVAL = timedelta(minutes=10)
HANDOVER_ACTION = "handover_triggered"

# knewit_leads columns mirrored into contact/deal custom payloads.
# Only these keys are written by the sync; any other custom keys belong to
# the manager and are left untouched (merge, never replace).
CUSTOM_FIELDS = (
    "direction",
    "goal",
    "experience_level",
    "preferred_format",
    "preferred_time",
    "last_objection",
)


def _merge_bot_custom(existing: Any, lead: dict[str, Any]) -> dict[str, Any]:
    """Merge bot-mirrored keys into the stored custom payload.

    Manager keys (anything outside CUSTOM_FIELDS) are preserved as-is;
    bot keys are always refreshed from the lead (including NULL clears),
    so bot fields keep updating while manual fields survive.
    """
    base = dict(existing) if isinstance(existing, dict) else {}
    for name in CUSTOM_FIELDS:
        base[name] = lead.get(name)
    return base


def _norm_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    return None


def _datetimes_equal(first: Any, second: Any) -> bool:
    return _norm_dt(first) == _norm_dt(second)


def _sync_contact_name(contact: CrmContact, bot_name: str | None) -> None:
    """Overwrite contact.name only when the manager did not edit it manually.

    The manager edit is detected by comparing the current name against the
    last bot value seen by the sync (``last_bot_name``). NULL bot names
    never erase anything.
    """
    if bot_name is None:
        return
    snapshot = contact.last_bot_name
    if snapshot is None:
        # Row predates the snapshot column (migration backfill missed it,
        # e.g. bot tables were absent): record the snapshot, fill empty
        # names only, never clobber a possible manager value.
        if not contact.name:
            contact.name = bot_name
        contact.last_bot_name = bot_name
        return
    if not contact.name or contact.name == snapshot:
        if contact.name != bot_name:
            contact.name = bot_name
    # Else: manager changed the name manually -> keep it.
    contact.last_bot_name = bot_name


def _sync_deal_trial(deal: CrmDeal, bot_trial: Any) -> None:
    """Overwrite deal.trial_at only on a real bot change.

    NULL from the bot never erases a manager value; a non-NULL bot value
    is applied only when it differs from the last synced bot value, so a
    manager edit made while the bot value is stable survives the sync.
    """
    if bot_trial is None:
        return
    snapshot = deal.last_bot_trial_at
    if snapshot is None:
        # Untracked row (see _sync_contact_name): fill empty trials only,
        # otherwise preserve the possible manager value and just record.
        if deal.trial_at is None:
            deal.trial_at = bot_trial
            deal.last_bot_trial_at = bot_trial
        elif _datetimes_equal(deal.trial_at, bot_trial):
            deal.last_bot_trial_at = bot_trial
        else:
            # trial_at holds a manager value while the bot already carries
            # bot_trial (bot unchanged since before tracking) -> keep the
            # manager value, record the snapshot for future change detection.
            deal.last_bot_trial_at = bot_trial
        return
    if not _datetimes_equal(bot_trial, snapshot):
        deal.trial_at = bot_trial
        deal.last_bot_trial_at = bot_trial
    # Else: bot value stable -> keep whatever the manager set.


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
    # Realtime events buffered during a batch, published after its commit.
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _Funnel:
    pipeline_id: uuid.UUID
    by_stage_key: dict[str, CrmStage] = field(default_factory=dict)
    by_status_key: dict[str, CrmStage] = field(default_factory=dict)
    first_open: CrmStage | None = None


async def run_sync_cycle(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    force_full: bool = False,
) -> SyncStats | None:
    """Run one sync pass. Returns None when another instance holds the lock."""
    async with session_factory() as session:
        got_lock = (
            await session.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": SYNC_LOCK_KEY})
        ).scalar()
        if not got_lock:
            logger.debug("sync skipped: lock held by another instance")
            return None
        try:
            stats = await sync_all(session, force_full=force_full)
        finally:
            try:
                await session.rollback()
            except Exception:
                logger.warning("sync pre-unlock rollback failed", exc_info=True)
            try:
                await session.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": SYNC_LOCK_KEY}
                )
            except Exception:
                logger.warning("sync lock release failed", exc_info=True)
    logger.info(
        "sync cycle done leads=%d contacts+=%d deals+=%d moved=%d blocked=%d",
        stats.leads_seen,
        stats.contacts_created,
        stats.deals_created,
        stats.moved,
        stats.blocked,
    )
    return stats


async def sync_all(session: AsyncSession, *, force_full: bool = False) -> SyncStats:
    """Sync bot leads into contacts/deals. Commits after every batch.

    Incremental cycles fetch only leads with
    ``GREATEST(updated_at, last_message_at)`` newer than the previous
    ``last_synced_at`` minus an overlap window; a full reconciliation runs
    when the last full pass is older than ``FULL_RESCAN_INTERVAL``.
    The caller must hold the advisory lock.
    """
    funnel = await _load_funnel(session)
    now = datetime.now(UTC)
    last_synced = await _load_marker(session, SETTINGS_KEY_LAST_SYNCED)
    last_full = await _load_marker(session, SETTINGS_KEY_LAST_FULL)
    full = force_full or last_full is None or (now - last_full) >= FULL_RESCAN_INTERVAL
    cutoff = last_synced - OVERLAP_WINDOW if (not full and last_synced is not None) else None
    stats = SyncStats()
    manager_ids = [user_id for user_id, _ in await active_managers(session)]
    auto_pause = await _get_setting(session, "auto_pause_on_manager")
    last_id = ""
    while True:
        rows = await _fetch_lead_batch(session, last_id, cutoff)
        if not rows:
            break
        await _sync_batch(
            session, funnel, [dict(row) for row in rows], stats, manager_ids, auto_pause
        )
        await session.commit()
        for pending in stats.events:
            bus.publish(pending["type"], pending["data"])
        stats.events.clear()
        last_id = rows[-1]["whatsapp_id"]
    finished = datetime.now(UTC)
    await _store_marker(session, SETTINGS_KEY_LAST_SYNCED, finished)
    if full:
        await _store_marker(session, SETTINGS_KEY_LAST_FULL, finished)
    await session.commit()
    return stats


_LEAD_SELECT = (
    "SELECT whatsapp_id, name, current_stage, previous_stage, status,"
    " direction, goal, experience_level, preferred_format,"
    " preferred_time, trial_datetime, last_objection"
    " FROM knewit_leads"
)


async def _fetch_lead_batch(
    session: AsyncSession, last_id: str, cutoff: datetime | None
) -> list[Any]:
    """One keyset page of leads; incremental when ``cutoff`` is set."""
    if cutoff is None:
        result = await session.execute(
            text(_LEAD_SELECT + " WHERE whatsapp_id > :last" " ORDER BY whatsapp_id LIMIT :limit"),
            {"last": last_id, "limit": BATCH_SIZE},
        )
    else:
        result = await session.execute(
            text(
                _LEAD_SELECT + " WHERE whatsapp_id > :last"
                " AND GREATEST(updated_at, COALESCE(last_message_at, updated_at)) > :cutoff"
                " ORDER BY whatsapp_id LIMIT :limit"
            ),
            {"last": last_id, "limit": BATCH_SIZE, "cutoff": cutoff},
        )
    return list(result.mappings())


async def _load_marker(session: AsyncSession, key: str) -> datetime | None:
    value = await _get_setting(session, key)
    if value is None:
        return None
    if isinstance(value, datetime):
        marker = value
    else:
        try:
            marker = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if marker.tzinfo is None:
        marker = marker.replace(tzinfo=UTC)
    return marker


async def _store_marker(session: AsyncSession, key: str, when: datetime) -> None:
    await session.execute(
        text(
            "INSERT INTO crm_settings (key, value) VALUES (:key, CAST(:value AS jsonb))"
            " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        ),
        {"key": key, "value": json.dumps(when.isoformat())},
    )


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


async def _sync_batch(
    session: AsyncSession,
    funnel: _Funnel,
    leads: list[dict[str, Any]],
    stats: SyncStats,
    manager_ids: list[uuid.UUID],
    auto_pause: Any,
) -> None:
    """Sync one lead batch with a constant number of queries (no N+1)."""
    wa_ids = [lead["whatsapp_id"] for lead in leads]

    states, fresh_states = await _load_states(session, wa_ids, stats)
    await session.flush()
    unread = await _unread_counts(session, wa_ids)
    await _refresh_last_messages(session, states, wa_ids)
    for lead in leads:
        whatsapp_id = lead["whatsapp_id"]
        stats.leads_seen += 1
        state = states[whatsapp_id]
        unread_before = 0 if whatsapp_id in fresh_states else state.unread_count
        state.unread_count = unread.get(whatsapp_id, 0)
        if unread_before == 0 and state.unread_count > 0 and state.assigned_to is not None:
            stats.events.extend(
                await notify(
                    session,
                    [state.assigned_to],
                    "dialog_message",
                    {"whatsapp_id": whatsapp_id, "unread": state.unread_count},
                )
            )

    contacts = {
        contact.whatsapp_id: contact
        for contact in (
            await session.execute(select(CrmContact).where(CrmContact.whatsapp_id.in_(wa_ids)))
        )
        .scalars()
        .all()
    }
    created_was: set[str] = set()
    for lead in leads:
        whatsapp_id = lead["whatsapp_id"]
        if whatsapp_id not in contacts:
            contact = CrmContact(
                whatsapp_id=whatsapp_id,
                name=lead.get("name"),
                source=CONTACT_SOURCE_BOT,
                custom={name: lead.get(name) for name in CUSTOM_FIELDS},
                last_bot_name=lead.get("name"),
            )
            session.add(contact)
            contacts[whatsapp_id] = contact
            created_was.add(whatsapp_id)
            stats.contacts_created += 1
    await session.flush()
    for lead in leads:
        whatsapp_id = lead["whatsapp_id"]
        if whatsapp_id in created_was:
            continue
        contact = contacts[whatsapp_id]
        if contact.deleted_at is None:
            _sync_contact_name(contact, lead.get("name"))
            contact.custom = _merge_bot_custom(contact.custom, lead)

    live_ids = [c.id for c in contacts.values() if c.deleted_at is None]
    managed: dict[uuid.UUID, CrmDeal] = {}
    if live_ids:
        managed = {
            deal.contact_id: deal
            for deal in (
                await session.execute(
                    select(CrmDeal)
                    .distinct(CrmDeal.contact_id)
                    .where(CrmDeal.contact_id.in_(live_ids), CrmDeal.deleted_at.is_(None))
                    .order_by(CrmDeal.contact_id, CrmDeal.updated_at.desc())
                )
            )
            .scalars()
            .all()
        }

    pending: list[tuple[dict[str, Any], CrmContact, CrmStage, str]] = []
    for lead in leads:
        contact = contacts[lead["whatsapp_id"]]
        if contact.deleted_at is not None or contact.id in managed:
            continue
        target_stage, target_status = _resolve_target(
            funnel, lead.get("status"), lead.get("current_stage")
        )
        pending.append((lead, contact, target_stage, target_status))
    tops: dict[uuid.UUID, Any] = {}
    if pending:
        tops = await _stage_tops(session, list({target.id for _, _, target, _ in pending}))
    handed_over = (
        await _handed_over_deal_ids(session, [deal.id for deal in managed.values()])
        if managed
        else set()
    )

    new_contact_ids: set[uuid.UUID] = set()
    if pending:
        for lead, contact, target_stage, target_status in pending:
            new_contact_ids.add(contact.id)
            position = (tops.get(target_stage.id) or 0) + 1
            tops[target_stage.id] = position
            session.add(
                CrmDeal(
                    contact_id=contact.id,
                    pipeline_id=funnel.pipeline_id,
                    stage_id=target_stage.id,
                    title=lead.get("name") or lead["whatsapp_id"],
                    status=target_status,
                    trial_at=lead.get("trial_datetime"),
                    last_bot_trial_at=lead.get("trial_datetime"),
                    closed_at=datetime.now(UTC) if target_status != DEAL_STATUS_OPEN else None,
                    position=position,
                    custom={name: lead.get(name) for name in CUSTOM_FIELDS},
                )
            )
        await session.flush()
        # Deals were just flushed above; fetch them back in one query
        # instead of one SELECT per deal.
        created_deals = {
            deal.contact_id: deal
            for deal in (
                await session.execute(
                    select(CrmDeal)
                    .distinct(CrmDeal.contact_id)
                    .where(
                        CrmDeal.contact_id.in_([c.id for _, c, _, _ in pending]),
                        CrmDeal.deleted_at.is_(None),
                    )
                    .order_by(CrmDeal.contact_id, CrmDeal.updated_at.desc())
                )
            )
            .scalars()
            .all()
        }
        for lead, contact, target_stage, target_status in pending:
            deal = created_deals[contact.id]
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
            await _maybe_handover(
                session,
                lead,
                deal,
                states[lead["whatsapp_id"]],
                manager_ids,
                auto_pause,
                handed_over,
                stats,
            )

    for lead in leads:
        contact = contacts[lead["whatsapp_id"]]
        if contact.deleted_at is not None or contact.id in new_contact_ids:
            continue
        deal = managed.get(contact.id)
        if deal is None:
            continue
        await _sync_existing_deal(
            session,
            funnel,
            lead,
            deal,
            states[lead["whatsapp_id"]],
            stats,
            manager_ids,
            auto_pause,
            handed_over,
        )


async def _load_states(
    session: AsyncSession, wa_ids: list[str], stats: SyncStats
) -> tuple[dict[str, CrmConversationState], set[str]]:
    rows = (
        await session.execute(
            select(CrmConversationState).where(CrmConversationState.whatsapp_id.in_(wa_ids))
        )
    ).scalars()
    states = {state.whatsapp_id: state for state in rows}
    # Fresh rows start as read; unread counts from here forward (D14).
    fresh: set[str] = set()
    now = datetime.now(UTC)
    for whatsapp_id in wa_ids:
        state = states.get(whatsapp_id)
        if state is None:
            state = CrmConversationState(whatsapp_id=whatsapp_id, unread_count=0, last_read_at=now)
            session.add(state)
            states[whatsapp_id] = state
            fresh.add(whatsapp_id)
            stats.states_created += 1
        elif state.last_read_at is None:
            state.last_read_at = now
            state.unread_count = 0
            fresh.add(whatsapp_id)
    return states, fresh


async def _refresh_last_messages(
    session: AsyncSession, states: dict[str, CrmConversationState], wa_ids: list[str]
) -> None:
    """Cache the latest message summary on each conversation state.

    The dialog list orders and renders from these columns, so it never
    touches ``knewit_messages`` (owned by n8n, no new indexes allowed).
    """
    if not wa_ids:
        return
    rows = (
        (
            await session.execute(
                text(
                    "SELECT DISTINCT ON (whatsapp_id) whatsapp_id, direction, content,"
                    " created_at FROM knewit_messages WHERE whatsapp_id = ANY(:ids)"
                    " ORDER BY whatsapp_id, created_at DESC, id DESC"
                ),
                {"ids": wa_ids},
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        state = states.get(row["whatsapp_id"])
        if state is None:
            continue
        state.last_message_at = row["created_at"]
        state.last_message_direction = row["direction"]
        state.last_message_preview = (row["content"] or "")[:200]


async def _unread_counts(session: AsyncSession, wa_ids: list[str]) -> dict[str, int]:
    """Unread incoming messages per lead in a single GROUP BY query."""
    rows = (
        await session.execute(
            text(
                "SELECT m.whatsapp_id AS wa, COUNT(*) AS cnt"
                " FROM knewit_messages m"
                " JOIN crm_conversation_state s ON s.whatsapp_id = m.whatsapp_id"
                " WHERE m.whatsapp_id = ANY(:ids)"
                " AND m.direction = 'in'"
                " AND s.last_read_at IS NOT NULL"
                " AND m.created_at > s.last_read_at"
                " GROUP BY m.whatsapp_id"
            ),
            {"ids": list(wa_ids)},
        )
    ).mappings()
    return {row["wa"]: row["cnt"] for row in rows}


async def _stage_tops(session: AsyncSession, stage_ids: list[uuid.UUID]) -> dict[uuid.UUID, Any]:
    if not stage_ids:
        return {}
    rows = (
        await session.execute(
            select(func.max(CrmDeal.position), CrmDeal.stage_id)
            .where(CrmDeal.stage_id.in_(stage_ids), CrmDeal.deleted_at.is_(None))
            .group_by(CrmDeal.stage_id)
        )
    ).all()
    return {stage_id: top for top, stage_id in rows}


async def _handed_over_deal_ids(session: AsyncSession, deal_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Deals already handed over, ever: a handover task (done or not) or a log entry."""
    if not deal_ids:
        return set()
    tasks = await session.execute(
        select(CrmTask.deal_id).where(
            CrmTask.deal_id.in_(deal_ids),
            CrmTask.title == "Ответить клиенту",
        )
    )
    logged = await session.execute(
        select(CrmActivityLog.entity_id).where(
            CrmActivityLog.entity == "deal",
            CrmActivityLog.action == HANDOVER_ACTION,
            CrmActivityLog.entity_id.in_(deal_ids),
        )
    )
    return set(tasks.scalars().all()) | set(logged.scalars().all())


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


async def _sync_existing_deal(
    session: AsyncSession,
    funnel: _Funnel,
    lead: dict[str, Any],
    deal: CrmDeal,
    state: CrmConversationState,
    stats: SyncStats,
    manager_ids: list[uuid.UUID],
    auto_pause: Any,
    handed_over: set[uuid.UUID],
) -> None:
    target_stage, target_status = _resolve_target(
        funnel, lead.get("status"), lead.get("current_stage")
    )
    deal.custom = _merge_bot_custom(deal.custom, lead)
    _sync_deal_trial(deal, lead.get("trial_datetime"))
    if deal.stage_id == target_stage.id and deal.status == target_status:
        await _maybe_handover(
            session, lead, deal, state, manager_ids, auto_pause, handed_over, stats
        )
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
        await _notify_locked(session, deal, target_stage.id, manager_ids, stats)
        await _maybe_handover(
            session, lead, deal, state, manager_ids, auto_pause, handed_over, stats
        )
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
    stats.events.append(
        {
            "type": "deal_moved",
            "data": {
                "deal_id": str(deal.id),
                "to_stage_id": str(target_stage.id),
                "source": "bot",
                "owner_id": str(deal.owner_id) if deal.owner_id else None,
            },
        }
    )
    _count_terminal(stats, target_status)
    await _maybe_handover(session, lead, deal, state, manager_ids, auto_pause, handed_over, stats)


def _count_terminal(stats: SyncStats, status: str) -> None:
    if status == DEAL_STATUS_WON:
        stats.won += 1
    elif status == DEAL_STATUS_LOST:
        stats.lost += 1


async def _get_setting(session: AsyncSession, key: str) -> Any:
    return (
        await session.execute(text("SELECT value FROM crm_settings WHERE key = :key"), {"key": key})
    ).scalar_one_or_none()


async def _notify_locked(
    session: AsyncSession,
    deal: CrmDeal,
    target_stage_id: uuid.UUID,
    manager_ids: list[uuid.UUID],
    stats: SyncStats,
) -> None:
    """Tell the owner (or all managers) that the bot hit a locked deal."""
    if deal.owner_id is not None:
        targets = [deal.owner_id]
    else:
        targets = list(manager_ids)
    stats.events.extend(
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
    )


async def _maybe_handover(
    session: AsyncSession,
    lead: dict[str, Any],
    deal: CrmDeal,
    state: CrmConversationState,
    manager_ids: list[uuid.UUID],
    auto_pause: Any,
    handed_over: set[uuid.UUID],
    stats: SyncStats,
) -> None:
    """D5/D15: the first МЕНЕДЖЕР status of a deal creates one urgent task and notifies once.

    Later passes do nothing for the deal, even after the task is done or read.
    The notification is also skipped when a notification with the same key already
    exists for the recipient, read or not.
    """
    if lead.get("status") != STATUS_MANAGER:
        return
    if deal.id not in handed_over:
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
        await log_activity(
            session,
            None,
            "deal",
            deal.id,
            HANDOVER_ACTION,
            {"whatsapp_id": lead["whatsapp_id"]},
        )
        handed_over.add(deal.id)
        if deal.owner_id is not None:
            targets = [deal.owner_id]
        else:
            targets = list(manager_ids)
        dedupe_key = f"handover:{deal.id}"
        already = set(
            (
                await session.execute(
                    select(CrmNotification.user_id).where(
                        CrmNotification.type == "manager_handover",
                        CrmNotification.dedupe_key == dedupe_key,
                        CrmNotification.user_id.in_(targets),
                    )
                )
            )
            .scalars()
            .all()
        )
        targets = [user_id for user_id in targets if user_id not in already]
        stats.events.extend(
            await notify(
                session,
                targets,
                "manager_handover",
                {
                    "deal_id": str(deal.id),
                    "whatsapp_id": lead["whatsapp_id"],
                    "dedupe_key": dedupe_key,
                },
            )
        )
    if auto_pause is True and not state.bot_paused:
        state.bot_paused = True
        state.paused_at = datetime.now(UTC)
        state.paused_by = None


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
