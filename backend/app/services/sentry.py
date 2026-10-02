from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def init_sentry(settings) -> bool:
    """Initialize Sentry only when a DSN is configured (optional, see D22).

    sentry-sdk stays an optional dependency: without it installed the CRM
    runs normally and this is a no-op (a warning is logged once).
    """
    dsn = (settings.sentry_dsn or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed; skipping")
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment or settings.app_env,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    logger.info("sentry enabled (env=%s)", settings.sentry_environment or settings.app_env)
    return True
