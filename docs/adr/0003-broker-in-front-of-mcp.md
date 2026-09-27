# ADR 0003: A broker in front of every consequential MCP tool

- Status: Accepted
- Date: 2026-09-27

## Context

MCP servers (starting with the official GitHub MCP server) expose powerful write operations. A model can be manipulated into requesting them. Earlier brokers (k1, k2a) used a custom REST client, a Windows service and named pipes; they proved the allowlist and ledger ideas but were hard to run anywhere else.

## Decision

`services/broker` is the only path to tools that write, send, delete or spend. For each call it:

1. evaluates its own deny-by-default policy from `policies/*.yaml` (strictest matching rule wins),
2. consumes a human approval bound to the SHA256 of the exact canonicalized operation, once,
3. appends to a hash-chained ledger,
4. forwards to the MCP server listed as enabled in `mcp/servers.yaml`, limited to its allowed toolsets.

The orchestrator also checks permissions, but the broker never trusts that check.

## Consequences

- The model is not the security boundary; a compromised prompt cannot skip approval or audit.
- Policy is data, reviewable in pull requests, with tests for allow, approval and deny paths.
- An extra network hop per consequential call; reads can bypass the broker only where policy marks them read-only.
- The Windows service and pipes from k1 and k2a are not ported; only their allowlist and ledger ideas are.
