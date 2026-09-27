# Migration Map

Where each old folder in `C:\Users\emmat\Documents\greenloop-*` will be ported. Nothing has been copied yet. The scaffold was built without reading these folders.

Update the status as each row moves: `not started`, `in progress`, `ported`, `not ported`, `decided`.

| Old folder | New path | Notes | Status |
|---|---|---|---|
| greenloop-contracts | `packages/contracts` | Shared contract models | not started |
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

## Porting rules

- Staging, mock and scratch code is never copied into the runtime.
- Ported code lands behind the existing contracts, permission model and orchestrator. No parallel versions.
- Every ported module ships with tests.
