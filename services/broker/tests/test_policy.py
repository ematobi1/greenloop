from pathlib import Path

import pytest
from pydantic import ValidationError

from app.policy import DEFAULT_DENY, Effect, Policy, Rule, load_policy

POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"


def rule(**overrides) -> Rule:
    fields = {"id": "r1", "tool": "github", "operation": "*", "effect": "allow"}
    return Rule.model_validate({**fields, **overrides})


class TestDenyByDefault:
    def test_empty_policy_denies(self, permission):
        assert Policy([]).evaluate(permission()) == DEFAULT_DENY

    def test_unmatched_tool_is_denied(self, permission):
        policy = Policy([rule(tool="github")])
        decision = policy.evaluate(permission(tool="slack", consequence="send"))
        assert decision.effect is Effect.DENY
        assert decision.rule_id is None

    def test_unmatched_consequence_is_denied(self, permission):
        policy = Policy([rule(consequences=["read"])])
        assert policy.evaluate(permission(consequence="write")).effect is Effect.DENY

    def test_empty_policy_directory_denies(self, tmp_path, permission):
        assert load_policy(tmp_path).evaluate(permission(consequence="read")) == DEFAULT_DENY


class TestPrecedence:
    def test_deny_beats_allow(self, permission):
        policy = Policy([rule(id="a"), rule(id="d", effect="deny")])
        assert policy.evaluate(permission()).rule_id == "d"

    def test_approval_beats_allow(self, permission):
        policy = Policy([rule(id="a"), rule(id="q", effect="require_approval")])
        assert policy.evaluate(permission()).effect is Effect.REQUIRE_APPROVAL

    def test_order_does_not_matter(self, permission):
        forward = Policy([rule(id="a"), rule(id="d", effect="deny")])
        backward = Policy([rule(id="d", effect="deny"), rule(id="a")])
        assert forward.evaluate(permission()) == backward.evaluate(permission())

    def test_wildcards_are_case_sensitive(self, permission):
        policy = Policy([rule(operation="get_*")])
        assert policy.evaluate(permission(operation="get_issue")).effect is Effect.ALLOW
        assert policy.evaluate(permission(operation="GET_issue")).effect is Effect.DENY


class TestValidation:
    def test_duplicate_rule_ids_rejected(self):
        with pytest.raises(ValueError, match="unique"):
            Policy([rule(), rule()])

    def test_unknown_rule_field_rejected(self):
        with pytest.raises(ValidationError):
            rule(priority=1)

    def test_unknown_effect_rejected(self):
        with pytest.raises(ValidationError):
            rule(effect="maybe")

    def test_malformed_policy_file_fails_loudly(self, tmp_path):
        (tmp_path / "bad.yaml").write_text("rules:\n  - id: x\n    effect: allow\n")
        with pytest.raises(ValidationError):
            load_policy(tmp_path)


class TestShippedPolicies:
    @pytest.fixture
    def policy(self) -> Policy:
        return load_policy(POLICY_DIR)

    def test_github_read_allowed(self, policy, permission):
        decision = policy.evaluate(permission(operation="get_file_contents", consequence="read"))
        assert decision.effect is Effect.ALLOW

    def test_github_write_needs_approval(self, policy, permission):
        assert policy.evaluate(permission()).effect is Effect.REQUIRE_APPROVAL

    def test_github_merge_denied_even_as_write(self, policy, permission):
        decision = policy.evaluate(permission(operation="merge_pull_request"))
        assert decision.effect is Effect.DENY
        assert decision.rule_id == "github-merge-deny"

    def test_github_delete_denied(self, policy, permission):
        assert policy.evaluate(permission(consequence="delete")).effect is Effect.DENY

    def test_spend_denied_everywhere(self, policy, permission):
        assert policy.evaluate(permission(consequence="spend")).effect is Effect.DENY

    def test_unknown_tool_denied(self, policy, permission):
        assert policy.evaluate(permission(tool="gmail", consequence="read")) == DEFAULT_DENY
