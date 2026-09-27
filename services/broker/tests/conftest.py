from collections.abc import Callable

import pytest

from greenloop_contracts import ToolPermission


@pytest.fixture
def permission() -> Callable[..., ToolPermission]:
    def factory(
        tool: str = "github",
        operation: str = "create_issue",
        consequence: str = "write",
        principal_id: str = "user-1",
        **arguments: object,
    ) -> ToolPermission:
        return ToolPermission(
            principal_id=principal_id,
            tool=tool,
            operation=operation,
            consequence=consequence,
            arguments=arguments or {"repo": "greenloop", "title": "Bug"},
        )

    return factory
