# Build from the repository root:
#   docker build -f services/broker/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 greenloop
WORKDIR /srv

COPY packages/contracts /tmp/contracts
COPY services/broker/pyproject.toml /tmp/broker/pyproject.toml
RUN pip install /tmp/contracts /tmp/broker && rm -rf /tmp/contracts /tmp/broker

COPY services/broker/policies ./policies
COPY services/broker/app ./app
COPY mcp/servers.yaml ./mcp/servers.yaml

USER greenloop
EXPOSE 8100
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
