"""Provider-neutral model interface. The orchestrator depends on this, never on a vendor SDK."""

from dataclasses import dataclass, field
from typing import Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    system: str
    messages: tuple[Message, ...]
    max_tokens: int = 4096


@dataclass(frozen=True)
class CompletionResponse:
    text: str
    model: str
    stop_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


class ModelProvider(Protocol):
    name: str

    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...
