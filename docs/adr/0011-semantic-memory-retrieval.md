# ADR 0011: Semantic memory retrieval with pgvector

- Status: Accepted; implemented on feature/phase2-rest
- Date: 2026-10-05

## Context

Chat retrieved memory by recency only (`app/memory/retrieval.py`), so an old but relevant record never reached the prompt once newer ones filled the budget. Phase 2 needs relevance ranking that stays principal-scoped, never returns superseded or deleted versions, and still reaches the prompt only through `context_builder.build_memory_context`.

## Decision

1. **pgvector in Postgres.** No new infrastructure. `scripts/db/bootstrap-roles.sql` creates the `vector` extension because that needs a superuser; migrations only check that it exists. The extension's objects stay owned by the superuser; the ownership transfer and the startup checks skip extension members and their array types.
2. **Embeddings live in their own table.** `memory_embeddings (record_id, model, embedding vector(768))`, keyed by record and model, with an HNSW cosine index. `memory_records` stays append-only: adding or backfilling an embedding never updates a memory row, and a tombstone needs no embedding change because retrieval only reads live heads.
3. **One provider abstraction.** `Embedder` with `OllamaEmbedder` (`/api/embed`, default `nomic-embed-text`, 768 dimensions) and a deterministic offline `FakeEmbedder` for tests and evals. `EMBEDDING_PROVIDER=none|ollama|fake`; `fake` is refused in prod. The Ollama URL must be loopback or exactly `host.docker.internal` (so the container can reach Ollama on the host); memory text never leaves the machine. The chat Ollama provider stays loopback-only.
4. **Embedding never blocks a write.** The memory API embeds a new create, correct or supersede in the same transaction. If no embedder is configured, or it fails, the record is stored without a vector and `python -m app.cli embed-memory` backfills later.
5. **Ranking.** Each chat turn embeds the user's message. Retrieval ranks live records (the principal's own, chain head, not a tombstone, not expired) that have a vector from the same model by cosine distance, then fills any remaining slots with the most recent live records, so unembedded records still appear. Without an embedder or on failure, retrieval is recency only, as before. Vectors from a different model are never compared.
6. **Only the context builder injects memory.** Retrieval returns `MemoryRecord`s; `build_turn_request` passes them to `build_memory_context`, which filters, sanitizes, redacts, bounds and escapes them as before.

## Consequences

- Switching models needs a backfill (`embed-memory`) before the new model ranks anything; until then recency fills in.
- The dev database needs `db-bootstrap.ps1` rerun once (to create the extension) before `alembic upgrade head`.
- The fake embedder is a bag of hashed words, good enough to test ranking plumbing, not to judge retrieval quality. Retrieval quality with the real model is measured by the paid evals.
