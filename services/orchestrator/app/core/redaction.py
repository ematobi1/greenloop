"""The one secret redactor: used for memory context, model output streams and logs.

Three layers, applied in order:
1. Exact known secrets (values from settings), longest first.
2. Known credential shapes: private key blocks, provider API keys, GitHub, AWS and
   Slack tokens, JWTs, GreenLoop API (glt_) and session (gls_) tokens.
3. Quoted keys (JSON and Python dicts): `"password": "x"`, `'db_password': 'x'`,
   `"apiKey":"x"` keep the key and quotes and lose the value. A key matches when it
   ends with a secret word, so `access_token` matches and `token_count` doesn't.
4. Labelled values: `Bearer x`, `Authorization: x`, `password=x`, `api_key: x` and
   similar keep the label and lose the value.

StreamRedactor applies the same rules to text that arrives in chunks. It holds back
a short tail so a secret split across chunks is still caught, never splits right
after a label such as "Bearer" or inside a quoted value after a secret key, and
suppresses everything after an unterminated `-----BEGIN ... PRIVATE KEY-----`
until its END marker arrives.
"""

import re
from collections.abc import Iterable
from typing import Any

REDACTED = "[REDACTED]"
MIN_KNOWN_SECRET_LENGTH = 8
HOLD_BACK_CHARS = 32
FORCE_FLUSH_CHARS = 8192
KEY_END_TAIL_CHARS = 64
"""Tail kept while suppressing a key body; holds any END marker split across chunks."""

_KEY_BEGIN = re.compile(r"-----BEGIN[^-\n]*PRIVATE KEY-----")
_KEY_END = re.compile(r"-----END[^-\n]*PRIVATE KEY-----")

_SHAPES: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN[^-\n]*PRIVATE KEY-----.*?-----END[^-\n]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"-----BEGIN[^-\n]*PRIVATE KEY-----.*", re.DOTALL),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,200}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,200}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,200}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,200}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgl[ts]_[A-Za-z0-9_\-]{20,200}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,200}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"),
)
_LABEL_WORDS = (
    r"api[_-]?key|secret|token|password|passwd|access[_-]?key|client[_-]?secret|authorization"
)
_QUOTED_KEY = re.compile(
    rf"(?i)([\"'])([\w-]*(?:{_LABEL_WORDS}))\1(\s*:\s*)([\"'])[^\"'\\\n]{{6,200}}\4"
)
_LABELLED: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(bearer)(\s+)[A-Za-z0-9._~+/=\-]{8,200}"),
    re.compile(r"(?i)\b(authorization)(\s*[:=]\s*)(?!bearer\b)[^\s\"']{8,200}"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd|access[_-]?key|client[_-]?secret)"
        r"(\s*[=:]\s*[\"']?)[^\s\"']{6,200}"
    ),
)
_TRAILING_LABEL = re.compile(
    r"(?i)\b(bearer|authorization|api[_-]?key|secret|token|password|passwd|access[_-]?key"
    r"|client[_-]?secret)\s*[=:]?\s*$"
)
_TRAILING_QUOTED_KEY = re.compile(
    rf"(?i)[\"'][\w-]*(?:{_LABEL_WORDS})(?:[\"']?\s*:?\s*[\"']?|[\"']\s*:\s*[\"'][^\"'\\\n]*)$"
)
"""A quoted secret key at the end of the pending text, or its value still open."""


class Redactor:
    def __init__(self, known_secrets: Iterable[str] = ()) -> None:
        self._known = sorted(
            {secret for secret in known_secrets if len(secret) >= MIN_KNOWN_SECRET_LENGTH},
            key=len,
            reverse=True,
        )

    def redact(self, text: str) -> str:
        return self.redact_counted(text)[0]

    def redact_counted(self, text: str) -> tuple[str, int]:
        count = 0
        for secret in self._known:
            hits = text.count(secret)
            if hits:
                text = text.replace(secret, REDACTED)
                count += hits
        for pattern in _SHAPES:
            text, hits = pattern.subn(REDACTED, text)
            count += hits
        text, hits = _QUOTED_KEY.subn(rf"\1\2\1\3\4{REDACTED}\4", text)
        count += hits
        for pattern in _LABELLED:
            text, hits = pattern.subn(rf"\1\2{REDACTED}", text)
            count += hits
        return text, count

    def stream(self) -> "StreamRedactor":
        return StreamRedactor(self)


class StreamRedactor:
    def __init__(self, redactor: Redactor) -> None:
        self._redactor = redactor
        self._pending = ""
        self._inside_key = False

    def feed(self, chunk: str) -> str:
        self._pending += chunk
        output = []
        while True:
            if self._inside_key:
                end = _KEY_END.search(self._pending)
                if end is None:
                    self._pending = self._pending[-KEY_END_TAIL_CHARS:]
                    return "".join(output)
                self._pending = self._pending[end.end() :]
                self._inside_key = False
                continue
            split = self._safe_split()
            if split <= 0:
                return "".join(output)
            ready, self._pending = self._pending[:split], self._pending[split:]
            begin = _KEY_BEGIN.search(ready)
            if begin is not None and _KEY_END.search(ready, begin.end()) is None:
                output.append(self._redactor.redact(ready[: begin.start()]) + REDACTED)
                self._pending = ready[begin.end() :] + self._pending
                self._inside_key = True
                continue
            output.append(self._redactor.redact(ready))

    def flush(self) -> str:
        ready, self._pending = self._pending, ""
        if self._inside_key:
            self._inside_key = False
            return ""
        return self._redactor.redact(ready)

    def _safe_split(self) -> int:
        pending = self._pending
        begin = _KEY_BEGIN.search(pending)
        if begin is not None and _KEY_END.search(pending, begin.end()) is None:
            return len(pending) if len(pending) >= FORCE_FLUSH_CHARS else begin.start()
        limit = len(pending) - HOLD_BACK_CHARS
        if limit <= 0:
            return 0
        boundary = max(pending.rfind(" ", 0, limit), pending.rfind("\n", 0, limit))
        if boundary > 0:
            head = pending[: boundary + 1]
            starts = [
                match.start()
                for match in (_TRAILING_LABEL.search(head), _TRAILING_QUOTED_KEY.search(head))
                if match
            ]
            return min(starts) if starts else boundary + 1
        return limit if len(pending) >= FORCE_FLUSH_CHARS else 0


def redact_event_dict(redactor: Redactor):
    """structlog processor: redact every string value, including nested ones."""

    def processor(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        return {key: _redact_value(redactor, value) for key, value in event_dict.items()}

    return processor


def _redact_value(redactor: Redactor, value: Any) -> Any:
    if isinstance(value, str):
        return redactor.redact(value)
    if isinstance(value, dict):
        return {key: _redact_value(redactor, item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_redact_value(redactor, item) for item in value]
    return value
