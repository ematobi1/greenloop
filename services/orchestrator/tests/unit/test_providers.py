"""Providers against mock HTTP transports: the real SDK and wire formats, no network."""

import asyncio
import json

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from app.ai.errors import AiError
from app.ai.providers.anthropic import AnthropicProvider
from app.ai.providers.base import Done, GenerationRequest, Message, ProviderConfig, TextDelta
from app.ai.providers.ollama import OllamaProvider, validate_loopback_url
from app.ai.providers.registry import build_registry
from app.core.config import Settings

REQUEST = GenerationRequest(
    system="system text", messages=(Message("user", "hello"),), max_output_tokens=1024
)
CONFIG = ProviderConfig(name="anthropic", model="claude-opus-5-5", timeout_seconds=5, max_retries=0)


def _collect(provider, request=REQUEST):
    async def run():
        return [event async for event in provider.stream(request)]

    return asyncio.run(run())


def _sse(*events: tuple[str, dict]) -> bytes:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


def _message_stream(texts: list[str], stop_reason: str = "end_turn") -> bytes:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-opus-5-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 42, "output_tokens": 1},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
    ]
    events += [
        (
            "content_block_delta",
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": t}},
        )
        for t in texts
    ]
    events += [
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 7},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return _sse(*events)


def _anthropic(handler, effort="medium"):
    client = anthropic.AsyncAnthropic(
        api_key="synthetic-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicProvider(
        CONFIG, api_key=SecretStr("synthetic-key"), effort=effort, client=client
    )


def test_anthropic_streams_text_then_done_with_usage_and_request_id():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["body"] = json.loads(request.content)
        seen["path"] = request.url.path
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream", "request-id": "req_synthetic_1"},
            content=_message_stream(["Hel", "lo"]),
        )

    events = _collect(_anthropic(handler))
    assert events[:-1] == [TextDelta("Hel"), TextDelta("lo")]
    assert events[-1] == Done(
        stop_reason="end_turn", input_tokens=42, output_tokens=7, request_id="req_synthetic_1"
    )
    body = seen["body"]
    assert seen["path"] == "/v1/messages"
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 1024
    assert body["system"] == "system text"
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["output_config"] == {"effort": "medium"}
    assert body["stream"] is True
    assert "thinking" not in body
    assert "temperature" not in body


def test_anthropic_refusal_is_an_error_not_an_empty_answer():
    def handler(request):
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_message_stream([], stop_reason="refusal"),
        )

    with pytest.raises(AiError) as err:
        _collect(_anthropic(handler))
    assert err.value.code == "refused"


@pytest.mark.parametrize(
    ("status", "error_type", "code"),
    [
        (400, "invalid_request_error", "rejected"),
        (401, "authentication_error", "not_configured"),
        (403, "permission_error", "not_configured"),
        (404, "not_found_error", "rejected"),
        (429, "rate_limit_error", "unavailable"),
        (500, "api_error", "unavailable"),
        (529, "overloaded_error", "unavailable"),
    ],
)
def test_anthropic_http_errors_map_to_safe_codes(status, error_type, code, caplog):
    vendor_message = "vendor detail that must stay server-side"

    def handler(request):
        return httpx2.Response(
            status,
            headers={"request-id": "req_synthetic_err"},
            json={"type": "error", "error": {"type": error_type, "message": vendor_message}},
        )

    with pytest.raises(AiError) as err:
        _collect(_anthropic(handler))
    assert err.value.code == code
    assert vendor_message not in err.value.public_message
    assert "req_synthetic_err" in caplog.text


def test_anthropic_connection_failure_is_unavailable():
    def handler(request):
        raise httpx2.ConnectError("refused")

    with pytest.raises(AiError) as err:
        _collect(_anthropic(handler))
    assert err.value.code == "unavailable"


def test_anthropic_timeout_is_timeout():
    def handler(request):
        raise httpx2.ReadTimeout("slow")

    with pytest.raises(AiError) as err:
        _collect(_anthropic(handler))
    assert err.value.code == "timeout"


def _ollama(handler, retries=0):
    config = ProviderConfig(name="ollama", model="llama3", timeout_seconds=5, max_retries=retries)
    return OllamaProvider(
        config, base_url="http://127.0.0.1:11434", transport=httpx2.MockTransport(handler)
    )


def _ndjson(*chunks: dict) -> bytes:
    return "\n".join(json.dumps(chunk) for chunk in chunks).encode()


def test_ollama_streams_ndjson_and_reports_usage():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            content=_ndjson(
                {"message": {"content": "Hi "}},
                {"message": {"content": "there"}},
                {"done": True, "done_reason": "stop", "prompt_eval_count": 9, "eval_count": 2},
            ),
        )

    events = _collect(_ollama(handler))
    assert events == [
        TextDelta("Hi "),
        TextDelta("there"),
        Done(stop_reason="stop", input_tokens=9, output_tokens=2),
    ]
    assert seen["body"]["messages"][0] == {"role": "system", "content": "system text"}
    assert seen["body"]["options"] == {"num_predict": 1024}


def test_ollama_retries_a_5xx_before_any_output():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx2.Response(503)
        return httpx2.Response(200, content=_ndjson({"message": {"content": "ok"}}, {"done": True}))

    events = _collect(_ollama(handler, retries=1))
    assert len(calls) == 2
    assert events[0] == TextDelta("ok")


def test_ollama_never_replays_a_stream_that_already_produced_text():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx2.Response(200, content=_ndjson({"message": {"content": "partial"}}))

    with pytest.raises(AiError) as err:
        _collect(_ollama(handler, retries=3))
    assert err.value.code == "invalid_response"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx2.Response(400), "rejected"),
        (httpx2.Response(200, content=b"not json"), "invalid_response"),
        (httpx2.Response(200, content=_ndjson({"error": "model not found"})), "rejected"),
    ],
)
def test_ollama_failures_map_to_safe_codes(response, code):
    with pytest.raises(AiError) as err:
        _collect(_ollama(lambda request: response))
    assert err.value.code == code


@pytest.mark.parametrize(
    "url", ["http://example.com:11434", "http://10.0.0.5:11434", "file:///etc/passwd"]
)
def test_ollama_only_accepts_loopback_urls(url):
    with pytest.raises(ValueError, match="this machine"):
        validate_loopback_url(url)


def test_registry_is_empty_without_configuration():
    registry = build_registry(Settings(_env_file=None))
    assert registry.names == []
    with pytest.raises(AiError) as err:
        registry.get()
    assert err.value.code == "not_configured"


def test_registry_registers_configured_providers():
    settings = Settings(_env_file=None, anthropic_api_key="synthetic-key", ollama_model="llama3")
    registry = build_registry(settings)
    assert registry.names == ["anthropic", "ollama"]
    assert registry.get().config.name == "anthropic"
    assert registry.get("ollama").config.model == "llama3"
    with pytest.raises(AiError) as err:
        registry.get("gpt")
    assert err.value.code == "unknown_provider"


def test_registry_uses_the_configured_chat_model():
    settings = Settings(
        _env_file=None, anthropic_api_key="synthetic-key", GREENLOOP_CHAT_MODEL="claude-sonnet-5-5"
    )
    assert build_registry(settings).get().config.model == "claude-sonnet-5-5"


def test_registry_default_falls_back_to_not_configured_when_missing():
    registry = build_registry(
        Settings(_env_file=None, ollama_model="llama3", ai_default_provider="anthropic")
    )
    with pytest.raises(AiError) as err:
        registry.get()
    assert err.value.code == "not_configured"
    assert registry.get("ollama").config.name == "ollama"
