"""Provider-neutral model interface. The orchestrator depends on this, never on a vendor SDK.

A provider streams TextDelta events and ends with exactly one Done carrying the
stop reason and token usage, or raises AiError.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class GenerationRequest:
    system: str
    messages: tuple[Message, ...]
    max_output_tokens: int


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class Done:
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    request_id: str | None = None


StreamEvent = TextDelta | Done


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    timeout_seconds: float
    max_retries: int


class ModelProvider(Protocol):
    config: ProviderConfig

    def stream(self, request: GenerationRequest) -> AsyncIterator[StreamEvent]: ...
