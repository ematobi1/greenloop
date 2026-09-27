"""Embedding interface for memory retrieval. The vendor sits behind this Protocol."""

from typing import Protocol


class Embedder(Protocol):
    dimensions: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


# TODO(phase-2): choose an embedding provider and fix the pgvector column dimension to match.
