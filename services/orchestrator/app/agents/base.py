"""Agent base class. Every agent is described by an Agent contract and runs one Dispatch."""

from abc import ABC, abstractmethod

from greenloop_contracts import Agent, Dispatch, ExecutionResult


class BaseAgent(ABC):
    descriptor: Agent

    @abstractmethod
    async def run(self, item: Dispatch) -> ExecutionResult: ...


def result_id(item: Dispatch) -> str:
    """One result per dispatch, so the id is derived from it."""
    return f"res-{item.dispatch_id.removeprefix('dsp-')}"
