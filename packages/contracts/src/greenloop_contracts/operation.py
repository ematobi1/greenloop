"""The canonical form and SHA256 of one exact tool operation.

An approval binds to `operation_hash(permission)`. Every service computes it with
this one function, so the orchestrator and the broker can't disagree about what was
approved. Canonical form: the ToolPermission as JSON with sorted keys, no
whitespace, UTF-8 (not ASCII-escaped), and NaN or Infinity refused.
"""

import hashlib
import json

from greenloop_contracts.tool_permission import ToolPermission


def canonical_operation(permission: ToolPermission) -> bytes:
    return json.dumps(
        permission.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def operation_hash(permission: ToolPermission) -> str:
    return hashlib.sha256(canonical_operation(permission)).hexdigest()
