"""Ollama provider for an optional local model. Only loopback URLs are accepted.

Streams /api/chat NDJSON. Retries 5xx and connection errors with jittered backoff,
but only before the first chunk: a stream that already produced text is never
replayed, so the client never sees duplicated output.
"""

import asyncio
import json
import random
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import httpx2
import structlog

from app.ai.errors import AiError
from app.ai.providers.base import Done, GenerationRequest, ProviderConfig, StreamEvent, TextDelta

logger = structlog.get_logger(__name__)

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_BACKOFF_SECONDS = 2.0


def validate_loopback_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or parts.hostname not in LOOPBACK_HOSTS:
        raise ValueError("ollama_base_url must point at this machine (127.0.0.1, localhost, ::1)")
    return base_url.rstrip("/")


class OllamaProvider:
    def __init__(
        self,
        config: ProviderConfig,
        base_url: str,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._base_url = validate_loopback_url(base_url)
        self._transport = transport

    async def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        attempts = 1 + self.config.max_retries
        for attempt in range(attempts):
            started = False
            try:
                async for event in self._stream_once(request):
                    started = True
                    yield event
                return
            except AiError as err:
                if started or not err.retryable or attempt == attempts - 1:
                    raise
                await asyncio.sleep(_backoff(attempt))

    async def _stream_once(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]:
        timeout = httpx2.Timeout(
            connect=5.0, read=self.config.timeout_seconds, write=10.0, pool=5.0
        )
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": request.system}]
            + [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": True,
            "options": {"num_predict": request.max_output_tokens},
        }
        done = False
        try:
            async with (
                httpx2.AsyncClient(
                    base_url=self._base_url,
                    timeout=timeout,
                    transport=self._transport,
                    trust_env=False,
                ) as client,
                client.stream("POST", "/api/chat", json=payload) as response,
            ):
                if response.status_code >= 500:
                    raise AiError("unavailable", retryable=True)
                if response.status_code >= 400:
                    logger.warning("ollama_rejected_request", status=response.status_code)
                    raise AiError("rejected")
                async for line in response.aiter_lines():
                    if line.strip():
                        for event in _parse_chunk(line):
                            done = done or isinstance(event, Done)
                            yield event
        except httpx2.TimeoutException as err:
            raise AiError("timeout") from err
        except httpx2.TransportError as err:
            raise AiError("unavailable", retryable=True) from err
        if not done:
            raise AiError("invalid_response")


def _parse_chunk(line: str) -> list[StreamEvent]:
    try:
        chunk = json.loads(line)
    except ValueError as err:
        raise AiError("invalid_response") from err
    if not isinstance(chunk, dict):
        raise AiError("invalid_response")
    if "error" in chunk:
        logger.warning("ollama_reported_error")
        raise AiError("rejected")
    events: list[StreamEvent] = []
    content = (chunk.get("message") or {}).get("content", "")
    if content:
        events.append(TextDelta(content))
    if chunk.get("done"):
        events.append(
            Done(
                stop_reason=str(chunk.get("done_reason", "stop")),
                input_tokens=int(chunk.get("prompt_eval_count", 0)),
                output_tokens=int(chunk.get("eval_count", 0)),
            )
        )
    return events


def _backoff(attempt: int) -> float:
    return min(MAX_BACKOFF_SECONDS, 0.2 * (2**attempt)) + random.uniform(0, 0.1)  # noqa: S311 - jitter, not crypto
