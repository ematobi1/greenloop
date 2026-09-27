# ADR 0005: Self-improvement execution disabled by default

- Status: Accepted
- Date: 2026-09-27

## Context

The self-improvement pipeline proposes changes to GreenLoop itself. Running proposed code is the highest-risk capability in the system: it could alter permissions, leak secrets or escape a weak sandbox. On the current Windows 11 Home host there is no Hyper-V or Windows Sandbox, and a Git worktree is not a sandbox. Slice B gates 1 to 3 are not approved.

## Decision

- `SELF_IMPROVEMENT_EXECUTION_ENABLED` defaults to `false` (`services/self-improvement/app/config.py`).
- `runner.run` refuses when the flag is false, and still refuses when it is true (`GatesNotApprovedError`) until the gates are approved and the code is changed deliberately.
- `isolation.require_isolation` raises until an isolation mechanism (disposable container or VM, no network, no secrets) is chosen and recorded in a new ADR.
- Proposals, static validation and evidence collection may proceed; they never execute a diff.

## Consequences

- Turning on an environment variable alone cannot enable execution; it takes a reviewed code change.
- Tests pin both locks (`tests/test_execution_disabled.py`), so a regression fails CI.
- Phase 7 work starts with the isolation ADR and Terry's approval of the gates.
