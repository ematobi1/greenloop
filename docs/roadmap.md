# Roadmap

Seven phases. Each folder's phase is listed in [ARCHITECTURE.md](../ARCHITECTURE.md). A phase is done when its exit criteria are met and verified.

## Phase 1: Consolidate and foundation

Scaffold this monorepo, port the existing code from the old greenloop-* folders (see [migration-map.md](migration-map.md)), stand up Postgres + pgvector, and run CI.

Exit criteria:
- Every row in the migration map is ported, marked not ported, or decided.
- Contracts, orchestrator, broker and self-improvement tests pass in CI.
- Postgres + pgvector runs locally and Alembic migrations apply.

## Phase 2: Usable core MVP

Authentication, chat, memory, reasoning and plan drafting, and a basic UI.

Exit criteria:
- A signed-in principal can chat, have memory stored and retrieved within their scope, and see a drafted plan.
- Retrieved memory reaches prompts only through the context builder.
- A first set of injection evals runs against the chat path.

## Phase 3: Tools and approvals

Policy engine, approval UI, the broker in front of the official GitHub MCP server, then two or three more MCP tools.

Exit criteria:
- Every consequential tool call passes policy, approval when required, broker and audit, in that order.
- Approvals bind to the SHA256 of the exact operation and are consumed once, atomically.
- The broker denies any call that no policy matches.

## Phase 4: Agents, workflows, self-correction

Agent registry and dispatch, multi-step workflows with a queue, and the self-correction lifecycle.

Exit criteria:
- Plans dispatch to registered agents through the one permission model.
- Failed steps are detected, recorded as ErrorReports, and retried, re-planned or escalated.

## Phase 5: Unified frontend and voice

One web app covering chat, memory, approvals, agents, workflows, audit and settings, plus voice through the SpeechProvider interface.

Exit criteria:
- All user-facing flows are in `apps/web`.
- Voice works end to end, and ElevenLabs is replaceable without orchestrator changes.

## Phase 6: Production deployment and hardening

AWS (ECS or App Runner), RDS, Secrets Manager, OpenTelemetry, evals in CI, and a security review.

Exit criteria:
- Terraform provisions dev and prod.
- No secret lives outside Secrets Manager or a local gitignored `.env`.
- Evals run before release with pass thresholds.
- Security review findings are resolved or accepted in writing.

## Phase 7: Controlled self-improvement and scale

Enable the self-improvement pipeline under explicit human gates, and scale.

Exit criteria:
- Slice B gates 1 to 3 are approved by Terry before proposed-code execution is enabled.
- Every proposal carries evidence and runs in isolation.
