#!/bin/sh
# Container entrypoint (Step 15, see docs/DEPLOY.md).
# 1. Run Alembic migrations (idempotent; concurrent boots serialize on the
#    pg_advisory_lock in backend/alembic/env.py).
# 2. Start uvicorn with ONE worker. The realtime event bus is process-local
#    (P1-1): with two workers, an event published by one worker never reaches
#    SSE clients of the other. Keep 1 until LISTEN/NOTIFY is in place.
# Secrets only from the environment. `exec` keeps signal handling intact.
set -eu

alembic -c backend/alembic.ini upgrade head

exec uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips="*" \
  --timeout-graceful-shutdown 20
