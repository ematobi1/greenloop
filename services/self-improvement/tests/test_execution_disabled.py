import pytest
from pydantic import ValidationError

from app.config import SelfImprovementSettings
from app.isolation import IsolationUnavailableError, require_isolation
from app.proposal import Proposal
from app.runner import ExecutionDisabledError, GatesNotApprovedError, run

FLAG = "SELF_IMPROVEMENT_EXECUTION_ENABLED"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(FLAG, raising=False)


@pytest.fixture
def proposal() -> Proposal:
    return Proposal(
        proposal_id="prop-1",
        title="Tighten retry limit",
        rationale="Retries above 3 never succeeded in the last 30 days.",
        diff="--- a/x\n+++ b/x\n",
        created_by="self-improvement",
    )


def test_flag_defaults_to_disabled():
    assert SelfImprovementSettings(_env_file=None).self_improvement_execution_enabled is False


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_falsy_env_values_keep_it_disabled(monkeypatch, value):
    monkeypatch.setenv(FLAG, value)
    assert SelfImprovementSettings(_env_file=None).self_improvement_execution_enabled is False


def test_env_can_enable_the_flag(monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    assert SelfImprovementSettings(_env_file=None).self_improvement_execution_enabled is True


def test_garbage_flag_value_is_rejected(monkeypatch):
    monkeypatch.setenv(FLAG, "maybe")
    with pytest.raises(ValidationError):
        SelfImprovementSettings(_env_file=None)


def test_runner_refuses_by_default(proposal):
    with pytest.raises(ExecutionDisabledError):
        run(proposal, SelfImprovementSettings(_env_file=None))


def test_runner_still_refuses_when_flag_enabled(proposal):
    settings = SelfImprovementSettings(_env_file=None, self_improvement_execution_enabled=True)
    with pytest.raises(GatesNotApprovedError):
        run(proposal, settings)


def test_no_isolation_mechanism_is_available():
    with pytest.raises(IsolationUnavailableError):
        require_isolation()


def test_proposal_rejects_naive_timestamp():
    with pytest.raises(ValidationError):
        Proposal(
            proposal_id="p",
            title="t",
            rationale="r",
            diff="d",
            created_by="c",
            created_at="2026-09-27T12:00:00",
        )
