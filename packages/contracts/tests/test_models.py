import pytest
from pydantic import ValidationError

from greenloop_contracts import (
    MAX_TIMEOUT_MS,
    Agent,
    AgentDomain,
    AgentStatus,
    AuditRecord,
    Dispatch,
    ErrorReport,
    Event,
    MemoryCategory,
    MemoryConfidence,
    MemoryRecord,
    MemoryScope,
    Task,
    TaskStatus,
    ToolPermission,
)


def _memory(payloads, **provenance):
    payload = payloads["MemoryRecord"]
    return {**payload, "provenance": {**payload["provenance"], **provenance}}


class TestAgent:
    def test_defaults_to_registered(self, payloads):
        assert Agent.model_validate(payloads["Agent"]).status is AgentStatus.REGISTERED

    @pytest.mark.parametrize("domain", [d.value for d in AgentDomain])
    def test_accepts_every_domain(self, payloads, domain):
        assert Agent.model_validate({**payloads["Agent"], "domain": domain}).domain == domain

    @pytest.mark.parametrize(
        "broken",
        [
            {"domain": "made-up-domain"},
            {"agent_id": "Has Spaces"},
            {"agent_id": "UPPERCASE"},
            {"capabilities": []},
            {"status": "running"},
            {"version": ""},
            {"name": "   "},
            {"capabilities": ["search", "search"]},
        ],
    )
    def test_rejects_invalid_domain_id_capabilities_status_and_version(self, payloads, broken):
        with pytest.raises(ValidationError):
            Agent.model_validate({**payloads["Agent"], **broken})

    @pytest.mark.parametrize("field", ["agent_id", "name", "domain", "version", "capabilities"])
    def test_rejects_missing_required_fields(self, payloads, field):
        payload = {k: v for k, v in payloads["Agent"].items() if k != field}
        with pytest.raises(ValidationError):
            Agent.model_validate(payload)

    def test_updated_at_cannot_precede_created_at(self, payloads):
        with pytest.raises(ValidationError, match="updated_at"):
            Agent.model_validate({**payloads["Agent"], "updated_at": "2026-09-27T11:59:59Z"})


class TestTask:
    def test_defaults_to_pending(self, payloads):
        assert Task.model_validate(payloads["Task"]).status is TaskStatus.PENDING

    def test_accepts_a_full_record(self, payloads):
        task = Task.model_validate(
            {
                **payloads["Task"],
                "task_id": "t2",
                "status": "assigned",
                "parent_task_id": "t1",
                "depends_on": ["t1"],
                "assigned_agent_id": "research-agent",
            }
        )
        assert task.assigned_agent_id == "research-agent"

    def test_status_set_is_the_agreed_union(self):
        assert {s.value for s in TaskStatus} == {
            "pending",
            "assigned",
            "awaiting_approval",
            "running",
            "blocked",
            "succeeded",
            "failed",
            "cancelled",
        }

    @pytest.mark.parametrize("status", ["done", "PENDING", "", None, "in_progress", "completed"])
    def test_rejects_unknown_status_values(self, payloads, status):
        with pytest.raises(ValidationError):
            Task.model_validate({**payloads["Task"], "status": status})

    def test_null_parent_is_valid(self, payloads):
        assert (
            Task.model_validate({**payloads["Task"], "parent_task_id": None}).parent_task_id is None
        )

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

    def test_rejects_malformed_assigned_agent(self, payloads):
        with pytest.raises(ValidationError):
            Task.model_validate({**payloads["Task"], "assigned_agent_id": "Bad Agent"})

    def test_updated_at_cannot_precede_created_at(self, payloads):
        with pytest.raises(ValidationError, match="updated_at"):
            Task.model_validate({**payloads["Task"], "updated_at": "2026-09-27T11:00:00Z"})


class TestDispatch:
    def test_accepts_an_open_ended_input_object(self, payloads):
        dispatch = Dispatch.model_validate(payloads["Dispatch"])
        assert dispatch.inputs["filters"] == {"recent": True}

    @pytest.mark.parametrize("timeout", [1, 5000, MAX_TIMEOUT_MS])
    def test_accepts_timeout_within_bounds(self, payloads, timeout):
        assert (
            Dispatch.model_validate({**payloads["Dispatch"], "timeout_ms": timeout}).timeout_ms
            == timeout
        )

    @pytest.mark.parametrize("timeout", [0, -1, MAX_TIMEOUT_MS + 1, 1.5, "5000", 5000.0, True])
    def test_timeout_must_be_a_positive_bounded_integer(self, payloads, timeout):
        with pytest.raises(ValidationError):
            Dispatch.model_validate({**payloads["Dispatch"], "timeout_ms": timeout})

    @pytest.mark.parametrize("bad_input", ["a string", 5, ["array"], None])
    def test_rejects_a_non_object_input(self, payloads, bad_input):
        with pytest.raises(ValidationError):
            Dispatch.model_validate({**payloads["Dispatch"], "inputs": bad_input})

    def test_rejects_non_json_input_value(self, payloads):
        with pytest.raises(ValidationError):
            Dispatch.model_validate({**payloads["Dispatch"], "inputs": {"fn": object()}})

    def test_rejects_attempt_above_max(self, payloads):
        with pytest.raises(ValidationError, match="max_attempts"):
            Dispatch.model_validate({**payloads["Dispatch"], "attempt": 4, "max_attempts": 3})

    def test_rejects_zero_attempt(self, payloads):
        with pytest.raises(ValidationError):
            Dispatch.model_validate({**payloads["Dispatch"], "attempt": 0})


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
    @pytest.mark.parametrize("category", [c.value for c in MemoryCategory])
    @pytest.mark.parametrize("confidence", [c.value for c in MemoryConfidence])
    def test_accepts_each_category_and_confidence_combination(self, payloads, category, confidence):
        record = MemoryRecord.model_validate(
            {**payloads["MemoryRecord"], "category": category, "confidence": confidence}
        )
        assert (record.category, record.confidence) == (category, confidence)

    def test_confidence_defaults_to_unverified(self, payloads):
        record = MemoryRecord.model_validate(payloads["MemoryRecord"])
        assert record.confidence is MemoryConfidence.UNVERIFIED

    @pytest.mark.parametrize("confidence", ["true", "false", "maybe", "1.0"])
    def test_rejects_non_enum_confidence_values(self, payloads, confidence):
        with pytest.raises(ValidationError):
            MemoryRecord.model_validate({**payloads["MemoryRecord"], "confidence": confidence})

    def test_category_is_required(self, payloads):
        payload = {k: v for k, v in payloads["MemoryRecord"].items() if k != "category"}
        with pytest.raises(ValidationError):
            MemoryRecord.model_validate(payload)

    def test_scope_is_the_private_shared_enum(self, payloads):
        assert {s.value for s in MemoryScope} == {"private", "shared"}
        assert (
            MemoryRecord.model_validate({**payloads["MemoryRecord"], "scope": "shared"}).scope
            is MemoryScope.SHARED
        )

    @pytest.mark.parametrize("scope", ["personal", "project:x", "PRIVATE", ""])
    def test_rejects_scopes_outside_the_enum(self, payloads, scope):
        with pytest.raises(ValidationError):
            MemoryRecord.model_validate({**payloads["MemoryRecord"], "scope": scope})

    def test_accepts_related_task_and_expiry(self, payloads):
        record = MemoryRecord.model_validate(
            {
                **payloads["MemoryRecord"],
                "related_task_id": "task-1",
                "expires_at": "2027-01-01T00:00:00Z",
            }
        )
        assert record.related_task_id == "task-1"
        assert record.expires_at.year == 2027

    @pytest.mark.parametrize("field", ["related_task_id", "expires_at"])
    def test_optional_fields_accept_explicit_null(self, payloads, field):
        assert (
            getattr(MemoryRecord.model_validate({**payloads["MemoryRecord"], field: None}), field)
            is None
        )

    def test_rejects_a_malformed_expiry(self, payloads):
        with pytest.raises(ValidationError):
            MemoryRecord.model_validate(
                {**payloads["MemoryRecord"], "expires_at": "not-a-timestamp"}
            )

    def test_expiry_must_be_after_creation(self, payloads):
        with pytest.raises(ValidationError, match="expires_at"):
            MemoryRecord.model_validate(
                {**payloads["MemoryRecord"], "expires_at": "2026-09-27T12:00:00Z"}
            )

    def test_records_have_no_updated_at_or_deleted_at(self):
        assert "updated_at" not in MemoryRecord.model_fields, "records are immutable"
        assert "deleted_at" not in MemoryRecord.model_fields, "deletes are tombstone records"

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
    @pytest.mark.parametrize(
        "event_type",
        [
            "task.created",
            "memory.record.superseded",
            "task.status_changed",
            "memory.record_written.v2",
        ],
    )
    def test_accepts_dotted_lowercase_types(self, payloads, event_type):
        assert Event.model_validate({**payloads["Event"], "event_type": event_type})

    @pytest.mark.parametrize(
        "event_type",
        ["created", "Task.Created", "TaskChanged", "task_changed", "task.", ".task", "task..x", ""],
    )
    def test_rejects_malformed_types(self, payloads, event_type):
        with pytest.raises(ValidationError):
            Event.model_validate({**payloads["Event"], "event_type": event_type})

    def test_accepts_task_and_agent_context(self, payloads):
        event = Event.model_validate(
            {**payloads["Event"], "task_id": "task-1", "agent_id": "research-agent"}
        )
        assert (event.task_id, event.agent_id) == ("task-1", "research-agent")

    def test_task_and_agent_default_to_none(self, payloads):
        event = Event.model_validate(payloads["Event"])
        assert event.task_id is None and event.agent_id is None


class TestErrorReport:
    def test_accepts_code_fields_and_agent(self, payloads):
        report = ErrorReport.model_validate(
            {
                **payloads["ErrorReport"],
                "fields": {"agent_id": "no such agent"},
                "agent_id": "research-agent",
            }
        )
        assert report.fields == {"agent_id": "no such agent"}

    @pytest.mark.parametrize(
        "code",
        [
            "lowercase",
            "Mixed_Case",
            "HAS-DASH",
            "HAS SPACE",
            "",
            "_",
            "_LEADING_UNDERSCORE",
            "429_FIRST_DIGIT",
            "X" * 65,
        ],
    )
    def test_rejects_codes_not_matching_the_shared_uppercase_pattern(self, payloads, code):
        with pytest.raises(ValidationError):
            ErrorReport.model_validate({**payloads["ErrorReport"], "code": code})

    @pytest.mark.parametrize(
        "code",
        [
            "HTTP_429",
            "X",
            "TOOL_UNAVAILABLE",
            "TRAILING_",
            "NOT_IMPLEMENTED",
            "NOT_FOUND",
            "HTTP_ERROR",
            "VALIDATION_FAILED",
            "INTERNAL_ERROR",
        ],
    )
    def test_accepts_uppercase_codes_with_digits_after_the_first_letter(self, payloads, code):
        assert ErrorReport.model_validate({**payloads["ErrorReport"], "code": code}).code == code

    def test_code_is_required(self, payloads):
        payload = {k: v for k, v in payloads["ErrorReport"].items() if k != "code"}
        with pytest.raises(ValidationError):
            ErrorReport.model_validate(payload)

    def test_rejects_unknown_category(self, payloads):
        with pytest.raises(ValidationError):
            ErrorReport.model_validate({**payloads["ErrorReport"], "category": "oops"})

    def test_rejects_empty_message(self, payloads):
        with pytest.raises(ValidationError):
            ErrorReport.model_validate({**payloads["ErrorReport"], "message": ""})


class TestAuditRecord:
    def test_accepts_the_fields_the_old_audit_events_table_wrote(self, payloads):
        record = AuditRecord.model_validate(
            {
                "audit_id": "448ef21331cf42e19795ab36495142c6",
                "principal_id": "user-1",
                "actor": "local-token",
                "action": "broker.read-status.rejected",
                "resource_type": "broker_operation",
                "resource_id": None,
                "outcome": "denied",
                "correlation_id": "6e75c595e20a4fd49497324e3a2a4551",
                "occurred_at": "2026-09-25T12:00:00Z",
            }
        )
        assert record.resource_type == "broker_operation"

    def test_resource_id_is_optional(self, payloads):
        payload = {k: v for k, v in payloads["AuditRecord"].items() if k != "resource_id"}
        assert AuditRecord.model_validate(payload).resource_id is None

    def test_resource_type_is_required(self, payloads):
        payload = {k: v for k, v in payloads["AuditRecord"].items() if k != "resource_type"}
        with pytest.raises(ValidationError):
            AuditRecord.model_validate(payload)

    def test_rejects_empty_resource_id(self, payloads):
        with pytest.raises(ValidationError):
            AuditRecord.model_validate({**payloads["AuditRecord"], "resource_id": ""})

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


class TestAgentModelAccess:
    def test_defaults_to_no_model_access(self, payloads):
        assert Agent.model_validate(payloads["Agent"]).model_access is False

    def test_model_access_can_be_declared(self, payloads):
        agent = Agent.model_validate({**payloads["Agent"], "model_access": True})
        assert agent.model_access is True

    @pytest.mark.parametrize("value", ["true", "yes", 1, None])
    def test_model_access_is_a_strict_boolean(self, payloads, value):
        with pytest.raises(ValidationError):
            Agent.model_validate({**payloads["Agent"], "model_access": value})

    def test_agent_schema_is_version_3(self):
        assert Agent.schema_version == "3"


class TestToolPermissionArguments:
    @pytest.mark.parametrize(
        "value", [float("nan"), float("inf"), -float("inf"), [1, float("nan")]]
    )
    def test_non_finite_numbers_are_refused(self, payloads, value):
        with pytest.raises(ValidationError, match="strict JSON"):
            ToolPermission.model_validate({**payloads["ToolPermission"], "arguments": {"x": value}})

    def test_arguments_are_capped_in_utf8_bytes(self, payloads):
        from greenloop_contracts.tool_permission import MAX_ARGUMENT_BYTES

        fits = {"t": "é" * (MAX_ARGUMENT_BYTES // 2 - 10)}
        assert ToolPermission.model_validate({**payloads["ToolPermission"], "arguments": fits})
        with pytest.raises(ValidationError, match="at most"):
            ToolPermission.model_validate(
                {**payloads["ToolPermission"], "arguments": {"t": "x" * MAX_ARGUMENT_BYTES}}
            )

    def test_an_integer_too_long_to_print_is_refused_with_the_right_reason(self, payloads):
        with pytest.raises(ValidationError, match="integer over 4300 digits"):
            ToolPermission.model_validate(
                {**payloads["ToolPermission"], "arguments": {"n": 10**5000}}
            )
