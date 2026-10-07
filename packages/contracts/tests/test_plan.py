from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from greenloop_contracts import MAX_PLAN_STEPS, Plan, PlanStatus, PlanStep, parse

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _plan(steps, **fields):
    return Plan(
        plan_id="plan-1",
        principal_id="user-1",
        goal="Move the blog to a static site",
        steps=steps,
        created_at=NOW,
        updated_at=NOW,
        **fields,
    )


def test_a_plan_is_a_draft_with_backward_dependencies():
    plan = _plan(
        [
            {"title": "Export posts"},
            {"title": "Pick a generator", "description": "Compare two."},
            {"title": "Publish", "depends_on": [0, 1]},
        ]
    )
    assert plan.status is PlanStatus.DRAFT
    assert plan.steps[2].depends_on == (0, 1)
    assert parse("Plan", plan.model_dump(mode="json")) == plan


@pytest.mark.parametrize(
    "steps",
    [
        [{"title": "Loop", "depends_on": [0]}],
        [{"title": "A", "depends_on": [1]}, {"title": "B"}],
        [{"title": "A"}, {"title": "B", "depends_on": [0, 0]}],
        [{"title": "A", "depends_on": [-1]}],
    ],
)
def test_dependencies_must_point_to_distinct_earlier_steps(steps):
    with pytest.raises(ValidationError):
        _plan(steps)


@pytest.mark.parametrize("steps", [[], [{"title": "x"}] * (MAX_PLAN_STEPS + 1)])
def test_a_plan_has_one_to_twenty_steps(steps):
    with pytest.raises(ValidationError):
        _plan(steps)


@pytest.mark.parametrize(
    "fields",
    [
        {"goal": " "},
        {"goal": "x" * 2001},
        {"status": "running"},
        {"updated_at": NOW - timedelta(seconds=1)},
        {"surprise": True},
    ],
)
def test_bad_plan_fields_are_rejected(fields):
    payload = _plan([{"title": "x"}]).model_dump() | fields
    with pytest.raises(ValidationError):
        Plan.model_validate(payload)


def test_steps_need_a_title_and_bounded_text():
    with pytest.raises(ValidationError):
        PlanStep(title=" ")
    with pytest.raises(ValidationError):
        PlanStep(title="x", description="y" * 4001)
