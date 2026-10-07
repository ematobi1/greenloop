"""Checks docker-compose.yml gives each service only its own variables (ADR 0009 rule 18).

Run by scripts/tests/test-compose-secrets.ps1 and by CI. Prints each failure and
exits 1. Each service has an allowlist, so a new variable must be added here on
purpose; the database URLs must log in as the service's own role.
"""

import re
import sys

import yaml

ALLOWED = {
    "orchestrator": {
        "DATABASE_URL",
        "BROKER_URL",
        "BROKER_SERVICE_TOKEN",
        "ALLOWED_HOSTS",
        "CORS_ORIGINS",
        "ENVIRONMENT",
        "LOG_LEVEL",
        "ANTHROPIC_API_KEY",
        "GREENLOOP_CHAT_MODEL",
        "ANTHROPIC_EFFORT",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "ELEVENLABS_API_KEY",
        "AI_DEFAULT_PROVIDER",
        "AI_TIMEOUT_SECONDS",
        "AI_MAX_RETRIES",
        "AI_MAX_OUTPUT_TOKENS",
        "AI_CONTEXT_TOKEN_LIMIT",
        "AI_HISTORY_MESSAGE_LIMIT",
        "AI_MAX_MESSAGE_CHARS",
        "AI_MEMORY_RECORD_LIMIT",
        "EMBEDDING_PROVIDER",
        "EMBEDDING_BASE_URL",
        "EMBEDDING_MODEL",
    },
    "broker": {"BROKER_DATABASE_URL", "APPROVAL_TTL_SECONDS"},
    "web": {"ORCHESTRATOR_URL", "WEB_ORIGIN"},
}
ROLE_URLS = {
    "orchestrator": ("DATABASE_URL", "greenloop_orchestrator", "ORCHESTRATOR_DB_PASSWORD"),
    "broker": ("BROKER_DATABASE_URL", "greenloop_broker", "BROKER_DB_PASSWORD"),
}
FOREIGN_SECRETS = ("POSTGRES_PASSWORD", "ORCHESTRATOR_DB_PASSWORD", "BROKER_DB_PASSWORD")


def check(services: dict) -> list[str]:
    failures = []
    for name, allowed in ALLOWED.items():
        service = services[name]
        if "env_file" in service:
            failures.append(f"{name} must not use env_file")
        if "ports" in service and name == "broker":
            failures.append("broker must not publish a host port")
        environment = service.get("environment") or {}
        for variable in sorted(set(environment) - allowed):
            failures.append(f"{name} must not get {variable}")
        own_password = None
        if name in ROLE_URLS:
            url_name, role, own_password = ROLE_URLS[name]
            url = str(environment.get(url_name, ""))
            user = re.match(r"^[a-z+]+://([^:@/]+)[:@]", url)
            if user is None or user.group(1) != role:
                failures.append(f"{name} must connect as {role}")
        for value in map(str, environment.values()):
            for secret in FOREIGN_SECRETS:
                if secret != own_password and f"${{{secret}" in value:
                    failures.append(f"{name} must not reference {secret}")
    return failures


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as compose:
        problems = check(yaml.safe_load(compose)["services"])
    print("\n".join(problems))
    sys.exit(1 if problems else 0)
