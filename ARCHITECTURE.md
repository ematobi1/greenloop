# GreenLoop Architecture

GreenLoop is a secure, adaptive AI second-brain platform. One canonical orchestrator coordinates reasoning, memory, agents, permissioned tools, workflows, self-correction and controlled self-improvement. Humans stay in control of consequential actions.

This document maps every folder to its role, owning component and roadmap phase. Phases are defined in [docs/roadmap.md](docs/roadmap.md). Where each piece of the old code will be ported from is tracked in [docs/migration-map.md](docs/migration-map.md). Terms are defined in [docs/glossary.md](docs/glossary.md).

## Principles

- **One of each.** One orchestrator, one permission model, one contract package (`packages/contracts`). Extend them; never create parallel versions.
- **GreenLoop owns orchestration.** External providers (model APIs, ElevenLabs) sit behind GreenLoop interfaces: `ai/providers/` for models, `speech/` for voice.
- **Memory is untrusted data.** Postgres + pgvector, append-only with provenance (history, supersede, correct, delete), scoped by principal and enforced server-side. Retrieved memory reaches a prompt only through `memory/context_builder.py`, which bounds, redacts and escapes it.
- **The model is not the security boundary.** Every tool call goes permission check, then approval if required, then tool, then audit.
- **The broker is the only path to consequential tools.** Anything that writes, sends, deletes or spends goes through `services/broker`, which enforces policy, one-time approvals bound to a SHA256 of the exact operation, and an audit ledger. It then forwards to MCP servers.
- **Self-improvement is off by default.** `SELF_IMPROVEMENT_EXECUTION_ENABLED` defaults to `false`.

## Diagram

```
                     +--------------------------------------+
  User  ------------>|  apps/web  (Next.js, TypeScript)     |
  text / voice / UI  +------------------+-------------------+
                                        | HTTPS + auth
                                        v
+------------------------------------------------------------------------------+
|  services/orchestrator  (FastAPI, the canonical brain)                       |
|                                                                              |
|  api/v1 --> core/auth --> orchestration/reasoning --> orchestration/planner  |
|                                  |                          |                |
|                                  v                          v                |
|        memory/retrieval --> memory/context_builder     orchestration/        |
|              ^              (bound, redact, escape)     dispatcher            |
|              |                     |                        |                |
|              |                     v                        v                |
|              |               ai/engine ---> ai/providers   agents/*          |
|              |                                              |                |
|              |                   permissions/policy <-------+                |
|              |                          |                                    |
|              |                   permissions/approvals  (human in the loop)  |
|              |                          |                                    |
|              |                   tools/broker_client                         |
|              |                          |                                    |
|        memory/store <-- audit/recorder <-- correction/lifecycle              |
|                                          |          ^                        |
|  speech/  (SpeechProvider: ElevenLabs)   |          | result                 |
+------------------------------------------+----------+------------------------+
                                           |          |
                                           v          |
                    +---------------------------------+-----+
                    |  services/broker                      |
                    |  policy (deny by default)             |
                    |  approval_binding (SHA256, one use)   |
                    |  ledger (append-only audit)           |
                    |  mcp_proxy                            |
                    +------------------+--------------------+
                                       |
                                       v
                    +---------------------------------------+
                    |  MCP tool servers  (mcp/servers.yaml) |
                    |  github, filesystem, fetch,           |
                    |  postgres-readonly, google-workspace  |
                    +---------------------------------------+

  Postgres 16 + pgvector:  memory, audit, approvals, workflows
  packages/contracts:      shared schemas imported by every Python service
  services/self-improvement: proposals + validation, execution disabled
```

## Request flow

1. **User** sends text, voice or a UI action to `apps/web`.
2. **Web app** calls the orchestrator API (`api/v1`).
3. **Auth** (`core/auth.py`) resolves the principal. Every later step is scoped to that principal.
4. **Reasoning** (`orchestration/reasoning.py`) interprets the request.
5. **Planning** (`orchestration/planner.py`) drafts a plan of steps as `Task` contracts.
6. **Memory retrieval** (`memory/retrieval.py`) fetches relevant records. They pass through `memory/context_builder.py` before any prompt sees them.
7. **Agent dispatch** (`orchestration/dispatcher.py`) sends each step to an agent as a `Dispatch`.
8. **Permission check** (`permissions/policy.py`) evaluates the requested `ToolPermission`.
9. **Approval if needed** (`permissions/approvals.py`) asks a human and binds the approval to the SHA256 of the exact operation.
10. **Broker** (`tools/broker_client.py` to `services/broker`) re-checks policy, consumes the approval once, writes the ledger entry and forwards the call.
11. **MCP tool servers** execute the operation.
12. **Result validation** checks the `ExecutionResult` against what the step expected.
13. **Self-correction** (`correction/lifecycle.py`) retries, re-plans or escalates on failure, recording an `ErrorReport`.
14. **Audit** (`audit/recorder.py`) writes an `AuditRecord` for every consequential decision.
15. **Memory store** (`memory/store.py`) appends new records with provenance.
16. **Response** returns to the user.

## Folder map

### Top level

| Folder | Role | Owner component | Phase |
|---|---|---|---|
| `.claude/` | Claude Code configuration for this repo | Tooling | 1 |
| `.devcontainer/` | Reproducible dev container definition | Platform | 1 |
| `.github/` | CI workflow and PR template | Platform | 1 |
| `scripts/` | PowerShell dev, test, lint and read-only migration mapping scripts | Platform | 1 |
| `docs/` | Roadmap, security model, migration map, glossary, ADRs | Architecture | 1 |
| `packages/` | Shared libraries imported by services | Contracts | 1 |
| `services/` | Independently deployable backend services | Backend | 1 to 7 |
| `apps/` | User-facing applications | Frontend | 2, 5 |
| `mcp/` | MCP server configuration: enabled flags and allowed toolsets | Tools | 3 |
| `evals/` | Prompt and injection evals (the only evals folder) | Quality | 2, 6 |
| `infra/` | Infrastructure as code | Platform | 6 |
| `tests/` | Cross-service end-to-end tests | Quality | 2 |

### Second level

| Folder | Role | Owner component | Phase |
|---|---|---|---|
| `.claude/agents/` | Subagent definitions (prompt-engineer) | Tooling | 1 |
| `.github/workflows/` | CI: Ruff and pytest for Python, lint and typecheck for web | Platform | 1 |
| `docs/adr/` | Architecture decision records | Architecture | 1 |
| `packages/contracts/` | Pydantic v2 models: Agent, Task, Dispatch, ToolPermission, MemoryRecord, Event, ExecutionResult, ErrorReport, AuditRecord, plus the registry | Contracts | 1 |
| `services/orchestrator/` | FastAPI orchestrator: auth, reasoning, planning, memory, agents, permissions, audit | Orchestrator | 1, 2 |
| `services/broker/` | Policy, approval binding and ledger gate in front of MCP | Broker | 3 |
| `services/self-improvement/` | Proposal, validation, isolation and evidence pipeline; execution disabled | Self-improvement | 7 |
| `apps/web/` | Next.js + TypeScript UI: chat, memory, approvals, agents, workflows, audit, settings | Frontend | 2, 5 |
| `evals/prompts/` | Prompt quality evals | Quality | 2, 6 |
| `evals/injection/` | Prompt injection and memory-poisoning evals | Quality | 2, 6 |
| `evals/datasets/` | Eval inputs and expected outputs | Quality | 2, 6 |
| `infra/terraform/` | AWS modules (network, ecs, rds, secrets, observability) and envs (dev, prod) | Platform | 6 |
| `tests/e2e/` | End-to-end tests across web, orchestrator and broker | Quality | 2 |

### Orchestrator modules (`services/orchestrator/app/`)

| Module | Role | Phase |
|---|---|---|
| `main.py` | FastAPI app factory and router wiring | 1 |
| `api/v1/` | REST endpoints: health, chat, memory, plans, agents, approvals, audit | 1 (health), 2 |
| `core/` | Config from environment, auth, logging, errors | 1 (config), 2 (auth) |
| `ai/` | Engine, system prompts, context framing, model providers | 2 |
| `orchestration/` | Reasoning, planner, dispatcher | 2 (reasoning, planner), 4 (dispatcher) |
| `memory/` | Store, retrieval, context builder, provenance, embeddings | 1 (context builder), 2 |
| `agents/` | Agent base, registry, planner, research and coding agents | 4 |
| `permissions/` | Policy evaluation and approval requests | 3 |
| `tools/` | Tool registry and broker client | 3 |
| `workflows/` | Workflow engine and queue | 4 |
| `correction/` | Self-correction lifecycle | 4 |
| `audit/` | Audit recorder | 3 |
| `speech/` | SpeechProvider interface and ElevenLabs implementation | 5 |
| `db/` | SQLAlchemy session, models, Alembic migrations | 1 |

### Root files

| File | Role | Phase |
|---|---|---|
| `README.md` | What GreenLoop is and quick start | 1 |
| `ARCHITECTURE.md` | This map | 1 |
| `CLAUDE.md` | Standing rules for Claude Code | 1 |
| `docker-compose.yml` | Local db (pgvector/pgvector:pg16), orchestrator, broker, web, github-mcp (profile `tools`) | 1 |
| `.env.example` | Environment variable names, no values | 1 |
| `.dockerignore` | Keeps `.env`, keys and local state out of image build contexts | 1 |
| `ruff.toml` | Shared Ruff lint and format config for all Python packages | 1 |

## Testing layout

- Each Python package and service has its own `tests/` and runs independently.
- Security and behavior tests live in each service's `tests/security/`.
- Prompt and injection evals live only in the top-level `evals/`.
- Cross-service tests live in `tests/e2e/`.
