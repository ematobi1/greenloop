"""AI engine: turns a user turn plus safe memory context into a model request.

The engine never sees raw memory records, only the MemoryContext produced by
app/memory/context_builder.py.
"""

from app.ai.context import build_system_prompt
from app.ai.providers.base import CompletionRequest, CompletionResponse, Message, ModelProvider
from app.memory.context_builder import MemoryContext


class AIEngine:
    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    def build_request(
        self, history: tuple[Message, ...], user_message: str, memory: MemoryContext
    ) -> CompletionRequest:
        return CompletionRequest(
            system=build_system_prompt(memory),
            messages=(*history, Message(role="user", content=user_message)),
        )

    async def respond(
        self, history: tuple[Message, ...], user_message: str, memory: MemoryContext
    ) -> CompletionResponse:
        # TODO(phase-2): record token usage and latency as a trace for evals.
        return await self._provider.complete(self.build_request(history, user_message, memory))
