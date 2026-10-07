"""Offline memory-injection eval: adversarial memory through the real context builder.

Free and deterministic (no model calls), so it runs in the gate tests
(services/orchestrator/tests/security/test_memory_injection_offline.py). Each case in
datasets/memory_injection_offline.jsonl builds MemoryRecords and passes them through
app.memory.context_builder.build_memory_context, the only path memory takes into a
prompt, then checks structural invariants:

- the block is intact: exactly one <retrieved_memory ...> opener and closer, one
  <memory_record ...> pair per included record, and no other tag anywhere;
- no raw `<` or `>` from memory content survives, so nothing can open or close a tag;
- listed substrings are absent (secrets, invisible and look-alike characters);
- included, rejected, truncated and redaction counts and the size bound hold.

Pass rule: every case passes. Run from the repo root:
    .venv\\Scripts\\python.exe evals\\injection\\memory_injection_offline.py
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "evals" / "datasets" / "memory_injection_offline.jsonl"
sys.path.insert(0, str(REPO_ROOT / "services" / "orchestrator"))

from app.memory.context_builder import ContextLimits, build_memory_context  # noqa: E402
from greenloop_contracts import MemoryRecord  # noqa: E402

PRINCIPAL_ID = "eval-user"
LIMITS = ContextLimits()
TAG = re.compile(r"</?[A-Za-z_|][^<>]*>")
ALLOWED_TAG = re.compile(
    r'^(<retrieved_memory count="\d+" omitted="\d+">|</retrieved_memory>'
    r'|<memory_record id="[^"<>]*" source="[a-z]+" created="[^"<>]*">|</memory_record>)$'
)


def _specs(case: dict) -> list[dict]:
    specs = list(case.get("records", []))
    if "records_repeat" in case:
        spec, count = case["records_repeat"]
        specs += [spec] * count
    return specs


def _record(index: int, spec: dict) -> MemoryRecord:
    content = spec.get("content", "")
    if "content_repeat" in spec:
        text, count = spec["content_repeat"]
        content = text * count
    operation = spec.get("operation", "create")
    return MemoryRecord.model_validate(
        {
            "record_id": f"mem-eval-{index}",
            "principal_id": spec.get("principal_id", PRINCIPAL_ID),
            "scope": "private",
            "category": "user_context",
            "content": content[:20000],
            "provenance": {
                "source": "import",
                "created_by": PRINCIPAL_ID,
                "operation": operation,
                "supersedes": "mem-eval-prior" if operation != "create" else None,
            },
            "created_at": datetime(2026, 10, 5, tzinfo=UTC),
        }
    )


def _structure_failures(text: str, included: int) -> list[str]:
    failures = []
    tags = TAG.findall(text)
    stray = [tag for tag in tags if not ALLOWED_TAG.match(tag)]
    if stray:
        failures.append(f"unexpected tags {stray[:3]}")
    openers = sum(tag.startswith("<retrieved_memory") for tag in tags)
    if openers != 1 or tags.count("</retrieved_memory>") != 1:
        failures.append("memory block opener/closer count is not exactly one")
    record_openers = sum(tag.startswith("<memory_record ") for tag in tags)
    if record_openers != included or tags.count("</memory_record>") != included:
        failures.append("record tags do not match included records")
    remainder = TAG.sub("", text)
    if "<" in remainder or ">" in remainder:
        failures.append("a raw angle bracket from memory content survived")
    return failures


def check(case: dict) -> list[str]:
    records = [_record(index, spec) for index, spec in enumerate(_specs(case))]
    context = build_memory_context(records, principal_id=PRINCIPAL_ID, limits=LIMITS)
    text, expect = context.text, case["expect"]
    failures = _structure_failures(text, len(context.included_ids))
    failures += [f"found {needle!r}" for needle in expect.get("absent", []) if needle in text]
    for key, actual in (
        ("included", len(context.included_ids)),
        ("rejected", context.rejected_count),
        ("truncated", context.truncated_count),
    ):
        if key in expect and actual != expect[key]:
            failures.append(f"{key} {actual} != {expect[key]}")
    if context.redaction_count < expect.get("min_redactions", 0):
        failures.append(f"redactions {context.redaction_count} < {expect['min_redactions']}")
    if len(context.included_ids) > expect.get("max_included", LIMITS.max_records):
        failures.append("too many records included")
    if len(text) > expect.get("max_chars", LIMITS.max_total_chars):
        failures.append(f"block is {len(text)} characters")
    return failures


def run(dataset: Path = DATASET) -> dict[str, list[str]]:
    lines = dataset.read_text(encoding="utf-8").splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    return {case["id"]: check(case) for case in cases}


def main() -> int:
    results = run()
    for case_id, failures in results.items():
        detail = f": {'; '.join(failures)}" if failures else ""
        print(f"{'FAIL' if failures else 'PASS'} {case_id}{detail}")
    failed = sum(bool(failures) for failures in results.values())
    print(f"{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
