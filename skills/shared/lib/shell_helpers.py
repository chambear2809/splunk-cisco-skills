"""Shared Python helpers called from shell scripts.

These were previously embedded inline via ``python3 -c '...'`` heredocs
inside the bash libraries.  Extracting them here makes them visible to
Python linters, testable in isolation, and reusable across multiple
shell entry-points.

Entry-points are designed to be invoked from bash via:
    python3 /path/to/shell_helpers.py <subcommand> [args...]
"""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import quote, quote_plus

# ---------------------------------------------------------------------------
# form_urlencode_pairs
# ---------------------------------------------------------------------------


def form_urlencode_pairs(args: list[str]) -> str:
    if len(args) % 2 != 0:
        print("ERROR: form_urlencode_pairs requires key/value pairs.", file=sys.stderr)
        raise SystemExit(1)
    parts = []
    for i in range(0, len(args), 2):
        parts.append(f"{quote_plus(args[i])}={quote_plus(args[i + 1])}")
    return "&".join(parts)


# ---------------------------------------------------------------------------
# urlencode (single value, safe='')
# ---------------------------------------------------------------------------


def urlencode(value: str) -> str:
    return quote(value, safe="")


# ---------------------------------------------------------------------------
# sanitize_response
# ---------------------------------------------------------------------------

_SENSITIVE_TOKENS = (
    "password",
    "secret",
    "token",
    "apikey",
    "clientsecret",
    "sessionkey",
    "certificate",
    "privatekey",
    "jsontext",
    "accesssecret",
    "externalid",
    "passphrase",
)

_KEY_PATTERN = (
    r"[A-Za-z0-9_.-]*?(?:password|secret|token|api[_-]?key|client[_-]?secret"
    r"|sessionkey|certificate|private[_-]?key|json[_-]?text|access[_-]?secret"
    r"|external[_-]?id|passphrase)[A-Za-z0-9_.-]*"
)


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", str(key).lower())
    return any(tok in normalized for tok in _SENSITIVE_TOKENS)


def _redact_json(value: object) -> object:
    if isinstance(value, dict):
        return {k: ("REDACTED" if _is_sensitive_key(k) else _redact_json(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    return value


def _redact_text(raw: str) -> str:
    def replace_equals(match: re.Match) -> str:  # type: ignore[type-arg]
        return f"{match.group(1)}{match.group(2)}REDACTED"

    def replace_colon(match: re.Match) -> str:  # type: ignore[type-arg]
        value = match.group(3)
        if value.startswith('"') and value.endswith('"'):
            replacement = '"REDACTED"'
        elif value.startswith("'") and value.endswith("'"):
            replacement = "'REDACTED'"
        else:
            replacement = "REDACTED"
        return f"{match.group(1)}{match.group(2)}{replacement}"

    raw = re.sub(
        rf"(?i)\b({_KEY_PATTERN})\b(\s*=\s*)([^&\s]+)",
        replace_equals,
        raw,
    )
    raw = re.sub(
        rf"""(?ix)
        (["']?\b{_KEY_PATTERN}\b["']?)
        (\s*:\s*)
        ("[^"]*"|'[^']*'|[^,\}}\]\s]+)
        """,
        replace_colon,
        raw,
    )
    return raw


def sanitize_response(text: str, max_lines: int = 20) -> str:
    try:
        sanitized = json.dumps(_redact_json(json.loads(text)))
    except Exception:
        sanitized = _redact_text(text)
    lines = sanitized.splitlines() or [sanitized]
    return "\n".join(lines[:max_lines])


# ---------------------------------------------------------------------------
# CLI dispatcher
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: shell_helpers.py <subcommand> [args...]", file=sys.stderr)
        raise SystemExit(1)

    command = sys.argv[1]

    if command == "form_urlencode_pairs":
        print(form_urlencode_pairs(sys.argv[2:]), end="")

    elif command == "urlencode":
        print(urlencode(sys.argv[2]), end="")

    elif command == "sanitize_response":
        max_lines = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        with os.fdopen(3, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        result = sanitize_response(text, max_lines)
        print(result)

    elif command == "curl_config_escape":
        print(sys.argv[2].replace("\\", "\\\\").replace('"', '\\"'))

    elif command == "is_splunk_package":
        import tarfile

        raise SystemExit(0 if tarfile.is_tarfile(sys.argv[2]) else 1)

    else:
        print(f"Unknown subcommand: {command}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
