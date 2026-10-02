# ADR 0009: Approvals are stored and consumed by the broker

- Status: Accepted; implemented in PR5b-1 (contracts) and PR5b-2 (roles, store, APIs)
- Date: 2026-10-02

## Context

Port decision 2 (2026-09-28) put approval storage and consumption in `services/broker`, with the orchestrator's `/v1/approvals` forwarding through `tools/broker_client.py`. Before PR5b the broker bound approvals to a SHA256 of the exact operation and consumed them once, but only in memory (`app/approval_binding.py`, removed in PR5b-2). It had no database, no authentication and no approval endpoints. PR5 was split so this security-critical half gets its own review.

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

### Added 2026-10-02 (PR5b-2 implementation decisions)

11. **Trust boundary between the services.** The broker trusts the orchestrator's statement of who is acting (`ApprovalActor`: principal, user or system, inside a dispatch or not) because the call carries the service token. The orchestrator fills those fields only from its authenticated `Principal` and the dispatch context (`orchestration/dispatch_context.py`), never from user request data. The broker still checks that the decider owns the approval (anyone else gets the same 404 as a missing approval) and refuses non-human deciders itself. Later hardening: a signed per-user assertion, so the broker can verify the human independently of the orchestrator.
12. **Request contracts (contracts 0.4.0).** `ApprovalCreateRequest` and `ApprovalDecisionRequest` are the only request bodies. The actor's `kind` and `in_dispatch` have no defaults, and no request can carry an approval id, status, summary or hash.
13. **No consume endpoint.** Consume is internal to the broker (`ApprovalStore.consume`), used by its phase 3 tool path and tested directly.
14. **The broker is not published.** Compose gives it no host port; only the orchestrator, on the compose network, can reach it.
15. **The operation is stored as `json`, not `jsonb`.** `jsonb` rewrites numbers (`1e16` comes back as an integer, `-0.0` as `0`), which would break the hash binding of a stored operation. A test fails if the column becomes `jsonb`.
16. **Roles.** `scripts/db/bootstrap-roles.sql` creates `greenloop_orchestrator` (owns `public`) and `greenloop_broker` (owns `broker`) with no cluster privileges, and `transfer-public-ownership.sql` moved the existing tables (decision B). Both run from PowerShell wrappers that keep passwords off command lines and out of the server log; see [database roles](../database-roles.md).

## Consequences

- The broker becomes a database service with its own migrations and role.
- The orchestrator can read and decide approvals only through the broker API, so a bug in the orchestrator can't mark an approval consumed.
- Each service runs its own migrations as its own role. The bootstrap superuser is needed only for the bootstrap and ownership scripts.

## Known gaps

- No end-to-end test runs the orchestrator against a real broker; each side is tested against a fake of the other, because both services use a top-level `app` package.
- The orchestrator audits consume only once the phase 3 tool path calls it; until then only the broker audits consume.
- Unauthenticated requests to the broker each write an audit row. The broker is reachable only on the internal network, so this is not a flooding risk today; it becomes one if the broker is ever exposed.
