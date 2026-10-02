"""Used by test-compose-secrets.ps1. Exits 1 and prints each failure."""

import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as compose:
    services = yaml.safe_load(compose)["services"]
failures = []


def env_text(name):
    return " ".join(f"{k}={v}" for k, v in (services[name].get("environment") or {}).items())


for name in ("orchestrator", "broker"):
    if "env_file" in services[name]:
        failures.append(f"{name} must not use env_file")
orchestrator, broker = env_text("orchestrator"), env_text("broker")
for secret in ("BROKER_DB_PASSWORD", "POSTGRES_PASSWORD", "BROKER_DATABASE_URL"):
    if secret in orchestrator:
        failures.append(f"orchestrator must not get {secret}")
for secret in (
    "ORCHESTRATOR_DB_PASSWORD",
    "POSTGRES_PASSWORD",
    "BROKER_SERVICE_TOKEN",
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
):
    if secret in broker:
        failures.append(f"broker must not get {secret}")
if "ports" in services["broker"]:
    failures.append("broker must not publish a host port")
if "greenloop_orchestrator:" not in orchestrator or "greenloop_broker:" not in broker:
    failures.append("each service must connect as its own role")
print("\n".join(failures))
sys.exit(1 if failures else 0)
