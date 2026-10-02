"""Whether the current code runs inside a dispatch (an agent's turn).

The dispatcher sets the flag around `agent.run`; context variables carry it into
every coroutine and task the agent starts. The approvals service reads it so that
nothing running inside a dispatch can decide an approval (ADR 0009 rule 6).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_in_dispatch: ContextVar[bool] = ContextVar("in_dispatch", default=False)


def in_dispatch() -> bool:
    return _in_dispatch.get()


@contextmanager
def dispatch_scope() -> Iterator[None]:
    token = _in_dispatch.set(True)
    try:
        yield
    finally:
        _in_dispatch.reset(token)
