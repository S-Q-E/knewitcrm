from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def scrub_sentry_event(event: dict, hint: dict | None = None) -> dict | None:
    """Strip request bodies and SQL bind params from a Sentry event.

    Bodies may hold passwords and message texts; SQLAlchemy breadcrumbs
    carry bind params (phones, tokens) next to the statement text. The
    statement text itself and the request method/URL are kept — they are
    needed to triage. Returning the event (never None) keeps the report.
    """
    del hint
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
    for crumb in event.get("breadcrumbs", {}).get("values", []) or []:
        data = crumb.get("data") if isinstance(crumb, dict) else None
        if isinstance(data, dict):
            data.pop("params", None)
    return event


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
        before_send=scrub_sentry_event,
    )
    logger.info("sentry enabled (env=%s)", settings.sentry_environment or settings.app_env)
    return True
