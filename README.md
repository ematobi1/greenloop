# GreenLoop

GreenLoop is a secure, adaptive AI second-brain platform. One canonical orchestrator coordinates reasoning, memory, agents, permissioned tools, workflows, self-correction and controlled self-improvement, with humans in control of consequential actions.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the folder map and request flow, and [docs/roadmap.md](docs/roadmap.md) for the phases.

## Layout

| Path | Role |
|---|---|
| `packages/contracts` | Shared Pydantic contracts (Agent, Task, Dispatch, ToolPermission, MemoryRecord, Event, ExecutionResult, ErrorReport, AuditRecord) |
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
Copy-Item .env.example .env        # then fill in values locally; never commit .env
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
.\scripts\test.ps1                 # run all tests
docker compose up -d db            # Postgres + pgvector
.\scripts\dev.ps1                  # start the orchestrator
```

Then open http://localhost:8000/health (expects `{"status":"ok"}`) and http://localhost:8000/docs.

## Rules

Standing rules for contributors and Claude Code live in [CLAUDE.md](CLAUDE.md).
