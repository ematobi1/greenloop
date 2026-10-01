"""Thinking smoke test: one paid call that checks a long-thinking reply never goes
quiet for longer than the engine's idle timeout.

Opus 5.5 always thinks. The Anthropic provider asks for summarized thinking so the
stream keeps sending events (Activity) while the model thinks; this measures the
largest gap between any two stream events on a prompt that forces long thinking.

Paid: ONE call to the configured Anthropic model (ANTHROPIC_API_KEY from the root
.env). Run from services/orchestrator:

    python ../../evals/thinking_smoke.py [--effort high] [--out gaps.log]

PASS when the largest gap (including the wait for the first event) is below
AI_TIMEOUT_SECONDS and the reply is not truncated. Exit 0 pass, 1 fail, 2 no provider.
"""

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "orchestrator"))

from app.ai.errors import AiError  # noqa: E402
from app.ai.providers.base import (  # noqa: E402
    Activity,
    Done,
    GenerationRequest,
    Message,
    ModelProvider,
    TextDelta,
)

PROMPT = (
    "Find every positive integer n below 2000 such that n^2 + 1 is divisible by a perfect "
    "square greater than 1. Work it out carefully and completely before answering, then "
    "give the count and the five smallest such n, each with the square that divides n^2 + 1."
)


@dataclass(frozen=True)
class Timeline:
    events: list[tuple[float, str]]
    done: Done

    @property
    def gaps(self) -> list[float]:
        times = [0.0] + [at for at, _ in self.events]
        return [later - earlier for earlier, later in pairwise(times)]

    @property
    def max_gap(self) -> float:
        return max(self.gaps, default=0.0)

    @property
    def first_text_at(self) -> float | None:
        return next((at for at, kind in self.events if kind == "text"), None)


async def record(provider: ModelProvider, request: GenerationRequest) -> Timeline:
    """Timestamps every provider event, measured from the moment the request starts."""
    started = time.perf_counter()
    events: list[tuple[float, str]] = []
    done = Done()
    async for event in provider.stream(request):
        at = time.perf_counter() - started
        if isinstance(event, TextDelta):
            events.append((at, "text"))
        elif isinstance(event, Activity):
            events.append((at, "activity"))
        elif isinstance(event, Done):
            events.append((at, "done"))
            done = event
    return Timeline(events=events, done=done)


def verdict(timeline: Timeline, idle_timeout: float) -> tuple[bool, str]:
    passed = timeline.max_gap < idle_timeout and not timeline.done.truncated
    first_text = timeline.first_text_at
    summary = (
        f"events={len(timeline.events)} max_gap={timeline.max_gap:.1f}s "
        f"idle_timeout={idle_timeout:.0f}s "
        f"first_text_at={'none' if first_text is None else f'{first_text:.1f}s'} "
        f"total={timeline.events[-1][0] if timeline.events else 0:.1f}s "
        f"input_tokens={timeline.done.input_tokens} output_tokens={timeline.done.output_tokens} "
        f"stop_reason={timeline.done.stop_reason} -> {'PASS' if passed else 'FAIL'}"
    )
    return passed, summary


def main(argv: list[str] | None = None) -> int:
    from app.ai.providers.registry import build_registry
    from app.core.config import get_settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"]
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    settings = get_settings().model_copy(update={"anthropic_effort": args.effort})
    try:
        provider = build_registry(settings).get("anthropic")
    except AiError as err:
        print(f"No provider: {err.api_code}", file=sys.stderr)
        return 2
    request = GenerationRequest(
        system="You are a careful mathematician.",
        messages=(Message(role="user", content=PROMPT),),
        max_output_tokens=settings.ai_max_output_tokens,
    )
    try:
        timeline = asyncio.run(record(provider, request))
    except AiError as err:
        print(f"provider error {err.api_code} -> FAIL")
        return 1
    if args.out:
        args.out.write_text(
            "".join(f"{at:9.3f}s {kind}\n" for at, kind in timeline.events), encoding="utf-8"
        )
    passed, summary = verdict(timeline, settings.ai_timeout_seconds)
    print(f"model={provider.config.model} effort={args.effort}")
    print(summary)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
