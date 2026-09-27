# ADR 0001: One monorepo with independent services

- Status: Accepted
- Date: 2026-09-27

## Context

GreenLoop grew as separate folders (greenloop-contracts, several brokers and adapters, a canonical orchestrator, self-improvement, staging copies). Contracts drifted between them, and there were parallel versions of the broker and the permission logic. Changes that crossed folders had no single test run.

## Decision

Consolidate into one repository with a services-first layout: `packages/contracts`, `services/orchestrator`, `services/broker`, `services/self-improvement`, `apps/web`, plus `mcp/`, `evals/`, `infra/` and `docs/`. Each service has its own `pyproject.toml`, tests and Dockerfile and builds on its own. Services share only the contracts package. One `.venv` at the root; each service's `app/` package runs from its own folder (dependencies-only install), so services never import each other.

## Consequences

- One CI run covers every package, and a contract change is visible to every consumer in the same pull request.
- Services stay independently testable and deployable.
- Old folders are ported piece by piece, tracked in `docs/migration-map.md`.
- `import app` does not work from the repository root by design; run tools from the service folder.
