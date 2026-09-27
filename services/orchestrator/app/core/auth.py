"""Authentication: resolve the principal every request acts for.

Memory and permissions are scoped to the principal server-side, so every
endpoint beyond /health will depend on `get_current_principal`.
"""

from dataclasses import dataclass

from app.core.errors import not_implemented


@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str


async def get_current_principal() -> Principal:
    # TODO(phase-2): verify the session or bearer token and load the principal.
    raise not_implemented("Authentication", phase=2)
