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
4. **Single use.** Consume is one statement (`UPDATE … WHERE status = 'approved' AND consumed_at IS NULL AND expires_at > now() AND operation_hash = … RETURNING`). A mismatched or expired attempt is refused without using up the approval. Only the owning principal can decide.

## Consequences

- The broker becomes a database service with its own migrations and role.
- The orchestrator can read and decide approvals only through the broker API, so a bug in the orchestrator can't mark an approval consumed.
