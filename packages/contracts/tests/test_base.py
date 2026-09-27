from datetime import datetime

import pytest
from pydantic import ValidationError

from greenloop_contracts import CONTRACTS, Agent, Task

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
        Agent.model_validate({**payloads["Agent"], "agent_id": bad_id})


@pytest.mark.parametrize("good_id", ["a", "task-1", "github.create_issue", "project:x", "x" * 128])
def test_identifier_accepts_well_formed_values(good_id, payloads):
    assert Agent.model_validate({**payloads["Agent"], "agent_id": good_id}).agent_id == good_id


def test_naive_timestamp_is_rejected(payloads):
    with pytest.raises(ValidationError, match="timezone"):
        Task.model_validate({**payloads["Task"], "created_at": "2026-09-27T12:00:00"})


def test_default_timestamp_is_timezone_aware(payloads):
    payload = {k: v for k, v in payloads["Task"].items() if k != "created_at"}
    created_at = Task.model_validate(payload).created_at
    assert isinstance(created_at, datetime)
    assert created_at.utcoffset() is not None
