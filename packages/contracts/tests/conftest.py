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
            "domain": "research",
            "version": "0.1.0",
            "capabilities": ["search", "summarize"],
            "allowed_tools": ["fetch"],
            "created_at": T0,
            "updated_at": T0,
        },
        "Task": {
            "task_id": "task-1",
            "principal_id": "user-1",
            "title": "Summarize the roadmap",
            "depends_on": ["task-0"],
            "created_at": T0,
            "updated_at": T0,
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
        "ToolGrant": {
            "grant_id": "grant-1",
            "principal_id": "user-1",
            "agent_id": "coding-agent",
            "tool": "github",
            "actions": ["create_issue", "add_issue_comment"],
            "granted_by": "owner",
            "granted_at": T0,
            "expires_at": None,
        },
        "MemoryRecord": {
            "record_id": "mem-1",
            "principal_id": "user-1",
            "scope": "private",
            "category": "user_context",
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
            "agent_id": "research-agent",
            "status": "succeeded",
            "output": {"summary": "done"},
            "started_at": T0,
            "finished_at": T1,
        },
        "ErrorReport": {
            "error_id": "err-1",
            "correlation_id": "corr-1",
            "code": "TOOL_UNAVAILABLE",
            "message": "The tool did not respond.",
            "category": "tool_failure",
            "severity": "medium",
            "correction_action": "retry",
            "occurred_at": T0,
        },
        "AuditRecord": {
            "audit_id": "audit-1",
            "principal_id": "user-1",
            "actor": "broker",
            "action": "github.create_issue",
            "resource_type": "repository",
            "resource_id": "greenloop",
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
