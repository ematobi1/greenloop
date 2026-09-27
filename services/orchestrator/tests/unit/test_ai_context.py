import asyncio

from app.ai.context import build_system_prompt
from app.ai.engine import AIEngine
from app.ai.prompts import MEMORY_PREAMBLE, NO_MEMORY_NOTE, SYSTEM_PROMPT
from app.ai.providers.base import CompletionRequest, CompletionResponse, Message
from app.memory.context_builder import build_memory_context


class RecordingProvider:
    name = "recording"

    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request)
        return CompletionResponse(text="ok", model="fake")


def test_system_prompt_without_memory_uses_no_memory_note():
    memory = build_memory_context([], principal_id="user-1")
    prompt = build_system_prompt(memory)
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


def test_engine_keeps_memory_in_system_and_appends_user_turn(make_record):
    memory = build_memory_context([make_record()], principal_id="user-1")
    history = (Message(role="user", content="hi"), Message(role="assistant", content="hello"))
    request = AIEngine(RecordingProvider()).build_request(history, "what do I prefer?", memory)

    assert request.messages[-1] == Message(role="user", content="what do I prefer?")
    assert request.messages[:2] == history
    assert memory.text in request.system
    assert all(memory.text not in m.content for m in request.messages)


def test_engine_respond_calls_provider_once():
    provider = RecordingProvider()
    memory = build_memory_context([], principal_id="user-1")
    response = asyncio.run(AIEngine(provider).respond((), "hello", memory))
    assert response.text == "ok"
    assert len(provider.requests) == 1
