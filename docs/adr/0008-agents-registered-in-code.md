# ADR 0008: Agents are registered in code, and dispatch records observed facts only

- Status: Accepted
- Date: 2026-10-02

## Context

PR5a ports the agent registry and dispatch from `greenloop-canonical-orchestrator` (`69628c9`). The old code loaded agents from a vendored `greenloop-agent-registry` wheel, dispatched at `POST /v1/agents/dispatch`, and wrote execution memory with `scope: shared`.

## Decision

- **Registration is a code change.** `app/agents/registry.py` builds the registry at startup (`build_agent_registry`). There is no API to register, enable or disable an agent, for the same reason `AgentDomain` is a closed enum: a new agent is reviewed, not submitted.
- **Only active agents run.** An unknown agent is refused with `404 AGENT_NOT_FOUND`, and a registered or disabled one with `409 AGENT_NOT_ACTIVE`. Both refusals get a `denied` audit entry; if that entry can't be written the refusal still stands and `X-Audit-Persistence: failed` says so.
- **Two deterministic reference agents** (`echo-reference-agent`, `failing-reference-agent`) are rewritten, not copied from the wheel. They make no model or tool calls, so dispatch, audit and memory can be tested end to end for free. The planner, research and coding agents stay stubs and are not registered.
- **`POST /v1/dispatches`** (a noun, per the API rules) replaces `/v1/agents/dispatch`. It is a thin adapter over `orchestration/dispatcher.dispatch`, the single entry point that owns the agent checks, so the planner will reuse it rather than copy them. The server builds the `Dispatch`: id, principal, correlation id and time never come from the request. Inputs are capped at 64 KiB of UTF-8 JSON, and `timeout_ms` at 120 s (default 30 s), well below the contract's one hour, because the request stays open while the agent runs.
- **200, not 201.** A dispatch runs synchronously and is not a stored resource (there is no `GET /v1/dispatches/{id}`), so success is `200` with the `ExecutionResult`. Its record lives in the audit log and execution memory. If dispatches become asynchronous, they become a resource with `201`, `Location` and a GET.
- **A returned result is a fact.** Exceptions, the dispatch deadline (`AGENT_TIMEOUT`; a timeout raised inside the agent is `AGENT_FAILED`), a return value that isn't an `ExecutionResult`, and results naming another dispatch become failed results with user-safe codes. Only the exception type is logged, never its message. A cancelled dispatch (client gone, shutdown) is recorded as `cancelled` before the cancellation propagates; the write runs in a worker thread, so the host must drain the default executor on shutdown (uvicorn does). Recording can't change or hide the result: memory and audit are written in one transaction, then the audit entry alone, and `X-Execution-Memory` / `X-Audit-Persistence` say what was written.
- **Execution memory is private and factual** (port decision 6). One `task_execution_history` record per dispatch, written by the dispatcher (`source: system`, `created_by: orchestrator.dispatcher`), confidence `verified`, holding ids, status, error code and the start and finish times the result reports. The memory store's own `memory.create` audit entry sits beside the `agent.dispatch` entry; both are intended. Dispatch inputs and agent output are never stored in memory or the audit log, because they can contain user data or injected text that would later reach the model through retrieval.

## Consequences

- Adding an agent needs a PR, tests and review.
- **Agent-level permission is not enforced yet.** Any authenticated principal can dispatch any active agent. That is acceptable only while the registered agents are inert; a permission check through `permissions/` is required before any agent with model or tool access is registered.
- Agents must not block the event loop: the deadline can only interrupt an agent at an `await` (`BaseAgent` says so).
- Not handled yet, tracked with M10 (no per-principal rate or cost limit): a request body-size limit in middleware, a per-principal dispatch concurrency limit (429), a limit on audited refusals (each unknown `agent_id` writes one row), and keeping execution records from crowding recency-based chat retrieval.
- Tool use inside agents still goes permission check, approval, broker, audit (PR5b and phase 3).
