#!/bin/sh
# Container entrypoint (Step 15, see docs/DEPLOY.md).
# 1. Run Alembic migrations (idempotent; concurrent boots serialize on the
#    pg_advisory_lock in backend/alembic/env.py).
# 2. Start uvicorn. Two workers share the load; in-process background loops
#    (sync/outbox/notify/realtime) are advisory-locked, so only one worker
#    (or one container) does each job at a time.
# Secrets only from the environment. `exec` keeps signal handling intact.
set -eu

alembic -c backend/alembic.ini upgrade head

exec uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 2 \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --timeout-graceful-shutdown 20
