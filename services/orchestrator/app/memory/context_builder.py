"""The only path by which retrieved memory reaches a prompt.

Retrieved memory is untrusted data: it may contain prompt injection, markup
that tries to close the surrounding block, or secrets a user pasted earlier.
Every record passes through four steps, in this order:

1. Filter: drop tombstones and any record not owned by the requesting principal.
2. Sanitize: NFKC-normalize (so look-alike brackets become real ones and get
   escaped), then strip control and invisible format characters.
3. Redact: replace known secret shapes with [REDACTED].
4. Bound and escape: truncate each record, escape &, < and >, and stop adding
   records once the total budget is reached.

The output is a `<retrieved_memory>` block the system prompt frames as
reference data, never instructions.
"""

import html
import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

from greenloop_contracts import MemoryOperation, MemoryRecord

logger = logging.getLogger(__name__)

REDACTED = "[REDACTED]"
TRUNCATED_MARKER = " [truncated]"
BLOCK_TAG = "retrieved_memory"
RECORD_TAG = "memory_record"

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*", re.DOTALL),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{16,}=*"),
)
_ASSIGNED_SECRET = re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)(\s*[:=]\s*)(\S+)")


@dataclass(frozen=True)
class ContextLimits:
    max_records: int = 20
    max_record_chars: int = 2000
    max_total_chars: int = 12000

    def __post_init__(self) -> None:
        if min(self.max_records, self.max_record_chars, self.max_total_chars) < 1:
            raise ValueError("context limits must be positive")


@dataclass(frozen=True)
class MemoryContext:
    text: str
    included_ids: tuple[str, ...]
    omitted_count: int
    rejected_count: int
    redaction_count: int
    truncated_count: int


def sanitize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return "".join(
        ch
        for ch in normalized
        if ch in "\n\t" or unicodedata.category(ch) not in {"Cc", "Cf", "Co", "Cs"}
    )


def redact(text: str) -> tuple[str, int]:
    count = 0
    for pattern in _SECRET_PATTERNS:
        text, hits = pattern.subn(REDACTED, text)
        count += hits
    text, hits = _ASSIGNED_SECRET.subn(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return text, count + hits


def _render_record(record: MemoryRecord, content: str) -> str:
    attributes = " ".join(
        f'{name}="{html.escape(value, quote=True)}"'
        for name, value in (
            ("id", record.record_id),
            ("source", record.provenance.source.value),
            ("created", record.created_at.isoformat()),
        )
    )
    return f"<{RECORD_TAG} {attributes}>\n{html.escape(content, quote=False)}\n</{RECORD_TAG}>\n"


def _header(count: int, omitted: int) -> str:
    return f'<{BLOCK_TAG} count="{count}" omitted="{omitted}">\n'


def build_memory_context(
    records: Iterable[MemoryRecord],
    *,
    principal_id: str,
    limits: ContextLimits | None = None,
) -> MemoryContext:
    limits = limits or ContextLimits()
    footer = f"</{BLOCK_TAG}>"
    budget = limits.max_total_chars - len(_header(10**6, 10**6)) - len(footer)

    rendered: list[str] = []
    included: list[str] = []
    omitted = rejected = redactions = truncated = 0
    used = 0

    for record in records:
        if record.principal_id != principal_id:
            rejected += 1
            logger.warning("memory record %s dropped: principal mismatch", record.record_id)
            continue
        if record.provenance.operation is MemoryOperation.DELETE:
            continue
        if len(included) >= limits.max_records:
            omitted += 1
            continue

        content, hits = redact(sanitize(record.content))
        redactions += hits
        if len(content) > limits.max_record_chars:
            content = content[: limits.max_record_chars] + TRUNCATED_MARKER
            truncated += 1

        block = _render_record(record, content)
        if used + len(block) > budget:
            omitted += 1
            continue
        rendered.append(block)
        included.append(record.record_id)
        used += len(block)

    text = _header(len(included), omitted) + "".join(rendered) + footer
    return MemoryContext(
        text=text,
        included_ids=tuple(included),
        omitted_count=omitted,
        rejected_count=rejected,
        redaction_count=redactions,
        truncated_count=truncated,
    )
