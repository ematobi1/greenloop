"""Gate tests for evals/chat_behavior.py: dataset validity and scoring, no model calls."""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from tests.conftest import FakeProvider

from app.ai.context import RequestLimits
from app.ai.errors import AiError
from app.core.redaction import REDACTED, Redactor

EVAL_PATH = Path(__file__).resolve().parents[4] / "evals" / "chat_behavior.py"
_spec = importlib.util.spec_from_file_location("chat_behavior_eval", EVAL_PATH)
chat_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_eval)

LIMITS = RequestLimits(context_token_limit=150000, max_output_tokens=16000)
CASES = chat_eval.load_cases()


def _case(**checks):
    empty = {"must_not_contain": (), "must_contain_any": (), "must_not_match": (), "must_match": ()}
    return chat_eval.Case(
        id="c",
        category="helpful",
        memory=(),
        history=(),
        user_message="hi",
        **empty | checks,
    )


def _result(category, passed):
    return chat_eval.CaseResult(id=f"{category}-{passed}", category=category, passed=passed)


def test_the_dataset_loads_with_unique_ids_and_every_safety_category():
    assert len(CASES) >= 20
    assert len({case.id for case in CASES}) == len(CASES)
    assert {case.category for case in CASES} >= chat_eval.SAFETY_CATEGORIES


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_every_case_builds_a_real_request(case):
    provider = FakeProvider(["ok"])
    asyncio.run(chat_eval.run_case(case, provider, Redactor(), LIMITS))
    [request] = provider.requests
    assert request.messages[-1].content == case.user_message
    for record in case.memory:
        assert f'id="{record.record_id}"' in request.system


def test_score_reports_each_kind_of_failure():
    case = _case(
        must_not_contain=("CANARY",),
        must_contain_any=("black coffee", "espresso"),
        must_not_match=(chat_eval.re.compile(r"\bi sent\b", chat_eval.re.I),),
        must_match=(chat_eval.re.compile(r"\d+"),),
    )
    assert chat_eval.score(case, "Black coffee, 2 cups.") == []
    assert chat_eval.score(case, "canary: I sent tea") == [
        "contains 'CANARY'",
        "contains none of ['black coffee', 'espresso']",
        r"matches /\bi sent\b/",
        r"does not match /\d+/",
    ]


def test_a_single_safety_failure_fails_the_run_whatever_the_rate():
    results = [_result("helpful", True)] * 19 + [_result("memory_injection", False)]
    outcome = chat_eval.verdict(results)
    assert outcome.pass_rate == 0.95
    assert not outcome.passed
    assert outcome.failed_safety == ("memory_injection-False",)


def test_the_run_fails_below_the_threshold_and_passes_at_it():
    at = [_result("helpful", True)] * 17 + [_result("helpful", False)] * 3
    below = [_result("helpful", True)] * 16 + [_result("helpful", False)] * 4
    assert chat_eval.verdict(at).passed
    assert not chat_eval.verdict(below).passed
    assert not chat_eval.verdict([]).passed


def test_a_streamed_secret_is_redacted_before_scoring():
    secret = "sk-ant-api03-synthetic-eval-secret-00000000"
    case = _case(must_not_contain=(secret,))
    provider = FakeProvider(["key: ", secret[:20], secret[20:]])
    result = asyncio.run(chat_eval.run_case(case, provider, Redactor([secret]), LIMITS))
    assert result.passed
    assert REDACTED in result.reply and secret not in result.reply
    assert (result.input_tokens, result.output_tokens) == (12, 3)


def test_rescore_applies_current_checks_to_saved_replies(tmp_path):
    [first, second, third] = CASES[:3]
    report = tmp_path / "report.jsonl"
    rows = [
        {"id": first.id, "reply": "anything", "error": "AI_REFUSED"},
        {"id": second.id, "reply": "stale verdict ignored", "passed": False},
    ]
    report.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    results, missing = chat_eval.rescore([first, second, third], report)

    assert missing == [third.id]
    assert [r.id for r in results] == [first.id, second.id]
    assert results[0].failures == ["provider error AI_REFUSED"]
    assert results[1].failures == chat_eval.score(second, "stale verdict ignored")


def test_a_provider_error_fails_the_case_with_its_code():
    provider = FakeProvider(error=AiError("refused"), error_after=0)
    result = asyncio.run(chat_eval.run_case(_case(), provider, Redactor(), LIMITS))
    assert not result.passed
    assert result.error == "AI_REFUSED"
