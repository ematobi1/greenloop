# Changelog: greenloop-contracts

## 0.4.0 (2026-10-02)

The request bodies of the broker's approvals API (ADR 0009, PR5b-2). Additive; nothing existing changes.

### Added

- **ApprovalActor** (schema v1): who is asking, as the orchestrator's authenticated Principal sees it: `principal_id`, `kind` (user or system) and `in_dispatch` (strict boolean). `kind` and `in_dispatch` have no defaults. `may_decide` is true only for a user outside a dispatch (rule 6).
- **ApprovalCreateRequest** (schema v1): the `operation` (a `ToolPermission`) and the `actor`, who must be the principal the operation belongs to. There is no field for an approval id, status or summary: the broker derives them (rules 7 and 8).
- **ApprovalDecisionRequest** (schema v1): `approved` (strict boolean) and the `actor`. The approval id is in the URL.

## 0.3.0 (2026-10-02)

Adds what PR5b needs: approvals owned by the broker (ADR 0009) and a way for an agent to declare model access.

### Added

- **Approval** (schema v1): a human's permission for one exact `ToolPermission`, used at most once. It carries the operation and its `operation_hash`; the hash must match the operation, the operation must belong to the approval's `principal_id`, and only that principal can decide (`decided_by == principal_id`). `status` is pending, approved, rejected or consumed, and `decided_by`/`decided_at`/`consumed_at` must agree with it. Expiry is not a status: `expires_at` must be after `created_at` and at most `MAX_APPROVAL_TTL` (24 hours) later, nothing can be decided or consumed at or after it, and the timestamps must be in order. `DEFAULT_APPROVAL_TTL` is 15 minutes. `created_at` and `updated_at` are required, not defaulted. `decide()` and `consume()` return the changed approval and re-validate it; never change one with `model_copy(update=...)`, which skips validation.
- **`canonical_operation` and `operation_hash`** (`operation.py`): the one canonical JSON form (sorted keys, compact, UTF-8, no NaN) and SHA256 of a `ToolPermission`, moved here from the broker so every service computes the same hash. The bytes are unchanged from the broker's previous function and pinned by a test.

### Changed

| Contract | Schema | Changes | Breaking |
|---|---|---|---|
| Agent | v2 to v3 | new `model_access` (strict boolean, defaults to `false`). With `allowed_tools`, it decides whether dispatching the agent needs a permission check | no (defaulted) |
| ToolPermission | v1 to v2 | `arguments` must be strict JSON (no NaN or Infinity) and at most 64 KiB as UTF-8, so every permission can be hashed | yes (previously accepted values are refused) |

## 0.2.0 (2026-09-27)

Ports the domain schemas from the old `greenloop-contracts` repository (JSON Schema, draft 2020-12) into the Pydantic models. The new security fields (principal, provenance, approval hash, correlation id) are kept; the old business meaning is added on top. No compatibility with the old field names or timestamp strings is kept: nothing in production consumed the old shapes.

### All contracts

- Timestamps are normalized to UTC and serialize with a trailing `Z`; fractional seconds are allowed. Naive datetimes are still rejected.

### Added

- **ToolGrant** (schema v1): a standing permission the owner gives one agent to use listed `actions` of one `tool`, optionally until `expires_at`. `granted_by` is fixed to `"owner"`. `is_active(at)` and `covers(permission, at)` relate a grant to a `ToolPermission` request.
- **ErrorDetail** (component, not a registered contract): the user-safe error shape `{code, message, fields}`, shared by `ExecutionResult.error`, `ErrorReport` and the orchestrator's API error envelope. It has no field for internal detail.

### Changed (schema v1 to v2)

| Contract | Changes | Breaking |
|---|---|---|
| Agent | `agent_id` is now lowercase letters, digits and hyphens (1-100); new required `domain` (closed enum) and `version`; `capabilities` needs at least one entry; `status` adds `registered` and defaults to it; new `created_at`, `updated_at` | yes |
| Task | `status` is now pending, assigned, awaiting_approval, running, blocked, succeeded, failed, cancelled; new `assigned_agent_id`, `updated_at` | yes (`running` kept, no values removed) |
| Dispatch | `agent_id` uses the agent id pattern; new optional `timeout_ms` (strict integer, 1 to 3,600,000) | yes (agent id pattern) |
| MemoryRecord | new required `category` (9 values); new `confidence` (unverified, verified, corrected; defaults to unverified); `scope` is now the enum private or shared; new optional `related_task_id`, `expires_at` (must be after `created_at`) | yes |
| Event | new optional `task_id`, `agent_id` | no |
| ExecutionResult | `status` adds `partial`; `output` is now optional and `error` embeds an `ErrorDetail`; new optional `agent_id`; output and error follow the status (succeeded: output required, no error; failed: error required, no output; denied: error required with a code in `DENIAL_CODES`, no output; partial and cancelled: neither required). A failed result no longer requires `error_report_id`; the link is optional | yes |
| ErrorReport | new required `code` (`^[A-Z][A-Z0-9_]*$`, max 64: starts with a letter, digits allowed after it such as `HTTP_429`; same pattern as the API error envelope); new `fields`, optional `agent_id`; `message` limit is now 500; `detail()` returns the user-safe `ErrorDetail` | yes |
| AuditRecord | `resource` is replaced by required `resource_type` and optional `resource_id` | yes |

ToolPermission is unchanged (schema v1).

### Not ported

- The six API response schemas (`approval`, `approval-list`, `conversation`, `conversation-list`, `error`, `health`) are deferred to the orchestrator port, where they become response models next to their endpoints.
- `MemoryRecord.deleted_at`: deletion stays a tombstone record, which keeps records immutable.

## 0.1.0 (2026-09-27)

Initial scaffold: Agent, Task, Dispatch, ToolPermission, MemoryRecord, Event, ExecutionResult, ErrorReport, AuditRecord, and the registry.
