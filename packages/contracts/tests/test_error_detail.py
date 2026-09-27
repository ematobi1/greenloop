import pytest
from pydantic import ValidationError

from greenloop_contracts import ErrorDetail, ErrorReport, ExecutionResult

INTERNAL_NAMES = ("details", "stack", "stacktrace", "traceback", "internal", "exception", "cause")


def test_error_detail_has_exactly_code_message_and_fields():
    assert set(ErrorDetail.model_fields) == {"code", "message", "fields"}


@pytest.mark.parametrize("name", INTERNAL_NAMES)
def test_error_detail_has_no_internal_field(name):
    assert name not in ErrorDetail.model_fields
    with pytest.raises(ValidationError, match="extra"):
        ErrorDetail.model_validate({"code": "X", "message": "m", name: "secret"})


def test_execution_result_embeds_error_detail():
    annotation = ExecutionResult.model_fields["error"].annotation
    assert ErrorDetail in getattr(annotation, "__args__", (annotation,))


def test_error_report_user_safe_fields_match_error_detail_exactly():
    report_schema = ErrorReport.model_json_schema()
    detail_schema = ErrorDetail.model_json_schema()
    for field in ("code", "message", "fields"):
        assert report_schema["properties"][field] == detail_schema["properties"][field]


def test_error_report_detail_drops_internal_details(payloads):
    report = ErrorReport.model_validate(
        {
            **payloads["ErrorReport"],
            "fields": {"repo": "not found"},
            "details": {"stack": "Traceback ...", "upstream_status": 502},
        }
    )
    detail = report.detail()
    assert detail == ErrorDetail(
        code="TOOL_UNAVAILABLE", message="The tool did not respond.", fields={"repo": "not found"}
    )
    assert "Traceback" not in detail.model_dump_json()


@pytest.mark.parametrize(
    "code",
    ["NOT_IMPLEMENTED", "NOT_FOUND", "VALIDATION_FAILED", "INTERNAL_ERROR", "PERMISSION_DENIED"],
)
def test_accepts_api_style_codes(code):
    assert ErrorDetail(code=code, message="m").code == code


@pytest.mark.parametrize("bad", [{"message": ""}, {"message": "x" * 501}, {"fields": {"f": ""}}])
def test_rejects_empty_or_oversized_messages(bad):
    with pytest.raises(ValidationError):
        ErrorDetail.model_validate({"code": "X", "message": "m", **bad})
