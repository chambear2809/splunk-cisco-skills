#!/usr/bin/env python3
"""Redact credential-shaped values from staging validator diagnostics."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ANSI_ESCAPE = re.compile(r"\x1b(?:[@-_][0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
AUTHORIZATION = re.compile(
    r"(?im)(?P<prefix>\bAuthorization\s*:\s*)(?:(?:Bearer|Basic|Splunk)\s+)?[^\r\n]*$"
)
TOKEN_HEADER = re.compile(
    r"(?im)(?P<prefix>\b(?:X-SF-Token|X-Auth-Token|Api-Key)\s*:\s*)[^\r\n]*$"
)
BEARER = re.compile(r"(?i)(?P<prefix>\bBearer\s+)[A-Za-z0-9._~+/=-]+")
JSON_SECRET = re.compile(
    r"(?i)(?P<prefix>[\"'](?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)[\"']\s*:\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^,}\]\s]+)"
)
PLAIN_SECRET = re.compile(
    r"(?i)(?P<prefix>\b(?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token)\b\s*[=:]\s*)"
    r"(?P<value>[^\s,;]+)"
)
URL_USERINFO = re.compile(r"(?i)(https://[^:/\s]+:)[^@/\s]+@")


def redact_text(text: str) -> str:
    text = ANSI_ESCAPE.sub("", text)
    text = AUTHORIZATION.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = TOKEN_HEADER.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = BEARER.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = JSON_SECRET.sub(lambda match: f"{match.group('prefix')}\"[REDACTED]\"", text)
    text = PLAIN_SECRET.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    return URL_USERINFO.sub(r"\1[REDACTED]@", text)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: redact-output.py LOG_FILE", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                sys.stderr.write(redact_text(line))
    except OSError as exc:
        print(f"ERROR: could not read staging diagnostic log: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
