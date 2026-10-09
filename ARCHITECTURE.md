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
                    |  approvals (Postgres, SHA256, 1 use)  |
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

  Postgres 16 + pgvector:  memory, audit, conversations and messages, workflows (schema public,
                           role greenloop_orchestrator); approvals, broker audit, service tokens
                           (schema broker, role greenloop_broker). See docs/database-roles.md

  Chat today goes api/v1/chat -> ai/engine directly (conversations/ holds the
  transcript and the one-turn-at-a-time lease). Plan drafting goes api/v1/plans ->
  orchestration/planner -> provider (one tool-free call; plan_store keeps drafts).
  orchestration/reasoning is still a stub.
  packages/contracts:      shared schemas imported by every Python service
  services/self-improvement: proposals + validation, execution disabled
```

## Request flow

1. **User** sends text, voice or a UI action to `apps/web`.
2. **Web app** server routes (`apps/web/src/server`) call the orchestrator API (`api/v1`) over the compose network with the token from the user's httpOnly session cookie; the browser never calls the orchestrator directly ([ADR 0010](docs/adr/0010-web-proxies-with-cookie-session.md)).
3. **Auth** (`core/auth.py`) resolves the principal from an API token or a web session token (`core/accounts.py`: username and argon2id password sign-in, sessions, lockout; ADR 0012). Every later step is scoped to that principal.
4. **Reasoning** (`orchestration/reasoning.py`) interprets the request.
5. **Planning** (`orchestration/planner.py`, `orchestration/plan_store.py`) drafts a `Plan` of `PlanStep`s for the user to review; drafts never execute (ADR 0013). The workflow engine turns approved plans into `Task`s in phase 4.
6. **Memory retrieval** (`memory/retrieval.py`) ranks the principal's live records by pgvector similarity to the request, then fills with recent ones (`memory/embeddings.py`, `memory/indexing.py`; ADR 0011). They pass through `memory/context_builder.py` before any prompt sees them.
7. **Agent dispatch** (`orchestration/dispatcher.py`) runs a step on an agent as a `Dispatch`. Today only `POST /v1/dispatches` calls it; the planner will in phase 4.
8. **Permission check** (`permissions/policy.py`) evaluates the requested `ToolPermission`.
9. **Approval if needed** (`permissions/approvals.py`) asks the broker for an approval bound to the SHA256 of the exact operation; only the owning human user, outside any dispatch, can decide it (ADR 0009).
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
| `packages/contracts/` | Pydantic v2 models: Agent, Task, Dispatch, ToolPermission, ToolGrant, MemoryRecord, Event, ExecutionResult, ErrorReport, AuditRecord, the shared ErrorDetail, plus the registry | Contracts | 1 |
| `services/orchestrator/` | FastAPI orchestrator: auth, reasoning, planning, memory, agents, permissions, audit | Orchestrator | 1, 2 |
| `services/broker/` | Policy, approval binding and ledger gate in front of MCP | Broker | 3 |
| `services/self-improvement/` | Proposal, validation, isolation and evidence pipeline; execution disabled | Self-improvement | 7 |
| `apps/web/` | Next.js + TypeScript UI: the HUD command center (chat, KPI tiles, health, live activity, three.js globe; [ADR 0014](docs/adr/0014-hud-theme-and-globe.md)) in the `(hud)` route group with design tokens in `src/styles/tokens.css`; memory, plans, approvals, agents, workflows, audit, settings | Frontend | 2, 5 |
| `evals/chat_behavior.py` | Chat behavior eval covering both prompt quality and injection; imports orchestrator request assembly (ADR 0006 addendum) | Quality | 2, 6 |
| `evals/prompts/` | Prompt quality evals | Quality | 2, 6 |
| `evals/injection/` | Prompt injection and memory-poisoning evals | Quality | 2, 6 |
| `evals/datasets/` | Eval inputs and expected outputs | Quality | 2, 6 |
| `infra/terraform/` | AWS modules (network, ecs, rds, secrets, observability) and envs (dev, prod) | Platform | 6 |
| `tests/e2e/` | End-to-end tests across web, orchestrator and broker | Quality | 2 |

### Orchestrator modules (`services/orchestrator/app/`)

| Module | Role | Phase |
|---|---|---|
| `main.py` | FastAPI app factory and router wiring | 1 |
| `api/v1/` | REST endpoints: health (database and a 2 s broker probe), sessions (web sign-in, current session), chat (including remember), memory, plans, agents, dispatches, approvals, audit | 1 (health), 2 |
| `core/` | Config from environment, auth (API and session tokens), accounts (usernames, argon2id, sessions, lockout), logging, errors, redaction | 1 (config), 2 (auth) |
| `ai/` | Streaming chat engine, system prompts, request assembly (`context.py`), model providers (Anthropic default, Ollama optional), AI error codes | 2 |
| `conversations/` | Owner-scoped conversations, ordered write-once messages, the per-conversation turn lease | 2 |
| `orchestration/` | Reasoning, planner and plan store (drafts only), dispatcher (runs one `Dispatch` on one agent, records execution memory and audit) | 2 (reasoning, planner), 4 (dispatcher) |
| `memory/` | Store, retrieval (pgvector ranking with recency fill), context builder, provenance, execution memory, embeddings and indexing | 1 (context builder), 2 |
| `agents/` | Agent base, in-code registry, deterministic reference agents; planner, research and coding agents (stubs) | 4 |
| `permissions/` | Policy evaluation, approval requests, and dispatch permission (`dispatch.py`: who may run an agent with model or tool access) | 3 |
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
- Cross-service tests live in `tests/e2e/`, reserved for runs against the real web app, orchestrator and broker.
- App-local browser tests against a mock orchestrator live in `apps/web/e2e/` (`npm run test:e2e`).
