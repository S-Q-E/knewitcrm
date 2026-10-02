#!/usr/bin/env bash
# Nightly pg_dump backup for the CRM database (Step 14, see docs/BACKUP.md).
# Secrets only from the environment: DATABASE_URL (or PGHOST/PGPORT/PGUSER/
# PGPASSWORD/PGDATABASE). Never commit dumps or credentials.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/knewitcrm}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"

if [ -n "${DATABASE_URL:-}" ]; then
  PGURL="$DATABASE_URL"
else
  PGURL="postgresql://${PGUSER:-postgres}:${PGPASSWORD:-}@${PGHOST:-localhost}:${PGPORT:-5432}/${PGDATABASE:-railway}"
fi

DUMP="$BACKUP_DIR/knewitcrm-$STAMP.dump"
# Custom format: compressed, parallel-restorable, single transaction on restore.
pg_dump --format=custom --compress=9 --no-owner --file="$DUMP" "$PGURL"
echo "wrote $DUMP ($(du -h "$DUMP" | cut -f1))"

# Rotation, newest first: keep KEEP_DAILY dumps, then the newest dump of each
# ISO week (up to KEEP_WEEKLY extra weeks), delete the rest.
cd "$BACKUP_DIR"
mapfile -t all < <(ls -1t knewitcrm-*.dump 2>/dev/null || true)
declare -A keep=()
declare -A week_kept=()
weekly_extras=0
for ((i = 0; i < ${#all[@]}; i++)); do
  f="${all[$i]}"
  if ((i < KEEP_DAILY)); then
    keep["$f"]=1
    continue
  fi
  day="${f#knewitcrm-}"
  day="${day:0:8}"
  week="$(date -u -d "${day:0:4}-${day:4:2}-${day:6:2}" +%G-W%V 2>/dev/null || echo "day-$day")"
  if [[ -z "${week_kept[$week]:-}" && $weekly_extras -lt $KEEP_WEEKLY ]]; then
    week_kept["$week"]=1
    keep["$f"]=1
    weekly_extras=$((weekly_extras + 1))
  fi
done
for f in "${all[@]}"; do
  if [[ -z "${keep[$f]:-}" ]]; then
    rm -f "$f" && echo "rotated $f"
  fi
done

echo "ok: $(ls -1 knewitcrm-*.dump 2>/dev/null | wc -l) dumps retained"
