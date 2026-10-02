import pytest
from pydantic import ValidationError

from greenloop_contracts import (
    CONTRACTS,
    Task,
    UnknownContractError,
    get_contract,
    json_schemas,
    parse,
)

EXPECTED = {
    "Agent",
    "Task",
    "Dispatch",
    "ToolPermission",
    "ToolGrant",
    "Approval",
    "ApprovalActor",
    "ApprovalCreateRequest",
    "ApprovalDecisionRequest",
    "MemoryRecord",
    "Event",
    "ExecutionResult",
    "ErrorReport",
    "AuditRecord",
}


def test_registry_holds_exactly_the_fourteen_contracts():
    assert set(CONTRACTS) == EXPECTED


def test_registry_is_read_only():
    with pytest.raises(TypeError):
        CONTRACTS["Rogue"] = Task  # type: ignore[index]


def test_get_contract_returns_model():
    assert get_contract("Task") is Task


def test_get_contract_rejects_unknown_name():
    with pytest.raises(UnknownContractError):
        get_contract("Nope")


def test_parse_validates_payload(payloads):
    assert isinstance(parse("Task", payloads["Task"]), Task)


def test_parse_raises_on_invalid_payload(payloads):
    with pytest.raises(ValidationError):
        parse("Task", {**payloads["Task"], "task_id": ""})


def test_json_schemas_cover_every_contract_with_version():
    schemas = json_schemas()
    assert set(schemas) == EXPECTED
    for name, entry in schemas.items():
        assert entry["version"] == CONTRACTS[name].schema_version
        assert entry["schema"]["type"] == "object"
        assert entry["schema"]["additionalProperties"] is False
