"""Tool registry: which tools and operations exist and their consequence class.

Read-only tools may be called directly; anything consequential goes via broker_client.
"""

from greenloop_contracts import ToolConsequence


def consequence_of(tool: str, operation: str) -> ToolConsequence:
    raise NotImplementedError("TODO(phase-3): load from mcp/servers.yaml toolsets")
