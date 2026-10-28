"""Secret detection and redaction for action payloads.

Two layers: (1) key-name based (a value under "password" is a secret no matter what it looks like) and
(2) pattern based (well-known token formats inside free text). Redaction happens BEFORE anything is persisted
or logged, so secrets never reach PostgreSQL, audit logs or the dashboard.
"""
import re
from typing import Any

REDACTED = "[REDACTED]"
MAX_DEPTH = 12

_SENSITIVE_KEY = re.compile(
    r"(?:^|[_\-.])(password|passwd|pwd|secret|token|api_?key|apikey|authorization|private_?key|credentials?|"
    r"access_?key|client_?secret|session|cookie)(?:$|[_\-.])",
    re.IGNORECASE,
)

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), REDACTED),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), REDACTED),
    ("stripe_key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}\b"), REDACTED),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), REDACTED),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), REDACTED),
    ("guardrail_key", re.compile(r"\bgrk_[A-Za-z0-9_-]{20,}\b"), REDACTED),
    ("bearer_token", re.compile(r"\b(Bearer)\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE), r"\1 " + REDACTED),
    (
        "connection_string_password",
        re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)([^\s@/]+)(@)", re.IGNORECASE),
        r"\1" + REDACTED + r"\3",
    ),
    (
        "key_value_secret",
        re.compile(
            r"\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token)(\s*[=:]\s*)(['\"]?)[^\s'\",;]{4,}\3",
            re.IGNORECASE,
        ),
        r"\1\2" + REDACTED,
    ),
]


def redact_text(text: str) -> tuple[str, int]:
    count = 0
    for _, pattern, repl in _PATTERNS:
        text, n = pattern.subn(repl, text)
        count += n
    return text, count


def redact_value(value: Any, _depth: int = 0) -> tuple[Any, int]:
    """Returns (redacted_copy, number_of_redactions). Never mutates the input."""
    if _depth > MAX_DEPTH:
        return REDACTED, 1
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        total = 0
        for k, v in value.items():
            if _SENSITIVE_KEY.search(str(k)) and isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != "":
                out[k] = REDACTED
                total += 1
            else:
                out[k], n = redact_value(v, _depth + 1)
                total += n
        return out, total
    if isinstance(value, (list, tuple)):
        items, total = [], 0
        for v in value:
            rv, n = redact_value(v, _depth + 1)
            items.append(rv)
            total += n
        return items, total
    return value, 0
