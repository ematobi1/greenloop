from typing import Any

import pytest

T0 = "2026-09-27T12:00:00Z"
T1 = "2026-09-27T12:00:05Z"
HASH = "a" * 64


def valid_payloads() -> dict[str, dict[str, Any]]:
    return {
        "Agent": {
            "agent_id": "research-agent",
            "name": "Research agent",
            "capabilities": ["search", "summarize"],
            "allowed_tools": ["fetch"],
        },
        "Task": {
            "task_id": "task-1",
            "principal_id": "user-1",
            "title": "Summarize the roadmap",
            "depends_on": ["task-0"],
            "created_at": T0,
        },
        "Dispatch": {
            "dispatch_id": "dispatch-1",
            "task_id": "task-1",
            "agent_id": "research-agent",
            "principal_id": "user-1",
            "correlation_id": "corr-1",
            "inputs": {"query": "roadmap", "limit": 5, "filters": {"recent": True}},
            "dispatched_at": T0,
        },
        "ToolPermission": {
            "principal_id": "user-1",
            "agent_id": "coding-agent",
            "tool": "github",
            "operation": "create_issue",
            "arguments": {"repo": "greenloop", "title": "Bug"},
            "consequence": "write",
        },
        "MemoryRecord": {
            "record_id": "mem-1",
            "principal_id": "user-1",
            "scope": "personal",
            "content": "Prefers morning summaries.",
            "tags": ["preference"],
            "provenance": {"source": "user", "created_by": "user-1"},
            "created_at": T0,
        },
        "Event": {
            "event_id": "evt-1",
            "event_type": "task.created",
            "source": "orchestrator",
            "correlation_id": "corr-1",
            "payload": {"task_id": "task-1"},
            "occurred_at": T0,
        },
        "ExecutionResult": {
            "result_id": "res-1",
            "task_id": "task-1",
            "status": "succeeded",
            "output": {"summary": "done"},
            "started_at": T0,
            "finished_at": T1,
        },
        "ErrorReport": {
            "error_id": "err-1",
            "correlation_id": "corr-1",
            "category": "tool_failure",
            "severity": "medium",
            "message": "The tool did not respond.",
            "correction_action": "retry",
            "occurred_at": T0,
        },
        "AuditRecord": {
            "audit_id": "audit-1",
            "principal_id": "user-1",
            "actor": "broker",
            "action": "github.create_issue",
            "resource": "repo:greenloop",
            "outcome": "approved",
            "correlation_id": "corr-1",
            "operation_hash": HASH,
            "approval_id": "appr-1",
            "occurred_at": T0,
        },
    }


@pytest.fixture
def payloads() -> dict[str, dict[str, Any]]:
    return valid_payloads()
