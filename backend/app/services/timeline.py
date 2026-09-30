from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import ApiError

VALID_TIMELINE_TYPES = ("message", "event", "stage", "note", "task", "activity")

# Tiebreak rank for the (at DESC, rank ASC, id DESC) ordering.
_TYPE_RANK = {"message": 0, "event": 1, "stage": 2, "note": 3, "task": 4, "activity": 5}


def parse_types(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return VALID_TIMELINE_TYPES
    kinds = tuple(part.strip() for part in raw.split(",") if part.strip())
    unknown = set(kinds) - set(VALID_TIMELINE_TYPES)
    if unknown:
        raise ApiError("INVALID_TIMELINE_TYPE", f"Unknown types: {sorted(unknown)}", 422)
    if not kinds:
        raise ApiError("INVALID_TIMELINE_TYPE", "At least one type is required", 422)
    return kinds


def parse_cursor(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
        assert isinstance(payload.get("at"), str)
        assert payload.get("kind") in _TYPE_RANK
        assert isinstance(payload.get("id"), str)
        return payload
    except (ValueError, AssertionError):
        raise ApiError("INVALID_CURSOR", "Timeline cursor is invalid", 422) from None


def encode_cursor(item: dict[str, Any]) -> str:
    raw = json.dumps({"at": item["at"], "kind": item["kind"], "id": item["ref"]})
    return base64.urlsafe_b64encode(raw.encode()).decode()


async def get_deal_timeline(
    session: AsyncSession,
    deal_id: uuid.UUID,
    contact_id: uuid.UUID,
    whatsapp_id: str | None,
    contact_name: str | None,
    kinds: tuple[str, ...],
    limit: int,
    cursor: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Merge bot and CRM records into one newest-first stream with keyset paging."""
    per_source = limit + 1
    collections: list[list[dict[str, Any]]] = []
    if "message" in kinds and whatsapp_id:
        collections.append(await _messages(session, whatsapp_id, cursor, per_source))
    if "event" in kinds and whatsapp_id:
        collections.append(await _events(session, whatsapp_id, cursor, per_source))
    if "stage" in kinds:
        collections.append(await _stages(session, deal_id, cursor, per_source))
    if "note" in kinds:
        collections.append(await _notes(session, deal_id, contact_id, cursor, per_source))
    if "task" in kinds:
        collections.append(await _tasks(session, deal_id, contact_id, cursor, per_source))
    if "activity" in kinds:
        collections.append(await _activity(session, deal_id, contact_id, cursor, per_source))

    merged = sorted(
        (item for chunk in collections for item in chunk),
        key=lambda item: (item["at"], -_TYPE_RANK[item["kind"]], _id_key(item)),
        reverse=True,
    )
    page = merged[: limit + 1]
    await _enrich(session, page, contact_name)
    next_cursor = encode_cursor(page[limit - 1]) if len(page) > limit else None
    return page[:limit], next_cursor


def _id_key(item: dict[str, Any]) -> Any:
    ref = item["ref"]
    return int(ref) if item["kind"] in ("message", "event") else str(ref)


def _keyset_text(column: str, rank: int, numeric_id: bool, cursor: dict | None) -> str:
    """Keyset predicate for (at DESC, rank ASC, id DESC) with a fixed source rank."""
    if cursor is None:
        return "TRUE"
    rank_c = _TYPE_RANK[cursor["kind"]]
    if rank > rank_c:
        return f"{column} <= CAST(:cursor_at AS timestamptz)"
    if rank < rank_c:
        return f"{column} < CAST(:cursor_at AS timestamptz)"
    comparator = (
        f"{column} < CAST(:cursor_at AS timestamptz)"
        f" OR ({column} = CAST(:cursor_at AS timestamptz) AND "
    )
    if numeric_id:
        return comparator + "id < :cursor_id_int)"
    return comparator + "id::text < :cursor_id)"


def _cursor_params(cursor: dict | None) -> dict[str, Any]:
    if cursor is None:
        return {}
    ref = cursor["id"]
    return {
        "cursor_at": datetime.fromisoformat(cursor["at"]),
        "cursor_id": ref,
        "cursor_id_int": int(ref) if ref.isdigit() else -1,
    }


async def _messages(
    session: AsyncSession, whatsapp_id: str, cursor: dict | None, limit: int
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, direction, message_type, content, stage_at_moment,"
                " tokens_used, response_time_ms, created_at FROM knewit_messages"
                f" WHERE whatsapp_id = :wa AND {_keyset_text('created_at', 0, True, cursor)}"
                " ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"wa": whatsapp_id, "limit": limit, **_cursor_params(cursor)},
        )
    ).mappings()
    return [
        {
            "key": f"message:{row['id']}",
            "ref": str(row["id"]),
            "kind": "message",
            "at": row["created_at"].isoformat(),
            "direction": row["direction"],
            "message_type": row["message_type"],
            "body": row["content"],
            "stage_at_moment": row["stage_at_moment"],
            "tokens_used": row["tokens_used"],
            "response_time_ms": row["response_time_ms"],
            "author_kind": "client" if row["direction"] == "in" else "bot",
        }
        for row in rows
    ]


async def _events(
    session: AsyncSession, whatsapp_id: str, cursor: dict | None, limit: int
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, event_type, from_stage, to_stage, payload, created_at"
                " FROM knewit_events"
                f" WHERE whatsapp_id = :wa AND {_keyset_text('created_at', 1, True, cursor)}"
                " ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"wa": whatsapp_id, "limit": limit, **_cursor_params(cursor)},
        )
    ).mappings()
    return [
        {
            "key": f"event:{row['id']}",
            "ref": str(row["id"]),
            "kind": "event",
            "at": row["created_at"].isoformat(),
            "event_type": row["event_type"],
            "from_stage": row["from_stage"],
            "to_stage": row["to_stage"],
            "payload": row["payload"],
        }
        for row in rows
    ]


async def _stages(
    session: AsyncSession, deal_id: uuid.UUID, cursor: dict | None, limit: int
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT h.id, h.from_stage_id, h.to_stage_id, h.changed_by, h.source, h.at,"
                " fs.name AS from_name, ts.name AS to_name"
                " FROM crm_deal_stage_history h"
                " LEFT JOIN crm_stages fs ON fs.id = h.from_stage_id"
                " LEFT JOIN crm_stages ts ON ts.id = h.to_stage_id"
                f" WHERE h.deal_id = :deal AND {_keyset_text('h.at', 2, False, cursor)}"
                " ORDER BY h.at DESC, h.id DESC LIMIT :limit"
            ),
            {"deal": deal_id, "limit": limit, **_cursor_params(cursor)},
        )
    ).mappings()
    return [
        {
            "key": f"stage:{row['id']}",
            "ref": str(row["id"]),
            "kind": "stage",
            "at": row["at"].isoformat(),
            "from_stage": {
                "id": str(row["from_stage_id"]) if row["from_stage_id"] else None,
                "name": row["from_name"],
            },
            "to_stage": {
                "id": str(row["to_stage_id"]) if row["to_stage_id"] else None,
                "name": row["to_name"],
            },
            "source": row["source"],
            "changed_by": str(row["changed_by"]) if row["changed_by"] else None,
        }
        for row in rows
    ]


async def _notes(
    session: AsyncSession,
    deal_id: uuid.UUID,
    contact_id: uuid.UUID,
    cursor: dict | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, body, author_id, pinned, created_at FROM crm_notes"
                f" WHERE (deal_id = :deal OR contact_id = :contact)"
                f" AND {_keyset_text('created_at', 3, False, cursor)}"
                " ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"deal": deal_id, "contact": contact_id, "limit": limit, **_cursor_params(cursor)},
        )
    ).mappings()
    return [
        {
            "key": f"note:{row['id']}",
            "ref": str(row["id"]),
            "kind": "note",
            "at": row["created_at"].isoformat(),
            "body": row["body"],
            "pinned": row["pinned"],
            "author_id": str(row["author_id"]) if row["author_id"] else None,
        }
        for row in rows
    ]


async def _tasks(
    session: AsyncSession,
    deal_id: uuid.UUID,
    contact_id: uuid.UUID,
    cursor: dict | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, title, type, assignee_id, due_at, done_at, created_at FROM crm_tasks"
                f" WHERE (deal_id = :deal OR contact_id = :contact)"
                f" AND {_keyset_text('created_at', 4, False, cursor)}"
                " ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"deal": deal_id, "contact": contact_id, "limit": limit, **_cursor_params(cursor)},
        )
    ).mappings()
    return [
        {
            "key": f"task:{row['id']}",
            "ref": str(row["id"]),
            "kind": "task",
            "at": row["created_at"].isoformat(),
            "title": row["title"],
            "type": row["type"],
            "assignee_id": str(row["assignee_id"]) if row["assignee_id"] else None,
            "due_at": row["due_at"].isoformat() if row["due_at"] else None,
            "done_at": row["done_at"].isoformat() if row["done_at"] else None,
        }
        for row in rows
    ]


async def _activity(
    session: AsyncSession,
    deal_id: uuid.UUID,
    contact_id: uuid.UUID,
    cursor: dict | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT id, entity, action, actor_id, diff, created_at FROM crm_activity_log"
                " WHERE ((entity = 'deal' AND entity_id = :deal)"
                " OR (entity = 'contact' AND entity_id = :contact))"
                f" AND {_keyset_text('created_at', 5, False, cursor)}"
                " ORDER BY created_at DESC, id DESC LIMIT :limit"
            ),
            {"deal": deal_id, "contact": contact_id, "limit": limit, **_cursor_params(cursor)},
        )
    ).mappings()
    return [
        {
            "key": f"activity:{row['id']}",
            "ref": str(row["id"]),
            "kind": "activity",
            "at": row["created_at"].isoformat(),
            "entity": row["entity"],
            "action": row["action"],
            "actor_id": str(row["actor_id"]) if row["actor_id"] else None,
            "diff": row["diff"],
        }
        for row in rows
    ]


async def _enrich(
    session: AsyncSession, items: list[dict[str, Any]], contact_name: str | None
) -> None:
    """Resolve user ids to display names in place."""
    user_ids = {
        item[key]
        for item in items
        for key in ("changed_by", "author_id", "assignee_id", "actor_id")
        if item.get(key)
    }
    names: dict[str, str] = {}
    if user_ids:
        rows = (
            await session.execute(
                text("SELECT id::text AS id, name FROM crm_users WHERE id::text = ANY(:ids)"),
                {"ids": list(user_ids)},
            )
        ).mappings()
        names = {row["id"]: row["name"] for row in rows}
    for item in items:
        for key, label in (
            ("changed_by", "changed_by_name"),
            ("author_id", "author_name"),
            ("assignee_id", "assignee_name"),
            ("actor_id", "actor_name"),
        ):
            if item.get(key):
                item[label] = names.get(item[key], "?")
        if item["kind"] == "message" and item["author_kind"] == "client":
            item["author_name"] = contact_name or "Клиент"
        if item["kind"] == "message" and item["author_kind"] == "bot":
            item["author_name"] = "Бот"
