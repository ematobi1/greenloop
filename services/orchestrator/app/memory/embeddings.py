"""Embedding providers for memory retrieval. The vendor sits behind the Embedder Protocol.

Every vector has EMBEDDING_DIMENSIONS entries and is stored per (record, model), so
switching models never compares vectors from two different models.

- OllamaEmbedder calls a local Ollama (`/api/embed`, default nomic-embed-text). Its URL
  must be loopback or host.docker.internal: memory text never leaves the machine.
- FakeEmbedder is deterministic and offline, for tests and offline evals. Texts that
  share words land close together, so ranking behaves like a (crude) semantic model.

Failures raise EmbeddingError. Callers treat that as "no embedding": the record is
still stored, and retrieval falls back to recency (ADR 0011).
"""

import hashlib
import math
import re
from typing import Protocol
from urllib.parse import urlsplit

import httpx2

from app.core.config import Settings
from app.db.models import EMBEDDING_DIMENSIONS

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
MAX_TEXT_CHARS = 8000
_WORD = re.compile(r"\w+", re.UNICODE)


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class FakeEmbedder:
    model = "fake-bag-of-words-v1"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(text) for text in texts]

    @staticmethod
    def vector(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for word in _WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        return _normalize(vector)


def validate_embedding_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or parts.hostname not in ALLOWED_HOSTS:
        raise ValueError(
            "the embedding URL must be this machine (127.0.0.1, localhost, ::1)"
            " or host.docker.internal"
        )
    return base_url.rstrip("/")


class OllamaEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._base_url = validate_embedding_url(base_url)
        self._timeout = httpx2.Timeout(connect=5.0, read=timeout_seconds, write=10.0, pool=5.0)
        self._transport = transport

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {"model": self.model, "input": [text[:MAX_TEXT_CHARS] for text in texts]}
        try:
            async with httpx2.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post("/api/embed", json=payload)
        except httpx2.HTTPError as err:
            raise EmbeddingError("embedding service unavailable") from err
        if response.status_code != 200:
            raise EmbeddingError(f"embedding service returned {response.status_code}")
        try:
            vectors = response.json()["embeddings"]
        except (ValueError, KeyError, TypeError) as err:
            raise EmbeddingError("embedding service sent an invalid reply") from err
        if (
            not isinstance(vectors, list)
            or len(vectors) != len(texts)
            or any(
                not isinstance(vector, list)
                or len(vector) != EMBEDDING_DIMENSIONS
                or not all(
                    isinstance(value, int | float) and math.isfinite(value) for value in vector
                )
                for vector in vectors
            )
        ):
            raise EmbeddingError("embedding service sent vectors of the wrong shape")
        return [_normalize([float(value) for value in vector]) for vector in vectors]


def build_embedder(settings: Settings) -> Embedder | None:
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings.resolved_embedding_base_url, settings.embedding_model)
    if settings.embedding_provider == "fake":
        return FakeEmbedder()
    return None
