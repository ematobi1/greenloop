"""Isolation boundary for running proposed code. A Git worktree is not a sandbox.

TODO(phase-7): pick an isolation mechanism that works on the target host (a disposable
container or VM with no network and no secrets) and document it in an ADR before use.
"""


class IsolationUnavailableError(RuntimeError):
    pass


def require_isolation() -> None:
    raise IsolationUnavailableError("No isolation mechanism is configured.")
