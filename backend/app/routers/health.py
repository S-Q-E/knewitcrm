from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_session
from ..errors import ApiError

router = APIRouter()


@router.get("/api/health")
async def health(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise ApiError("DB_UNAVAILABLE", "Database is unavailable", 503) from exc
    return {"ok": True}


@router.get("/api/ready")
async def ready(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        raise ApiError("NOT_READY", "Service is not ready", 503) from exc
    return {"ready": True, "db": "up"}
