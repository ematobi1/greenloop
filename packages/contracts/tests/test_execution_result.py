import pytest
from pydantic import ValidationError

from greenloop_contracts import DENIAL_CODES, ExecutionResult, ExecutionStatus

OUTPUT = {"summary": "done"}
FAILURE = {"code": "TOOL_UNAVAILABLE", "message": "The tool could not be reached."}
DENIAL = {"code": "PERMISSION_DENIED", "message": "This action is not allowed."}


def result(payloads, **overrides):
    base = {k: v for k, v in payloads["ExecutionResult"].items() if k not in {"output", "status"}}
    return ExecutionResult.model_validate({**base, **overrides})


def test_status_set_is_the_five_agreed_values():
    assert {s.value for s in ExecutionStatus} == {
        "succeeded",
        "partial",
        "failed",
        "denied",
        "cancelled",
    }


class TestSucceeded:
    def test_output_without_error_is_valid(self, payloads):
        assert result(payloads, status="succeeded", output=OUTPUT).output == OUTPUT

    def test_empty_output_object_counts_as_output(self, payloads):
        assert result(payloads, status="succeeded", output={}).output == {}

    def test_requires_output(self, payloads):
        with pytest.raises(ValidationError, match="requires output"):
            result(payloads, status="succeeded")

    def test_forbids_error(self, payloads):
        with pytest.raises(ValidationError, match="cannot carry an error"):
            result(payloads, status="succeeded", output=OUTPUT, error=FAILURE)

    def test_forbids_error_report_link(self, payloads):
        with pytest.raises(ValidationError, match="cannot carry an error"):
            result(payloads, status="succeeded", output=OUTPUT, error_report_id="err-1")


class TestPartial:
    @pytest.mark.parametrize(
        "fields",
        [{}, {"output": OUTPUT}, {"error": FAILURE}, {"output": OUTPUT, "error": FAILURE}],
    )
    def test_neither_output_nor_error_is_required(self, payloads, fields):
        assert result(payloads, status="partial", **fields).status is ExecutionStatus.PARTIAL


class TestFailed:
    def test_error_without_output_is_valid(self, payloads):
        failed = result(payloads, status="failed", error=FAILURE, error_report_id="err-1")
        assert failed.error.code == "TOOL_UNAVAILABLE"

    def test_requires_error(self, payloads):
        with pytest.raises(ValidationError, match="requires an error"):
            result(payloads, status="failed")

    def test_forbids_output(self, payloads):
        with pytest.raises(ValidationError, match="cannot carry output"):
            result(payloads, status="failed", error=FAILURE, output={"partial": True})


class TestDenied:
    @pytest.mark.parametrize("code", sorted(DENIAL_CODES))
    def test_error_with_a_denial_code_is_valid(self, payloads, code):
        denied = result(payloads, status="denied", error={**DENIAL, "code": code})
        assert denied.error.code == code

    def test_requires_error(self, payloads):
        with pytest.raises(ValidationError, match="requires an error"):
            result(payloads, status="denied")

    def test_requires_a_denial_code(self, payloads):
        with pytest.raises(ValidationError, match="denial code"):
            result(payloads, status="denied", error=FAILURE)

    def test_forbids_output(self, payloads):
        with pytest.raises(ValidationError, match="cannot carry output"):
            result(payloads, status="denied", error=DENIAL, output=OUTPUT)

    def test_denial_codes_are_valid_error_codes(self):
        assert all(code.isupper() and " " not in code and "-" not in code for code in DENIAL_CODES)


class TestCancelled:
    @pytest.mark.parametrize("fields", [{}, {"output": OUTPUT}, {"error": FAILURE}])
    def test_neither_output_nor_error_is_required(self, payloads, fields):
        assert result(payloads, status="cancelled", **fields).status is ExecutionStatus.CANCELLED


def test_rejects_finish_before_start(payloads):
    with pytest.raises(ValidationError, match="before started_at"):
        result(
            payloads,
            status="succeeded",
            output=OUTPUT,
            started_at="2026-09-27T12:00:05Z",
            finished_at="2026-09-27T12:00:00Z",
        )


def test_agent_id_is_optional_for_broker_initiated_calls(payloads):
    assert result(payloads, status="succeeded", output=OUTPUT, agent_id=None).agent_id is None


def test_embedded_error_rejects_internal_fields(payloads):
    with pytest.raises(ValidationError, match="extra"):
        result(payloads, status="failed", error={**FAILURE, "stack": "Traceback ..."})
