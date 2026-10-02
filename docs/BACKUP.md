# Backups (Step 14)

One Postgres cluster holds both the n8n bot tables (`knewit_*`) and the CRM
tables (`crm_*`), so a single `pg_dump` covers everything. Restores are
full-database; there is no per-table point-in-time story by design.

## Schedule

`scripts/backup.sh` dumps custom-format (`-Fc`, compressed) to `$BACKUP_DIR`
(default `/var/backups/knewitcrm`) and rotates: newest `KEEP_DAILY` (default 7)
dumps plus the newest dump of each ISO week (`KEEP_WEEKLY`, default 4).

Run nightly via cron on the backup host (or a Railway cron service):

```cron
0 3 * * * BACKUP_DIR=/var/backups/knewitcrm KEEP_DAILY=7 KEEP_WEEKLY=4 \
  DATABASE_URL="$DATABASE_URL" /app/scripts/backup.sh >> /var/log/knewit-backup.log 2>&1
```

Connection comes only from the environment (`DATABASE_URL`, or
`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`). Never commit dumps or
credentials. The dump user needs `CONNECT` + `SELECT` on all tables.

Smoke-tested 2026-10-01: dump (15M, local dev DB) + `pg_restore` into a scratch
database + row-count check + drop. The single ignored warning
(`SET transaction_timeout`, client/server version skew) is harmless.

## Restore procedure

```bash
# 1. Stop writes: scale the Railway service to 0 (or stop workers).
# 2. Recreate the target database (example: Railway postgres plugin shell).
dropdb "$PGDATABASE" && createdb "$PGDATABASE"

# 3. Restore in one transaction.
pg_restore --dbname="$DATABASE_URL" --no-owner --single-transaction \
  knewitcrm-<STAMP>.dump

# 4. Verify: alembic version table + row counts.
psql "$DATABASE_URL" -c "SELECT version_num FROM crm_alembic_version;"
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM crm_users; SELECT COUNT(*) FROM knewit_leads;"

# 5. Redeploy / scale back up. Migrations run on boot; a restore at an older
#    migration state upgrades itself forward automatically.
```

## Restore checks

- `crm_alembic_version` matches the deployed code's `head` (or older — boot
  migrates forward; never restore a *newer* DB under *older* code without
  `alembic downgrade`).
- Spot-check counts: `crm_users`, `crm_deals`, `knewit_leads`, `knewit_messages`.
- Log in as admin, open board + one dialog + analytics overview.

## Off-site copies

Sync `$BACKUP_DIR/*.dump` to S3-compatible storage (rclone/restic) from the
backup host; encrypt at rest (`age`/`gpg`) since dumps contain personal data
(names, phones, message texts). Retention there: 30 daily + 12 monthly.
