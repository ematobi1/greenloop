"""Client for services/broker, the only path to tools that write, send, delete or spend."""

from greenloop_contracts import ExecutionResult, ToolPermission


class BrokerClient:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    async def execute(self, permission: ToolPermission, approval_id: str | None) -> ExecutionResult:
        raise NotImplementedError(
            "TODO(phase-3): POST to broker with correlation id, no retry on 4xx"
        )
