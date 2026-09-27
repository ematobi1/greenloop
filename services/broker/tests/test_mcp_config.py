from pathlib import Path

import pytest
import yaml

SERVERS_YAML = Path(__file__).resolve().parents[3] / "mcp" / "servers.yaml"
EXPECTED = {"github", "filesystem", "fetch", "postgres-readonly", "google-workspace"}


@pytest.fixture(scope="module")
def servers() -> dict:
    return yaml.safe_load(SERVERS_YAML.read_text(encoding="utf-8"))["servers"]


def test_lists_the_five_planned_servers(servers):
    assert set(servers) == EXPECTED


def test_only_github_is_enabled(servers):
    assert [name for name, spec in servers.items() if spec["enabled"] is True] == ["github"]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_server_declares_required_fields(servers, name):
    spec = servers[name]
    assert isinstance(spec["enabled"], bool)
    assert spec["allowed_toolsets"]
    assert isinstance(spec["read_only"], bool)
    assert isinstance(spec["auth"]["env"], list)


def test_credentials_are_env_var_names_not_values(servers):
    for spec in servers.values():
        for name in spec["auth"]["env"]:
            assert name.isupper()
            assert name.replace("_", "").isalnum()
