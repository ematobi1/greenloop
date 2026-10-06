"""Planner: drafts an ordered plan for a goal. Drafting never executes anything.

The request is built like a chat turn: memory only through the context builder, every
user-supplied string redacted, and the goal and conversation excerpt HTML-escaped so
they can't close the tags that frame them. The model must answer with one JSON object;
anything else, or steps that break the Plan contract, is a PlanDraftError and nothing
is stored. Prompt wording lives in app/ai/prompts.py.
"""

import html
import json
import re
from collections.abc import Iterable, Sequence

from pydantic import ValidationError

from app.ai.prompts import (
    MEMORY_PREAMBLE,
    NO_MEMORY_NOTE,
    PLANNER_SYSTEM_PROMPT,
    PLANNER_USER_TEMPLATE,
)
from app.ai.providers.base import Done, GenerationRequest, Message, ModelProvider, TextDelta
from app.core.redaction import Redactor
from app.memory.context_builder import build_memory_context
from greenloop_contracts import MAX_PLAN_STEPS, MemoryRecord, PlanStep

MAX_PLAN_OUTPUT_TOKENS = 8000
MAX_EXCERPT_CHARS = 8000
MAX_REPLY_CHARS = 200_000
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class PlanDraftError(Exception):
    """The model's reply was not a valid plan."""


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def conversation_excerpt(history: Sequence[Message], redactor: Redactor) -> str:
    """The newest turns that fit MAX_EXCERPT_CHARS, oldest first, redacted and escaped."""
    lines: list[str] = []
    used = 0
    for message in reversed(history):
        line = f"{message.role}: {_escape(redactor.redact(message.content))}"
        if used + len(line) > MAX_EXCERPT_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(reversed(lines)) or "(none)"


def build_planner_request(
    records: Iterable[MemoryRecord],
    goal: str,
    history: Sequence[Message],
    *,
    principal_id: str,
    redactor: Redactor,
) -> tuple[GenerationRequest, tuple[str, ...]]:
    """The database-free part of drafting: shared by the API and the planner eval."""
    memory = build_memory_context(records, principal_id=principal_id, redactor=redactor)
    framing = f"{MEMORY_PREAMBLE}\n\n{memory.text}" if memory.included_ids else NO_MEMORY_NOTE
    user = PLANNER_USER_TEMPLATE.format(
        goal=_escape(redactor.redact(goal)),
        conversation=conversation_excerpt(history, redactor),
    )
    request = GenerationRequest(
        system=f"{PLANNER_SYSTEM_PROMPT}\n\n{framing}",
        messages=(Message(role="user", content=user),),
        max_output_tokens=MAX_PLAN_OUTPUT_TOKENS,
    )
    return request, memory.included_ids


async def generate(provider: ModelProvider, request: GenerationRequest) -> str:
    parts: list[str] = []
    size = 0
    async for event in provider.stream(request):
        if isinstance(event, TextDelta):
            parts.append(event.text)
            size += len(event.text)
            if size > MAX_REPLY_CHARS:
                raise PlanDraftError("the reply is too long")
        elif isinstance(event, Done) and event.truncated:
            raise PlanDraftError("the reply was cut off")
    return "".join(parts)


def parse_plan_steps(reply: str) -> tuple[PlanStep, ...]:
    """Steps from the model's JSON reply. Raises PlanDraftError for anything off-contract."""
    text = reply.strip()
    if fenced := _FENCE.match(text):
        text = fenced.group(1)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        raise PlanDraftError("the reply is not JSON") from None
    if not isinstance(payload, dict) or set(payload) != {"steps"}:
        raise PlanDraftError("the reply must be an object with only a steps list")
    steps = payload["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_PLAN_STEPS:
        raise PlanDraftError(f"a plan needs 1 to {MAX_PLAN_STEPS} steps")
    try:
        parsed = tuple(PlanStep.model_validate(step) for step in steps)
    except ValidationError:
        raise PlanDraftError("a step does not match the plan contract") from None
    for index, step in enumerate(parsed):
        if any(dependency >= index for dependency in step.depends_on):
            raise PlanDraftError("a step depends on a later step")
        if len(set(step.depends_on)) != len(step.depends_on):
            raise PlanDraftError("a step lists a dependency twice")
    return parsed
