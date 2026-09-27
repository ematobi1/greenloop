"""ErrorDetail: the user-safe error shape embedded in results and API responses.

Only code, message and field messages. Internal detail (stack traces, upstream
responses, ids of internal systems) belongs in ErrorReport.details and never here.
"""

from pydantic import Field

from greenloop_contracts.base import ContractModel, ErrorCode, SafeMessage


class ErrorDetail(ContractModel):
    code: ErrorCode
    message: SafeMessage
    fields: dict[str, SafeMessage] = Field(default_factory=dict)
