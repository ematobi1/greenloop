# Build from the repository root:
#   docker build -f services/orchestrator/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 greenloop
WORKDIR /srv

COPY packages/contracts /tmp/contracts
COPY services/orchestrator/pyproject.toml /tmp/orchestrator/pyproject.toml
RUN pip install /tmp/contracts /tmp/orchestrator && rm -rf /tmp/contracts /tmp/orchestrator

COPY services/orchestrator/alembic.ini ./
COPY services/orchestrator/app ./app

USER greenloop
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
