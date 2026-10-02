#!/usr/bin/env bash
# Post-deploy smoke check (Step 15, see docs/DEPLOY.md).
# Verifies: /api/health, login, deals list, SSE stream, and (opt-in) one
# test WhatsApp message via the outbox queue.
#
# All inputs come from the environment; nothing secret is printed.
#   BASE_URL="https://crm-staging.up.railway.app" \
#   SMOKE_EMAIL="admin@example.com" SMOKE_PASSWORD="..." \
#   scripts/smoke.sh
# Optional full send path (delivers a real message to a test chat):
#   SEND_TEST_MESSAGE=1 TEST_WHATSAPP_ID="79990000001@c.us" scripts/smoke.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
# Empty credentials are allowed: the script then checks only the public
# health probe and skips the authenticated steps (exit 0). This keeps
# secrets out of CI `if:` conditions (Step 16a).
SMOKE_EMAIL="${SMOKE_EMAIL:-}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-}"
SEND_TEST_MESSAGE="${SEND_TEST_MESSAGE:-0}"
TEST_WHATSAPP_ID="${TEST_WHATSAPP_ID:-}"

step=0
pass() {
  step=$((step + 1))
  echo "ok $step: $1"
}
fail() {
  echo "FAIL: $1" >&2
  exit 1
}

WORKDIR="$(mktemp -d)"
export WORKDIR
trap 'rm -rf "$WORKDIR"' EXIT
JAR="$WORKDIR/jar"
BODY="$WORKDIR/body"

# 1. Health (public, DB-backed: 200 {"ok":true} only when Postgres is up).
code="$(curl -s -o "$BODY" -w '%{http_code}' "$BASE_URL/api/health")"
[ "$code" = "200" ] || fail "/api/health -> HTTP $code: $(head -c 200 "$BODY")"
grep -q '"ok":true' "$BODY" || fail "/api/health body: $(head -c 200 "$BODY")"
pass "/api/health 200 (DB up)"

if [ -z "$SMOKE_PASSWORD" ]; then
  echo "skip: SMOKE_PASSWORD is empty, authenticated checks skipped"
  exit 0
fi

# 2. Login (session + CSRF cookies; passwords travel in a temp file only).
SMOKE_EMAIL="$SMOKE_EMAIL" SMOKE_PASSWORD="$SMOKE_PASSWORD" python3 -c \
  'import json, os; json.dump({"email": os.environ["SMOKE_EMAIL"], "password": os.environ["SMOKE_PASSWORD"]}, open(os.environ["WORKDIR"] + "/login.json", "w"))'
code="$(curl -s -c "$JAR" -b "$JAR" -o "$BODY" -w '%{http_code}' -X POST "$BASE_URL/api/auth/login" -H 'Content-Type: application/json' --data-binary "@$WORKDIR/login.json")"
rm -f "$WORKDIR/login.json"
[ "$code" = "200" ] || fail "login -> HTTP $code: $(head -c 200 "$BODY")"
grep -q 'crm_csrf' "$JAR" || fail "login did not set CSRF cookie"
pass "login 200 (session + CSRF cookies set)"

CSRF="$(awk '/crm_csrf/ {print $NF}' "$JAR" | tail -1)"
[ -n "$CSRF" ] || fail "empty CSRF token"

# 3. Authenticated read: deals list (paginated envelope).
code="$(curl -s -b "$JAR" -o "$BODY" -w '%{http_code}' "$BASE_URL/api/deals?limit=1")"
[ "$code" = "200" ] || fail "/api/deals -> HTTP $code: $(head -c 200 "$BODY")"
grep -q '"items"' "$BODY" || fail "/api/deals body: $(head -c 200 "$BODY")"
pass "/api/deals 200 (items envelope)"

# 4. SSE stream: the `: connected` prologue must arrive within 10s
#    (heartbeats every 15s would need a longer window; prologue is instant).
if curl -s -N -b "$JAR" --max-time 10 "$BASE_URL/api/stream" -o "$WORKDIR/stream" 2>/dev/null; then
  true
fi
grep -q 'connected' "$WORKDIR/stream" || fail "/api/stream: no prologue in 10s"
pass "/api/stream prologue received"

# 5. Opt-in send path: queue one message to a TEST chat (HTTP 202).
if [ "$SEND_TEST_MESSAGE" = "1" ]; then
  [ -n "$TEST_WHATSAPP_ID" ] || fail "SEND_TEST_MESSAGE=1 needs TEST_WHATSAPP_ID"
  printf '{"body":"Smoke-проверка CRM (автотест деплоя)"}' > "$WORKDIR/msg.json"
  code="$(curl -s -b "$JAR" -o "$BODY" -w '%{http_code}' -X POST "$BASE_URL/api/chats/$TEST_WHATSAPP_ID/messages" -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" --data-binary "@$WORKDIR/msg.json")"
  [ "$code" = "202" ] || fail "send -> HTTP $code: $(head -c 200 "$BODY")"
  pass "test message queued 202 to $TEST_WHATSAPP_ID (check it in WhatsApp)"
else
  echo "skip: send path (set SEND_TEST_MESSAGE=1 TEST_WHATSAPP_ID=... to enable)"
fi

echo "smoke OK: $step checks passed against $BASE_URL"
