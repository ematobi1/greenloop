"""Forwards an approved, ledgered call to the MCP server configured in mcp/servers.yaml.

Only reached after policy allows the call and, when required, an approval was
consumed. Disabled servers and tools outside a server's allowed toolsets are refused.
"""

from greenloop_contracts import ExecutionResult, ToolPermission


async def forward(permission: ToolPermission, correlation_id: str) -> ExecutionResult:
    raise NotImplementedError("TODO(phase-3): MCP client call to the official GitHub MCP server")
