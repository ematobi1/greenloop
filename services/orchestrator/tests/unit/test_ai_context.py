import pytest

from app.ai.context import RequestLimits, build_request, build_system_prompt, estimate_tokens
from app.ai.errors import AiError
from app.ai.prompts import MEMORY_PREAMBLE, NO_MEMORY_NOTE, SYSTEM_PROMPT
from app.ai.providers.base import Message
from app.core.redaction import REDACTED, Redactor
from app.memory.context_builder import build_memory_context

LIMITS = RequestLimits(context_token_limit=100_000, max_output_tokens=1_000)
SECRET = "sk-ant-api03-synthetic-secret-value-0000000000"


def _empty_memory():
    return build_memory_context([], principal_id="user-1")


def test_system_prompt_without_memory_uses_no_memory_note():
    prompt = build_system_prompt(_empty_memory())
    assert prompt.startswith(SYSTEM_PROMPT)
    assert prompt.endswith(NO_MEMORY_NOTE)
    assert MEMORY_PREAMBLE not in prompt
    assert "<retrieved_memory count=" not in prompt


def test_system_prompt_with_memory_frames_block(make_record):
    memory = build_memory_context([make_record()], principal_id="user-1")
    prompt = build_system_prompt(memory)
    assert prompt.startswith(SYSTEM_PROMPT)
    assert prompt.index(MEMORY_PREAMBLE) < prompt.index(memory.text)
    assert prompt.endswith(memory.text)
    assert NO_MEMORY_NOTE not in prompt


def test_prompts_name_the_tags_the_builder_emits():
    assert "<retrieved_memory>" in SYSTEM_PROMPT
    assert "<memory_record>" in SYSTEM_PROMPT


def test_memory_goes_in_system_and_the_user_turn_goes_last(make_record):
    memory = build_memory_context([make_record()], principal_id="user-1")
    history = (Message("user", "hi"), Message("assistant", "hello"))
    request = build_request(
        memory, history, "what do I prefer?", redactor=Redactor(), limits=LIMITS
    )
    assert request.messages == (*history, Message("user", "what do I prefer?"))
    assert memory.text in request.system
    assert all(memory.text not in message.content for message in request.messages)
    assert request.max_output_tokens == LIMITS.max_output_tokens


def test_secrets_in_user_and_history_are_redacted_before_leaving():
    redactor = Redactor(known_secrets=[SECRET])
    history = (Message("user", f"my key is {SECRET}"), Message("assistant", "noted"))
    request = build_request(
        _empty_memory(), history, f"again: {SECRET}", redactor=redactor, limits=LIMITS
    )
    assert all(SECRET not in message.content for message in request.messages)
    assert all(REDACTED in request.messages[i].content for i in (0, 2))


def test_oldest_history_is_dropped_first_when_the_budget_is_tight():
    system_tokens = estimate_tokens(build_system_prompt(_empty_memory()))
    turn = "x" * 400
    history = tuple(Message("user" if i % 2 == 0 else "assistant", f"{i}{turn}") for i in range(10))
    limits = RequestLimits(context_token_limit=system_tokens + 1 + 350 + 100, max_output_tokens=100)
    request = build_request(_empty_memory(), history, "q", redactor=Redactor(), limits=limits)
    # Budget 350 fits turns 9, 8 and 7 (101 tokens each); 7 is an assistant turn and is
    # trimmed so history starts with a user turn.
    assert [message.content[0] for message in request.messages[:-1]] == ["8", "9"]
    assert request.messages[-1] == Message("user", "q")


def test_history_never_starts_with_an_assistant_turn():
    history = (Message("assistant", "a" * 4000), Message("assistant", "b"), Message("user", "c"))
    request = build_request(_empty_memory(), history, "q", redactor=Redactor(), limits=LIMITS)
    assert request.messages[0].role == "user"
    assert [m.content for m in request.messages] == ["c", "q"]


def test_a_message_that_leaves_no_room_for_the_reply_is_rejected():
    limits = RequestLimits(context_token_limit=2_000, max_output_tokens=1_000)
    with pytest.raises(AiError) as err:
        build_request(_empty_memory(), (), "y" * 8_000, redactor=Redactor(), limits=limits)
    assert err.value.code == "context_too_large"
