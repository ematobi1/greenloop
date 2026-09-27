# MCP servers

`servers.yaml` lists every MCP tool server GreenLoop may reach, whether it is enabled, and which toolsets it may use.

- The broker (`services/broker`) is the only caller. It checks policy (`services/broker/policies/`), consumes an approval when required, writes the ledger, and then forwards the call.
- A server with `enabled: false` is never contacted.
- `allowed_toolsets` limits the tools GreenLoop exposes from each server, even when the server offers more.
- Credentials are referenced by environment variable name only. Values live in a local `.env` (gitignored) or, in production, Secrets Manager.
- GitHub first, through the official GitHub MCP server authenticated as a GitHub App. The broker mints short-lived installation tokens from `GITHUB_APP_ID` and `GITHUB_APP_PRIVATE_KEY_PATH` (phase 3). Tests use synthetic credentials only.

To enable a server: flip `enabled`, add policy rules for its operations, and add broker tests covering allow, approval and deny paths.
