from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..models import ROLE_ADMIN, CrmUser
from ..security import MIN_PASSWORD_LENGTH, hash_password, normalize_email

logger = logging.getLogger(__name__)


async def ensure_bootstrap_admin(session, admin_email: str, admin_password: str) -> bool:
    """Create the first admin from env, but only when no admin exists yet.

    Returns True when a bootstrap admin was created. Raises ValueError for
    unusable credentials (never logs the password itself).
    """
    email = normalize_email(admin_email)
    if not email or not admin_password:
        return False
    if len(admin_password) < MIN_PASSWORD_LENGTH:
        raise ValueError("ADMIN_PASSWORD must be at least 10 characters")
    existing = (
        await session.execute(select(CrmUser.id).where(CrmUser.role == ROLE_ADMIN).limit(1))
    ).first()
    if existing is not None:
        return False
    session.add(
        CrmUser(
            email=email,
            name="Administrator",
            password_hash=hash_password(admin_password),
            role=ROLE_ADMIN,
            is_active=True,
        )
    )
    await session.commit()
    logger.info("bootstrap admin created email=%s", email)
    return True


async def try_bootstrap(session_factory, admin_email: str, admin_password: str) -> None:
    """Best-effort bootstrap at startup; never crashes the app."""
    if not admin_email or not admin_password:
        return
    try:
        async with session_factory() as session:
            await ensure_bootstrap_admin(session, admin_email, admin_password)
    except ValueError:
        logger.error("bootstrap admin skipped: ADMIN_PASSWORD is too short")
    except SQLAlchemyError as exc:
        logger.warning("bootstrap admin skipped: %s", type(exc).__name__)
