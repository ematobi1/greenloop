"""Anthropic implementation of ModelProvider.

TODO(phase-2): add the `anthropic` SDK dependency and call the Messages API with an
explicit timeout, retries with backoff on 5xx and network errors, and request-id logging.
"""

from pydantic import SecretStr

from app.ai.providers.base import CompletionRequest, CompletionResponse


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: SecretStr, model: str, timeout_seconds: float = 60.0) -> None:
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        raise NotImplementedError("TODO(phase-2): Anthropic Messages API call")
