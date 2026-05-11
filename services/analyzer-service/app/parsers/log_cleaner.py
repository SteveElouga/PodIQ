import re

MAX_LOG_LINES = 2000

_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(password\s*[=:]\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(passwd\s*[=:]\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(secret\s*[=:]\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(token\s*[=:]\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(api[_-]?key\s*[=:]\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(auth\s*[=:]\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(Authorization\s*:\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(private[_-]?key\s*[=:]\s*)\S+", re.IGNORECASE), r"\1***"),
]


def truncate(logs: str, max_lines: int = MAX_LOG_LINES) -> str:
    lines = logs.splitlines()
    if len(lines) <= max_lines:
        return logs
    kept = lines[-max_lines:]
    return (
        f"[... truncated — showing last {max_lines} of {len(lines)} lines ...]\n"
        + "\n".join(kept)
    )


def mask_secrets(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def clean(logs: str) -> str:
    """Truncate to MAX_LOG_LINES then mask secrets. Always call before transmission."""
    return mask_secrets(truncate(logs))
