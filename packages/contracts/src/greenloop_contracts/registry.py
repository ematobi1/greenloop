"""Registry of every contract by name, for validation and schema export.

Services validate inbound payloads with `parse(name, data)` and publish
schemas with `json_schemas()`. Adding a contract means adding it here.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from greenloop_contracts.agent import Agent
from greenloop_contracts.approval import Approval
from greenloop_contracts.audit_record import AuditRecord
from greenloop_contracts.base import ContractModel
from greenloop_contracts.dispatch import Dispatch
from greenloop_contracts.error_report import ErrorReport
from greenloop_contracts.event import Event
from greenloop_contracts.execution_result import ExecutionResult
from greenloop_contracts.memory_record import MemoryRecord
from greenloop_contracts.task import Task
from greenloop_contracts.tool_grant import ToolGrant
from greenloop_contracts.tool_permission import ToolPermission

CONTRACTS: Mapping[str, type[ContractModel]] = MappingProxyType(
    {
        model.__name__: model
        for model in (
            Agent,
            Task,
            Dispatch,
            ToolPermission,
            ToolGrant,
            Approval,
            MemoryRecord,
            Event,
            ExecutionResult,
            ErrorReport,
            AuditRecord,
        )
    }
)


class UnknownContractError(KeyError):
    pass


def get_contract(name: str) -> type[ContractModel]:
    try:
        return CONTRACTS[name]
    except KeyError:
        raise UnknownContractError(name) from None


def parse(name: str, data: Mapping[str, Any]) -> ContractModel:
    return get_contract(name).model_validate(data)


def json_schemas() -> dict[str, dict[str, Any]]:
    return {
        name: {"version": model.schema_version, "schema": model.model_json_schema()}
        for name, model in CONTRACTS.items()
    }
