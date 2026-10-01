from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_session
from ..errors import ApiError

router = APIRouter()


def row_to_dict(row) -> dict:
    data = dict(row._mapping)
    for key, value in list(data.items()):
        if hasattr(value, "isoformat"):
            data[key] = value.isoformat()
    return data


@router.get("/api/leads")
async def list_leads(
    search: str | None = None,
    status: str | None = None,
    stage: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    where = ["1=1"]
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if search:
        params["search"] = f"%{search.lower().strip()}%"
        where.append(
            "(lower(coalesce(l.name,'')) LIKE :search " "OR lower(l.whatsapp_id) LIKE :search)"
        )

    if status and status != "ALL":
        params["status"] = status
        where.append("l.status = :status")

    if stage and stage != "ALL":
        params["stage"] = stage
        where.append("l.current_stage = :stage")

    rows = (
        await session.execute(
            text(
                f"""
                SELECT
                    l.whatsapp_id, l.name, l.current_stage, l.previous_stage, l.status,
                    l.direction, l.goal, l.experience_level, l.preferred_format,
                    l.preferred_time, l.trial_datetime, l.last_objection,
                    l.created_at, l.updated_at, l.last_message_at, l.confidence_last,
                    (SELECT content FROM knewit_messages m
                        WHERE m.whatsapp_id = l.whatsapp_id
                        ORDER BY m.created_at DESC LIMIT 1) AS last_message,
                    (SELECT created_at FROM knewit_messages m
                        WHERE m.whatsapp_id = l.whatsapp_id
                        ORDER BY m.created_at DESC LIMIT 1) AS last_message_time,
                    (SELECT COUNT(*) FROM knewit_messages m
                        WHERE m.whatsapp_id = l.whatsapp_id) AS message_count
                FROM knewit_leads l
                WHERE {' AND '.join(where)}
                ORDER BY COALESCE(l.last_message_at, l.created_at) DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        )
    ).all()

    return {"items": [row_to_dict(r) for r in rows], "count": len(rows)}


@router.get("/api/leads/{whatsapp_id}")
async def get_lead(whatsapp_id: str, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(
            text(
                "SELECT whatsapp_id, name, current_stage, previous_stage, status,"
                " direction, goal, experience_level, preferred_format,"
                " preferred_time, trial_datetime, last_objection,"
                " created_at, updated_at, last_message_at, confidence_last"
                " FROM knewit_leads WHERE whatsapp_id = :whatsapp_id"
            ),
            {"whatsapp_id": whatsapp_id},
        )
    ).one_or_none()
    if row is None:
        raise ApiError("NOT_FOUND", "Lead not found", 404)
    return row_to_dict(row)


@router.get("/api/leads/{whatsapp_id}/messages")
async def get_lead_messages(
    whatsapp_id: str,
    limit: int = Query(500, ge=1, le=2000),
    session: AsyncSession = Depends(get_session),
):
    rows = (
        await session.execute(
            text(
                """
                SELECT id, direction, message_type, content, stage_at_moment,
                       tokens_used, response_time_ms, created_at
                FROM knewit_messages
                WHERE whatsapp_id = :whatsapp_id
                ORDER BY created_at ASC, id ASC
                LIMIT :limit
                """
            ),
            {"whatsapp_id": whatsapp_id, "limit": limit},
        )
    ).all()
    return {"items": [row_to_dict(r) for r in rows]}


@router.get("/api/leads/{whatsapp_id}/events")
async def get_lead_events(whatsapp_id: str, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(
            text(
                """
                SELECT id, event_type, from_stage, to_stage, payload, created_at
                FROM knewit_events
                WHERE whatsapp_id = :whatsapp_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"whatsapp_id": whatsapp_id},
        )
    ).all()
    return {"items": [row_to_dict(r) for r in rows]}
