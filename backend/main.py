from __future__ import annotations

import base64
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .db import init_pool, close_pool, get_pool

# Legacy frontend lives in frontend-legacy/ until step 7.
# Fall back to frontend/ for backward compatibility.
_BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = _BASE_DIR / "frontend-legacy" if (_BASE_DIR / "frontend-legacy").exists() else _BASE_DIR / "frontend"


def _get_basic_credentials() -> tuple[str, str]:
    user = os.getenv("CRM_BASIC_USER")
    password = os.getenv("CRM_BASIC_PASS")
    if not user or not password:
        raise RuntimeError(
            "CRM_BASIC_USER and CRM_BASIC_PASS must be set (step 0 temporary protection)"
        )
    return user, password


BASIC_USER, BASIC_PASS = _get_basic_credentials()

# Only health check stays public, everything else requires basic auth.
PUBLIC_PATHS = {"/api/health"}


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("basic "):
            return self._unauthorized()
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
        except Exception:
            return self._unauthorized()
        username, sep, password = decoded.partition(":")
        if not sep:
            return self._unauthorized()
        user_ok = secrets.compare_digest(username, BASIC_USER)
        pass_ok = secrets.compare_digest(password, BASIC_PASS)
        if not (user_ok and pass_ok):
            return self._unauthorized()
        return await call_next(request)

    @staticmethod
    def _unauthorized() -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": 'Basic realm="KnewIT CRM"'},
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(title="KnewIT CRM", version="1.0.0", lifespan=lifespan)

app.add_middleware(BasicAuthMiddleware)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in list(d.items()):
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health():
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"ok": True}


@app.get("/api/stats")
async def get_stats():
    pool = get_pool()
    async with pool.acquire() as conn:
        leads = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                                          AS total,
                COUNT(*) FILTER (WHERE status = 'ACTIVE')                         AS active,
                COUNT(*) FILTER (WHERE status = 'ЗАПИСАН')                        AS booked,
                COUNT(*) FILTER (WHERE status = 'КЛИЕНТ')                         AS clients,
                COUNT(*) FILTER (WHERE status = 'ОТКАЗ')                          AS lost,
                COUNT(*) FILTER (WHERE status = 'ДУМАЕТ')                         AS thinking,
                COUNT(*) FILTER (WHERE status = 'МЕНЕДЖЕР')                       AS manager,
                COUNT(*) FILTER (WHERE created_at > now() - interval '24 hours')  AS new_today,
                COUNT(*) FILTER (WHERE last_message_at > now() - interval '1 hour') AS active_last_hour
            FROM knewit_leads
            """
        )
        stages = await conn.fetch(
            """
            SELECT current_stage AS stage, COUNT(*) AS cnt
            FROM knewit_leads
            GROUP BY current_stage
            ORDER BY cnt DESC
            """
        )
        msgs = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE direction = 'in')  AS incoming,
                COUNT(*) FILTER (WHERE direction = 'out') AS outgoing
            FROM knewit_messages
            WHERE created_at > now() - interval '24 hours'
            """
        )

    return {
        "leads": row_to_dict(leads),
        "stages": [row_to_dict(r) for r in stages],
        "messages_24h": row_to_dict(msgs),
    }


@app.get("/api/leads")
async def list_leads(
    search: Optional[str] = None,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    pool = get_pool()
    where = ["1=1"]
    params: list[Any] = []

    if search:
        params.append(f"%{search.lower().strip()}%")
        idx = len(params)
        where.append(
            f"(lower(coalesce(l.name,'')) LIKE ${idx} "
            f"OR lower(l.whatsapp_id) LIKE ${idx})"
        )

    if status and status != "ALL":
        params.append(status)
        where.append(f"l.status = ${len(params)}")

    if stage and stage != "ALL":
        params.append(stage)
        where.append(f"l.current_stage = ${len(params)}")

    params.append(limit)
    limit_idx = len(params)
    params.append(offset)
    offset_idx = len(params)

    sql = f"""
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
        LIMIT ${limit_idx} OFFSET ${offset_idx}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return {"items": [row_to_dict(r) for r in rows], "count": len(rows)}


@app.get("/api/leads/{whatsapp_id}")
async def get_lead(whatsapp_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM knewit_leads WHERE whatsapp_id = $1", whatsapp_id
        )
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return row_to_dict(row)


@app.get("/api/leads/{whatsapp_id}/messages")
async def get_lead_messages(
    whatsapp_id: str,
    limit: int = Query(500, ge=1, le=2000),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, direction, message_type, content, stage_at_moment,
                   tokens_used, response_time_ms, created_at
            FROM knewit_messages
            WHERE whatsapp_id = $1
            ORDER BY created_at ASC, id ASC
            LIMIT $2
            """,
            whatsapp_id,
            limit,
        )
    return {"items": [row_to_dict(r) for r in rows]}


@app.get("/api/leads/{whatsapp_id}/events")
async def get_lead_events(whatsapp_id: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, from_stage, to_stage, payload, created_at
            FROM knewit_events
            WHERE whatsapp_id = $1
            ORDER BY created_at ASC, id ASC
            """,
            whatsapp_id,
        )
    return {"items": [row_to_dict(r) for r in rows]}


@app.get("/api/funnel")
async def get_funnel():
    pool = get_pool()
    async with pool.acquire() as conn:
        from_events = await conn.fetch(
            """
            SELECT to_stage AS stage, COUNT(DISTINCT whatsapp_id) AS cnt
            FROM knewit_events
            WHERE event_type = 'stage_entered'
            GROUP BY to_stage
            """
        )
        from_leads = await conn.fetch(
            """
            SELECT current_stage AS stage, COUNT(*) AS cnt
            FROM knewit_leads
            GROUP BY current_stage
            ORDER BY cnt DESC
            """
        )
    return {
        "from_events": [row_to_dict(r) for r in from_events],
        "from_leads": [row_to_dict(r) for r in from_leads],
    }


# ---------------------------------------------------------------------------
# Static frontend (mounted last so /api/* takes precedence)
# ---------------------------------------------------------------------------
@app.get("/")
async def root_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")