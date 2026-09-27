# Migration Map

Where each old folder in `C:\Users\emmat\Documents\greenloop-*` will be ported. The old folders stay read-only; ported code is rewritten against the new contracts, not copied.

Update the status as each row moves: `not started`, `in progress`, `ported`, `not ported`, `decided`.

| Old folder | New path | Notes | Status |
|---|---|---|---|
| greenloop-contracts | `packages/contracts` | 9 domain schemas + ToolGrant ported in 0.2.0; 6 API-response schemas and the old `services/` deferred to the orchestrator port (see below) | ported |
| greenloop-canonical-orchestrator | `services/orchestrator` | AI engine, memory, agents, dispatch, auth, audit, approvals | not started |
| greenloop-orchestrator-broker | `services/broker` (approval binding, ledger) and `services/orchestrator/app/tools/broker_client.py` | | not started |
| greenloop-k3-adapter | `services/broker` (approval binding, ledger) and `services/orchestrator/app/tools/broker_client.py` | | not started |
| greenloop-k1-broker | `services/broker` | Port the operation allowlist and ledger ideas only. The REST client, Windows service and pipes are replaced by the GitHub MCP server and containers. | not started |
| greenloop-k2a-broker | `services/broker` | Same as k1: allowlist and ledger ideas only | not started |
| greenloop-self-improvement | `services/self-improvement` | Execution stays disabled (Slice B gates 1 to 3 unapproved) | not started |
| greenloop-roadmap | `docs/` | | not started |
| greenloop-k2b-staging | not ported | Test environment | not started |
| greenloop-k2c-staging | not ported | Test environment | not started |
| greenloop-scratch | inspect before deciding | Staging, mock and scratch code is never copied into the runtime | not started |
| greenloop-ai-assistant | inspect before deciding | | not started |

## greenloop-contracts detail

Ported from branch `feature/unified-contracts` at `0eabefb`. Changes are recorded in [packages/contracts/CHANGELOG.md](../packages/contracts/CHANGELOG.md).

| Old item | New location | Status |
|---|---|---|
| `agent.schema.json` | `Agent` | ported |
| `task.schema.json` | `Task` | ported |
| `dispatch.schema.json` | `Dispatch` | ported |
| `tool-permission.schema.json` (owner grant) | `ToolGrant` (new); `ToolPermission` stays the per-call request | ported |
| `memory-record.schema.json` | `MemoryRecord` (`deleted_at` not ported: deletes are tombstones) | ported |
| `event.schema.json` | `Event` | ported |
| `execution-result.schema.json` | `ExecutionResult` with embedded `ErrorDetail` | ported |
| `error-report.schema.json` | `ErrorReport` and `ErrorDetail` | ported |
| `audit-record.schema.json` | `AuditRecord` | ported |
| `contracts/tests/test_contracts.py` | `packages/contracts/tests/` (rewritten for Pydantic; the Phase 1 compatibility and mislabeling-documentation tests dropped) | ported |
| `approval`, `approval-list`, `conversation`, `conversation-list`, `error`, `health` schemas | response models in `services/orchestrator/app/api/v1` | deferred to orchestrator port |
| `services/memory-store` | `services/orchestrator/app/memory` | deferred to orchestrator port |
| `services/agent-registry` | `services/orchestrator/app/agents` | deferred to orchestrator port |
| `services/backend`, `services/frontend` | compare with greenloop-canonical-orchestrator before deciding | deferred to orchestrator port |

## Porting rules

- Staging, mock and scratch code is never copied into the runtime.
- Ported code lands behind the existing contracts, permission model and orchestrator. No parallel versions.
- Every ported module ships with tests.
