"""Assembles a model request: system prompt from prompts.py plus a MemoryContext,
then as much recent history as fits the token budget.

Only the context builder's escaped block is ever inserted; raw records never are.
Every history and user message passes through the Redactor before it leaves the
server. Prompt wording lives in prompts.py.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.ai.errors import AiError
from app.ai.prompts import MEMORY_PREAMBLE, NO_MEMORY_NOTE, SYSTEM_PROMPT
from app.ai.providers.base import GenerationRequest, Message
from app.core.redaction import Redactor
from app.memory.context_builder import MemoryContext, build_memory_context
from greenloop_contracts import MemoryRecord

CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class RequestLimits:
    context_token_limit: int
    max_output_tokens: int


def estimate_tokens(text: str) -> int:
    """A conservative character-based estimate; exact counts come back in usage."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


@dataclass(frozen=True)
class TurnRequest:
    request: GenerationRequest
    memory_ids: tuple[str, ...]


def build_turn_request(
    records: Iterable[MemoryRecord],
    history: Sequence[Message],
    user_message: str,
    *,
    principal_id: str,
    redactor: Redactor,
    limits: RequestLimits,
) -> TurnRequest:
    """The database-free part of a chat turn: retrieved records through the context
    builder, then system prompt, history and user message into one request. The
    engine and evals/chat_behavior.py both call this, so the eval can't drift from
    production request assembly."""
    memory = build_memory_context(records, principal_id=principal_id, redactor=redactor)
    request = build_request(memory, history, user_message, redactor=redactor, limits=limits)
    return TurnRequest(request=request, memory_ids=memory.included_ids)


def build_system_prompt(memory: MemoryContext) -> str:
    if not memory.included_ids:
        return f"{SYSTEM_PROMPT}\n\n{NO_MEMORY_NOTE}"
    return f"{SYSTEM_PROMPT}\n\n{MEMORY_PREAMBLE}\n\n{memory.text}"


def build_request(
    memory: MemoryContext,
    history: Sequence[Message],
    user_message: str,
    *,
    redactor: Redactor,
    limits: RequestLimits,
) -> GenerationRequest:
    """Keep the newest history that fits; the new user message always goes in whole.

    Raises AiError("context_too_large") if the system prompt and user message alone
    leave no room for the reply.
    """
    system = build_system_prompt(memory)
    newest = Message(role="user", content=redactor.redact(user_message))
    budget = (
        limits.context_token_limit
        - limits.max_output_tokens
        - estimate_tokens(system)
        - estimate_tokens(newest.content)
    )
    if budget < 0:
        raise AiError("context_too_large")
    kept: list[Message] = []
    for message in reversed(history):
        content = redactor.redact(message.content)
        budget -= estimate_tokens(content)
        if budget < 0:
            break
        kept.append(Message(role=message.role, content=content))
    kept.reverse()
    while kept and kept[0].role != "user":
        kept.pop(0)
    return GenerationRequest(
        system=system,
        messages=(*kept, newest),
        max_output_tokens=limits.max_output_tokens,
    )
