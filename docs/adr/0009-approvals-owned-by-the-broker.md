# ADR 0009: Approvals are stored and consumed by the broker

- Status: Accepted (implementation in PR5b, not built yet)
- Date: 2026-10-02

## Context

Port decision 2 (2026-09-28) put approval storage and consumption in `services/broker`, with the orchestrator's `/v1/approvals` forwarding through `tools/broker_client.py`. The broker today binds approvals to a SHA256 of the exact operation and consumes them once, but only in memory (`app/approval_binding.py`). It has no database, no authentication and no approval endpoints. PR5 was split so this security-critical half gets its own review.

## Decision

PR5b adds an `Approval` contract in contracts 0.3.0, a Postgres approval store and API in the broker, and orchestrator forwarding, with these constraints:

1. **Separate database role.** The broker uses its own Postgres role with privileges only on its `broker` schema. The orchestrator's role has no access to the approvals table, and a test enforces that.
2. **Service token.** The orchestrator authenticates to the broker with a service token that the broker stores hashed and compares in constant time. It is never logged, it can be rotated, and `.env.example` lists it by name only.
3. **Expiry and audit.** Approvals expire after 15 minutes by default (configurable). Both the broker and the orchestrator write audit records for create, decide, consume and every refused attempt.
4. **Single use.** Consume is one statement (`UPDATE … WHERE status = 'approved' AND consumed_at IS NULL AND expires_at > now() AND operation_hash = … RETURNING`), and expiry is judged by the database's `now()`, not the application clock. A mismatched or expired attempt is refused without using up the approval.

### Added 2026-10-02 (Terry's PR5b decisions and the PR5b-1 reviews)

5. **The contract (contracts 0.3.0).** `Approval` carries the exact `ToolPermission` and its `operation_hash`, computed by `greenloop_contracts.operation_hash`, the one definition both services use (it lives in contracts because the hash is part of the contract, consistent with ADR 0006). Status is pending, approved, rejected or consumed. Expiry is not a status: an approval is expired when `expires_at` has passed. The contract refuses a decision or consume at or after `expires_at`, any lifetime over 24 hours, and timestamps out of order. Status changes go through `Approval.decide` and `Approval.consume`, which re-validate; `model_copy(update=...)` skips validation and is never used to change an approval.
6. **Who decides.** Only the owning principal (`decided_by == principal_id`, enforced by the contract), and only as a human user: system principals and anything running inside a dispatch are refused with 403, audited by both services. The owner approving their own agent's request is the intended flow.
7. **The broker trusts only its own store.** It never accepts an `Approval` as request input. Callers send an `approval_id` (to decide) or the operation (to create or consume); status comes from the broker's database.
8. **The summary is derived, not supplied.** The broker builds the summary from the operation (tool, operation, consequence, arguments), so free text can't describe a different operation than the one that runs. The approval UI shows the operation itself, with non-ASCII characters escaped or highlighted, because values are hashed as written (lookalike text and `1` vs `1.0` are different operations).
9. **Retries.** The orchestrator's broker client retries only GETs. Create and decide carry an idempotency key, and the broker returns the existing result for a repeated key instead of acting twice.
10. **Roles both ways.** A test logs in as each role and asserts the orchestrator role is denied on `broker.*` and the broker role is denied on the orchestrator's `public` tables. Role passwords and service tokens are never hardcoded or committed: they come from a prompt or an environment variable, and Terry runs the bootstrap and token issue.

## Consequences

- The broker becomes a database service with its own migrations and role.
- The orchestrator can read and decide approvals only through the broker API, so a bug in the orchestrator can't mark an approval consumed.
