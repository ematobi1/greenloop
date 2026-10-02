import os
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from greenloop_contracts import ToolPermission

# Tests never read the developer's .env: settings load from an empty file instead.
_EMPTY_ENV = Path(tempfile.mkdtemp(prefix="broker-tests-")) / "empty.env"
_EMPTY_ENV.touch()
os.environ["GREENLOOP_ENV_FILE"] = str(_EMPTY_ENV)
os.environ.pop("BROKER_DATABASE_URL", None)


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
