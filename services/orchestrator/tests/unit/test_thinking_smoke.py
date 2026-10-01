"""Gate tests for evals/thinking_smoke.py: gap measurement and verdict, no model calls."""

import asyncio
import importlib.util
from pathlib import Path

from tests.conftest import FakeProvider

from app.ai.providers.base import Done, GenerationRequest, Message

SMOKE_PATH = Path(__file__).resolve().parents[4] / "evals" / "thinking_smoke.py"
_spec = importlib.util.spec_from_file_location("thinking_smoke", SMOKE_PATH)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)

REQUEST = GenerationRequest(
    system="s", messages=(Message(role="user", content="q"),), max_output_tokens=256
)


def _timeline(times_and_kinds, **done):
    return smoke.Timeline(events=list(times_and_kinds), done=Done(**done))


def test_the_wait_for_the_first_event_counts_as_a_gap():
    timeline = _timeline([(30.0, "activity"), (31.0, "text"), (31.5, "done")])
    assert timeline.max_gap == 30.0
    assert timeline.first_text_at == 31.0


def test_verdict_fails_when_any_gap_reaches_the_idle_timeout():
    steady = _timeline([(10.0, "activity"), (100.0, "activity"), (110.0, "text")])
    stalled = _timeline([(10.0, "activity"), (130.0, "text")])
    assert smoke.verdict(steady, 120.0)[0] is True
    assert smoke.verdict(stalled, 120.0)[0] is False
    assert "max_gap=120.0s" in smoke.verdict(stalled, 120.0)[1]


def test_verdict_fails_a_truncated_reply():
    cut = _timeline([(1.0, "text"), (2.0, "done")], truncated=True, stop_reason="max_tokens")
    assert smoke.verdict(cut, 120.0)[0] is False


def test_record_timestamps_activity_text_and_done_from_a_provider():
    provider = FakeProvider(["answer"], thinking=[0.02, 0.02])
    timeline = asyncio.run(smoke.record(provider, REQUEST))
    assert [kind for _, kind in timeline.events] == ["activity", "activity", "text", "done"]
    assert timeline.max_gap < 1.0
    assert timeline.done.stop_reason == "end_turn"
