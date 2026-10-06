"""Gate: the offline memory-injection eval (evals/injection/memory_injection_offline.py)
passes every case, and fails when the context builder stops escaping or sanitizing,
so it can't pass vacuously."""

import importlib.util
from pathlib import Path

import pytest

from app.memory import context_builder

EVAL = Path(__file__).resolve().parents[4] / "evals" / "injection" / "memory_injection_offline.py"


@pytest.fixture(scope="module")
def offline_eval():
    spec = importlib.util.spec_from_file_location("memory_injection_offline", EVAL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_case_passes(offline_eval):
    results = offline_eval.run()
    assert len(results) >= 15
    assert {case: failures for case, failures in results.items() if failures} == {}


def test_it_fails_when_memory_is_not_escaped(offline_eval, monkeypatch):
    monkeypatch.setattr(context_builder.html, "escape", lambda text, quote=True: text)
    failed = {case for case, failures in offline_eval.run().items() if failures}
    assert {"close-block-tag", "close-record-tag", "fake-system-prompt"} <= failed


def test_it_fails_when_memory_is_not_sanitized(offline_eval, monkeypatch):
    monkeypatch.setattr(context_builder, "sanitize", lambda text: text)
    failed = {case for case, failures in offline_eval.run().items() if failures}
    assert {"fullwidth-brackets", "zero-width-split-tag", "bidi-override"} <= failed
