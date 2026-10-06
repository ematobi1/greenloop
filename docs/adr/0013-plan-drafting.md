# ADR 0013: Plan drafting, drafts only

- Status: Accepted; implemented on feature/phase2-rest
- Date: 2026-10-05

## Context

Phase 2's exit criteria include "see a drafted plan". Running plans needs the workflow engine, permissions and approvals of phases 3 and 4, so a drafted plan must not be able to do anything yet.

## Decision

1. **A Plan contract (contracts 0.5.0).** `Plan` holds a goal and 1 to 20 `PlanStep`s (title, description, `depends_on` as indices of earlier steps only), so every plan is acyclic and already in execution order. Status is `draft` or `discarded`; approval and execution states arrive with the workflow engine, which will turn steps into `Task`s.
2. **Drafting is one model call with no tools.** `POST /v1/plans` builds the request with `planner.build_planner_request`: `PLANNER_SYSTEM_PROMPT`, memory only through the context builder (ranked against the goal), and the goal plus an optional excerpt of the owner's conversation, redacted and HTML-escaped inside the `PLANNER_USER_TEMPLATE` tags. Prompt text was written by the prompt-engineer subagent.
3. **Strict parsing, nothing stored on failure.** The reply must be one JSON object `{"steps": [...]}` (a surrounding code fence is tolerated). Anything else, a cut-off reply, or steps that break the contract is `502 PLAN_DRAFT_INVALID` and no row is written. Provider errors map to the usual `AI_*` errors.
4. **Scoped and audited.** Plans belong to their principal; anyone else gets 404. Drafting and discarding are audited. Discard is a soft status change; a discarded plan stays readable.
5. **Web.** A "Draft a plan" form in a conversation shows the steps as text with a "nothing runs until you approve it" label, and can discard. The proxy forwards only `goal` and `conversation_id`, with a 150-second timeout because the orchestrator answers only when drafting is done.
6. **Evals.** `evals/planner_behavior.py` (paid) checks JSON validity, approval wording on consequential steps, injection resistance, clarify-first and refusal behaviour; its scorer is gate-tested without a model.

## Consequences

- A slow model holds a web request open for up to 150 seconds; streaming the draft is a later improvement.
- A description longer than 4000 characters fails the whole draft rather than being truncated.
- A "can't plan this" answer to a harmful goal is stored as an ordinary one-step draft.
