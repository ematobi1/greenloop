"""Agent base class. Every agent is described by an Agent contract and runs one Dispatch."""

from abc import ABC, abstractmethod

from greenloop_contracts import Agent, Dispatch, ExecutionResult


class BaseAgent(ABC):
    descriptor: Agent

    @abstractmethod
    async def run(self, item: Dispatch) -> ExecutionResult: ...
