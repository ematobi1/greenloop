# GreenLoop

GreenLoop is a secure, adaptive AI second-brain platform. One canonical orchestrator coordinates reasoning, memory, agents, permissioned tools, workflows, self-correction and controlled self-improvement, with humans in control of consequential actions.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the folder map and request flow, and [docs/roadmap.md](docs/roadmap.md) for the phases.

## Layout

| Path | Role |
|---|---|
| `packages/contracts` | Shared Pydantic contracts (Agent, Task, Dispatch, ToolPermission, ToolGrant, MemoryRecord, Event, ExecutionResult, ErrorReport, AuditRecord) |
| `services/orchestrator` | FastAPI orchestrator: auth, reasoning, planning, memory, agents, permissions, audit |
| `services/broker` | Policy, approval binding and audit ledger in front of MCP tool servers |
| `services/self-improvement` | Proposal and validation pipeline (execution disabled by default) |
| `apps/web` | Next.js + TypeScript web app |
| `mcp/` | MCP server configuration |
| `evals/` | Prompt and injection evals |
| `infra/terraform` | AWS infrastructure skeleton |
| `docs/` | Roadmap, security model, migration map, ADRs |

## Prerequisites

- Windows 11 with PowerShell
- Git
- Python 3.12 (`py -3.12`)
- Node.js 20+
- Docker Desktop (optional, for Postgres + pgvector)

## Quick start

```powershell
Copy-Item .env.example .env        # then fill in values locally; never commit .env (POSTGRES_PASSWORD is required)
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "packages/contracts[dev]" -e "services/orchestrator[dev]" -e "services/broker[dev]" -e "services/self-improvement[dev]"
npm --prefix apps/web ci
.\scripts\test.ps1                 # run every suite
.\scripts\lint.ps1                 # run every linter
.\scripts\dev.ps1 -Service db      # Postgres + pgvector in Docker
.\scripts\dev.ps1                  # start the orchestrator
.\scripts\test-postgres.ps1        # Postgres tests in a throwaway container (port 55433)
```

Then open http://localhost:8000/health (expects `{"status":"ok"}`) and http://localhost:8000/docs.

If ports 5432, 8000 or 3000 are taken, set `GREENLOOP_DB_PORT`, `GREENLOOP_ORCHESTRATOR_PORT` or `GREENLOOP_WEB_PORT` in `.env` before `docker compose up`. The broker has no host port: only the orchestrator reaches it, on the compose network.

Each service connects as its own Postgres role. Before the first `docker compose up` of the services, set up the roles, migrations and the broker service token as described in [docs/database-roles.md](docs/database-roles.md).

Each service keeps its own `app/` package and runs from its own folder, so run pytest and uvicorn from `services/<name>` (the scripts do this for you).

The orchestrator reads the repo-root `.env` from any working directory, so uvicorn, `python -m alembic` and `python -m app.cli` all work from `services/orchestrator`. Real environment variables override `.env`. Set `GREENLOOP_ENV_FILE` to load a different file (Docker, CI).

`scripts\test-postgres.ps1` runs the Postgres tests in a uniquely named throwaway container on `GREENLOOP_TEST_DB_PORT` (default 55433), separate from the dev database on `GREENLOOP_DB_PORT`, so both can run at once. It always removes its container, and cleans up any left by a killed run. It runs both services' integration suites by default; pass `-Service orchestrator -Path tests` for the whole orchestrator suite, or `-Service broker` for the broker only.

## Rules

Standing rules for contributors and Claude Code live in [CLAUDE.md](CLAUDE.md).
