## What and why

<!-- What changes, and which outcome or roadmap phase it moves. -->

## How it was verified

<!-- Commands run and exact results, e.g. "services/broker: 49 passed". Label verified vs inferred. -->

- [ ] `scripts/test.ps1` passes and no suite's count dropped
- [ ] `scripts/lint.ps1` passes
- [ ] New behavior has tests (security-relevant changes also in the service's `tests/security/`)

## Safety checklist

- [ ] No secrets, `.env`, key files or credentials in the diff
- [ ] Consequential tool paths still go permission check, approval if required, broker, audit
- [ ] Retrieved memory reaches prompts only through `memory/context_builder.py`
- [ ] Contract changes are made in `packages/contracts` (no parallel models)
- [ ] LLM-facing prompt changes went through the prompt-engineer subagent
- [ ] Self-improvement execution remains disabled
