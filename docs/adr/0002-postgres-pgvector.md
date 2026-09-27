# ADR 0002: Postgres with pgvector for memory, audit and workflow state

- Status: Accepted
- Date: 2026-09-27

## Context

Memory needs semantic retrieval, provenance chains, strict principal scoping and transactional writes. Approvals need an atomic consume. Audit needs append-only storage. Workflows need a durable queue.

## Decision

Use PostgreSQL 16 with the pgvector extension as the single datastore, accessed through SQLAlchemy 2 with Alembic migrations (`services/orchestrator/app/db`). Locally it runs as `pgvector/pgvector:pg16` in Docker Compose; in production on RDS.

## Consequences

- One system to operate, back up and secure. Relational integrity and vector search live together, so a retrieval query can filter by principal and scope in the same statement.
- Approval consume is one `UPDATE ... WHERE consumed_at IS NULL RETURNING` statement; the job queue uses `SELECT ... FOR UPDATE SKIP LOCKED`.
- Vector search scale is bounded by Postgres. If memory grows past what pgvector indexes serve well, revisit with a dedicated vector store behind the retrieval interface.
- The embedding dimension is fixed per column; choosing the embedding provider (phase 2) sets it.
