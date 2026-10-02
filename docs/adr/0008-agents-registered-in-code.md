# ADR 0008: Agents are registered in code, and dispatch records observed facts only

- Status: Accepted
- Date: 2026-10-02

## Context

PR5a ports the agent registry and dispatch from `greenloop-canonical-orchestrator` (`69628c9`). The old code loaded agents from a vendored `greenloop-agent-registry` wheel, dispatched at `POST /v1/agents/dispatch`, and wrote execution memory with `scope: shared`.

## Decision

- **Registration is a code change.** `app/agents/registry.py` builds the registry at startup (`build_agent_registry`). There is no API to register, enable or disable an agent, for the same reason `AgentDomain` is a closed enum: a new agent is reviewed, not submitted.
- **Only active agents run.** A registered or disabled agent is refused with `409 AGENT_NOT_ACTIVE` and a `denied` audit entry.
- **Two deterministic reference agents** (`echo-reference-agent`, `failing-reference-agent`) are rewritten, not copied from the wheel. They make no model or tool calls, so dispatch, audit and memory can be tested end to end for free. The planner, research and coding agents stay stubs and are not registered.
- **`POST /v1/dispatches`** (a noun, per the API rules) replaces `/v1/agents/dispatch`. The server builds the `Dispatch`: id, principal, correlation id and time never come from the request. Inputs are capped at 64 KiB as JSON.
- **A returned result is a fact.** Exceptions, timeouts (default 30 s, `timeout_ms` up to the contract maximum) and results naming another dispatch become failed results with user-safe codes. Recording can't change or hide the result: memory and audit are written in one transaction, then the audit entry alone, and `X-Execution-Memory` / `X-Audit-Persistence` say what was written.
- **Execution memory is private and factual** (port decision 6). One `task_execution_history` record per dispatch, confidence `verified`, holding ids, status, times and the error code only. Dispatch inputs and agent output are never stored in memory or the audit log, because they can contain user data or injected text that would later reach the model through retrieval.

## Consequences

- Adding an agent needs a PR, tests and review.
- A client that disconnects mid-dispatch is not handled specially yet; the reference agents finish in microseconds. Long-running agents will need cancellation and a `cancelled` audit path when they are added.
- Tool use inside agents still goes permission check, approval, broker, audit (PR5b and phase 3).
