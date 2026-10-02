from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_session
from ..errors import ApiError
from ..services.metrics import render_prometheus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])


def _token_ok(configured: str, provided: str | None) -> bool:
    if not configured or not provided:
        return False
    return hmac.compare_digest(configured, provided)


@router.get("/api/metrics")
async def metrics(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PlainTextResponse:
    """Prometheus exposition guarded by METRICS_TOKEN (never enabled by default).

    Missing token configuration reads as 404 so scanners learn nothing;
    a wrong token is 403. Auth sessions are deliberately NOT accepted here:
    browsers would otherwise leak the token-bearing URL into history.
    """
    settings = request.app.state.settings
    token = settings.metrics_token or ""
    if not token:
        raise ApiError("NOT_FOUND", "Not found", 404)
    auth = request.headers.get("authorization", "")
    provided = auth[7:] if auth.lower().startswith("bearer ") else None
    if not _token_ok(token, provided):
        raise ApiError("FORBIDDEN", "Invalid metrics token", 403)

    extra: list[str] = []
    try:
        counts = (
            (await session.execute(text("SELECT status, COUNT(*) FROM crm_outbox GROUP BY status")))
            .mappings()
            .all()
        )
        for row in counts:
            extra.append(f'crm_outbox_messages{{status="{row["status"]}"}} {int(row["count"])}')
    except Exception as exc:
        logger.warning("metrics outbox gauge failed: %s", type(exc).__name__)
    try:
        pool = request.app.state.engine.pool
        extra.append(f"crm_db_pool_size {pool.size()}")
        extra.append(f"crm_db_pool_checked_out {pool.checkedout()}")
        extra.append(f"crm_db_pool_overflow {pool.overflow()}")
    except Exception as exc:
        logger.warning("metrics pool gauges failed: %s", type(exc).__name__)
    return PlainTextResponse(render_prometheus(extra), media_type="text/plain; version=0.0.4")
