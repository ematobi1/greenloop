# ADR 0006: Per-service `app` packages, run from each service folder

- Status: Accepted
- Date: 2026-09-27

## Context

The target tree gives every Python service a top-level package named `app` (`services/orchestrator/app`, `services/broker/app`, `services/self-improvement/app`). The scaffold also asks for one virtual environment at `.venv` with packages installed in editable mode. Only one top-level package named `app` can be importable from a single environment, so installing all three editable would make them shadow each other.

Options considered:

- A: keep `app/` per service; install each service's dependencies only; run each service from its own folder.
- B: rename to `greenloop_orchestrator/`, `greenloop_broker/`, `greenloop_self_improvement/` and install everything editable.
- C: one virtual environment per service.

## Decision

Option A.

- Each service's `pyproject.toml` declares its dependencies and sets `[tool.setuptools] packages = []`, so `pip install -e services/<name>[dev]` installs dependencies without putting `app` on the shared path.
- `packages/contracts` is a normal installed package (`greenloop_contracts`) and is the only code services share.
- pytest runs from the service folder with `pythonpath = ["."]` and `--import-mode=importlib`; uvicorn runs `app.main:app` from the service folder; Dockerfiles copy `app/` into `/srv` and run from there.
- `scripts/test.ps1`, `scripts/dev.ps1` and CI change into the service folder before running.
- Ruff treats both `app` and `greenloop_contracts` as first-party.

## Consequences

- The tree matches the architecture as specified, and one `.venv` serves every package.
- Services cannot import each other by accident: `import app` from the repository root fails, which is verified during the scaffold.
- Tools must be run from the right folder. Running `pytest` from the root, or opening a Python shell at the root and importing `app`, does not work; the scripts and README say so.
- Each service's tests run in their own process, which keeps them independent.
- If a service ever needs to be imported by another Python process (for example a shared worker), revisit with option B for that service.

## Addendum (2026-10-01): the chat behavior eval

`evals/chat_behavior.py` imports orchestrator internals by putting `services/orchestrator` on `sys.path`, and `services/orchestrator/tests/unit/test_chat_eval.py` loads that file by path. This is the one sanctioned exception to the rule above.

- Why: the eval has to assemble requests exactly as production does. It calls `app.ai.context.build_turn_request`, the same function `ChatEngine.prepare` uses, and a gate test fails if they stop sharing it.
- Limits: the eval runs from `services/orchestrator` and imports only `app.ai.*`, `app.core.redaction` and `app.core.config`. No other service may import orchestrator code.
- Cost: a change under `evals/` can fail the orchestrator test suite. That's intended, since the eval's scorer is gate-tested there.
- Revisit with option B if a second consumer appears.
