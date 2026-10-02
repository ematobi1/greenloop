"""Client for services/broker, the only path to tools that write, send, delete or spend,
and the owner of approvals (ADR 0009).

Authenticates with the broker service token (never logged). Retries only GETs, on
network errors and 5xx, with exponential backoff and jitter (rule 9). POSTs are never
retried; each carries an Idempotency-Key, so a caller that does retry one with the
same key gets the stored result instead of a second action. 4xx is never retried.
Every response is validated against the contracts before it is used, and errors
carry the broker's error code but never its response body.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx2
from pydantic import ValidationError

from greenloop_contracts import (
    Approval,
    ApprovalActor,
    ApprovalStatus,
    ExecutionResult,
    ToolPermission,
)

DEFAULT_TIMEOUT_SECONDS = 10.0
GET_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.2


class BrokerError(Exception):
    """The broker refused or could not be reached. `status` is None for network errors."""

    def __init__(self, status: int | None, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


class BrokerClient:
    def __init__(
        self,
        base_url: str,
        service_token: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx2.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = service_token
        self._timeout = timeout_seconds
        self._transport = transport
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"BrokerClient({self._base_url!r})"

    async def create_approval(
        self,
        operation: ToolPermission,
        actor: ApprovalActor,
        *,
        idempotency_key: str,
        correlation_id: str,
    ) -> Approval:
        body = {
            "operation": operation.model_dump(mode="json"),
            "actor": actor.model_dump(mode="json"),
        }
        data = await self._post("/v1/approvals", body, idempotency_key, correlation_id)
        return _approval(data)

    async def decide_approval(
        self,
        approval_id: str,
        actor: ApprovalActor,
        *,
        approved: bool,
        idempotency_key: str,
        correlation_id: str,
    ) -> Approval:
        body = {"approved": approved, "actor": actor.model_dump(mode="json")}
        data = await self._post(
            f"/v1/approvals/{approval_id}/decisions", body, idempotency_key, correlation_id
        )
        return _approval(data)

    async def get_approval(
        self, approval_id: str, *, principal_id: str, correlation_id: str
    ) -> Approval:
        data = await self._get(
            f"/v1/approvals/{approval_id}", {"principal_id": principal_id}, correlation_id
        )
        return _approval(data)

    async def list_approvals(
        self,
        *,
        principal_id: str,
        correlation_id: str,
        status: ApprovalStatus | None = None,
        limit: int = 50,
    ) -> list[Approval]:
        params: dict[str, Any] = {"principal_id": principal_id, "limit": limit}
        if status is not None:
            params["status"] = status.value
        data = await self._get("/v1/approvals", params, correlation_id)
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise BrokerError(None, "BROKER_BAD_RESPONSE")
        return [_approval(item) for item in data["data"]]

    async def execute(self, permission: ToolPermission, approval_id: str | None) -> ExecutionResult:
        raise NotImplementedError("TODO(phase-3): POST to broker with correlation id")

    def _headers(self, correlation_id: str, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token}", "X-Correlation-ID": correlation_id}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            base_url=self._base_url, timeout=self._timeout, transport=self._transport
        )

    async def _post(
        self, path: str, body: dict[str, Any], idempotency_key: str, correlation_id: str
    ) -> Any:
        try:
            async with self._client() as client:
                response = await client.post(
                    path, json=body, headers=self._headers(correlation_id, idempotency_key)
                )
        except httpx2.TransportError:
            raise BrokerError(None, "BROKER_UNREACHABLE") from None
        return _json(response)

    async def _get(self, path: str, params: dict[str, Any], correlation_id: str) -> Any:
        for attempt in range(GET_ATTEMPTS):
            last = attempt == GET_ATTEMPTS - 1
            try:
                async with self._client() as client:
                    response = await client.get(
                        path, params=params, headers=self._headers(correlation_id)
                    )
            except httpx2.TransportError:
                if last:
                    raise BrokerError(None, "BROKER_UNREACHABLE") from None
            else:
                if response.status_code < 500 or last:
                    return _json(response)
            await self._sleep(BACKOFF_BASE_SECONDS * 2**attempt * (1 + random.random()))  # noqa: S311 (jitter, not security)
        raise AssertionError("unreachable")


def _approval(data: Any) -> Approval:
    try:
        return Approval.model_validate(data)
    except ValidationError:
        raise BrokerError(None, "BROKER_BAD_RESPONSE") from None


def _json(response: httpx2.Response) -> Any:
    if response.is_success:
        try:
            return response.json()
        except ValueError:
            raise BrokerError(response.status_code, "BROKER_BAD_RESPONSE") from None
    try:
        code = str(response.json()["error"]["code"])[:64]
    except (ValueError, KeyError, TypeError):
        code = "BROKER_ERROR"
    raise BrokerError(response.status_code, code)
