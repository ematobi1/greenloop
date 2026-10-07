"""Embedding providers: the fake is deterministic and roughly semantic; the Ollama client
only talks to this machine and rejects any reply that isn't a well-formed vector list."""

import asyncio
import json
import math

import httpx2
import pytest

from app.core.config import Settings
from app.db.models import EMBEDDING_DIMENSIONS
from app.memory.embeddings import (
    EmbeddingError,
    FakeEmbedder,
    OllamaEmbedder,
    build_embedder,
    validate_embedding_url,
)


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fake_vectors_are_deterministic_unit_vectors():
    first, again = (FakeEmbedder.vector("My dog is called Rex") for _ in range(2))
    assert first == again
    assert len(first) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0)


def test_fake_vectors_rank_shared_words_closer():
    query = FakeEmbedder.vector("what is my dog called")
    near = FakeEmbedder.vector("my dog is called Rex")
    far = FakeEmbedder.vector("quarterly tax filing deadline")
    assert _cosine(query, near) > _cosine(query, far)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434",
        "http://localhost:11434/",
        "http://[::1]:11434",
        "http://host.docker.internal:11434",
    ],
)
def test_local_embedding_urls_are_accepted(url):
    assert not validate_embedding_url(url).endswith("/")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:11434",
        "http://10.0.0.5:11434",
        "file:///etc/passwd",
        "http://host.docker.internal.evil.com",
    ],
)
def test_remote_embedding_urls_are_refused(url):
    with pytest.raises(ValueError, match="this machine"):
        validate_embedding_url(url)


def _ollama(handler) -> OllamaEmbedder:
    return OllamaEmbedder(
        "http://127.0.0.1:11434", "nomic-embed-text", transport=httpx2.MockTransport(handler)
    )


def test_ollama_embed_sends_the_model_and_normalizes_vectors():
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx2.Response(
            200, json={"embeddings": [[2.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)]}
        )

    [vector] = asyncio.run(_ollama(handler).embed(["hello"]))
    assert seen == {"path": "/api/embed", "body": {"model": "nomic-embed-text", "input": ["hello"]}}
    assert vector[0] == 1.0


@pytest.mark.parametrize(
    "reply",
    [
        httpx2.Response(500),
        httpx2.Response(200, text="not json"),
        httpx2.Response(200, json={"embeddings": [[0.1, 0.2]]}),
        httpx2.Response(200, json={"embeddings": []}),
        httpx2.Response(200, json={"embeddings": [["x"] * EMBEDDING_DIMENSIONS]}),
        httpx2.Response(200, json={"other": 1}),
    ],
)
def test_ollama_rejects_bad_replies(reply):
    with pytest.raises(EmbeddingError):
        asyncio.run(_ollama(lambda request: reply).embed(["hello"]))


def test_ollama_connection_failure_is_an_embedding_error():
    def handler(request):
        raise httpx2.ConnectError("refused")

    with pytest.raises(EmbeddingError):
        asyncio.run(_ollama(handler).embed(["hello"]))


def test_provider_selection_and_prod_guard():
    assert build_embedder(Settings(_env_file=None)) is None
    assert isinstance(
        build_embedder(Settings(_env_file=None, embedding_provider="fake")), FakeEmbedder
    )
    ollama = build_embedder(
        Settings(
            _env_file=None,
            embedding_provider="ollama",
            embedding_base_url="http://host.docker.internal:11434",
        )
    )
    assert isinstance(ollama, OllamaEmbedder)
    assert ollama.model == "nomic-embed-text"
    with pytest.raises(ValueError, match="tests only"):
        Settings(_env_file=None, environment="prod", embedding_provider="fake")
