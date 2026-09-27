"""Broker policy engine: deny by default.

Rules are loaded from YAML files in policies/. Each rule matches on tool and
operation (shell-style wildcards) and optionally on consequence. Across all
matching rules the strictest effect wins: deny, then require_approval, then
allow. If no rule matches, the request is denied.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from greenloop_contracts import ToolConsequence, ToolPermission


class Effect(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


_STRICTNESS = {Effect.ALLOW: 0, Effect.REQUIRE_APPROVAL: 1, Effect.DENY: 2}


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    consequences: tuple[ToolConsequence, ...] = ()
    effect: Effect
    reason: str = ""

    def matches(self, permission: ToolPermission) -> bool:
        return (
            fnmatchcase(permission.tool, self.tool)
            and fnmatchcase(permission.operation, self.operation)
            and (not self.consequences or permission.consequence in self.consequences)
        )


class PolicyFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[Rule] = []


@dataclass(frozen=True)
class Decision:
    effect: Effect
    rule_id: str | None
    reason: str


DEFAULT_DENY = Decision(Effect.DENY, None, "no policy rule matched; denied by default")


class Policy:
    def __init__(self, rules: Iterable[Rule]) -> None:
        self.rules: Sequence[Rule] = tuple(rules)
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("policy rule ids must be unique")

    def evaluate(self, permission: ToolPermission) -> Decision:
        matched = [rule for rule in self.rules if rule.matches(permission)]
        if not matched:
            return DEFAULT_DENY
        strictest = max(matched, key=lambda rule: _STRICTNESS[rule.effect])
        return Decision(strictest.effect, strictest.id, strictest.reason)


def load_policy(directory: Path) -> Policy:
    rules: list[Rule] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rules.extend(PolicyFile.model_validate(data).rules)
    return Policy(rules)
