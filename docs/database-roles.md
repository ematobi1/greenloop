# Database roles and service tokens

Each service connects to Postgres as its own role and owns its own schema ([ADR 0009](adr/0009-approvals-owned-by-the-broker.md)):

| Role | Owns | Can't touch | Used by |
|---|---|---|---|
| `greenloop_orchestrator` | schema `public` (principals, tokens, audit, memory, conversations) | schema `broker` | orchestrator (`DATABASE_URL`) |
| `greenloop_broker` | schema `broker` (approvals, audit_events, service_tokens) | schema `public` | broker (`BROKER_DATABASE_URL`) |
| `POSTGRES_USER` (bootstrap superuser) | everything | — | only the two scripts below |

Neither service role can create databases or roles, replicate, or bypass row security. Passwords and tokens never go in a file other than your local `.env`, and never on a command line. All commands run from the repo root in PowerShell.

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

## How the scripts keep secrets out of sight

- Passwords reach the container through `docker exec -e NAME` (copied from the environment, never on a command line) and reach SQL through psql's `:'variable'` quoting, never through the SQL text.
- The scripts switch statement logging off before any statement carries a password, and `set_config`'s echoed result is discarded.
- `scripts/test-postgres.ps1` runs both scripts against a throwaway container with full statement logging on and fails if a password appears in the output or the server log.
- `issue-service-token` writes only the token to stdout; everything else goes to stderr.
