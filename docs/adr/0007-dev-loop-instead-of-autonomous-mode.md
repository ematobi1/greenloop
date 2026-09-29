# ADR 0007: Human-gated dev loop instead of an autonomous mode

- Status: Accepted
- Date: 2026-09-29

## Context

Loki Mode, a multi-agent autonomous skill for Claude Code, was reviewed as a way to speed up GreenLoop development. As written it conflicts with GreenLoop's rules:

- It requires `--dangerously-skip-permissions`, which removes every permission check on a machine that holds the GitHub App key, `.env` and the old repos.
- Its "zero human intervention", "never ask" and "never stop" rules override CLAUDE.md checkpoints and GreenLoop's core rule that humans control consequential actions.
- It deploys to cloud providers automatically, while Terraform here is skeleton-only and no deploy happens without Terry.
- It runs 100+ agents with 10+ in parallel, which means unpredictable token spend and conflicting edits.
- It includes business, marketing, sales and HR swarms and "revenue-generating" goals, which are out of scope.
- It auto-resumes and runs background retry loops with no checkpoint.
- It relies on `.loki/` queues, state and `autonomy/run.sh`, which don't exist in the skill and would form a second orchestration system beside GreenLoop's own.
- It rewrites CLAUDE.md on "significant changes", letting the agent change its own rules.

Several of its engineering patterns are useful, though: a working-memory file, small verified steps, deterministic gates before AI review, blind parallel review with severity triage, and explicit escalation triggers.

## Decision

- Don't install Loki Mode. Adopt its useful patterns as the project skill `greenloop-dev-loop` (`.claude/skills/greenloop-dev-loop/SKILL.md`), with every autonomy, deploy, push and permission-bypass behavior removed. CLAUDE.md takes precedence over the skill.
- The loop is one feature at a time: Reason (plan, no code, checkpoint 1) → Act (small steps) → Reflect and verify (`scripts/lint.ps1`, `scripts/test.ps1`, `scripts/test-postgres.ps1`, free evals) → Review (three blind reviewers for correctness, security and architecture, plus a devil's advocate, triaged by severity) → checkpoint 2 report.
- Working memory lives in `.dev-loop/CONTINUITY.md`, which is gitignored and local only. Durable decisions go into ADRs.
- Harden project permissions in `.claude/settings.json`:
  - `disableBypassPermissionsMode: "disable"`.
  - Deny, for both the Bash and PowerShell tools: push, `gh`, `terraform apply`/`destroy`, hard resets, `git clean`, force-deleting branches, recursive deletes, Docker volume removal and prune.
  - Deny reading or editing `.env` and `.env.*` (except `.env.example`), `.pem` and `.key` files anywhere, and `%LOCALAPPDATA%\GreenLoop`.
  - Ask before commits, branch switches, rebases, merges, package installs, container runs and web fetches.

Patterns kept for GreenLoop's own runtime later, all human-gated and not enabled now:

- Phase 4 (agents, workflows): the Reason-Act-Reflect-Verify cycle maps to plan → execute → evaluate → self-correct, and the subagent brief template fits dispatch payloads.
- Phase 5 (self-correction): proponent/opponent/synthesizer debate for high-risk plans, ending in a human decision.
- Phases 3 and 7 (tools, approvals): confidence-based routing to decide which actions need approval, although consequential actions always need a human. Also circuit breakers and dead-letter queues in the broker.
- Memory: consolidating episodic memory into semantic memory, on top of the existing append-only store with provenance.

## Consequences

- Multi-step features stop at a plan checkpoint and a final report. Throughput is lower than a fully autonomous run, in exchange for control and predictable cost.
- Push, PRs, merges and deploys stay with Terry.
- The permission rules are Claude Code rules, not an OS security boundary. They match the command text Claude writes, so another form of the same command, such as `git -C dir push` or a script that opens files itself, isn't caught. They reduce accidents; they don't replace keeping secrets out of the repo or enabling the sandbox.
- A rule that blocks a task Terry approves, such as deleting a folder recursively, has to be run by Terry or relaxed deliberately. It is never routed around.
