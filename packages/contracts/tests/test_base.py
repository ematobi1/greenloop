from datetime import UTC, datetime

import jsonschema
import pytest
from pydantic import ValidationError

from greenloop_contracts import CONTRACTS, Agent, Task, json_schemas

NAMES = sorted(CONTRACTS)


@pytest.mark.parametrize("name", NAMES)
def test_every_contract_accepts_its_valid_payload(name, payloads):
    CONTRACTS[name].model_validate(payloads[name])


@pytest.mark.parametrize("name", NAMES)
def test_every_contract_rejects_unknown_fields(name, payloads):
    with pytest.raises(ValidationError, match="extra"):
        CONTRACTS[name].model_validate({**payloads[name], "unexpected": 1})


@pytest.mark.parametrize("name", NAMES)
def test_every_contract_is_immutable(name, payloads):
    instance = CONTRACTS[name].model_validate(payloads[name])
    first_field = next(iter(type(instance).model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(instance, first_field, getattr(instance, first_field))


@pytest.mark.parametrize("name", NAMES)
def test_every_contract_round_trips_through_json(name, payloads):
    model = CONTRACTS[name]
    instance = model.model_validate(payloads[name])
    assert model.model_validate_json(instance.model_dump_json()) == instance


@pytest.mark.parametrize(
    "bad_id",
    ["", "-leading-dash", "has space", "semi;colon", "x" * 129, "slash/path"],
)
def test_identifier_rejects_malformed_values(bad_id, payloads):
    with pytest.raises(ValidationError):
        Task.model_validate({**payloads["Task"], "task_id": bad_id})


@pytest.mark.parametrize("good_id", ["a", "task-1", "github.create_issue", "project:x", "x" * 128])
def test_identifier_accepts_well_formed_values(good_id, payloads):
    assert Task.model_validate({**payloads["Task"], "task_id": good_id}).task_id == good_id


@pytest.mark.parametrize(
    "bad_id", ["Has Spaces", "UPPERCASE", "dots.not.allowed", "-lead", "x" * 101]
)
def test_agent_identifier_is_lowercase_hyphenated(bad_id, payloads):
    with pytest.raises(ValidationError):
        Agent.model_validate({**payloads["Agent"], "agent_id": bad_id})


@pytest.mark.parametrize("good_id", ["a", "software-engineer-1", "x" * 100])
def test_agent_identifier_accepts_well_formed_values(good_id, payloads):
    assert Agent.model_validate({**payloads["Agent"], "agent_id": good_id}).agent_id == good_id


class TestTimestamps:
    def test_naive_timestamp_is_rejected(self, payloads):
        with pytest.raises(ValidationError, match="timezone"):
            Task.model_validate({**payloads["Task"], "created_at": "2026-09-27T12:00:00"})

    @pytest.mark.parametrize("bad", ["not-a-timestamp", "2026-13-01T00:00:00Z", ""])
    def test_malformed_timestamp_is_rejected(self, payloads, bad):
        with pytest.raises(ValidationError):
            Task.model_validate({**payloads["Task"], "created_at": bad})

    def test_offsets_are_normalized_to_utc(self, payloads):
        task = Task.model_validate(
            {
                **payloads["Task"],
                "created_at": "2026-09-27T14:00:00+02:00",
                "updated_at": "2026-09-27T07:30:00-05:00",
            }
        )
        assert task.created_at == datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
        assert task.created_at.utcoffset().total_seconds() == 0
        assert task.updated_at.hour == 12

    def test_utc_serializes_with_z_and_keeps_fractional_seconds(self, payloads):
        task = Task.model_validate({**payloads["Task"], "updated_at": "2026-09-27T12:00:00.25Z"})
        dumped = task.model_dump(mode="json")
        assert dumped["created_at"] == "2026-09-27T12:00:00Z"
        assert dumped["updated_at"] == "2026-09-27T12:00:00.250000Z"

    def test_default_timestamps_are_utc(self, payloads):
        payload = {
            k: v for k, v in payloads["Task"].items() if k not in {"created_at", "updated_at"}
        }
        task = Task.model_validate(payload)
        assert task.created_at.tzinfo is UTC


class TestSchemaExport:
    @pytest.mark.parametrize("name", NAMES)
    def test_exported_schema_is_valid_draft_2020_12(self, name):
        jsonschema.Draft202012Validator.check_schema(json_schemas()[name]["schema"])

    @pytest.mark.parametrize("name", NAMES)
    def test_exported_schema_accepts_the_valid_payload(self, name, payloads):
        schema = json_schemas()[name]["schema"]
        jsonschema.Draft202012Validator(schema).validate(payloads[name])

    def test_no_two_schemas_share_a_title(self):
        titles = [entry["schema"]["title"] for entry in json_schemas().values()]
        assert len(titles) == len(set(titles))

    def test_changed_contracts_are_at_schema_version_2(self):
        versions = {name: model.schema_version for name, model in CONTRACTS.items()}
        assert versions == {
            "Agent": "2",
            "Task": "2",
            "Dispatch": "2",
            "ToolPermission": "1",
            "ToolGrant": "1",
            "MemoryRecord": "2",
            "Event": "2",
            "ExecutionResult": "2",
            "ErrorReport": "2",
            "AuditRecord": "2",
        }
