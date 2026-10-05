# Database roles and service tokens

Each service connects to Postgres as its own role and owns its own schema ([ADR 0009](adr/0009-approvals-owned-by-the-broker.md)):

| Role | Owns | Can't touch | Used by |
|---|---|---|---|
| `greenloop_orchestrator` | schema `public` (principals, tokens, audit, memory, conversations) | schema `broker` | orchestrator (`DATABASE_URL`) |
| `greenloop_broker` | schema `broker` (approvals, audit_events, service_tokens) | schema `public` | broker (`BROKER_DATABASE_URL`) |
| `POSTGRES_USER` (bootstrap superuser) | everything | — | only the two scripts below |

Neither service role can create databases or roles, replicate, or bypass row security. Compose passes each container only its own variables (no shared `env_file`), so the orchestrator never receives the broker's password or the superuser's, and the broker never receives the orchestrator's. Passwords and tokens never go in a file other than your local `.env`, and never on a command line. All commands run from the repo root in PowerShell.

## First-time setup (or a fresh database)

1. Back up an existing database first:
   ```powershell
   $stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'; $dir = "$HOME\greenloop-backups"
   New-Item -ItemType Directory -Force $dir | Out-Null
   docker compose exec -T db sh -c 'pg_dump -U $POSTGRES_USER -d $POSTGRES_DB -Fc -f /tmp/backup.dump'
   docker compose cp db:/tmp/backup.dump "$dir\greenloop_$stamp.dump"
   ```
2. Create the roles and schemas. The script asks for each password twice, hidden, or takes `ORCHESTRATOR_DB_PASSWORD` and `BROKER_DB_PASSWORD` from the environment; each must be at least 16 characters:
   ```powershell
   .\scripts\db-bootstrap.ps1 -DryRun     # shows the plan, touches nothing
   .\scripts\db-bootstrap.ps1
   ```
3. Existing database only: move the tables in `public` to the orchestrator role. It refuses to commit if anything is left behind:
   ```powershell
   .\scripts\db-transfer-ownership.ps1
   ```
4. In `.env`, set `ORCHESTRATOR_DB_PASSWORD` and `BROKER_DB_PASSWORD`, plus `DATABASE_URL` and `BROKER_DATABASE_URL` for services run outside compose (compose builds its own URLs from the passwords).
5. Run each service's migrations as its own role:
   ```powershell
   Push-Location services\orchestrator; ..\..\.venv\Scripts\python.exe -m alembic upgrade head; Pop-Location
   Push-Location services\broker; ..\..\.venv\Scripts\python.exe -m alembic upgrade head; Pop-Location
   ```
6. Issue the orchestrator's service token straight to the clipboard, paste it into `.env` as `BROKER_SERVICE_TOKEN`, then clear the clipboard:
   ```powershell
   Push-Location services\broker; ..\..\.venv\Scripts\python.exe -m app.cli issue-service-token --name orchestrator | Set-Clipboard; Pop-Location
   ```
7. Restart: `docker compose up -d --build broker orchestrator`.

## Rotating a role password

Run `.\scripts\db-bootstrap.ps1` again with the new passwords (it rotates both), update `.env`, and restart both services.

## Rotating the service token

Several tokens can be active at once, so rotation has no downtime:

```powershell
Push-Location services\broker
..\..\.venv\Scripts\python.exe -m app.cli issue-service-token --name orchestrator | Set-Clipboard
# put it in .env as BROKER_SERVICE_TOKEN and restart the orchestrator, then:
..\..\.venv\Scripts\python.exe -m app.cli list-service-tokens
..\..\.venv\Scripts\python.exe -m app.cli revoke-service-token svc-<old id>
Pop-Location
```

Only the token's SHA256 is stored, so a lost token can't be recovered: issue a new one and revoke the old. Issue and revoke are audited in `broker.audit_events`.

## Restoring a backup

```powershell
docker compose cp "$HOME\greenloop-backups\<file>.dump" db:/tmp/restore.dump
docker compose exec -T db sh -c 'pg_restore -U $POSTGRES_USER -d $POSTGRES_DB --clean --if-exists /tmp/restore.dump'
```

A dump taken before PR5b-2 restores tables owned by the bootstrap superuser: run `db-transfer-ownership.ps1` again afterwards.

## Troubleshooting

At startup, each service checks its own schema and refuses to start if anything is wrong (`app/db/startup_check.py` in each service). The checks run in this order and stop at the first group that fails, so fixing one can reveal the next on restart:

1. The schema exists.
2. Every relation in it (table, view, materialized view, foreign table, sequence) is owned by the service's role. Functions and types aren't checked.
3. Migrations are at head.
4. Broker only: both append-only triggers on `broker.audit_events` are exactly as the migration created them (events, BEFORE, row or statement level, no `WHEN`, no column list, enabled), and `broker.audit_events_append_only()` still has its original body.

The error lists every problem in the failing group, never the URL, host, user or a password. If the database can't be reached at all, it names only the driver error class and SQLSTATE. Read it with:

```powershell
docker compose logs orchestrator broker
```

### "is owned by greenloop, not greenloop_orchestrator" (or "permission denied for table alembic_version")

Tables in `public` still belong to the bootstrap superuser. See who owns what:

```powershell
"select c.relname, c.relowner::regrole from pg_class c where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p','v','m','f','S') and not exists (select from pg_depend d where d.classid = 'pg_class'::regclass and d.objid = c.oid and d.deptype in ('a','i','e')) order by 1;" | docker compose exec -T db sh -c 'psql -X -U $POSTGRES_USER -d $POSTGRES_DB'
```

This is the same filter the check uses, so it lists the same objects.

Take a backup (step 1 of first-time setup), then run `.\scripts\db-transfer-ownership.ps1` and restart with `.\scripts\dev.ps1 -Service stack`.

This happened once on the dev database (2026-10-04): the first transfer didn't take effect on the dev DB, and all 7 tables in `public` were still owned by `greenloop`. The exact cause is unknown. The startup check now catches this. Restoring a dump taken before PR5b-2 does the same thing (see [Restoring a backup](#restoring-a-backup)).

For the broker, use the same query with `'broker'::regnamespace`. No script moves broker objects, because `greenloop_broker` creates them all through its own migrations. A foreign owner there means something was created by hand: find out what it is before you change its owner.

### "Migrations are at …, not head …" or "Migrations have not run"

The image is newer than the database. Run step 5 of first-time setup for that service, as its own role, then restart.

### "The database is at …, which this image doesn't know"

The database was migrated from a newer checkout than the image that's running, usually a stale image after `git pull`. Don't run alembic: rebuild with `.\scripts\dev.ps1 -Service stack`.

### "Schema … does not exist"

Run `.\scripts\db-bootstrap.ps1` (step 2 of first-time setup).

### "Append-only trigger broker.audit_events.… is not enabled", "is missing" or "has been changed", or "Function broker.audit_events_append_only() has been changed"

Someone disabled, dropped or rewrote what keeps the audit log append-only. Treat audit rows written since then as unprotected, and save the evidence before changing anything, because the fix runs as a role that could have made the change:

1. Back up the database (step 1 of first-time setup).
2. Save the current definitions, as the superuser:
   ```powershell
   "select tgname, tgenabled, pg_get_triggerdef(oid) from pg_trigger where tgrelid = 'broker.audit_events'::regclass and not tgisinternal; select pg_get_functiondef(p.oid) from pg_proc p where p.pronamespace = 'broker'::regnamespace;" | docker compose exec -T db sh -c 'psql -X -U $POSTGRES_USER -d $POSTGRES_DB' | Set-Content "$HOME\greenloop-backups\audit-triggers_$(Get-Date -Format 'yyyy-MM-dd_HHmm').txt"
   ```
3. Find out who made the change and why (Postgres logs, who holds the broker password).
4. Restore the function and both triggers exactly as the broker's first migration creates them (`services/broker/app/db/migrations/versions/2026-10-02_approvals_audit_service_tokens.py`): `CREATE OR REPLACE FUNCTION` with the migration's body, then drop and recreate each trigger. Run this as `greenloop_broker` or the superuser. If a trigger was only disabled, `ALTER TABLE broker.audit_events ENABLE TRIGGER <name>;` is enough.

The check finds these changes at the next start, not while the broker is running: the broker role owns the table, so it can change the triggers at any time (ADR 0009, known gaps).

### The containers run old code after `git pull`

`docker compose up --force-recreate` recreates containers from the image that already exists. It never rebuilds. Rebuild and start the stack with:

```powershell
.\scripts\dev.ps1 -Service stack      # docker compose up -d --build --wait
```

`--wait` makes the command fail when a service exits at startup, for example on the startup check above. The orchestrator waits for the broker to be healthy, so a broker that fails its check stops both. `--wait` doesn't catch a database that goes away later: `/v1/health` on the orchestrator reports that.

## How the scripts keep secrets out of sight

- Passwords reach the container through `docker exec -e NAME` (copied from the environment, never on a command line) and reach SQL through psql's `:'variable'` quoting, never through the SQL text.
- The scripts switch statement logging off before any statement carries a password, and `set_config`'s echoed result is discarded.
- `scripts/test-postgres.ps1` runs both scripts against a throwaway container with full statement logging on and fails if a password appears in the output or the server log.
- `issue-service-token` writes only the token to stdout; everything else goes to stderr.
