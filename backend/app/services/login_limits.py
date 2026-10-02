from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from ..models import CrmLoginAttempt, CrmSession, CrmUser

# Budgets preserved from the former in-memory limiter (D9): 5 failures per
# (IP, email) stop stuffing against one account from one source, 20 per
# email stop distributed guessing. The per-email block is soft (see below).
PAIR_MAX_ATTEMPTS = 5
EMAIL_MAX_ATTEMPTS = 20
FAIL_WINDOW = timedelta(minutes=10)
RETENTION = timedelta(hours=1)


def _retry_after(oldest: datetime, now: datetime) -> int:
    """Seconds until the oldest counted failure leaves the window (min 1)."""
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    return max(1, int((oldest + FAIL_WINDOW - now).total_seconds()) + 1)


async def _owner_last_ip(session, email: str) -> str | None:
    """IP of the account owner's most recent session, if the account exists."""
    return (
        await session.execute(
            select(CrmSession.ip)
            .join(CrmUser, CrmSession.user_id == CrmUser.id)
            .where(CrmUser.email == email)
            .order_by(CrmSession.created_at.desc(), CrmSession.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def is_blocked(session, ip: str, email: str) -> tuple[bool, int]:
    """Check the failure budget. Returns (blocked, retry_after_seconds)."""
    now = datetime.now(UTC)
    cutoff = now - FAIL_WINDOW

    pair_count, pair_oldest = (
        await session.execute(
            select(func.count(), func.min(CrmLoginAttempt.at)).where(
                CrmLoginAttempt.ip == ip,
                CrmLoginAttempt.email == email,
                CrmLoginAttempt.at >= cutoff,
            )
        )
    ).one()
    if (pair_count or 0) >= PAIR_MAX_ATTEMPTS and pair_oldest is not None:
        return True, _retry_after(pair_oldest, now)

    email_count, email_oldest = (
        await session.execute(
            select(func.count(), func.min(CrmLoginAttempt.at)).where(
                CrmLoginAttempt.email == email,
                CrmLoginAttempt.at >= cutoff,
            )
        )
    ).one()
    if (email_count or 0) >= EMAIL_MAX_ATTEMPTS:
        # Soft block: the owner's own network is never locked out by a
        # distributed flood. Unknown emails have no owner IP → always blocked.
        owner_ip = await _owner_last_ip(session, email)
        if (owner_ip is None or ip != owner_ip) and email_oldest is not None:
            return True, _retry_after(email_oldest, now)
    return False, 0


async def record_failure(session, ip: str, email: str) -> None:
    """Persist one failed attempt and drop rows older than the retention.

    Committed immediately: the caller raises 401/429 right after, which
    must not roll the attempt back. Joins no outer transaction semantics —
    attempt rows are append-only facts.
    """
    session.add(CrmLoginAttempt(ip=ip, email=email))
    await session.execute(
        delete(CrmLoginAttempt).where(CrmLoginAttempt.at < datetime.now(UTC) - RETENTION)
    )
    await session.commit()


async def record_success(session, ip: str, email: str) -> None:
    """Clear the email's failure budget. Committed by the caller."""
    del ip
    await session.execute(delete(CrmLoginAttempt).where(CrmLoginAttempt.email == email))
