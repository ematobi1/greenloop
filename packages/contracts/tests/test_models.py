import pytest
from pydantic import ValidationError

from greenloop_contracts import (
    Agent,
    AgentStatus,
    AuditRecord,
    Dispatch,
    ErrorReport,
    Event,
    ExecutionResult,
    MemoryRecord,
    Task,
    TaskStatus,
    ToolPermission,
)


def _memory(payloads, **provenance):
    payload = payloads["MemoryRecord"]
    return {**payload, "provenance": {**payload["provenance"], **provenance}}


class TestAgent:
    def test_defaults_to_active(self, payloads):
        assert Agent.model_validate(payloads["Agent"]).status is AgentStatus.ACTIVE

    def test_rejects_blank_name(self, payloads):
        with pytest.raises(ValidationError):
            Agent.model_validate({**payloads["Agent"], "name": "   "})

    def test_rejects_duplicate_capabilities(self, payloads):
        with pytest.raises(ValidationError, match="unique"):
            Agent.model_validate({**payloads["Agent"], "capabilities": ["search", "search"]})

    def test_rejects_unknown_status(self, payloads):
        with pytest.raises(ValidationError):
            Agent.model_validate({**payloads["Agent"], "status": "paused"})


class TestTask:
    def test_defaults_to_pending(self, payloads):
        assert Task.model_validate(payloads["Task"]).status is TaskStatus.PENDING

    def test_rejects_self_parent(self, payloads):
        with pytest.raises(ValidationError, match="own parent"):
            Task.model_validate({**payloads["Task"], "parent_task_id": "task-1"})

    def test_rejects_self_dependency(self, payloads):
        with pytest.raises(ValidationError, match="depend on itself"):
            Task.model_validate({**payloads["Task"], "depends_on": ["task-1"]})

    def test_rejects_duplicate_dependencies(self, payloads):
        with pytest.raises(ValidationError, match="unique"):
            Task.model_validate({**payloads["Task"], "depends_on": ["task-0", "task-0"]})

    def test_rejects_title_over_limit(self, payloads):
        with pytest.raises(ValidationError):
            Task.model_validate({**payloads["Task"], "title": "x" * 201})


class TestDispatch:
    def test_accepts_nested_json_inputs(self, payloads):
        dispatch = Dispatch.model_validate(payloads["Dispatch"])
        assert dispatch.inputs["filters"] == {"recent": True}

    def test_rejects_attempt_above_max(self, payloads):
        with pytest.raises(ValidationError, match="max_attempts"):
            Dispatch.model_validate({**payloads["Dispatch"], "attempt": 4, "max_attempts": 3})

    def test_rejects_zero_attempt(self, payloads):
        with pytest.raises(ValidationError):
            Dispatch.model_validate({**payloads["Dispatch"], "attempt": 0})

    def test_rejects_non_json_input(self, payloads):
        with pytest.raises(ValidationError):
            Dispatch.model_validate({**payloads["Dispatch"], "inputs": {"fn": object()}})


class TestToolPermission:
    def test_write_is_consequential(self, payloads):
        assert ToolPermission.model_validate(payloads["ToolPermission"]).is_consequential

    def test_read_is_not_consequential(self, payloads):
        permission = ToolPermission.model_validate(
            {**payloads["ToolPermission"], "consequence": "read"}
        )
        assert not permission.is_consequential

    def test_rejects_unknown_consequence(self, payloads):
        with pytest.raises(ValidationError):
            ToolPermission.model_validate({**payloads["ToolPermission"], "consequence": "admin"})

    def test_requires_consequence(self, payloads):
        payload = {k: v for k, v in payloads["ToolPermission"].items() if k != "consequence"}
        with pytest.raises(ValidationError):
            ToolPermission.model_validate(payload)


class TestMemoryRecord:
    def test_supersede_with_target_is_valid(self, payloads):
        record = MemoryRecord.model_validate(
            _memory(payloads, operation="supersede", supersedes="mem-0")
        )
        assert record.provenance.supersedes == "mem-0"

    def test_delete_tombstone_is_valid(self, payloads):
        payload = {
            **_memory(payloads, operation="delete", supersedes="mem-0"),
            "content": "",
        }
        assert MemoryRecord.model_validate(payload).content == ""

    def test_create_cannot_supersede(self, payloads):
        with pytest.raises(ValidationError, match="create cannot supersede"):
            MemoryRecord.model_validate(_memory(payloads, supersedes="mem-0"))

    @pytest.mark.parametrize("operation", ["supersede", "correct", "delete"])
    def test_non_create_requires_target(self, payloads, operation):
        with pytest.raises(ValidationError, match="must name the record"):
            MemoryRecord.model_validate(_memory(payloads, operation=operation))

    def test_cannot_supersede_itself(self, payloads):
        with pytest.raises(ValidationError, match="supersede itself"):
            MemoryRecord.model_validate(_memory(payloads, operation="correct", supersedes="mem-1"))

    def test_delete_must_not_carry_content(self, payloads):
        with pytest.raises(ValidationError, match="tombstone"):
            MemoryRecord.model_validate(_memory(payloads, operation="delete", supersedes="mem-0"))

    def test_create_requires_content(self, payloads):
        with pytest.raises(ValidationError, match="content is required"):
            MemoryRecord.model_validate({**payloads["MemoryRecord"], "content": "  "})

    def test_rejects_content_over_limit(self, payloads):
        with pytest.raises(ValidationError):
            MemoryRecord.model_validate({**payloads["MemoryRecord"], "content": "x" * 20001})


class TestEvent:
    @pytest.mark.parametrize("event_type", ["task.created", "memory.record.superseded"])
    def test_accepts_dotted_types(self, payloads, event_type):
        assert Event.model_validate({**payloads["Event"], "event_type": event_type})

    @pytest.mark.parametrize("event_type", ["created", "Task.Created", "task.", "task..x"])
    def test_rejects_malformed_types(self, payloads, event_type):
        with pytest.raises(ValidationError):
            Event.model_validate({**payloads["Event"], "event_type": event_type})


class TestExecutionResult:
    def test_failed_with_error_report_is_valid(self, payloads):
        result = ExecutionResult.model_validate(
            {**payloads["ExecutionResult"], "status": "failed", "error_report_id": "err-1"}
        )
        assert result.error_report_id == "err-1"

    def test_failed_requires_error_report(self, payloads):
        with pytest.raises(ValidationError, match="error report"):
            ExecutionResult.model_validate({**payloads["ExecutionResult"], "status": "failed"})

    def test_succeeded_rejects_error_report(self, payloads):
        with pytest.raises(ValidationError, match="error report"):
            ExecutionResult.model_validate(
                {**payloads["ExecutionResult"], "error_report_id": "err-1"}
            )

    def test_rejects_finish_before_start(self, payloads):
        payload = payloads["ExecutionResult"]
        with pytest.raises(ValidationError, match="before started_at"):
            ExecutionResult.model_validate(
                {
                    **payload,
                    "started_at": payload["finished_at"],
                    "finished_at": payload["started_at"],
                }
            )


class TestErrorReport:
    def test_rejects_unknown_category(self, payloads):
        with pytest.raises(ValidationError):
            ErrorReport.model_validate({**payloads["ErrorReport"], "category": "oops"})

    def test_rejects_empty_message(self, payloads):
        with pytest.raises(ValidationError):
            ErrorReport.model_validate({**payloads["ErrorReport"], "message": ""})


class TestAuditRecord:
    def test_denied_without_approval_is_valid(self, payloads):
        payload = {
            k: v
            for k, v in payloads["AuditRecord"].items()
            if k not in {"approval_id", "operation_hash"}
        }
        assert AuditRecord.model_validate({**payload, "outcome": "denied"})

    def test_approval_requires_operation_hash(self, payloads):
        payload = {k: v for k, v in payloads["AuditRecord"].items() if k != "operation_hash"}
        with pytest.raises(ValidationError, match="operation hash"):
            AuditRecord.model_validate(payload)

    def test_approved_requires_approval_id(self, payloads):
        payload = {k: v for k, v in payloads["AuditRecord"].items() if k != "approval_id"}
        with pytest.raises(ValidationError, match="reference the approval"):
            AuditRecord.model_validate(payload)

    @pytest.mark.parametrize("bad_hash", ["A" * 64, "a" * 63, "g" * 64])
    def test_rejects_malformed_hash(self, payloads, bad_hash):
        with pytest.raises(ValidationError):
            AuditRecord.model_validate({**payloads["AuditRecord"], "operation_hash": bad_hash})
