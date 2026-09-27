# Glossary

| Term | Meaning |
|---|---|
| Agent | A registered unit that carries out a plan step. Described by the `Agent` contract. |
| Approval | A human decision that allows one specific consequential operation. Bound to the operation's canonical hash and consumed once. |
| Approval binding | Tying an approval to the SHA256 of the exact canonicalized operation, so the approval cannot be reused for a different or repeated call. |
| Audit record | An append-only entry describing a consequential decision or action: who, what, when, outcome. The `AuditRecord` contract. |
| Broker | `services/broker`. The only path to tools that write, send, delete or spend. Enforces policy, approval binding and the ledger, then forwards to MCP servers. |
| Canonical hash | SHA256 over a deterministic serialization of an operation (sorted keys, fixed encoding). Two identical operations produce the same hash. |
| Consequential action | Any tool call that writes, sends, deletes or spends. Requires the broker, and approval when policy says so. |
| Context builder | `memory/context_builder.py`. The only way retrieved memory enters a prompt. Bounds size, redacts secrets and escapes content so it reads as data, not instructions. |
| Contract | A shared Pydantic model in `packages/contracts`. The one schema system for all services. |
| Correct | A memory operation that records a fix to an earlier record without erasing the original. |
| Deny by default | When no policy rule matches a request, the answer is deny. |
| Dispatch | Sending a task to an agent. The `Dispatch` contract. |
| Error detail | The user-safe error shape `{code, message, fields}` shared by results, error reports and API errors. Never carries internal detail. |
| Error report | A structured record of a failure and its handling. Its `details` hold internal information that is never returned to users. The `ErrorReport` contract. |
| Eval | A measured check of model behavior (prompt quality, injection resistance). Lives in the top-level `evals/`. |
| Event | A timestamped occurrence published inside GreenLoop. The `Event` contract. |
| Execution result | The outcome of a task or tool call. The `ExecutionResult` contract. |
| Ledger | The broker's append-only record of every forwarded call and its approval. |
| MCP | Model Context Protocol. The protocol GreenLoop's tool servers speak. Configured in `mcp/servers.yaml`. |
| Memory category | What kind of knowledge a memory record holds (for example user_context, decision, verified_outcome), so preferences are not mistaken for facts. |
| Memory confidence | Whether a memory record is unverified, verified or corrected. New records start unverified. |
| Memory record | One stored memory item with scope (private or shared), principal, category, confidence and provenance. The `MemoryRecord` contract. |
| Orchestrator | `services/orchestrator`. The one canonical coordinator of reasoning, memory, agents and tools. |
| Policy | Rules that decide whether a tool permission is allowed, denied or needs approval. |
| Principal | The authenticated identity a request acts for. Memory and permissions are scoped to it server-side. |
| Prompt injection | Text in user input, memory or tool output that tries to act as instructions. Treated as data. |
| Proposal | A self-improvement change suggestion, with evidence. Execution is disabled by default. |
| Provenance | Where a memory record came from and how it changed: source, history, supersede and correct links. |
| Provider | An external service behind a GreenLoop interface, such as a model API or ElevenLabs. |
| Scope | Who may read a memory record: `private` (only its principal) or `shared`. An enum, so a `project` scope can be added later. |
| Self-correction | Detecting a failed step and retrying, re-planning or escalating. `correction/lifecycle.py`. |
| Self-improvement | The pipeline that proposes and validates changes to GreenLoop itself. `services/self-improvement`. |
| SpeechProvider | The voice interface in `speech/provider.py`. ElevenLabs is one implementation. |
| Supersede | A memory operation that replaces a record with a newer one while keeping the old one in history. |
| Task | A unit of planned work. The `Task` contract. |
| Tool grant | A standing permission the owner gives an agent to use listed actions of a tool, optionally until an expiry. Never a credential. The `ToolGrant` contract. |
| Tool permission | A request to use a specific tool operation, evaluated by policy. The `ToolPermission` contract. |
