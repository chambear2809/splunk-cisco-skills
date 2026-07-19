"""Shared apply-state.json helpers for the Splunk Observability GCP integration API client.

The renderer creates ``state/apply-state.json`` and ``state/idempotency-keys.json``
under the rendered output directory. Each API client appends a step record with
``timestamp``, ``section``, ``step``, ``idempotency_key``, ``result``
(``success | skipped | failed``), and a sanitized response body. Records never
contain a token, password, or project key (the redactor strips those).

This module is intentionally dependency-free so it works under the repo's
default Python 3.11 interpreter without installing anything.
"""

from __future__ import annotations

import base64
import binascii
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEY_PATTERN = (
    r"authorization|password|[a-z0-9_-]*token|client[ _-]*secret|"
    r"secret(?:[ _-]*key)?|external[ _-]*id|credentials?|"
    r"private[ _-]*key(?:[ _-]*id)?|api[ _-]*key|"
    r"access[ _-]*key(?:[ _-]*id)?|project[ _-]*key|client[ _-]*key|"
    r"app[ _-]*id|aws[ _-]*secret[ _-]*access[ _-]*key"
)
SENSITIVE_ASSIGNMENT_MARKER = re.compile(
    rf"(?i)(?<![a-z0-9_])[\"']?(?:{_SENSITIVE_KEY_PATTERN}|"
    r"[a-z0-9_-]*sha256)(?![a-z0-9_])[\"']?\s*[:=]"
)
_PRIVATE_KEY_VALUE_MARKER = re.compile(
    r"-----BEGIN (?:(?:[A-Z0-9][A-Z0-9 -]* )?PRIVATE KEY|"
    r"PGP PRIVATE KEY BLOCK)-----",
    re.IGNORECASE,
)
SECRET_VALUE_MARKERS: tuple[re.Pattern[str], ...] = (_PRIVATE_KEY_VALUE_MARKER,)
_COMPACT_JWS_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_-]+)\."
    r"([^\s.]*)\.([A-Za-z0-9_-]*)(?![A-Za-z0-9_.-])"
)
_COMPACT_JWE_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_-]+)\."
    r"([A-Za-z0-9_-]*)\.([A-Za-z0-9_-]+)\."
    r"([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)(?![A-Za-z0-9_.-])"
)
_MAX_JWT_SEGMENT_CHARS = 16 * 1024
_MAX_JWT_JSON_BYTES = 12 * 1024
_MAX_JOSE_CANDIDATES = 64
_EXACT_BEARER_VALUE = re.compile(
    r"(?i)^Bearer[ \t]+([A-Za-z0-9\-._~+/]+={0,})$"
)
_EXACT_BASIC_VALUE = re.compile(r"(?i)^Basic[ \t]+([A-Za-z0-9+/]+={0,2})$")
_AUTHORIZATION_CONTEXT = re.compile(
    r"(?i)(?:^|[\s,{;])[\"']?authorization[\"']?\s*[:=]\s*[\"']?"
    r"(Basic|Bearer)[ \t]+([A-Za-z0-9\-._~+/]+={0,2})"
)
_EMBEDDED_BASIC_VALUE = re.compile(
    r"(?i)(?<![A-Za-z0-9+/])Basic[ \t]+"
    r"([A-Za-z0-9+/]+={0,2})(?![A-Za-z0-9+/=])"
)
_EMBEDDED_BEARER_VALUE = re.compile(
    r"(?i)(?<![A-Za-z0-9\-._~+/])Bearer[ \t]+"
    r"([A-Za-z0-9\-._~+/]+={0,})(?![A-Za-z0-9\-._~+/=])"
)
_MIN_EMBEDDED_BEARER_CHARS = 16
_STRUCTURED_TEXT_ESCAPE = re.compile(
    r"\\(?:x([0-9a-fA-F]{2})|u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8}))"
)
_JSON_SHORT_ASSIGNMENT_ESCAPE = re.compile(r"\\([\"\\/bfnrt])")
_MAX_QUOTED_ASSIGNMENT_KEY_CHARS = 4096
_MAX_ESCAPE_INSPECTION_PASSES = 8
_SEMANTIC_SECRET_KEYS = frozenset(
    {
        "authorization",
        "password",
        "token",
        "accesstoken",
        "refreshtoken",
        "apitoken",
        "apikey",
        "o11ytoken",
        "clientsecret",
        "appsecret",
        "secret",
        "secretkey",
        "credentials",
        "credential",
        "privatekey",
        "privatekeyid",
        "accesskey",
        "accesskeyid",
        "projectkey",
        "clientkey",
        "appid",
        "externalid",
        "awssecretaccesskey",
        "workloadidentityfederationconfig",
        "workloadidentityfederationconfigs",
    }
)

INTERNAL_DIGEST_SCHEMAS: dict[str, frozenset[str]] = {
    "plan_sha256": frozenset({"scalar"}),
    "reviewed_state_sha256": frozenset({"scalar"}),
    "app_id_sha256": frozenset({"scalar"}),
    "secret_key_sha256": frozenset({"scalar"}),
    "secret_sha256": frozenset({"scalar"}),
    "project_key_sha256": frozenset({"mapping"}),
    "wif_config_sha256": frozenset({"scalar", "mapping"}),
}
INTERNAL_DIGEST_KEYS = frozenset(INTERNAL_DIGEST_SCHEMAS)
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")


class _UnsafeJsonForRedaction(ValueError):
    """A JSON structure that must be redacted without raw-text fallback."""

REDACT_PLACEHOLDER = "[REDACTED]"
MAX_SECRET_BYTES = 64 * 1024


def _is_lower_sha256(value: Any) -> bool:
    return isinstance(value, str) and _LOWER_SHA256.fullmatch(value) is not None


def is_valid_internal_digest(key: Any, value: Any) -> bool:
    """Validate an explicitly allowlisted internal digest field and its shape."""
    if not isinstance(key, str) or key not in INTERNAL_DIGEST_SCHEMAS:
        return False
    allowed = INTERNAL_DIGEST_SCHEMAS[key]
    if "scalar" in allowed and _is_lower_sha256(value):
        return True
    if "list" in allowed and isinstance(value, list):
        return all(_is_lower_sha256(item) for item in value)
    if "mapping" in allowed and isinstance(value, dict):
        return all(
            is_safe_mapping_key(item_key)
            and _is_lower_sha256(item_value)
            for item_key, item_value in value.items()
        )
    return False


def _strict_json_for_redaction(value: str) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for key, item in pairs:
            if key in document:
                raise _UnsafeJsonForRedaction(f"duplicate JSON key {key!r}")
            document[key] = item
        return document

    def reject_constant(constant: str) -> Any:
        raise _UnsafeJsonForRedaction(
            f"non-standard JSON constant {constant!r}"
        )

    return json.loads(
        value,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )


def _decode_base64url_segment(segment: str, *, allow_empty: bool = False) -> bytes:
    if not segment:
        if allow_empty:
            return b""
        raise ValueError("JOSE segment is empty")
    if len(segment) > _MAX_JWT_SEGMENT_CHARS or len(segment) % 4 == 1:
        raise ValueError("JWT segment is empty or too large")
    padding = "=" * ((4 - len(segment) % 4) % 4)
    decoded = base64.b64decode(
        (segment + padding).encode("ascii"), altchars=b"-_", validate=True
    )
    if base64.urlsafe_b64encode(decoded).rstrip(b"=") != segment.encode("ascii"):
        raise ValueError("JOSE segment is not canonical unpadded base64url")
    return decoded


def _contains_structural_jose(value: str) -> bool:
    candidate_count = 0
    for candidate in _COMPACT_JWS_CANDIDATE.finditer(value):
        candidate_count += 1
        if candidate_count > _MAX_JOSE_CANDIDATES:
            return True
        header_segment, payload_segment, signature_segment = candidate.groups()
        if any(
            len(segment) > _MAX_JWT_SEGMENT_CHARS
            for segment in candidate.groups()
        ):
            return True
        try:
            header_raw = _decode_base64url_segment(header_segment)
            if len(header_raw) > _MAX_JWT_JSON_BYTES:
                return True
            header = _strict_json_for_redaction(
                header_raw.decode("utf-8", errors="strict")
            )
        except (binascii.Error, UnicodeError, ValueError, RecursionError):
            continue
        if not isinstance(header, dict):
            continue
        try:
            signature_raw = _decode_base64url_segment(
                signature_segment, allow_empty=True
            )
            if header.get("b64", True) is False:
                critical = header.get("crit")
                if (
                    not isinstance(critical, list)
                    or "b64" not in critical
                    or len(critical) != len(set(critical))
                    or not all(isinstance(item, str) and item for item in critical)
                ):
                    continue
                if len(payload_segment.encode("utf-8")) > _MAX_JWT_JSON_BYTES:
                    return True
            else:
                if "b64" in header and header["b64"] is not True:
                    continue
                payload_raw = _decode_base64url_segment(
                    payload_segment, allow_empty=True
                )
                if len(payload_raw) > _MAX_JWT_JSON_BYTES:
                    return True
        except (binascii.Error, UnicodeError, ValueError):
            continue
        algorithm = header.get("alg")
        if algorithm == "none":
            if signature_raw:
                continue
        elif isinstance(algorithm, str) and algorithm:
            if not signature_raw:
                continue
        elif header == {} and len(signature_segment) >= 16:
            try:
                payload = _strict_json_for_redaction(
                    _decode_base64url_segment(payload_segment)
                    .decode("utf-8", errors="strict")
                )
            except (binascii.Error, UnicodeError, ValueError, RecursionError):
                continue
            if not isinstance(payload, dict):
                continue
        else:
            continue
        return True
    for candidate in _COMPACT_JWE_CANDIDATE.finditer(value):
        candidate_count += 1
        if candidate_count > _MAX_JOSE_CANDIDATES:
            return True
        (
            header_segment,
            encrypted_key_segment,
            iv_segment,
            ciphertext_segment,
            tag_segment,
        ) = candidate.groups()
        if any(
            len(segment) > _MAX_JWT_SEGMENT_CHARS
            for segment in candidate.groups()
        ):
            return True
        try:
            header_raw = _decode_base64url_segment(header_segment)
            _decode_base64url_segment(encrypted_key_segment, allow_empty=True)
            _decode_base64url_segment(iv_segment)
            _decode_base64url_segment(ciphertext_segment)
            _decode_base64url_segment(tag_segment)
            if len(header_raw) > _MAX_JWT_JSON_BYTES:
                return True
            header = _strict_json_for_redaction(
                header_raw.decode("utf-8", errors="strict")
            )
        except (
            binascii.Error,
            UnicodeError,
            ValueError,
            RecursionError,
        ):
            continue
        if (
            isinstance(header, dict)
            and isinstance(header.get("alg"), str)
            and header["alg"]
            and isinstance(header.get("enc"), str)
            and header["enc"]
        ):
            return True
    return False


def _is_basic_credential(token: str) -> bool:
    try:
        decoded = base64.b64decode(token.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeError, ValueError):
        return False
    return base64.b64encode(decoded).decode("ascii") == token and b":" in decoded


def _contains_auth_credential(value: str) -> bool:
    stripped = value.strip()
    bearer = _EXACT_BEARER_VALUE.fullmatch(stripped)
    if bearer is not None:
        return True
    basic = _EXACT_BASIC_VALUE.fullmatch(stripped)
    if basic is not None and _is_basic_credential(basic.group(1)):
        return True
    for context in _AUTHORIZATION_CONTEXT.finditer(value):
        scheme, token = context.groups()
        if scheme.casefold() == "bearer" or _is_basic_credential(token):
            return True
    for embedded in _EMBEDDED_BASIC_VALUE.finditer(value):
        if _is_basic_credential(embedded.group(1)):
            return True
    for embedded in _EMBEDDED_BEARER_VALUE.finditer(value):
        token = embedded.group(1)
        if len(token) >= _MIN_EMBEDDED_BEARER_CHARS:
            return True
    return False


def _decode_structured_text_escapes_for_inspection(value: str) -> str:
    current = value
    for _ in range(_MAX_ESCAPE_INSPECTION_PASSES):
        if _STRUCTURED_TEXT_ESCAPE.search(current) is None:
            return current

        def decode_escape(match: re.Match[str]) -> str:
            encoded = next(group for group in match.groups() if group is not None)
            codepoint = int(encoded, 16)
            if codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
                raise _UnsafeJsonForRedaction("invalid Unicode escape code point")
            return chr(codepoint)

        current = _STRUCTURED_TEXT_ESCAPE.sub(decode_escape, current)
    if _STRUCTURED_TEXT_ESCAPE.search(current) is not None:
        raise _UnsafeJsonForRedaction("nested Unicode escape depth exceeds limit")
    return current


def _remove_default_ignorables(value: str) -> str:
    visible: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if category == "Cs":
            raise _UnsafeJsonForRedaction("surrogate code point in inspected text")
        if category in {"Cf", "Mn", "Me"}:
            continue
        if 0xFE00 <= ord(character) <= 0xFE0F:
            continue
        if 0xE0100 <= ord(character) <= 0xE01EF:
            continue
        visible.append(character)
    return "".join(visible)


def _inspection_view(value: str) -> tuple[str, bool]:
    current = value
    transformed = False
    for _ in range(_MAX_ESCAPE_INSPECTION_PASSES):
        decoded = _decode_structured_text_escapes_for_inspection(current)
        compatible = unicodedata.normalize("NFKC", decoded)
        visible = _remove_default_ignorables(compatible)
        transformed = transformed or (
            decoded != current or compatible != decoded or visible != compatible
        )
        folded = visible.casefold()
        if folded == current:
            return folded, transformed
        current = folded
    raise _UnsafeJsonForRedaction("inspection normalization depth exceeds limit")


def _decode_json_short_assignment_escapes(value: str) -> str:
    replacements = {
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "n": "\n",
        "r": "\r",
        "t": "\t",
    }
    current = value
    for _ in range(_MAX_ESCAPE_INSPECTION_PASSES):
        updated = _JSON_SHORT_ASSIGNMENT_ESCAPE.sub(
            lambda match: replacements[match.group(1)], current
        )
        if updated == current:
            return current
        current = updated
    if _JSON_SHORT_ASSIGNMENT_ESCAPE.search(current) is not None:
        raise _UnsafeJsonForRedaction("nested JSON short-escape depth exceeds limit")
    return current


def _iter_quoted_assignment_keys(value: str) -> Any:
    """Yield quoted assignment keys with a bounded, single-pass scanner."""
    index = 0
    while index < len(value):
        quote = value[index]
        if quote not in {'"', "'"}:
            index += 1
            continue
        start = index + 1
        cursor = start
        while cursor < len(value):
            character = value[cursor]
            if character == "\\" and cursor + 1 < len(value):
                cursor += 2
                continue
            if character != quote:
                cursor += 1
                continue
            delimiter = cursor + 1
            while delimiter < len(value) and value[delimiter] in " \t\r\n":
                delimiter += 1
            if delimiter < len(value) and value[delimiter] in ":=":
                size = cursor - start
                yield (
                    value[start:cursor]
                    if size <= _MAX_QUOTED_ASSIGNMENT_KEY_CHARS
                    else "",
                    size > _MAX_QUOTED_ASSIGNMENT_KEY_CHARS,
                )
            index = cursor + 1
            break
        else:
            return


def _contains_assignment(value: str, classifier: Any) -> bool:
    for candidate, oversized in _iter_quoted_assignment_keys(value):
        if oversized or classifier(candidate):
            return True
    for line in re.split(r"(?:\r\n|[\r\n]|\\[nr])", value):
        segment_start = 0
        for delimiter in re.finditer(r"[:=]", line):
            candidate = line[segment_start : delimiter.start()].strip(" \t\"'")
            segment_start = delimiter.end()
            if candidate and classifier(candidate):
                return True
    return False


def _is_sensitive_assignment_key(key: str) -> bool:
    """Classify free-form assignment keys without structured digest exemptions."""
    try:
        inspected, _transformed = _inspection_view(
            _decode_json_short_assignment_escapes(key)
        )
    except _UnsafeJsonForRedaction:
        return True
    canonical = re.sub(r"[^a-z0-9]", "", inspected)
    if canonical == "namedtoken":
        return False
    return (
        "sha256" in canonical
        or "clientsecret" in canonical
        or canonical.endswith("token")
        or canonical in _SEMANTIC_SECRET_KEYS
        or any(canonical.endswith(secret_key) for secret_key in _SEMANTIC_SECRET_KEYS)
    )


def _is_semantic_secret_assignment_key(key: str) -> bool:
    try:
        inspected, _transformed = _inspection_view(
            _decode_json_short_assignment_escapes(key)
        )
    except _UnsafeJsonForRedaction:
        return True
    canonical = re.sub(r"[^a-z0-9]", "", inspected)
    if canonical == "namedtoken":
        return False
    return (
        canonical.endswith("sha256")
        or "clientsecret" in canonical
        or canonical.endswith("token")
        or any(
            canonical == secret_key or canonical.endswith(secret_key)
            for secret_key in _SEMANTIC_SECRET_KEYS
        )
    )


def _contains_sensitive_assignment(value: str) -> bool:
    return _contains_assignment(value, _is_sensitive_assignment_key)


def _contains_semantic_secret_assignment(value: str) -> bool:
    return _contains_assignment(value, _is_semantic_secret_assignment_key)


def is_safe_mapping_key(key: Any) -> bool:
    """Validate path/project mapping keys without rejecting safe diagnostic paths."""
    if not isinstance(key, str) or not key or _redact_string(key) != key:
        return False
    try:
        inspected, transformed = _inspection_view(key)
    except _UnsafeJsonForRedaction:
        return False
    if transformed:
        return not is_sensitive_key(inspected)
    return True


def _redact_string(value: str) -> str:
    try:
        parsed = _strict_json_for_redaction(value)
    except (_UnsafeJsonForRedaction, RecursionError):
        return REDACT_PLACEHOLDER
    except json.JSONDecodeError:
        try:
            inspected, _transformed = _inspection_view(value)
        except _UnsafeJsonForRedaction:
            return REDACT_PLACEHOLDER
        return (
            REDACT_PLACEHOLDER
            if _contains_sensitive_assignment(value)
            or _contains_sensitive_assignment(inspected)
            or _contains_structural_jose(value)
            or _contains_structural_jose(inspected)
            or _contains_auth_credential(value)
            or _contains_auth_credential(inspected)
            or any(
                marker.search(candidate)
                for candidate in (value, inspected)
                for marker in SECRET_VALUE_MARKERS
            )
            else value
        )
    try:
        sanitized = redact(parsed)
    except RecursionError:
        return REDACT_PLACEHOLDER
    return value if sanitized == parsed else REDACT_PLACEHOLDER


def redact(value: Any) -> Any:
    """Walk a value and replace anything that looks like a secret."""
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or _redact_string(key) != key:
                continue
            if key in INTERNAL_DIGEST_KEYS:
                redacted[key] = (
                    item
                    if is_valid_internal_digest(key, item)
                    else REDACT_PLACEHOLDER
                )
            elif is_sensitive_key(key):
                redacted[key] = REDACT_PLACEHOLDER
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def is_sensitive_key(key: Any) -> bool:
    """Classify structured credential keys across every local persistence path."""
    if not isinstance(key, str):
        return True
    if key in INTERNAL_DIGEST_KEYS:
        return False
    try:
        inspected, _transformed = _inspection_view(key)
    except _UnsafeJsonForRedaction:
        return True
    canonical = re.sub(r"[^a-z0-9]", "", inspected)
    if canonical.endswith("sha256"):
        return True
    if canonical in {
        "idempotencykey",
        "operationid",
        "attemptid",
        "namedtoken",
    }:
        return False
    return canonical.endswith("key") or "credential" in canonical or any(s in canonical for s in (
        "token", "password", "secret", "apikey", "jwt", "appid", "privatekey",
        "authorization", "xsftoken", "externalid", "awssecret",
        "accesskey", "awsaccesskey", "projectkey", "wifconfig",
        "workloadidentityfederationconfig", "workloadidentityfederationconfigs",
    ))


def is_high_confidence_secret_key(key: Any) -> bool:
    """Identify unexpected structured secret keys without heuristic substrings."""
    if not isinstance(key, str):
        return True
    try:
        inspected, _transformed = _inspection_view(key)
    except _UnsafeJsonForRedaction:
        return True
    canonical = re.sub(r"[^a-z0-9]", "", inspected)
    return (
        canonical.endswith("sha256")
        or canonical in _SEMANTIC_SECRET_KEYS
        or _contains_semantic_secret_assignment(key)
        or _contains_structural_jose(key)
        or _PRIVATE_KEY_VALUE_MARKER.search(inspected) is not None
    )


def contains_high_confidence_secret(value: str) -> bool:
    """Detect credential material suitable for fail-closed semantic snapshots."""
    if not isinstance(value, str):
        return False
    try:
        inspected, _transformed = _inspection_view(value)
    except _UnsafeJsonForRedaction:
        return True
    if (
        _contains_auth_credential(value)
        or _contains_auth_credential(inspected)
        or _contains_structural_jose(value)
        or _contains_structural_jose(inspected)
        or _PRIVATE_KEY_VALUE_MARKER.search(inspected) is not None
        or _contains_semantic_secret_assignment(value)
        or _contains_semantic_secret_assignment(inspected)
    ):
        return True
    try:
        parsed = _strict_json_for_redaction(value)
    except (_UnsafeJsonForRedaction, RecursionError):
        return True
    except json.JSONDecodeError:
        return False
    return _semantic_structure_contains_secret(parsed)


def _semantic_structure_contains_secret(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            is_high_confidence_secret_key(key)
            or _semantic_structure_contains_secret(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_semantic_structure_contains_secret(item) for item in value)
    if isinstance(value, str):
        return contains_high_confidence_secret(value)
    return False


_looks_secret_key = is_sensitive_key


@dataclass(frozen=True)
class SecureDirectory:
    """An absolute directory path anchored by a held no-follow descriptor."""

    path: Path
    fd: int


def _canonicalize_platform_directory_alias(path: Path) -> Path:
    """Resolve only audited root-owned macOS /var and /tmp platform aliases."""
    for alias, destination in (
        (Path("/var"), Path("/private/var")),
        (Path("/tmp"), Path("/private/tmp")),
    ):
        if path.parts[: len(alias.parts)] != alias.parts:
            continue
        try:
            metadata = alias.lstat()
        except OSError:
            continue
        if not stat.S_ISLNK(metadata.st_mode) or metadata.st_uid != 0:
            continue
        target = Path(os.readlink(alias))
        if not target.is_absolute():
            target = alias.parent / target
        if target != destination:
            raise PermissionError(f"unreviewed root platform directory alias: {alias}")
        return destination.joinpath(*path.parts[len(alias.parts):])
    return path


@contextmanager
def secure_private_directory(
    path: Path,
    *,
    allow_shared_sticky: bool = False,
    create: bool = True,
):
    """Open every directory component with openat/O_NOFOLLOW and hold the leaf."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise PermissionError("platform lacks O_NOFOLLOW/O_DIRECTORY for private paths")
    absolute = path if path.is_absolute() else Path.cwd() / path
    absolute = _canonicalize_platform_directory_alias(absolute)
    if ".." in absolute.parts:
        raise PermissionError(f"private directory must not contain parent traversal: {path}")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open("/", flags)
    current = Path("/")
    try:
        components = absolute.parts[1:]
        for index, component in enumerate(components):
            current = current / component
            created = False
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise PermissionError(f"private directory is missing: {current}")
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise PermissionError(
                        f"private directory component could not be opened safely: {current}"
                    ) from exc
            except OSError as exc:
                raise PermissionError(
                    f"private directory component must not be a symlink: {current}"
                ) from exc
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            mode = stat.S_IMODE(metadata.st_mode)
            sticky_shared = bool(metadata.st_mode & stat.S_ISVTX and mode & stat.S_IWOTH)
            trusted_shared_sticky = sticky_shared and metadata.st_uid == 0
            if not stat.S_ISDIR(metadata.st_mode):
                raise PermissionError(f"private path component is not a directory: {current}")
            if index < len(components) - 1:
                current_uid = os.getuid() if hasattr(os, "getuid") else metadata.st_uid
                if metadata.st_uid not in {0, current_uid} and not trusted_shared_sticky:
                    raise PermissionError(
                        f"private directory ancestor has an untrusted owner: {current}"
                    )
                if mode & (stat.S_IWGRP | stat.S_IWOTH) and not trusted_shared_sticky:
                    raise PermissionError(
                        f"private directory ancestor is writable by other users: {current}"
                    )
                continue
            current_uid = os.getuid() if hasattr(os, "getuid") else metadata.st_uid
            allowed_shared = allow_shared_sticky and trusted_shared_sticky
            if metadata.st_uid != current_uid and not allowed_shared:
                raise PermissionError(
                    f"private directory must be owned by the current user: {current}"
                )
            if mode & (stat.S_IWGRP | stat.S_IWOTH) and not allowed_shared:
                raise PermissionError(
                    f"private directory must not be group/world writable: {current}"
                )
            if created and mode != 0o700:
                raise PermissionError(
                    f"new private directory was not created mode 0700: {current}"
                )
        yield SecureDirectory(absolute, descriptor)
    finally:
        os.close(descriptor)


def _prepare_directory(path: Path, *, allow_shared_sticky: bool) -> None:
    """Create missing components privately while rejecting every symlink ancestor."""
    with secure_private_directory(
        path, allow_shared_sticky=allow_shared_sticky, create=True
    ):
        pass


def prepare_private_directory(path: Path) -> None:
    """Prepare an owned, non-writable-by-others directory without chmodding it."""
    _prepare_directory(path, allow_shared_sticky=False)


def _validate_existing_private_file(directory: SecureDirectory, name: str) -> None:
    try:
        metadata = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PermissionError(f"private JSON is unreadable: {directory.path / name}") from exc
    current_uid = os.getuid() if hasattr(os, "getuid") else metadata.st_uid
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != current_uid
    ):
        raise PermissionError(f"refusing to replace unsafe private JSON: {directory.path / name}")


def _write_all(descriptor: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short write to private file")
        view = view[written:]


def open_secure_lock_file(
    directory: SecureDirectory, name: str, *, label: str
) -> int:
    """Create a 0600 lock atomically or validate an existing lock before open."""
    base_flags = os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    current_uid = os.getuid() if hasattr(os, "getuid") else None
    try:
        descriptor = os.open(
            name,
            base_flags | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory.fd,
        )
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
    except FileExistsError:
        existing = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_nlink != 1
            or (current_uid is not None and existing.st_uid != current_uid)
            or stat.S_IMODE(existing.st_mode) != 0o600
        ):
            raise PermissionError(
                f"{label} must be an owned single-hardlink mode-0600 regular file: "
                f"{directory.path / name}"
            )
        descriptor = os.open(name, base_flags, dir_fd=directory.fd)
        metadata = os.fstat(descriptor)
        if (metadata.st_dev, metadata.st_ino) != (existing.st_dev, existing.st_ino):
            os.close(descriptor)
            raise PermissionError(f"{label} changed while opening: {directory.path / name}")
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or (current_uid is not None and metadata.st_uid != current_uid)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        os.close(descriptor)
        raise PermissionError(
            f"{label} failed secure validation: {directory.path / name}"
        )
    return descriptor


def _write_private_json_at(
    directory: SecureDirectory,
    path: Path,
    value: Any,
    *,
    redact_value: bool,
) -> None:
    """Atomically write JSON through a mode-0600 temporary sibling."""
    content = (
        json.dumps(redact(value) if redact_value else value, indent=2) + "\n"
    ).encode("utf-8")
    _validate_existing_private_file(directory, path.name)
    temporary = f".{path.name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory.fd)
        os.fchmod(descriptor, 0o600)
        _write_all(descriptor, content)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(
            temporary,
            path.name,
            src_dir_fd=directory.fd,
            dst_dir_fd=directory.fd,
        )
        temporary = ""
        os.fsync(directory.fd)
        final = os.stat(path.name, dir_fd=directory.fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(final.st_mode)
            or final.st_nlink != 1
            or stat.S_IMODE(final.st_mode) != 0o600
        ):
            raise PermissionError(f"private JSON failed final validation: {path}")
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary, dir_fd=directory.fd)
            except FileNotFoundError:
                pass


def write_private_json(
    path: Path,
    value: Any,
    *,
    redact_value: bool = True,
    _directory: SecureDirectory | None = None,
) -> None:
    """Atomically write JSON through a mode-0600 temporary sibling."""
    if _directory is not None:
        _write_private_json_at(_directory, path, value, redact_value=redact_value)
        return
    with secure_private_directory(
        path.parent, allow_shared_sticky=True
    ) as directory:
        _write_private_json_at(directory, path, value, redact_value=redact_value)


def _state_path(state_dir: Path) -> Path:
    return state_dir / "apply-state.json"


def _load_state(state_path: Path, directory: SecureDirectory) -> dict[str, Any]:
    try:
        metadata = os.stat(state_path.name, dir_fd=directory.fd, follow_symlinks=False)
    except FileNotFoundError:
        return {"steps": []}
    current_uid = os.getuid() if hasattr(os, "getuid") else metadata.st_uid
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != current_uid
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        raise PermissionError(f"apply state must be an owned mode-0600 regular file: {state_path}")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            state_path.name,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory.fd,
        )
        opened = os.fstat(descriptor)
        identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_nlink,
            metadata.st_uid,
            stat.S_IMODE(metadata.st_mode),
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_nlink,
            opened.st_uid,
            stat.S_IMODE(opened.st_mode),
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        ) != identity:
            raise PermissionError(f"apply state changed while opening: {state_path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > 8 * 1024 * 1024:
                raise ValueError(f"apply state is too large: {state_path}")
        final = os.fstat(descriptor)
        after = os.stat(state_path.name, dir_fd=directory.fd, follow_symlinks=False)
        if any(
            (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_nlink,
                item.st_uid,
                stat.S_IMODE(item.st_mode),
                item.st_mtime_ns,
                item.st_ctime_ns,
            ) != identity
            for item in (final, after)
        ) or total != metadata.st_size:
            raise PermissionError(f"apply state changed or was short-read: {state_path}")
        state = json.loads(b"".join(chunks).decode("utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot trust invalid apply state {state_path}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(state, dict) or set(state) != {"steps"} or not isinstance(state["steps"], list):
        raise ValueError(f"cannot trust malformed apply state {state_path}")
    return state


@contextmanager
def _journal_lock(state_dir: Path):
    """Serialize all read-modify-write operations on the shared journal."""
    descriptor: int | None = None
    with secure_private_directory(state_dir) as directory:
        try:
            descriptor = open_secure_lock_file(
                directory, ".apply-state.lock", label="journal lock"
            )
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield directory
        finally:
            if descriptor is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)


def _append_step_unlocked(
    state_dir: Path,
    section: str,
    step: str,
    idempotency_key: str,
    result: str,
    response: Any | None,
    notes: str | None,
    directory: SecureDirectory,
) -> None:
    state_path = _state_path(state_dir)
    state = _load_state(state_path, directory)
    state["steps"].append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "section": section,
        "step": step,
        "idempotency_key": idempotency_key,
        "result": result,
        "notes": notes,
        "response": redact(response),
    })
    write_private_json(state_path, state, _directory=directory)


def append_step(
    state_dir: Path,
    section: str,
    step: str,
    idempotency_key: str,
    result: str,
    response: Any | None = None,
    notes: str | None = None,
) -> None:
    """Append a serialized, redacted step record to ``apply-state.json``."""
    with _journal_lock(state_dir) as directory:
        _append_step_unlocked(
            state_dir, section, step, idempotency_key, result, response, notes, directory
        )


def claim_rollback_attempt(
    state_dir: Path,
    *,
    plan_path: Path,
    claim_root: Path | SecureDirectory,
    provider: str,
    realm: str,
    action: str,
    integration_id: str,
    plan_id: str,
    plan_sha256: str,
) -> str:
    """Durably consume one reviewed plan before its single mutation attempt."""
    if not isinstance(plan_sha256, str) or not re.fullmatch(
        r"[0-9a-fA-F]{64}", plan_sha256
    ):
        raise ValueError("plan_sha256 must be exactly 64 hexadecimal characters")
    plan_sha256 = plan_sha256.lower()
    idempotency_key = ":".join(
        (
            provider.lower(),
            realm,
            "rollback",
            action,
            integration_id,
            plan_id,
            plan_sha256.lower(),
        )
    )
    marker_digest = hashlib.sha256(
        f"{provider}:{realm}:{integration_id}:{plan_id}:{plan_sha256.lower()}".encode("utf-8")
    ).hexdigest()
    marker = json.dumps(
        {
            "provider": provider,
            "realm": realm,
            "action": action,
            "integration_id": integration_id,
            "plan_id": plan_id,
            "plan_sha256": plan_sha256.lower(),
            "status": "attempted",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    _create_exclusive_marker(
        claim_root,
        f".rollback-consumed-{marker_digest}.json",
        marker,
        consumed=True,
    )
    _create_exclusive_marker(
        plan_path.parent,
        f".rollback-attempt-{marker_digest}.json",
        marker,
        consumed=False,
    )
    with _journal_lock(state_dir) as directory:
        state_path = _state_path(state_dir)
        state = _load_state(state_path, directory)
        if any(
            isinstance(entry, dict) and entry.get("idempotency_key") == idempotency_key
            for entry in state["steps"]
        ):
            raise ValueError("rollback plan has already been attempted and cannot be reused")
        state["steps"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "section": "integration",
            "step": "rollback-plan-attempt",
            "idempotency_key": idempotency_key,
            "result": "attempted",
            "notes": "plan consumed before the single mutation attempt",
            "response": {
                "provider": provider,
                "realm": realm,
                "action": action,
                "integration_id": integration_id,
                "plan_id": plan_id,
                "plan_sha256": plan_sha256.lower(),
            },
        })
        write_private_json(state_path, state, _directory=directory)
    return idempotency_key


def _create_exclusive_marker_at(
    directory: SecureDirectory,
    name: str,
    content: bytes,
    *,
    consumed: bool,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if not hasattr(os, "O_NOFOLLOW"):
        raise PermissionError("platform lacks O_NOFOLLOW; cannot claim rollback plans safely")
    flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory.fd)
        metadata = os.fstat(descriptor)
        current_uid = os.getuid() if hasattr(os, "getuid") else metadata.st_uid
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != current_uid
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise PermissionError(
                f"rollback attempt marker is unsafe: {directory.path / name}"
            )
        _write_all(descriptor, content)
        os.fsync(descriptor)
    except FileExistsError as exc:
        kind = "plan" if consumed else "plan audit receipt"
        raise ValueError(f"rollback {kind} has already been attempted and cannot be reused") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    os.fsync(directory.fd)


def _create_exclusive_marker(
    directory: Path | SecureDirectory,
    name: str,
    content: bytes,
    *,
    consumed: bool,
) -> None:
    if isinstance(directory, SecureDirectory):
        _create_exclusive_marker_at(directory, name, content, consumed=consumed)
        return
    with secure_private_directory(
        directory, allow_shared_sticky=True
    ) as anchored:
        _create_exclusive_marker_at(anchored, name, content, consumed=consumed)


def has_step(state_dir: Path, idempotency_key: str) -> bool:
    """Return True when a previous run recorded a successful step under the same idempotency key."""
    with _journal_lock(state_dir) as directory:
        state = _load_state(_state_path(state_dir), directory)
        return any(
            isinstance(entry, dict)
            and entry.get("idempotency_key") == idempotency_key
            and entry.get("result") == "success"
            for entry in state["steps"]
        )


def read_private_file_bytes(
    path: str | os.PathLike[str],
    *,
    allow_loose: bool = False,
    max_bytes: int = MAX_SECRET_BYTES,
    label: str = "secret file",
) -> bytes:
    """Read stable bytes once from an owned, bounded, non-symlink private file."""
    p = Path(os.fspath(path))
    if max_bytes <= 0:
        raise ValueError("private file size limit must be positive")
    descriptor: int | None = None
    try:
        with secure_private_directory(
            p.parent, allow_shared_sticky=True, create=False
        ) as directory:
            metadata = os.stat(p.name, dir_fd=directory.fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise PermissionError(
                    f"input file must be a regular, non-symlink file: {p} ({label})"
                )
            if metadata.st_size == 0 or metadata.st_size > max_bytes:
                raise PermissionError(f"input file is empty or too large: {p} ({label})")
            if metadata.st_nlink != 1:
                raise PermissionError(
                    f"input file must have exactly one hard link: {p} ({label})"
                )
            if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
                raise PermissionError(
                    f"input file must be owned by the current user: {p} ({label})"
                )
            mode = stat.S_IMODE(metadata.st_mode)
            if mode != 0o600 and not allow_loose:
                raise PermissionError(
                    f"{label} {p} has loose permissions ({oct(mode)}); mode 600 is required."
                )
            descriptor = os.open(
                p.name,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
                dir_fd=directory.fd,
            )
            opened = os.fstat(descriptor)
            identity = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_nlink,
                metadata.st_uid,
                stat.S_IMODE(metadata.st_mode),
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
            if (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_nlink,
                opened.st_uid,
                stat.S_IMODE(opened.st_mode),
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            ) != identity:
                raise PermissionError(
                    f"input file changed while it was being opened: {p} ({label})"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(65536, max_bytes + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > max_bytes:
                    raise PermissionError(
                        f"input file exceeds the size limit: {p} ({label})"
                    )
            final_opened = os.fstat(descriptor)
            after = os.stat(p.name, dir_fd=directory.fd, follow_symlinks=False)
            final_identity = (
                final_opened.st_dev,
                final_opened.st_ino,
                final_opened.st_size,
                final_opened.st_nlink,
                final_opened.st_uid,
                stat.S_IMODE(final_opened.st_mode),
                final_opened.st_mtime_ns,
                final_opened.st_ctime_ns,
            )
            entry_identity = (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_nlink,
                after.st_uid,
                stat.S_IMODE(after.st_mode),
                after.st_mtime_ns,
                after.st_ctime_ns,
            )
            if final_identity != identity or entry_identity != identity or total != metadata.st_size:
                raise PermissionError(
                    f"input file changed or was short-read: {p} ({label})"
                )
            raw = b"".join(chunks)
    except PermissionError:
        raise
    except OSError as exc:
        raise PermissionError(
            f"input file could not be opened safely: {p} ({label})"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return raw


def read_secret_file_material(
    path: str | os.PathLike[str], allow_loose: bool = False
) -> tuple[str, bytes]:
    """Read and parse one secret line, returning the exact bytes from the same open."""
    p = Path(os.fspath(path))
    raw = read_private_file_bytes(p, allow_loose=allow_loose)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError(f"input file must contain UTF-8 text: {p} (secret file)") from exc
    if text.endswith("\r\n"):
        value = text[:-2]
    elif text.endswith("\n"):
        value = text[:-1]
    else:
        value = text
    if (
        not value
        or "\n" in value
        or "\r" in value
        or any(not (0x21 <= ord(character) <= 0x7E) for character in value)
    ):
        raise ValueError(
            f"input file must contain exactly one non-empty line: {p} (secret file)"
        )
    return value, raw


def read_secret_file(path: str | os.PathLike[str], allow_loose: bool = False) -> str:
    """Read one bounded line from a stable, mode-0600 regular file."""
    value, _raw = read_secret_file_material(path, allow_loose=allow_loose)
    return value
