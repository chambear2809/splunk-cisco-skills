#!/usr/bin/env python3
"""Redact credential-shaped values from staging validator diagnostics."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
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
    r"(?P<value>"
    r"\"(?:\\[^\r\n]|[^\"\\\r\n])*\""
    r"|'(?:\\[^\r\n]|[^'\\\r\n])*'"
    # An unterminated JSON quote is still sensitive through the field/line.
    r'|\"[^\r\n]*'
    r"|'[^\r\n]*"
    # Malformed unquoted JSON has no reliable value boundary. Suppress the
    # remaining field/line instead of retaining a possible secret fragment.
    r"|[^\r\n]*"
    r")"
)
PLAIN_SECRET = re.compile(
    r"(?i)(?P<prefix>\b(?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)\b\s*[=:]\s*)"
    r"(?P<value>"
    r'"(?:\\[^\r\n]|[^"\\\r\n])*"'
    r"|'(?:\\[^\r\n]|[^'\\\r\n])*'"
    # If a sensitive quote is unterminated, consume the rest of the line
    # rather than risking disclosure of a fragment after the assignment.
    r'|\"[^\r\n]*'
    r"|'[^\r\n]*"
    # Whitespace, commas, and semicolons may all be part of an unquoted
    # diagnostic value, so there is no safe delimiter short of end-of-line.
    r"|[^\r\n]*"
    r")"
)
URL_USERINFO = re.compile(r"(?i)(https://[^:/\s]+:)[^@/\s]+@")
SENSITIVE_QUOTED_ASSIGNMENT = re.compile(
    r"(?i)(?:"
    r"\b(?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)\b\s*[=:]\s*"
    r"|[\"'](?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)[\"']\s*:\s*"
    r")(?:(?:Bearer|Basic|Splunk)\s+)?(?P<quote>[\"'])"
)
SENSITIVE_VALUE_PENDING = re.compile(
    r"(?i)(?:"
    r"\b(?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)\b[ \t]*[=:][ \t]*"
    r"|[\"'](?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)[\"'][ \t]*:[ \t]*"
    r")(?:(?:Bearer|Basic|Splunk)[ \t]*)?(?:\r?\n)?\Z"
)
SENSITIVE_VALUE_LINE = re.compile(
    r"(?i)(?:"
    r"\b(?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)\b[ \t]*[=:][ \t]*"
    r"|[\"'](?:token|password|secret|api[_-]?key|access[_-]?token|"
    r"bearer[_-]?token|(?:x[_-]?)?sf[_-]?token|x[_-]?auth[_-]?token|"
    r"hec[_-]?token|authorization)[\"'][ \t]*:[ \t]*"
    r")(?:(?:Bearer|Basic|Splunk)[ \t]*)?(?P<value>[^\r\n]*)"
)


def redact_text(text: str) -> str:
    text = ANSI_ESCAPE.sub("", text)
    text = AUTHORIZATION.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = TOKEN_HEADER.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = BEARER.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    text = JSON_SECRET.sub(lambda match: f"{match.group('prefix')}\"[REDACTED]\"", text)
    text = PLAIN_SECRET.sub(lambda match: f"{match.group('prefix')}[REDACTED]", text)
    return URL_USERINFO.sub(r"\1[REDACTED]@", text)


def closing_quote(text: str, start: int, quote: str) -> int | None:
    """Return the next unescaped matching quote, if this physical line has one."""
    escaped = False
    for offset in range(start, len(text)):
        character = text[offset]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return offset
    return None


def unterminated_sensitive_quote(text: str) -> str | None:
    """Find a sensitive quoted assignment that does not close on this line."""
    cursor = 0
    while match := SENSITIVE_QUOTED_ASSIGNMENT.search(text, cursor):
        quote = match.group("quote")
        close_at = closing_quote(text, match.end(), quote)
        if close_at is None:
            return quote
        cursor = close_at + 1
    return None


def sensitive_assignment_opens_at(text: str, quote_at: int) -> bool:
    """Return true when quote_at starts a sensitive JSON key or value."""
    cursor = 0
    while match := SENSITIVE_QUOTED_ASSIGNMENT.search(text, cursor):
        if match.start() == quote_at or match.end() - 1 == quote_at:
            return True
        cursor = match.end()
    return False


def sensitive_unquoted_continuation(text: str) -> bool:
    """Return true when a sensitive assignment ends in an odd backslash."""
    match = SENSITIVE_VALUE_LINE.search(text)
    if match is None:
        return False
    return ends_in_odd_backslash(match.group("value"))


def ends_in_odd_backslash(text: str) -> bool:
    """Return true when a physical line ends in an unpaired backslash."""
    value = text.rstrip("\r\n").rstrip(" \t")
    if not value:
        return False
    trailing_backslashes = len(value) - len(value.rstrip("\\"))
    return trailing_backslashes % 2 == 1


def redact_lines(lines: Iterable[str]) -> Iterator[str]:
    """Redact a diagnostic stream while suppressing quoted continuations."""
    pending_quote: str | None = None
    pending_value = False
    suppress_remainder = False
    for line in lines:
        # Detection and redaction must see the same byte positions; otherwise
        # an ANSI escape embedded in an assignment can hide its opening quote.
        line = ANSI_ESCAPE.sub("", line)
        if suppress_remainder:
            yield "[REDACTED]" + ("\n" if line.endswith("\n") else "")
            continue
        if pending_value:
            value_at = len(line) - len(line.lstrip(" \t"))
            if value_at < len(line) and line[value_at] in {"\"", "'"}:
                quote = line[value_at]
                close_at = closing_quote(line, value_at + 1, quote)
                if close_at is None:
                    pending_quote = quote
                    pending_value = False
                    if ends_in_odd_backslash(line):
                        pending_quote = None
                        suppress_remainder = True
                    yield "[REDACTED]" + ("\n" if line.endswith("\n") else "")
                    continue
                tail = line[close_at + 1 :]
                pending_quote = unterminated_sensitive_quote(tail)
                pending_value = pending_quote is None and bool(
                    SENSITIVE_VALUE_PENDING.search(tail)
                )
                if pending_quote is not None and ends_in_odd_backslash(tail):
                    pending_quote = None
                    pending_value = False
                    suppress_remainder = True
                elif pending_quote is None and sensitive_unquoted_continuation(tail):
                    pending_value = False
                    suppress_remainder = True
                yield "[REDACTED]" + redact_text(tail)
                continue
            # Without a quoted boundary there is no reliable way to identify
            # where a malformed multiline value ends. Remain fail-closed for
            # the rest of the stream without accumulating its contents.
            pending_value = False
            suppress_remainder = True
            yield "[REDACTED]" + ("\n" if line.endswith("\n") else "")
            continue
        if pending_quote is not None:
            close_at = closing_quote(line, 0, pending_quote)
            if close_at is None:
                if ends_in_odd_backslash(line):
                    pending_quote = None
                    suppress_remainder = True
                yield "[REDACTED]" + ("\n" if line.endswith("\n") else "")
                continue
            if sensitive_assignment_opens_at(line, close_at):
                # Ambiguous malformed input: this quote opens a new sensitive
                # assignment and cannot prove where the older value ends.
                # A bounded nesting model could still release too early, so
                # suppress the remainder of the stream without retaining it.
                pending_quote = None
                pending_value = False
                suppress_remainder = True
                yield "[REDACTED]" + ("\n" if line.endswith("\n") else "")
                continue
            # Include the candidate closing quote while scanning the tail. It
            # may instead be the opening quote of a new sensitive JSON key on
            # a malformed diagnostic line; scanning from the following byte
            # would make that key invisible to the JSON redactor.
            quoted_tail = line[close_at:]
            redacted_tail = redact_text(quoted_tail)
            yield "[REDACTED]" + redacted_tail[1:]
            pending_quote = unterminated_sensitive_quote(quoted_tail)
            pending_value = pending_quote is None and bool(
                SENSITIVE_VALUE_PENDING.search(quoted_tail)
            )
            if pending_quote is not None and ends_in_odd_backslash(quoted_tail):
                pending_quote = None
                pending_value = False
                suppress_remainder = True
            elif pending_quote is None and sensitive_unquoted_continuation(quoted_tail):
                pending_value = False
                suppress_remainder = True
            continue

        pending_quote = unterminated_sensitive_quote(line)
        pending_value = pending_quote is None and bool(
            SENSITIVE_VALUE_PENDING.search(line)
        )
        if pending_quote is not None and ends_in_odd_backslash(line):
            pending_quote = None
            pending_value = False
            suppress_remainder = True
        elif pending_quote is None and sensitive_unquoted_continuation(line):
            pending_value = False
            suppress_remainder = True
        yield redact_text(line)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: redact-output.py LOG_FILE", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in redact_lines(handle):
                sys.stderr.write(line)
    except OSError as exc:
        print(f"ERROR: could not read staging diagnostic log: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
