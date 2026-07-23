#!/usr/bin/env python3
"""Render and validate a non-mutating Cisco collaboration onboarding packet."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import io
import json
import math
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SKILL_NAME = "cisco-collaboration-setup"
API_VERSION = "cisco-collaboration-setup/v1"
BUNDLE_SCHEMA = "cisco-collaboration-setup/bundle/v1"
BASE_COMMIT = "4c4712a136c9cd770440c85f25063e4fe61f2ce3"
SC4S_COMMIT = "f878a6e8031b07ae8777e97738b27afe735f118d"
CHECKED_DATE = "2026-07-19"
MARKER_NAME = ".cisco-collaboration-setup"
MAX_SPEC_BYTES = 1_048_576
MAX_EVIDENCE_BYTES = 5_242_880
MAX_ARTIFACT_BYTES = 5_242_880

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
DEFAULT_SPEC = SKILL_DIR / "template.example"
DEFAULT_OUTPUT = REPO_ROOT / "cisco-collaboration-rendered"
SOURCE_LEDGER_PATH = SKILL_DIR / "references" / "source-ledger.json"
sys.path.insert(0, str(REPO_ROOT / "skills" / "shared" / "lib"))
from yaml_compat import YamlCompatError, _SimpleYamlParser, load_yaml_or_json  # noqa: E402


class SpecError(ValueError):
    """Raised when input or output violates a fail-closed contract."""


SECRET_KEY_RE = re.compile(
    r"(?:^|[_-])(?:password|passwd|secret|token|credential|authorization|"
    r"api[_-]?key|private[_-]?key|client[_-]?secret|encryption[_-]?key|key[_-]?file)(?:$|[_-])",
    re.IGNORECASE,
)
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
INDEX_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SOURCETYPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_*.-]{1,127}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TECHNICAL_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$", re.ASCII)
EMAIL_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])",
    re.ASCII,
)
CREDENTIAL_LITERAL_RE = re.compile(
    r"(?:\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b)",
    re.ASCII,
)
OPENAI_CREDENTIAL_RE = re.compile(
    r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}(?![A-Za-z0-9_-])",
    re.ASCII,
)
GOOGLE_API_CREDENTIAL_RE = re.compile(
    r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])",
    re.ASCII,
)
FORBIDDEN_SPL_RE = re.compile(
    r"(?:^|\|)\s*(?:collect|delete|outputlookup|sendemail|script|run|rest|map|"
    r"loadjob|outputcsv|sendresults|mcollect|metasearch|inputlookup|loadjob|"
    r"dbxquery|makeresults)\b",
    re.IGNORECASE,
)
READ_ONLY_SPL_COMMANDS = {
    "dedup",
    "eval",
    "fields",
    "head",
    "rename",
    "search",
    "sort",
    "stats",
    "table",
    "where",
}

CDR_REQUIRED_FIELDS = {
    "cdrRecordType",
    "globalCallID_callManagerId",
    "globalCallID_callId",
    "origLegCallIdentifier",
    "dateTimeOrigination",
    "callingPartyNumber",
    "finalCalledPartyNumber",
}
CDR_REQUIRED_TYPES = {
    "cdrRecordType": "INTEGER",
    "globalCallID_callManagerId": "INTEGER",
    "globalCallID_callId": "INTEGER",
    "origLegCallIdentifier": "INTEGER",
    "dateTimeOrigination": "INTEGER",
    "callingPartyNumber": "VARCHAR(50)",
    "finalCalledPartyNumber": "VARCHAR(50)",
}
CDR_INTEGER_FIELDS = {
    "cdrRecordType",
    "globalCallID_callManagerId",
    "globalCallID_callId",
    "origLegCallIdentifier",
    "dateTimeOrigination",
}
CDR_POSITIVE_INTEGER_FIELDS = {
    "globalCallID_callManagerId",
    "globalCallID_callId",
    "origLegCallIdentifier",
}
CMR_REQUIRED_FIELDS = {
    "cdrRecordType",
    "globalCallID_callManagerId",
    "nodeId",
    "callIdentifier",
    "dateTimeStamp",
    "numberPacketsLost",
    "jitter",
    "latency",
}
CMR_REQUIRED_TYPES = {
    "cdrRecordType": "INTEGER",
    "globalCallID_callManagerId": "INTEGER",
    "nodeId": "INTEGER",
    "callIdentifier": "INTEGER",
    "dateTimeStamp": "INTEGER",
    "numberPacketsLost": "INTEGER",
    "jitter": "INTEGER",
    "latency": "INTEGER",
}
CMR_INTEGER_FIELDS = set(CMR_REQUIRED_FIELDS)
CMR_POSITIVE_INTEGER_FIELDS = {
    "globalCallID_callManagerId",
    "nodeId",
    "callIdentifier",
}
CMR_UNSIGNED_INTEGER_FIELDS = {"jitter"}
CMR_DOCUMENTED_VARIANTS = (
    ("globalCallId_callId", "directoryNumber", "field_description_table"),
    ("globalCallID_callId", "directoryNum", "current_example_schema"),
)
CIM_REQUIREMENTS = {
    "authentication": {
        "model": "Authentication",
        "fields": {
            "action",
            "app",
            "authentication_method",
            "dest",
            "src",
            "user",
        },
        "tags": {"authentication"},
    },
    "change": {
        "model": "Change",
        "fields": {
            "action",
            "change_type",
            "object",
            "object_category",
            "status",
            "user",
        },
        "tags": {"change"},
    },
}
FORBIDDEN_ARG_FLAGS = {
    "--apply",
    "--apply-host",
    "--apply-k8s",
    "--execute",
    "--install",
    "--enable-inputs",
    "--splunk-prep",
    "--configure",
    "--live",
    "--mutate",
    "--token",
    "--password",
    "--secret",
    "--api-key",
    "--client-secret",
    "--authorization",
}

PARTNER_PACKAGES: dict[str, dict[str, Any]] = {
    "669": {
        "version": "8.4.2",
        "tiers": {"search-tier", "standalone-indexer"},
        "dependencies": set(),
        "entitlement": "commercial",
    },
    "4434": {
        "version": "8.3.1",
        "tiers": {"universal-forwarder", "heavy-forwarder"},
        "dependencies": {"669"},
        "entitlement": "partner-license-review",
    },
    "4640": {
        "version": "1.2.9",
        "tiers": {"search-tier"},
        "dependencies": {"669"},
        "entitlement": "separate-license",
        "max_platform": "10.4",
    },
    "8413": {
        "version": "0.6.1",
        "tiers": set(),
        "dependencies": {"669"},
        "entitlement": "receiver-and-tier-unknown",
    },
    "8592": {
        "version": "0.5.0",
        "tiers": {"indexer", "heavy-forwarder"},
        "dependencies": set(),
        "entitlement": "partner-license-review",
    },
    "8593": {
        "version": "0.5.3",
        "tiers": {"search-tier"},
        "dependencies": {"669", "8592"},
        "entitlement": "partner-license-review",
    },
}

DELEGATION_SECTIONS = {
    "collaboration-syslog",
    "cdr-cmr-collection",
    "roomos-webex",
    "roomos-thousandeyes",
    "downstream-readiness",
}

EXPECTED_ARTIFACTS = {
    "artifact-manifest.json",
    "metadata.json",
    "plan.json",
    "source-ledger.json",
    "readiness/readiness-report.json",
    "readiness/readiness-report.md",
    "readiness/index-plan.json",
    "privacy/privacy-plan.json",
    "privacy/privacy-plan.md",
    "dashboards/cisco-collaboration-dashboard.spl",
    "dashboards/starter-search-readiness.md",
    "sc4s/classifier-plan.json",
    "sc4s/classifier-review.md",
    "evidence/requirements.json",
    "evidence/cdr-cmr.md",
    "evidence/cms-xml-cdr.json",
    "evidence/roomos.json",
    "evidence/broadworks.json",
    "evidence/uccx-ucce.json",
    "handoffs/handoff-plan.json",
    "handoffs/sc4s.md",
    "handoffs/roomos-webex.md",
    "handoffs/roomos-thousandeyes.md",
    "handoffs/broadworks.md",
    "cim/mappings.json",
    "cim/mappings.spl",
    "partners/package-review.json",
    "gaps/gap-register.json",
    "gaps/gap-register.md",
}
EXPECTED_TOP_LEVEL = {MARKER_NAME} | {Path(item).parts[0] for item in EXPECTED_ARTIFACTS}


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec")
    parser.add_argument("--expected-spec-sha256")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--replace-existing", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _json_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SpecError(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def _strip_yaml_comment(raw: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(raw):
        if in_double and escaped:
            escaped = False
            continue
        if in_double and char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            if index == 0 or raw[index - 1].isspace():
                return raw[:index]
    return raw


def _split_yaml_mapping(content: str, *, source: str, line_number: int) -> tuple[str, str]:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(content):
        if in_double and escaped:
            escaped = False
            continue
        if in_double and char == "\\":
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == ":" and not in_single and not in_double:
            key = content[:index].strip()
            value = content[index + 1 :].strip()
            if not key:
                raise SpecError(f"empty YAML key at {source}:{line_number}")
            if key.startswith(("'", '"')) or "\\" in key:
                raise SpecError(
                    f"quoted or escaped YAML mapping keys are forbidden at {source}:{line_number}"
                )
            return key, value
    raise SpecError(f"expected YAML mapping at {source}:{line_number}")


def reject_duplicate_yaml_keys(text: str, *, source: str) -> None:
    """Check the conservative YAML subset before PyYAML/fallback can overwrite keys."""
    prepared: list[tuple[int, int, str]] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise SpecError(f"tabs are forbidden in YAML indentation at {source}:{line_number}")
        stripped = _strip_yaml_comment(raw).rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        content = stripped[indent:]
        if indent > 64:
            raise SpecError(f"YAML nesting exceeds the v1 limit at {source}:{line_number}")
        if content.startswith(("%", "---", "...", "? ")):
            raise SpecError(f"YAML directives/document markers/complex keys are forbidden at {source}:{line_number}")
        if content.startswith("<<:"):
            raise SpecError(f"YAML merge keys are forbidden at {source}:{line_number}")
        scan_content = re.sub(r":\s*\[\]\s*$", ": canonical-empty-list", content)
        in_single = False
        in_double = False
        escaped = False
        for char in scan_content:
            if in_double and escaped:
                escaped = False
                continue
            if in_double and char == "\\":
                escaped = True
                continue
            if char == "'" and not in_double:
                in_single = not in_single
                continue
            if char == '"' and not in_single:
                in_double = not in_double
                continue
            if not in_single and not in_double and char in "{}[]&*!":
                raise SpecError(
                    f"YAML flow collections, anchors, aliases, and tags are forbidden at {source}:{line_number}"
                )
        prepared.append((line_number, indent, content))
        if len(prepared) > 10_000:
            raise SpecError(f"YAML document exceeds the v1 node limit: {source}")

    def check_block(index: int, indent: int) -> int:
        if index >= len(prepared):
            return index
        return check_list(index, indent) if prepared[index][2] == "-" or prepared[index][2].startswith("- ") else check_mapping(index, indent)

    def skip_scalar(index: int, parent_indent: int) -> int:
        while index < len(prepared) and prepared[index][1] > parent_indent:
            index += 1
        return index

    def check_mapping(index: int, indent: int, initial: set[str] | None = None) -> int:
        keys = set(initial or set())
        while index < len(prepared):
            line_number, current_indent, content = prepared[index]
            if current_indent < indent:
                break
            if current_indent != indent or content == "-" or content.startswith("- "):
                break
            key, raw_value = _split_yaml_mapping(content, source=source, line_number=line_number)
            if key in keys:
                raise SpecError(f"duplicate YAML key {key!r} at {source}:{line_number}")
            keys.add(key)
            index += 1
            if raw_value in {"|", "|-", "|+", ">", ">-", ">+"}:
                index = skip_scalar(index, current_indent)
            elif not raw_value and index < len(prepared):
                next_indent = prepared[index][1]
                if next_indent > current_indent:
                    index = check_block(index, next_indent)
                elif next_indent == current_indent and (
                    prepared[index][2] == "-" or prepared[index][2].startswith("- ")
                ):
                    index = check_list(index, current_indent)
        return index

    def check_list(index: int, indent: int) -> int:
        while index < len(prepared):
            line_number, current_indent, content = prepared[index]
            if current_indent < indent:
                break
            if current_indent != indent or not (content == "-" or content.startswith("- ")):
                break
            raw_item = "" if content == "-" else content[2:].strip()
            index += 1
            if not raw_item:
                if index < len(prepared) and prepared[index][1] > current_indent:
                    index = check_block(index, prepared[index][1])
                continue
            if ":" in raw_item:
                first_key, raw_value = _split_yaml_mapping(
                    raw_item,
                    source=source,
                    line_number=line_number,
                )
                if raw_value in {"|", "|-", "|+", ">", ">-", ">+"}:
                    index = skip_scalar(index, current_indent)
                elif index < len(prepared) and prepared[index][1] > current_indent:
                    index = check_mapping(index, prepared[index][1], initial={first_key})
        return index

    if prepared:
        end = check_block(0, prepared[0][1])
        if end != len(prepared):
            line_number = prepared[end][0]
            raise SpecError(f"unsupported YAML structure at {source}:{line_number}")


def validate_plain_tree(value: Any, *, source: str) -> None:
    stack: list[tuple[Any, int, str]] = [(value, 0, "root")]
    containers: set[int] = set()
    nodes = 0
    while stack:
        current, depth, path = stack.pop()
        nodes += 1
        if nodes > 10_000 or depth > 32:
            raise SpecError(f"parsed input exceeds bounded v1 structure at {source}:{path}")
        if isinstance(current, (dict, list)):
            identity = id(current)
            if identity in containers:
                raise SpecError(f"aliases or cyclic/shared containers are forbidden at {source}:{path}")
            containers.add(identity)
        if isinstance(current, dict):
            for key, child in current.items():
                if not isinstance(key, str):
                    raise SpecError(f"mapping keys must be strings at {source}:{path}")
                stack.append((child, depth + 1, f"{path}.{key}"))
        elif isinstance(current, list):
            for index, child in enumerate(current):
                stack.append((child, depth + 1, f"{path}[{index}]"))
        elif current is None or isinstance(current, (str, int, bool)):
            continue
        elif isinstance(current, float) and math.isfinite(current):
            continue
        else:
            raise SpecError(f"only bounded plain dict/list/scalar input is allowed at {source}:{path}")


def strict_load_yaml_or_json(
    text: str,
    *,
    source: str,
    force_fallback: bool = False,
) -> Any:
    try:
        result = json.loads(text, object_pairs_hook=_json_pairs_no_duplicates)
    except json.JSONDecodeError:
        reject_duplicate_yaml_keys(text, source=source)
        if force_fallback:
            result = _SimpleYamlParser(text, source=source).parse()
        else:
            result = load_yaml_or_json(text, source=source)
    validate_plain_tree(result, source=source)
    return result


def strict_load_json_bytes(payload: bytes, *, source: str) -> Any:
    try:
        text = payload.decode("utf-8")
        result = json.loads(text, object_pairs_hook=_json_pairs_no_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpecError(f"strict JSON decode failed for {source}: {exc}") from exc
    validate_plain_tree(result, source=source)
    return result


def lexical_absolute(raw: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(raw))))


def current_uid() -> int:
    if not hasattr(os, "getuid"):
        raise SpecError("this renderer requires a POSIX runtime with file ownership checks")
    return os.getuid()


def require_owned_directory(
    path: Path,
    *,
    label: str,
    private: bool,
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SpecError(f"{label} does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SpecError(f"{label} must be a real directory: {path}")
    if metadata.st_uid != current_uid():
        raise SpecError(f"{label} must be owned by the current user: {path}")
    mode = stat.S_IMODE(metadata.st_mode)
    if private:
        if mode != 0o700:
            raise SpecError(f"{label} must have mode 0700: {path} has {mode:04o}")
    elif mode & 0o022:
        raise SpecError(f"{label} must not be group/world writable: {path} has {mode:04o}")
    return metadata


def reject_symlink_components(path: Path, *, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise SpecError(f"{label} contains a symlink component: {current}")
        if not current.exists():
            break


def secure_regular_file(path: Path, *, label: str, max_bytes: int) -> os.stat_result:
    reject_symlink_components(path, label=label)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SpecError(f"{label} does not exist: {path}") from exc
    if not stat.S_ISREG(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
        raise SpecError(f"{label} must be a regular file, never a symlink: {path}")
    if metadata.st_nlink != 1:
        raise SpecError(f"{label} must be a single-link regular file: {path}")
    if metadata.st_size < 1 or metadata.st_size > max_bytes:
        raise SpecError(f"{label} size must be 1..{max_bytes} bytes: {path}")
    return metadata


def read_regular_bytes(path: Path, *, label: str, max_bytes: int) -> bytes:
    expected = secure_regular_file(path, label=label, max_bytes=max_bytes)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        expected_identity = (expected.st_dev, expected.st_ino)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != expected_identity
            or opened.st_size < 1
            or opened.st_size > max_bytes
        ):
            raise SpecError(f"{label} changed before its no-follow descriptor was opened: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(131072, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise SpecError(f"{label} exceeds the {max_bytes}-byte limit: {path}")
        after = os.fstat(fd)
        before_identity = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_identity != after_identity or after.st_nlink != 1:
            raise SpecError(f"{label} changed while its descriptor was read: {path}")
        return b"".join(chunks)
    finally:
        os.close(fd)


def expect_mapping(
    value: Any,
    path: str,
    *,
    allowed: set[str],
    required: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"{path} must be an object")
    keys = set(value)
    unknown = sorted(keys - allowed)
    missing = sorted((required if required is not None else allowed) - keys)
    if unknown:
        raise SpecError(f"{path} contains unknown field(s): {', '.join(unknown)}")
    if missing:
        raise SpecError(f"{path} is missing field(s): {', '.join(missing)}")
    return value


def expect_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise SpecError(f"{path} must be a list")
    return value


def require_schema_version(value: dict[str, Any], path: str) -> None:
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise SpecError(f"{path}.schema_version must be integer 1")


def expect_bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SpecError(f"{path} must be true or false")
    return value


def expect_string(
    value: Any,
    path: str,
    *,
    allow_empty: bool = False,
    max_length: int = 512,
) -> str:
    if not isinstance(value, str):
        raise SpecError(f"{path} must be a string")
    if not allow_empty and not value:
        raise SpecError(f"{path} must not be empty")
    if len(value) > max_length or CONTROL_RE.search(value):
        raise SpecError(f"{path} contains unsupported or excessive text")
    return value


def expect_string_list(value: Any, path: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list):
        raise SpecError(f"{path} must be a list")
    if not allow_empty and not value:
        raise SpecError(f"{path} must not be empty")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(expect_string(item, f"{path}[{index}]", max_length=128))
    if len(result) != len(set(result)):
        raise SpecError(f"{path} must not contain duplicates")
    return result


def expect_optional_string_list(value: Any, path: str) -> list[str]:
    if value is None:
        return []
    return expect_string_list(value, path)


def reject_secret_keys(value: Any, path: str = "spec") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise SpecError(f"{path} contains a non-string key")
            if SECRET_KEY_RE.search(key):
                raise SpecError(f"{path}.{key} is a secret-bearing field and is forbidden")
            reject_secret_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_secret_keys(child, f"{path}[{index}]")
    elif isinstance(value, str):
        if "-----BEGIN" in value and "PRIVATE KEY-----" in value:
            raise SpecError(f"{path} contains private-key material")
        if re.search(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{8,}", value):
            raise SpecError(f"{path} contains bearer credential material")


def reject_copied_sensitive_text(value: str, path: str) -> None:
    """Reject identifier/credential shapes from values persisted verbatim."""
    if EMAIL_LITERAL_RE.search(value):
        raise SpecError(f"{path} contains an email-shaped identifier that cannot be copied into the packet")
    if (
        CREDENTIAL_LITERAL_RE.search(value)
        or OPENAI_CREDENTIAL_RE.search(value)
        or GOOGLE_API_CREDENTIAL_RE.search(value)
    ):
        raise SpecError(f"{path} contains credential-shaped material that cannot be copied into the packet")
    if "-----BEGIN" in value and "PRIVATE KEY-----" in value:
        raise SpecError(f"{path} contains private-key material")
    if re.search(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{8,}", value):
        raise SpecError(f"{path} contains bearer credential material")


def reject_sensitive_text_values(value: Any, path: str = "spec") -> None:
    """Apply the finite persisted-text DLP screen to every intake string."""
    if isinstance(value, dict):
        for key, child in value.items():
            reject_sensitive_text_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            reject_sensitive_text_values(child, f"{path}[{index}]")
    elif isinstance(value, str):
        reject_copied_sensitive_text(value, path)


def type_aware_equal(actual: Any, expected: Any) -> bool:
    """Compare JSON-like values without Python's bool/int equality coercion."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            type_aware_equal(actual[key], expected[key]) for key in expected
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            type_aware_equal(actual_item, expected_item)
            for actual_item, expected_item in zip(actual, expected)
        )
    return actual == expected


def validate_index(value: Any, path: str) -> str:
    text = expect_string(value, path, max_length=64)
    reject_copied_sensitive_text(text, path)
    if not INDEX_RE.fullmatch(text):
        raise SpecError(f"{path} is not a safe Splunk index name")
    return text


def validate_sourcetype(value: Any, path: str, *, wildcard: bool = False) -> str:
    text = expect_string(value, path, max_length=128)
    reject_copied_sensitive_text(text, path)
    if not SOURCETYPE_RE.fullmatch(text):
        raise SpecError(f"{path} is not a safe source type")
    if not wildcard and "*" in text:
        raise SpecError(f"{path} must not contain a wildcard")
    return text


def validate_hash(value: Any, path: str) -> str:
    text = expect_string(value, path, max_length=64)
    if not SHA256_RE.fullmatch(text):
        raise SpecError(f"{path} must be a lowercase 64-character SHA-256")
    return text


def parse_strict_numeric_version(value: Any, path: str) -> tuple[int, int, int]:
    text = expect_string(value, path, max_length=32)
    match = re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:\.(0|[1-9][0-9]*))?",
        text,
    )
    if not match:
        raise SpecError(
            f"{path} must be a strict major.minor or major.minor.patch numeric version without prerelease or unknown semantics"
        )
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def validate_safe_search(value: Any, path: str) -> tuple[str, str, str]:
    search = expect_string(value, path, max_length=4096)
    if FORBIDDEN_SPL_RE.search(search):
        raise SpecError(f"{path} contains a write-capable or privileged SPL command")
    if any(token in search for token in ("`", "[", "]", "\\", "/*", "*/", "//")):
        raise SpecError(f"{path} contains a macro, subsearch, escape, or comment token")
    if re.search(r"(^|\s)#|\bOR\b", search, re.IGNORECASE):
        raise SpecError(f"{path} contains a comment or OR broadening")
    assignment_pattern = re.compile(
        r"(?<![A-Za-z0-9_])(index|sourcetype)\s*=\s*(\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s|()]+)",
        re.IGNORECASE,
    )
    assignments: dict[str, list[str]] = {"index": [], "sourcetype": []}
    for key, raw in assignment_pattern.findall(
        search,
    ):
        value_text = raw[1:-1] if raw[:1] in {'"', "'"} else raw
        assignments[key.lower()].append(value_text)
    for key in ("index", "sourcetype"):
        if len(assignments[key]) != 1:
            raise SpecError(f"{path} must bind exactly one concrete {key}=")
        if "*" in assignments[key][0] or "?" in assignments[key][0]:
            raise SpecError(f"{path} {key}= must not contain a wildcard")
    index = validate_index(assignments["index"][0], f"{path}.index_constraint")
    sourcetype = validate_sourcetype(
        assignments["sourcetype"][0],
        f"{path}.sourcetype_constraint",
    )
    generating = search.split("|", 1)[0].strip()
    if re.match(r"(?i)^search\b", generating):
        generating = re.sub(r"(?i)^search\b", "", generating, count=1).strip()
    remainder = assignment_pattern.sub("", generating).strip()
    if remainder:
        raise SpecError(
            f"{path} generating segment may contain only the exact index= and sourcetype= bindings"
        )
    for segment in search.split("|")[1:]:
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)", segment)
        if not match or match.group(1).lower() not in READ_ONLY_SPL_COMMANDS:
            command = match.group(1) if match else "UNKNOWN"
            raise SpecError(f"{path} uses unsupported SPL command {command!r}")
    return search, index, sourcetype


def safe_relative_evidence_path(raw: Any, spec_path: Path, field_path: str) -> Path:
    text = expect_string(raw, field_path, max_length=240)
    if "\\" in text:
        raise SpecError(f"{field_path} must use a relative POSIX path")
    pure = PurePosixPath(text)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SpecError(f"{field_path} must be traversal-free and relative to the spec")
    root = spec_path.parent.resolve()
    candidate = lexical_absolute(root / Path(*pure.parts))
    reject_symlink_components(candidate, label=field_path)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SpecError(f"{field_path} escapes the spec directory") from exc
    secure_regular_file(candidate, label=field_path, max_bytes=MAX_EVIDENCE_BYTES)
    return candidate


def verify_evidence_file(
    path_value: Any,
    hash_value: Any,
    spec_path: Path,
    field_prefix: str,
) -> tuple[Path, str]:
    evidence_path = safe_relative_evidence_path(path_value, spec_path, f"{field_prefix}_path")
    expected_hash = validate_hash(hash_value, f"{field_prefix}_sha256")
    payload = read_regular_bytes(
        evidence_path,
        label=f"{field_prefix}_path",
        max_bytes=MAX_EVIDENCE_BYTES,
    )
    actual_hash = sha256_bytes(payload)
    if actual_hash != expected_hash:
        raise SpecError(
            f"{field_prefix}_sha256 does not match {evidence_path.name}: "
            f"expected {expected_hash}, got {actual_hash}"
        )
    return evidence_path, actual_hash


def validate_syslog(
    value: Any,
    path: str,
    *,
    fixed_index: str,
    fixed_sourcetype: str,
    transports: set[str],
) -> dict[str, Any]:
    block = expect_mapping(
        value,
        path,
        allowed={"enabled", "transport", "index", "sourcetype"},
    )
    expect_bool(block["enabled"], f"{path}.enabled")
    transport = expect_string(block["transport"], f"{path}.transport")
    if transport not in transports:
        raise SpecError(f"{path}.transport must be one of: {', '.join(sorted(transports))}")
    index = validate_index(block["index"], f"{path}.index")
    sourcetype = validate_sourcetype(block["sourcetype"], f"{path}.sourcetype")
    if index != fixed_index:
        raise SpecError(f"{path}.index must preserve documented index {fixed_index}")
    if sourcetype != fixed_sourcetype:
        raise SpecError(f"{path}.sourcetype must preserve documented source type {fixed_sourcetype}")
    return block


def validate_cucm_audit_syslog(value: Any, path: str) -> dict[str, Any]:
    """Validate only the source-backed CUCM 15 remote-audit syslog profile."""
    block = expect_mapping(
        value,
        path,
        allowed={
            "enabled",
            "scope",
            "transport",
            "receiver_port",
            "tls_authentication",
            "trust_requirements_reviewed",
            "index",
            "sourcetype",
        },
    )
    enabled = expect_bool(block["enabled"], f"{path}.enabled")
    if block["scope"] != "remote_audit_logging":
        raise SpecError(f"{path}.scope must remain remote_audit_logging")
    transport = expect_string(block["transport"], f"{path}.transport")
    if transport not in {"udp", "tcp", "tls"}:
        raise SpecError(f"{path}.transport must be udp, tcp, or tls for CUCM remote audit logging")
    port = block["receiver_port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise SpecError(f"{path}.receiver_port must be an explicit operator-selected port from 1 through 65535")
    authentication = expect_string(block["tls_authentication"], f"{path}.tls_authentication")
    trust_reviewed = expect_bool(
        block["trust_requirements_reviewed"],
        f"{path}.trust_requirements_reviewed",
    )
    expected_trust_review = enabled and transport == "tls"
    if trust_reviewed is not expected_trust_review:
        raise SpecError(
            f"{path}.trust_requirements_reviewed must equal enabled && transport == tls"
        )
    if transport == "tls":
        if authentication not in {"unidirectional_x509", "bidirectional_x509"}:
            raise SpecError(
                f"{path}.tls_authentication must be unidirectional_x509 or bidirectional_x509 for TLS"
            )
    elif authentication != "none" or trust_reviewed is not False:
        raise SpecError(
            f"{path} non-TLS transport requires tls_authentication: none and trust_requirements_reviewed: false"
        )
    if validate_index(block["index"], f"{path}.index") != "ucm":
        raise SpecError(f"{path}.index must preserve documented index ucm")
    if validate_sourcetype(block["sourcetype"], f"{path}.sourcetype") != "cisco:ucm":
        raise SpecError(f"{path}.sourcetype must preserve documented source type cisco:ucm")
    return block


def validate_flat_file_path(value: Any, path: str) -> str:
    text = expect_string(value, path, max_length=512)
    reject_copied_sensitive_text(text, path)
    pure = PurePosixPath(text)
    if not pure.is_absolute() or ".." in pure.parts or str(pure) != text:
        raise SpecError(f"{path} must be a normalized absolute export path without traversal")
    if text == "/":
        raise SpecError(f"{path} must not be the filesystem root")
    return text


def validate_cdr_cmr(
    value: Any,
    path: str,
    spec_path: Path,
    *,
    expected_file_type: str,
) -> dict[str, Any]:
    block = expect_mapping(
        value,
        path,
        allowed={"enabled", "collection", "index", "sourcetype", "evidence"},
    )
    enabled = expect_bool(block["enabled"], f"{path}.enabled")
    collection = expect_string(block["collection"], f"{path}.collection")
    if collection not in {"sftp_billing_server", "ondemand_soap_sftp"}:
        raise SpecError(
            f"{path}.collection must be sftp_billing_server or ondemand_soap_sftp; AXL is not a CDR/CMR collector"
        )
    validate_index(block["index"], f"{path}.index")
    sourcetype = expect_string(block["sourcetype"], f"{path}.sourcetype", allow_empty=True, max_length=128)
    evidence = expect_mapping(
        block["evidence"],
        f"{path}.evidence",
        allowed={
            "file_type",
            "header_rows",
            "sample_path",
            "sha256",
            "record_count",
            "observed_fields",
            "export_path",
            "receiver_owner",
            "collection_evidence",
            "source_type_origin",
        },
    )
    file_type = expect_string(evidence["file_type"], f"{path}.evidence.file_type")
    if file_type != expected_file_type:
        raise SpecError(f"{path}.evidence.file_type must remain {expected_file_type}")
    if type(evidence["header_rows"]) is not int or evidence["header_rows"] != 2:
        raise SpecError(f"{path}.evidence.header_rows must remain exactly 2")
    for name in ("sample_path", "sha256", "export_path", "receiver_owner", "collection_evidence", "source_type_origin"):
        expect_string(evidence[name], f"{path}.evidence.{name}", allow_empty=True, max_length=512)
    if type(evidence["record_count"]) is not int or evidence["record_count"] < 0:
        raise SpecError(f"{path}.evidence.record_count must be a nonnegative integer")
    fields = expect_string_list(evidence["observed_fields"], f"{path}.evidence.observed_fields")
    if not enabled:
        return block

    validate_sourcetype(sourcetype, f"{path}.sourcetype")
    if evidence["source_type_origin"] not in {"customer_normalized", "verified_package_inspection"}:
        raise SpecError(
            f"{path}.evidence.source_type_origin must be customer_normalized or verified_package_inspection"
        )
    validate_flat_file_path(evidence["export_path"], f"{path}.evidence.export_path")
    owner = expect_string(evidence["receiver_owner"], f"{path}.evidence.receiver_owner", max_length=128)
    if not IDENTIFIER_RE.fullmatch(owner):
        raise SpecError(f"{path}.evidence.receiver_owner must be a non-secret operator identifier")
    reject_copied_sensitive_text(owner, f"{path}.evidence.receiver_owner")
    narrative = expect_string(
        evidence["collection_evidence"],
        f"{path}.evidence.collection_evidence",
        max_length=512,
    )
    if len(narrative) < 12:
        raise SpecError(f"{path}.evidence.collection_evidence is incomplete")
    reject_copied_sensitive_text(narrative, f"{path}.evidence.collection_evidence")
    if evidence["record_count"] < 1:
        raise SpecError(f"{path}.evidence.record_count must be nonzero when enabled")
    if not fields:
        raise SpecError(f"{path}.evidence.observed_fields must be nonempty when enabled")
    sample_path, _ = verify_evidence_file(
        evidence["sample_path"],
        evidence["sha256"],
        spec_path,
        f"{path}.evidence.sample",
    )
    family_pattern = re.compile(
        rf"^{expected_file_type}_[A-Za-z0-9][A-Za-z0-9.-]*"
        rf"(?:_[A-Za-z0-9][A-Za-z0-9.-]*){{3,}}(?:\.csv)?$"
    )
    if not family_pattern.fullmatch(sample_path.name):
        raise SpecError(
            f"{path}.evidence.sample_path must match the documented {expected_file_type}_ multi-component filename family"
        )
    try:
        text = read_regular_bytes(
            sample_path,
            label=f"{path}.evidence.sample_path",
            max_bytes=MAX_EVIDENCE_BYTES,
        ).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpecError(f"{path}.evidence.sample_path must be UTF-8 text") from exc
    if "\x00" in text:
        raise SpecError(f"{path}.evidence.sample_path contains a NUL byte")
    try:
        rows = [
            row
            for row in csv.reader(io.StringIO(text, newline=""), strict=True)
            if any(cell.strip() for cell in row)
        ]
    except csv.Error as exc:
        raise SpecError(f"{path}.evidence.sample_path is not strict CSV: {exc}") from exc
    if len(rows) < 3 or not rows[0] or not rows[1]:
        raise SpecError(f"{path}.evidence.sample_path must contain two header rows and at least one record")
    if any(cell != cell.strip() for cell in rows[0]):
        raise SpecError(f"{path}.evidence.sample_path field-name row must not contain surrounding whitespace")
    if any(cell != cell.strip() for cell in rows[1]):
        raise SpecError(f"{path}.evidence.sample_path type row must not contain surrounding whitespace")
    field_names = list(rows[0])
    field_types = list(rows[1])
    if any(not field for field in field_names) or len(field_names) != len(set(field_names)):
        raise SpecError(f"{path}.evidence.sample_path field-name row must be nonempty and unique")
    for field in field_names:
        if not TECHNICAL_FIELD_RE.fullmatch(field):
            raise SpecError(
                f"{path}.evidence.sample_path field names must use bounded Cisco-style letters, digits, and underscores"
            )
        if SECRET_KEY_RE.search(field):
            raise SpecError(f"{path}.evidence.sample_path contains forbidden secret-shaped field name {field!r}")
        reject_copied_sensitive_text(field, f"{path}.evidence.sample_path field {field}")
    if any(not field_type for field_type in field_types) or len(field_types) != len(field_names):
        raise SpecError(f"{path}.evidence.sample_path type row must be nonempty and match the field-name row width")
    for row_number, row in enumerate(rows[2:], start=3):
        if len(row) != len(field_names):
            raise SpecError(
                f"{path}.evidence.sample_path data row {row_number} has width {len(row)}; expected {len(field_names)}"
            )
    required_fields = CDR_REQUIRED_FIELDS if expected_file_type == "cdr" else CMR_REQUIRED_FIELDS
    required_types = dict(CDR_REQUIRED_TYPES if expected_file_type == "cdr" else CMR_REQUIRED_TYPES)
    if expected_file_type == "cmr":
        matched_variants = [
            (call_field, directory_field, variant)
            for call_field, directory_field, variant in CMR_DOCUMENTED_VARIANTS
            if call_field in field_names and directory_field in field_names
        ]
        known_aliases_present = set(field_names) & {
            "globalCallId_callId",
            "globalCallID_callId",
            "directoryNumber",
            "directoryNum",
        }
        if len(matched_variants) != 1 or len(known_aliases_present) != 2:
            raise SpecError(
                f"{path}.evidence.sample_path must use exactly one documented CMR alias pair: "
                "globalCallId_callId+directoryNumber or globalCallID_callId+directoryNum"
            )
        required_types[matched_variants[0][0]] = "INTEGER"
        required_types[matched_variants[0][1]] = (
            "INTEGER"
            if matched_variants[0][2] == "field_description_table"
            else "VARCHAR(50)"
        )
    absent_signature = sorted(required_fields - set(field_names))
    if absent_signature:
        raise SpecError(
            f"{path}.evidence.sample_path is missing documented {expected_file_type.upper()} family field(s): "
            + ", ".join(absent_signature)
        )
    types_by_field = dict(zip(field_names, field_types))
    wrong_types = sorted(
        f"{field}={types_by_field.get(field)!r} (expected {expected_type})"
        for field, expected_type in required_types.items()
        if types_by_field.get(field) != expected_type
    )
    if wrong_types:
        raise SpecError(
            f"{path}.evidence.sample_path has incorrect required signature field type(s): "
            + ", ".join(wrong_types)
        )
    if expected_file_type == "cmr" and matched_variants[0][2] != "current_example_schema":
        raise SpecError(
            f"{path}.evidence.sample_path uses field-description compatibility names without "
            "a Release 15 exported line-2 type-row authority; only "
            "globalCallID_callId+directoryNum can qualify local evidence"
        )
    integer_indexes = {
        field: index
        for index, (field, declared_type) in enumerate(zip(field_names, field_types))
        if declared_type == "INTEGER"
    }
    positive_fields = set(CDR_POSITIVE_INTEGER_FIELDS if expected_file_type == "cdr" else CMR_POSITIVE_INTEGER_FIELDS)
    unsigned_fields = set() if expected_file_type == "cdr" else set(CMR_UNSIGNED_INTEGER_FIELDS)
    if expected_file_type == "cmr":
        positive_fields.add(matched_variants[0][0])
    for row_number, row in enumerate(rows[2:], start=3):
        for field, field_index in integer_indexes.items():
            cell = row[field_index]
            if not re.fullmatch(r"[+-]?[0-9]+", cell, re.ASCII):
                raise SpecError(
                    f"{path}.evidence.sample_path row {row_number} field {field} must contain a nonempty ASCII base-10 integer"
                )
            signless = cell[1:] if cell[:1] in {"+", "-"} else cell
            is_zero = not signless.strip("0")
            if field in positive_fields and (cell.startswith("-") or is_zero):
                raise SpecError(
                    f"{path}.evidence.sample_path row {row_number} field {field} is a Cisco Positive Integer and must be greater than zero"
                )
            if field in unsigned_fields and cell.startswith("-"):
                raise SpecError(
                    f"{path}.evidence.sample_path row {row_number} field {field} is unsigned and must be zero or greater"
                )
    record_type_index = field_names.index("cdrRecordType")
    expected_record_type = "1" if expected_file_type == "cdr" else "2"
    for row_number, row in enumerate(rows[2:], start=3):
        if row[record_type_index].strip() != expected_record_type:
            raise SpecError(
                f"{path}.evidence.sample_path row {row_number} cdrRecordType must be {expected_record_type} for {expected_file_type.upper()}"
            )
    actual_count = len(rows[2:])
    if actual_count != evidence["record_count"]:
        raise SpecError(
            f"{path}.evidence.record_count is {evidence['record_count']} but sample contains {actual_count} record(s)"
        )
    if fields != field_names:
        raise SpecError(f"{path}.evidence.observed_fields must exactly match line 1 in order")
    return block


def validate_operator_readiness_metadata(
    value: Any,
    path: str,
    *,
    enabled: bool,
) -> dict[str, Any]:
    """Validate explicitly non-qualifying operator metadata.

    These optional product paths have no source-backed event schema in this
    router.  Operator search/field notes can guide a later live review, but no
    file/hash or claimed field can upgrade offline readiness.
    """
    metadata = expect_mapping(
        value,
        path,
        allowed={"qualifying_search", "asserted_fields", "observation_note"},
    )
    search = expect_string(
        metadata["qualifying_search"],
        f"{path}.qualifying_search",
        allow_empty=True,
        max_length=4096,
    )
    fields = expect_string_list(metadata["asserted_fields"], f"{path}.asserted_fields")
    note = expect_string(
        metadata["observation_note"],
        f"{path}.observation_note",
        allow_empty=True,
        max_length=512,
    )
    if search:
        validate_safe_search(search, f"{path}.qualifying_search")
    if fields and not search:
        raise SpecError(f"{path}.asserted_fields requires a constrained qualifying_search")
    if note and len(note) < 12:
        raise SpecError(f"{path}.observation_note is incomplete")
    if not enabled and (search or fields or note):
        raise SpecError(f"{path} must remain empty when its route is disabled")
    metadata["operator_metadata_present"] = bool(enabled and (search or fields or note))
    return metadata


def validate_classifier(value: Any, path: str) -> tuple[dict[str, Any], tuple[str, Any]]:
    block = expect_mapping(value, path, allowed={"mode", "value"})
    mode = expect_string(block["mode"], f"{path}.mode")
    if mode not in {"exact_host", "exact_ip", "dedicated_port"}:
        raise SpecError(f"{path}.mode must be exact_host, exact_ip, or dedicated_port; regex is forbidden")
    raw = block["value"]
    if mode == "dedicated_port":
        if type(raw) is not int:
            raise SpecError(f"{path}.value must be an integer for dedicated_port")
        if raw < 1024 or raw > 65535 or raw in {514, 6514}:
            raise SpecError(f"{path}.value must be a unique non-shared port from 1024 through 65535")
        return block, ("dedicated_port", raw)
    text = expect_string(raw, f"{path}.value", max_length=253)
    reject_copied_sensitive_text(text, f"{path}.value")
    if any(char in text for char in "*+?[](){}|^$\\/"):
        raise SpecError(f"{path}.value must be exact and contain no wildcard or regex metacharacters")
    if mode == "exact_ip":
        try:
            address = ipaddress.ip_address(text)
        except ValueError as exc:
            raise SpecError(f"{path}.value must be an exact IPv4 or IPv6 address") from exc
        return block, ("exact_ip", address.compressed)
    try:
        ipaddress.ip_address(text)
    except ValueError:
        pass
    else:
        raise SpecError(f"{path}.value is an IP address; use exact_ip")
    host = text.rstrip(".").lower()
    if host != text.lower() or len(host) > 253:
        raise SpecError(f"{path}.value must be a normalized exact host name")
    labels = host.split(".")
    if any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise SpecError(f"{path}.value must be an RFC-valid exact host name")
    return block, ("exact_host", host)


def validate_cmm_syslog_path(
    value: Any,
    path: str,
    spec_path: Path,
    *,
    route: str,
    fixed_sourcetype: str,
) -> dict[str, Any]:
    block = expect_mapping(
        value,
        path,
        allowed={
            "enabled",
            "wire_protocol",
            "tls_version",
            "receiver_max_bytes",
            "planned_server_count",
            "index",
            "sourcetype",
            "evidence_path",
            "evidence_sha256",
        },
    )
    enabled = expect_bool(block["enabled"], f"{path}.enabled")
    wire_protocol = expect_string(block["wire_protocol"], f"{path}.wire_protocol")
    if wire_protocol not in {"tcp", "tls"}:
        raise SpecError(f"{path}.wire_protocol must be tcp or tls; documented UDP is outside this deterministic TCP router")
    if block["tls_version"] != ("TLS1.2" if wire_protocol == "tls" else "none"):
        raise SpecError(f"{path}.tls_version must be TLS1.2 when TLS is enabled, otherwise none")
    if type(block["receiver_max_bytes"]) is not int or block["receiver_max_bytes"] != 8192:
        raise SpecError(f"{path}.receiver_max_bytes must preserve the documented 8192-byte receiver requirement")
    server_count = block["planned_server_count"]
    if type(server_count) is not int:
        raise SpecError(f"{path}.planned_server_count must be an integer")
    if enabled and not 1 <= server_count <= 5:
        raise SpecError(f"{path}.planned_server_count must be 1..5 when enabled")
    if not enabled and server_count != 0:
        raise SpecError(f"{path}.planned_server_count must be 0 when disabled")
    if validate_index(block["index"], f"{path}.index") != "netops":
        raise SpecError(f"{path}.index must preserve documented index netops")
    if validate_sourcetype(
        block["sourcetype"],
        f"{path}.sourcetype",
        wildcard=fixed_sourcetype.endswith("*"),
    ) != fixed_sourcetype:
        raise SpecError(f"{path}.sourcetype must preserve {fixed_sourcetype}")
    evidence_path = expect_string(block["evidence_path"], f"{path}.evidence_path", allow_empty=True, max_length=240)
    evidence_hash = expect_string(block["evidence_sha256"], f"{path}.evidence_sha256", allow_empty=True, max_length=64)
    if bool(evidence_path) != bool(evidence_hash):
        raise SpecError(f"{path} local evidence path and hash must be supplied together")
    if not enabled and evidence_path:
        raise SpecError(f"{path} disabled routes must not retain operator-attested evidence")
    block["operator_attested_metadata_validated"] = False
    if evidence_path:
        evidence_file, _ = verify_evidence_file(
            evidence_path,
            evidence_hash,
            spec_path,
            f"{path}.evidence",
        )
        try:
            evidence = strict_load_yaml_or_json(
                read_regular_bytes(
                    evidence_file,
                    label=f"{path}.evidence_path",
                    max_bytes=MAX_EVIDENCE_BYTES,
                ).decode("utf-8"),
                source=str(evidence_file),
            )
        except UnicodeDecodeError as exc:
            raise SpecError(f"{path}.evidence_path must be UTF-8 JSON") from exc
        evidence = expect_mapping(
            evidence,
            f"{path}.evidence",
            allowed={
                "schema",
                "route",
                "index",
                "sourcetype",
                "wire_protocol",
                "tls_version",
                "receiver_max_bytes",
                "planned_server_count",
                "sanitized",
                "raw_event_values_included",
            },
        )
        expected = {
            "schema": "cisco-collaboration-setup/cmm-syslog-evidence/v1",
            "route": route,
            "index": "netops",
            "sourcetype": fixed_sourcetype,
            "wire_protocol": wire_protocol,
            "tls_version": block["tls_version"],
            "receiver_max_bytes": 8192,
            "planned_server_count": server_count,
            "sanitized": True,
            "raw_event_values_included": False,
        }
        if not type_aware_equal(evidence, expected):
            raise SpecError(f"{path}.evidence must exactly match the sanitized v1 route evidence schema")
        block["operator_attested_metadata_validated"] = True
    return block


def validate_partner_packages(value: Any, spec_path: Path, platform_version: str) -> dict[str, Any]:
    block = expect_mapping(value, "spec.partner_packages", allowed={"mode", "selections"})
    mode = expect_string(block["mode"], "spec.partner_packages.mode")
    if mode not in {"disabled", "evidence_only"}:
        raise SpecError("spec.partner_packages.mode must be disabled or evidence_only")
    selections = block["selections"]
    if not isinstance(selections, list):
        raise SpecError("spec.partner_packages.selections must be a list")
    if mode == "disabled" and selections:
        raise SpecError("partner package selections require mode evidence_only")
    if mode == "evidence_only" and not selections:
        raise SpecError("partner_packages.mode evidence_only requires at least one selection")
    ids: list[str] = []
    for index, selection_value in enumerate(selections):
        path = f"spec.partner_packages.selections[{index}]"
        selection = expect_mapping(
            selection_value,
            path,
            allowed={
                "app_id",
                "version",
                "tier",
                "entitlement_reviewed",
                "license_assumption",
                "entitlement_evidence_path",
                "entitlement_evidence_sha256",
                "package_metadata_evidence_path",
                "package_metadata_evidence_sha256",
            },
        )
        app_id = expect_string(selection["app_id"], f"{path}.app_id", max_length=8)
        if app_id not in PARTNER_PACKAGES:
            raise SpecError(f"{path}.app_id is unsupported: {app_id}")
        facts = PARTNER_PACKAGES[app_id]
        version = expect_string(selection["version"], f"{path}.version", max_length=32)
        if version != facts["version"]:
            raise SpecError(f"{path}.version must equal verified listing version {facts['version']}")
        tier = expect_string(selection["tier"], f"{path}.tier", max_length=32)
        if not facts["tiers"]:
            raise SpecError(f"{path}: app {app_id} receiver/tier placement is UNKNOWN and cannot be selected")
        if tier not in facts["tiers"]:
            raise SpecError(f"{path}.tier is unsupported for app {app_id}; expected one of {sorted(facts['tiers'])}")
        if "max_platform" in facts:
            selected_platform = parse_strict_numeric_version(
                platform_version,
                "spec.project.splunk_platform_version",
            )
            verified_maximum = parse_strict_numeric_version(
                facts["max_platform"],
                f"partner package {app_id} max_platform",
            )
            if selected_platform > verified_maximum:
                raise SpecError(
                    f"{path}: app {app_id} has no verified Splunk compatibility above {facts['max_platform']}"
                )
        if expect_bool(selection["entitlement_reviewed"], f"{path}.entitlement_reviewed") is not True:
            raise SpecError(f"{path}.entitlement_reviewed must be true")
        if expect_string(selection["license_assumption"], f"{path}.license_assumption") != "none":
            raise SpecError(f"{path}.license_assumption must be none; licenses cannot be assumed")
        verify_evidence_file(
            selection["entitlement_evidence_path"],
            selection["entitlement_evidence_sha256"],
            spec_path,
            f"{path}.entitlement_evidence",
        )
        verify_evidence_file(
            selection["package_metadata_evidence_path"],
            selection["package_metadata_evidence_sha256"],
            spec_path,
            f"{path}.package_metadata_evidence",
        )
        ids.append(app_id)
    if len(ids) != len(set(ids)):
        raise SpecError("spec.partner_packages.selections contains duplicate app IDs")
    selected = set(ids)
    for app_id in ids:
        missing = PARTNER_PACKAGES[app_id]["dependencies"] - selected
        if missing:
            raise SpecError(f"partner app {app_id} is missing evidence-only dependency selection(s): {', '.join(sorted(missing))}")
    return block


def validate_cim(
    value: Any,
    spec_path: Path,
    *,
    cmm_audit_enabled: bool,
) -> dict[str, Any]:
    cim = expect_mapping(value, "spec.cim", allowed={"authentication", "change"})
    for model, requirements in CIM_REQUIREMENTS.items():
        path = f"spec.cim.{model}"
        block = expect_mapping(
            cim[model],
            path,
            allowed={"enabled", "qualifying_search", "verified_fields", "evidence_path", "evidence_sha256"},
        )
        enabled = expect_bool(block["enabled"], f"{path}.enabled")
        search = expect_string(block["qualifying_search"], f"{path}.qualifying_search", allow_empty=True, max_length=4096)
        fields = expect_string_list(block["verified_fields"], f"{path}.verified_fields")
        evidence_path = expect_string(block["evidence_path"], f"{path}.evidence_path", allow_empty=True, max_length=240)
        evidence_hash = expect_string(block["evidence_sha256"], f"{path}.evidence_sha256", allow_empty=True, max_length=64)
        block["evidence_schema_validated"] = False
        if not enabled:
            if search or fields or evidence_path or evidence_hash:
                raise SpecError(f"{path} disabled candidates must keep search, fields, and evidence empty")
            continue
        if not cmm_audit_enabled:
            raise SpecError(f"{path} can only qualify against an enabled Meeting Management audit route")
        validated_search, constrained_index, constrained_sourcetype = validate_safe_search(
            search,
            f"{path}.qualifying_search",
        )
        if constrained_index != "netops" or constrained_sourcetype != "cisco:mm:audit":
            raise SpecError(f"{path} must bind exactly index=netops sourcetype=cisco:mm:audit")
        required_fields = requirements["fields"]
        if set(fields) != required_fields:
            raise SpecError(
                f"{path}.verified_fields must exactly match the conservative CIM 8.5 field set: "
                + ", ".join(sorted(required_fields))
            )
        evidence_file, _ = verify_evidence_file(
            evidence_path,
            evidence_hash,
            spec_path,
            f"{path}.evidence",
        )
        try:
            evidence = json.loads(
                read_regular_bytes(
                    evidence_file,
                    label=f"{path}.evidence_path",
                    max_bytes=MAX_EVIDENCE_BYTES,
                ).decode("utf-8"),
                object_pairs_hook=_json_pairs_no_duplicates,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpecError(f"{path}.evidence_path must be strict UTF-8 JSON: {exc}") from exc
        validate_plain_tree(evidence, source=str(evidence_file))
        reject_secret_keys(evidence, f"{path}.evidence")
        evidence = expect_mapping(
            evidence,
            f"{path}.evidence",
            allowed={
                "schema",
                "model",
                "route",
                "index",
                "sourcetype",
                "qualifying_search_sha256",
                "required_fields",
                "required_tags",
                "field_presence",
                "tag_presence",
                "sanitized",
                "raw_event_values_included",
            },
        )
        expected_fields = sorted(required_fields)
        expected_tags = sorted(requirements["tags"])
        expected = {
            "schema": "cisco-collaboration-setup/cim-evidence/v1",
            "model": requirements["model"],
            "route": "meeting_management.audit_syslog",
            "index": "netops",
            "sourcetype": "cisco:mm:audit",
            "qualifying_search_sha256": sha256_bytes(validated_search.encode("utf-8")),
            "required_fields": expected_fields,
            "required_tags": expected_tags,
            "field_presence": {field: True for field in expected_fields},
            "tag_presence": {tag: True for tag in expected_tags},
            "sanitized": True,
            "raw_event_values_included": False,
        }
        if not type_aware_equal(evidence, expected):
            raise SpecError(f"{path}.evidence must exactly match the sanitized CIM v1 evidence schema")
        block["evidence_schema_validated"] = True
    return cim


def validate_spec(document: Any, spec_path: Path) -> dict[str, Any]:
    reject_secret_keys(document)
    reject_sensitive_text_values(document)
    spec = expect_mapping(
        document,
        "spec",
        allowed={"api_version", "project", "privacy", "products", "cim", "partner_packages", "delegation"},
    )
    if spec["api_version"] != API_VERSION:
        raise SpecError(f"spec.api_version must be {API_VERSION}")

    project = expect_mapping(
        spec["project"],
        "spec.project",
        allowed={"name", "environment", "owner", "splunk_platform_version", "sc4s_deployment"},
    )
    for field in ("name", "environment", "owner"):
        value = expect_string(project[field], f"spec.project.{field}", max_length=128)
        if not IDENTIFIER_RE.fullmatch(value):
            raise SpecError(f"spec.project.{field} contains unsupported characters")
        reject_copied_sensitive_text(value, f"spec.project.{field}")
    platform_version = expect_string(project["splunk_platform_version"], "spec.project.splunk_platform_version", max_length=32)
    parse_strict_numeric_version(platform_version, "spec.project.splunk_platform_version")
    if project["sc4s_deployment"] not in {"host", "k8s"}:
        raise SpecError("spec.project.sc4s_deployment must be host or k8s")

    privacy = expect_mapping(
        spec["privacy"],
        "spec.privacy",
        allowed={"dashboard_mode", "mask_phone_numbers", "mask_user_ids", "retention_reviewed", "restricted_role"},
    )
    if privacy["dashboard_mode"] != "masked":
        raise SpecError("spec.privacy.dashboard_mode must be masked")
    if expect_bool(privacy["mask_phone_numbers"], "spec.privacy.mask_phone_numbers") is not True:
        raise SpecError("spec.privacy.mask_phone_numbers must remain true")
    if expect_bool(privacy["mask_user_ids"], "spec.privacy.mask_user_ids") is not True:
        raise SpecError("spec.privacy.mask_user_ids must remain true")
    expect_bool(privacy["retention_reviewed"], "spec.privacy.retention_reviewed")
    role = expect_string(privacy["restricted_role"], "spec.privacy.restricted_role", max_length=128)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{1,127}", role):
        raise SpecError("spec.privacy.restricted_role must be an explicit Splunk role name")
    reject_copied_sensitive_text(role, "spec.privacy.restricted_role")

    products = expect_mapping(
        spec["products"],
        "spec.products",
        allowed={"cucm", "expressway", "cms", "meeting_management", "roomos", "broadworks", "uccx_ucce"},
    )
    cucm = expect_mapping(products["cucm"], "spec.products.cucm", allowed={"syslog", "cdr", "cmr", "axl"})
    validate_cucm_audit_syslog(cucm["syslog"], "spec.products.cucm.syslog")
    validate_cdr_cmr(
        cucm["cdr"],
        "spec.products.cucm.cdr",
        spec_path,
        expected_file_type="cdr",
    )
    validate_cdr_cmr(
        cucm["cmr"],
        "spec.products.cucm.cmr",
        spec_path,
        expected_file_type="cmr",
    )
    if cucm["cdr"]["enabled"] and cucm["cmr"]["enabled"]:
        cdr_evidence = cucm["cdr"]["evidence"]
        cmr_evidence = cucm["cmr"]["evidence"]
        cdr_path = safe_relative_evidence_path(
            cdr_evidence["sample_path"],
            spec_path,
            "spec.products.cucm.cdr.evidence.sample_path",
        )
        cmr_path = safe_relative_evidence_path(
            cmr_evidence["sample_path"],
            spec_path,
            "spec.products.cucm.cmr.evidence.sample_path",
        )
        if cdr_path == cmr_path or cdr_evidence["sha256"] == cmr_evidence["sha256"]:
            raise SpecError("enabled CUCM CDR and CMR must use distinct samples and distinct SHA-256 values")
    axl = expect_mapping(
        cucm["axl"],
        "spec.products.cucm.axl",
        allowed={"enabled", "purpose", "endpoint_path", "operator_metadata"},
    )
    axl_enabled = expect_bool(axl["enabled"], "spec.products.cucm.axl.enabled")
    if axl["purpose"] != "configuration_enrichment_only" or axl["endpoint_path"] != "/axl/":
        raise SpecError("CUCM AXL must remain configuration_enrichment_only at /axl/ and cannot substitute for CDR/CMR")
    validate_operator_readiness_metadata(
        axl["operator_metadata"],
        "spec.products.cucm.axl.operator_metadata",
        enabled=axl_enabled,
    )

    expressway = expect_mapping(
        products["expressway"],
        "spec.products.expressway",
        allowed={"syslog", "cdr_readiness", "media_readiness"},
    )
    expressway_syslog = expect_mapping(
        expressway["syslog"],
        "spec.products.expressway.syslog",
        allowed={
            "enabled",
            "transport",
            "format",
            "port",
            "trust_requirements_reviewed",
            "index",
            "sourcetype",
        },
    )
    expressway_syslog_enabled = expect_bool(
        expressway_syslog["enabled"],
        "spec.products.expressway.syslog.enabled",
    )
    expressway_transport = expect_string(
        expressway_syslog["transport"],
        "spec.products.expressway.syslog.transport",
    )
    expressway_format = expect_string(
        expressway_syslog["format"],
        "spec.products.expressway.syslog.format",
    )
    expressway_port = expressway_syslog["port"]
    if type(expressway_port) is not int:
        raise SpecError("spec.products.expressway.syslog.port must be an integer")
    trust_reviewed = expect_bool(
        expressway_syslog["trust_requirements_reviewed"],
        "spec.products.expressway.syslog.trust_requirements_reviewed",
    )
    expected_expressway_trust = expressway_syslog_enabled and expressway_transport == "tls"
    if trust_reviewed is not expected_expressway_trust:
        raise SpecError(
            "Expressway trust_requirements_reviewed must equal enabled && transport == tls"
        )
    if expressway_transport == "udp":
        if expressway_port != 514 or expressway_format not in {"legacy_bsd", "ietf"}:
            raise SpecError("Expressway UDP must use port 514 and format legacy_bsd or ietf")
    elif expressway_transport == "tls":
        if expressway_port != 6514 or expressway_format != "ietf":
            raise SpecError("Expressway TLS must use port 6514 and IETF format")
    else:
        raise SpecError("Expressway device transport must be udp or tls; plain TCP is not in the verified X15.5 contract")
    if validate_index(expressway_syslog["index"], "spec.products.expressway.syslog.index") != "main":
        raise SpecError("spec.products.expressway.syslog.index must preserve documented index main")
    if validate_sourcetype(
        expressway_syslog["sourcetype"],
        "spec.products.expressway.syslog.sourcetype",
    ) != "cisco:tvcs":
        raise SpecError("spec.products.expressway.syslog.sourcetype must preserve cisco:tvcs")
    cdr_readiness = expect_mapping(
        expressway["cdr_readiness"],
        "spec.products.expressway.cdr_readiness",
        allowed={"enabled", "mode", "operator_metadata"},
    )
    cdr_enabled = expect_bool(cdr_readiness["enabled"], "spec.products.expressway.cdr_readiness.enabled")
    if cdr_readiness["mode"] != "syslog_info":
        raise SpecError("spec.products.expressway.cdr_readiness.mode must be syslog_info")
    validate_operator_readiness_metadata(
        cdr_readiness["operator_metadata"],
        "spec.products.expressway.cdr_readiness.operator_metadata",
        enabled=cdr_enabled,
    )
    media = expect_mapping(
        expressway["media_readiness"],
        "spec.products.expressway.media_readiness",
        allowed={"enabled", "facility", "operator_metadata"},
    )
    media_enabled = expect_bool(media["enabled"], "spec.products.expressway.media_readiness.enabled")
    if media["facility"] != "local2":
        raise SpecError("spec.products.expressway.media_readiness.facility must preserve local2")
    validate_operator_readiness_metadata(
        media["operator_metadata"],
        "spec.products.expressway.media_readiness.operator_metadata",
        enabled=media_enabled,
    )

    cms = expect_mapping(products["cms"], "spec.products.cms", allowed={"syslog", "xml_cdr_receiver"})
    cms_syslog = expect_mapping(
        cms["syslog"],
        "spec.products.cms.syslog",
        allowed={"enabled", "wire_protocol", "tls_server_prefix", "index", "sourcetype", "classifier"},
    )
    expect_bool(cms_syslog["enabled"], "spec.products.cms.syslog.enabled")
    cms_wire_protocol = expect_string(cms_syslog["wire_protocol"], "spec.products.cms.syslog.wire_protocol")
    if cms_wire_protocol not in {"tcp", "tls"}:
        raise SpecError("spec.products.cms.syslog.wire_protocol must be tcp or tls; CMS never uses UDP")
    cms_tls_prefix = expect_bool(cms_syslog["tls_server_prefix"], "spec.products.cms.syslog.tls_server_prefix")
    if cms_tls_prefix is not (cms_wire_protocol == "tls"):
        raise SpecError("CMS tls_server_prefix must be true exactly when wire_protocol is tls")
    if validate_index(cms_syslog["index"], "spec.products.cms.syslog.index") != "netops":
        raise SpecError("spec.products.cms.syslog.index must preserve documented index netops")
    if validate_sourcetype(cms_syslog["sourcetype"], "spec.products.cms.syslog.sourcetype") != "cisco:ms":
        raise SpecError("spec.products.cms.syslog.sourcetype must preserve cisco:ms")
    _, cms_selector = validate_classifier(cms_syslog["classifier"], "spec.products.cms.syslog.classifier")
    xml_cdr = expect_mapping(
        cms["xml_cdr_receiver"],
        "spec.products.cms.xml_cdr_receiver",
        allowed={"status", "enabled", "transport", "receiver_implementation"},
    )
    if (
        xml_cdr["status"] != "gap"
        or expect_bool(xml_cdr["enabled"], "spec.products.cms.xml_cdr_receiver.enabled") is not False
        or xml_cdr["transport"] != "https"
        or xml_cdr["receiver_implementation"] != "UNKNOWN"
    ):
        raise SpecError("CMS XML CDR receiver must remain an explicit disabled HTTPS gap with implementation UNKNOWN")

    cmm = expect_mapping(
        products["meeting_management"],
        "spec.products.meeting_management",
        allowed={"classifier", "system_syslog", "audit_syslog"},
    )
    _, cmm_selector = validate_classifier(
        cmm["classifier"],
        "spec.products.meeting_management.classifier",
    )
    cmm_system = validate_cmm_syslog_path(
        cmm["system_syslog"],
        "spec.products.meeting_management.system_syslog",
        spec_path,
        route="meeting_management.system_syslog",
        fixed_sourcetype="cisco:mm:system:*",
    )
    cmm_audit = validate_cmm_syslog_path(
        cmm["audit_syslog"],
        "spec.products.meeting_management.audit_syslog",
        spec_path,
        route="meeting_management.audit_syslog",
        fixed_sourcetype="cisco:mm:audit",
    )
    if (
        cmm_system["enabled"]
        and cmm_audit["enabled"]
        and cmm_system["wire_protocol"] != cmm_audit["wire_protocol"]
    ):
        raise SpecError("enabled CMM system and audit routes must share one wire_protocol under the shared deterministic classifier")
    if cms_syslog["enabled"] and (cmm_system["enabled"] or cmm_audit["enabled"]):
        if cms_selector[0] != cmm_selector[0]:
            raise SpecError(
                "CMS and Meeting Management must use the same classifier mode; mixed modes cannot prove disjointness"
            )
        if cms_selector == cmm_selector:
            raise SpecError("CMS and Meeting Management classifiers overlap; use distinct values in the same selector mode")

    roomos = expect_mapping(
        products["roomos"],
        "spec.products.roomos",
        allowed={"status", "emit_webex_handoff", "emit_thousandeyes_handoff"},
    )
    if roomos["status"] != "unsupported_roadmap":
        raise SpecError("RoomOS must remain unsupported_roadmap")
    expect_bool(roomos["emit_webex_handoff"], "spec.products.roomos.emit_webex_handoff")
    expect_bool(roomos["emit_thousandeyes_handoff"], "spec.products.roomos.emit_thousandeyes_handoff")
    broadworks = expect_mapping(
        products["broadworks"],
        "spec.products.broadworks",
        allowed={"status", "vendor_url"},
    )
    if broadworks["status"] != "unsupported_roadmap":
        raise SpecError("BroadWorks must remain unsupported_roadmap")
    expected_broadworks_url = "https://developer.cisco.com/docs/broadworks/getting-started/"
    if broadworks["vendor_url"] != expected_broadworks_url:
        raise SpecError("BroadWorks vendor_url must remain the verified Cisco documentation URL")
    ucc = expect_mapping(products["uccx_ucce"], "spec.products.uccx_ucce", allowed={"status"})
    if ucc["status"] != "UNKNOWN":
        raise SpecError("UCCX/UCCE status must remain UNKNOWN")

    validate_cim(
        spec["cim"],
        spec_path,
        cmm_audit_enabled=cmm_audit["enabled"],
    )
    validate_partner_packages(spec["partner_packages"], spec_path, platform_version)

    delegation = expect_mapping(spec["delegation"], "spec.delegation", allowed={"mode", "sections"})
    if delegation["mode"] != "handoff_only":
        raise SpecError("spec.delegation.mode must be handoff_only; executable or mixed modes are forbidden")
    if not isinstance(delegation["sections"], list) or not delegation["sections"]:
        raise SpecError("spec.delegation.sections must be a nonempty list")
    section_names: list[str] = []
    dispositions: set[str] = set()
    for index, section_value in enumerate(delegation["sections"]):
        path = f"spec.delegation.sections[{index}]"
        section = expect_mapping(section_value, path, allowed={"name", "disposition"})
        name = expect_string(section["name"], f"{path}.name")
        disposition = expect_string(section["disposition"], f"{path}.disposition")
        if name not in DELEGATION_SECTIONS:
            raise SpecError(f"{path}.name is unsupported: {name}")
        dispositions.add(disposition)
        if disposition != "handoff_only":
            raise SpecError(f"{path}.disposition must be handoff_only; executable sections are forbidden")
        section_names.append(name)
    if len(section_names) != len(set(section_names)):
        raise SpecError("spec.delegation.sections contains duplicates")
    if dispositions != {"handoff_only"}:
        raise SpecError("mixed executable and handoff-only sections are forbidden")
    required_sections: set[str] = set()
    if any(
        route["enabled"]
        for route in (cucm["syslog"], expressway["syslog"], cms_syslog, cmm_system, cmm_audit)
    ):
        required_sections.add("collaboration-syslog")
    if cucm["cdr"]["enabled"] or cucm["cmr"]["enabled"]:
        required_sections.add("cdr-cmr-collection")
    if roomos["emit_webex_handoff"]:
        required_sections.add("roomos-webex")
    if roomos["emit_thousandeyes_handoff"]:
        required_sections.add("roomos-thousandeyes")
    missing_sections = sorted(required_sections - set(section_names))
    if missing_sections:
        raise SpecError(f"spec.delegation.sections is missing required handoff(s): {', '.join(missing_sections)}")
    return spec


def load_spec(path_value: str | Path) -> tuple[dict[str, Any], Path, str]:
    path = lexical_absolute(path_value)
    payload = read_regular_bytes(path, label="spec", max_bytes=MAX_SPEC_BYTES)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SpecError("spec must be UTF-8 text") from exc
    try:
        document = strict_load_yaml_or_json(text, source=str(path))
    except (YamlCompatError, ValueError) as exc:
        raise SpecError(str(exc)) from exc
    spec = validate_spec(document, path)
    return spec, path, sha256_bytes(payload)


def load_source_ledger() -> dict[str, Any]:
    payload = read_regular_bytes(
        SOURCE_LEDGER_PATH,
        label="source ledger",
        max_bytes=MAX_SPEC_BYTES,
    )
    try:
        ledger = json.loads(payload, object_pairs_hook=_json_pairs_no_duplicates)
    except json.JSONDecodeError as exc:
        raise SpecError(f"source ledger is invalid JSON: {exc}") from exc
    validate_plain_tree(ledger, source=str(SOURCE_LEDGER_PATH))
    if (
        type(ledger.get("schema_version")) is not int
        or ledger.get("schema_version") != 1
        or ledger.get("skill") != SKILL_NAME
        or ledger.get("repository_base_commit") != BASE_COMMIT
        or ledger.get("sc4s_upstream_commit") != SC4S_COMMIT
        or ledger.get("research_checked_date") != CHECKED_DATE
    ):
        raise SpecError("source ledger metadata is not pinned to the verified Phase 3 base and source dates")
    sources = ledger.get("sources")
    if not isinstance(sources, list) or not sources:
        raise SpecError("source ledger must contain sources")
    claim_ids = [row.get("claim_id") for row in sources if isinstance(row, dict)]
    if len(claim_ids) != len(sources) or len(claim_ids) != len(set(claim_ids)):
        raise SpecError("source ledger claim IDs must be complete and unique")
    by_id = {row["claim_id"]: row for row in sources}
    exact_sc4s_sources = {
        "sc4s-ucm-parser-source": "package/shared/addons/cisco/app-cisco-cisco_ucm.conf",
        "sc4s-ucm-parser-test": "tests/test_cisco_ucm.py",
        "sc4s-tvcs-parser-source": "package/shared/addons/cisco/app-syslog-cisco_tvcs.conf",
        "sc4s-tvcs-parser-test": "tests/test_cisco_tvcs.py",
        "sc4s-cms-parser-source": "package/shared/addons/cisco/app-netsource-cisco_ms.conf",
        "sc4s-cmm-classifier-source": "package/shared/addons/cisco/app-netsource-cisco_mm.conf",
        "sc4s-cmm-parser-source": "package/shared/addons/cisco/app-syslog-cisco_mm.conf",
    }
    for claim_id, expected_path in exact_sc4s_sources.items():
        url = str(by_id.get(claim_id, {}).get("url", ""))
        if (
            SC4S_COMMIT not in url
            or not url.endswith(expected_path)
            or "/main/" in url
            or "/latest/" in url
        ):
            raise SpecError(f"{claim_id} must use a commit-addressed SC4S source URL")
    tree_url = str(by_id.get("sc4s-cisco-source-index", {}).get("url", ""))
    if tree_url != (
        "https://github.com/splunk/splunk-connect-for-syslog/tree/"
        + SC4S_COMMIT
        + "/package/shared/addons/cisco"
    ):
        raise SpecError("SC4S source index must use the exact commit-pinned package/shared/addons/cisco tree")
    required_claims = {
        "cisco-cucm-cdr-15",
        "cisco-cucm-cdr-15-billing-setup",
        "cisco-cucm-cdr-15-export-distinction",
        "cisco-cucm-cdr-15-export-cdr-type-mapping",
        "cisco-cucm-cdr-15-export-cmr-type-mapping",
        "cisco-cucm-cdr-15-record-format",
        "cisco-cucm-cdr-15-cdr-fields",
        "cisco-cucm-cdr-15-cmr-fields",
        "cisco-cucm-15-remote-audit-syslog",
        "cisco-cms-product-3-13",
        "cisco-cms-mmp-3-13",
        "cisco-cms-cdr-3-11-current",
        "cisco-cmm-3-13-current",
        "sc4s-ucm-parser-source",
        "sc4s-ucm-parser-test",
        "sc4s-custom-port-source-current",
        "sc4s-custom-port-troubleshooting-3-29",
        "sc4s-tvcs-parser-source",
        "sc4s-tvcs-parser-test",
        "sc4s-cms-parser-source",
        "sc4s-cmm-classifier-source",
        "sc4s-cmm-parser-source",
        "sc4s-cisco-source-index",
        "splunk-cim-model-list-8-5",
        "splunk-cim-authentication-8-5",
        "splunk-cim-change-8-5",
        "splunk-fields-command-10-5-2605",
        "splunk-dashboard-studio-current",
        "cisco-roomos-26-2-api",
        "cisco-webex-xapi",
        "cisco-roomos-environmental-sensors",
        "cisco-roomos-people-presence",
        "cisco-roomos-thousandeyes-handoff",
        "cisco-broadworks-primary-interface",
    }
    missing_claims = sorted(required_claims - set(by_id))
    if missing_claims:
        raise SpecError(f"source ledger is missing current primary claim(s): {', '.join(missing_claims)}")
    if "cisco-cmm-3-1-historical" in by_id:
        raise SpecError("dead CMM 3.1 historical source must not be retained")
    required_claim_text = {
        "cisco-cucm-cdr-15-record-format": ("line 1", "line 2", "lines 3"),
        "cisco-cucm-cdr-15-export-cdr-type-mapping": (
            "exported CDR type row maps callingPartyNumber and finalCalledPartyNumber to VARCHAR(50)",
            "current exported CDR type row",
        ),
        "cisco-cucm-cdr-15-export-cmr-type-mapping": (
            "maps globalCallID_callId to INTEGER",
            "directoryNum to VARCHAR(50)",
            "only exported CMR pair eligible",
        ),
        "cisco-cucm-cdr-15-cdr-fields": (
            "always 1",
            "Positive Integer",
            "origLegCallIdentifier",
        ),
        "cisco-cucm-cdr-15-cmr-fields": (
            "always 2",
            "globalCallId_callId with directoryNumber is field-description compatibility only",
            "Positive Integer",
            "jitter is unsigned",
            "may be negative",
        ),
        "cisco-cucm-15-remote-audit-syslog": (
            "specifically to CUCM remote audit logging",
            "default protocol is UDP",
            "UDP, TCP, or TLS",
            "operator-selected port",
        ),
        "cisco-cms-mmp-3-13": ("TCP, not UDP", "tls:"),
        "cisco-cmm-3-13-current": ("up to five", "UDP, TCP, and TLS", "TLS 1.2", "8192"),
        "sc4s-ucm-parser-source": ("cisco:ucm", "%UC_/%CCM_"),
        "sc4s-custom-port-source-current": ("SC4S_LISTEN_{VENDOR}_{PRODUCT}_{PROTOCOL}_PORT", "exclusively"),
        "sc4s-tvcs-parser-source": ("cisco:tvcs", "implemented"),
        "cisco-roomos-26-2-api": ("does not establish a verified Splunk parser or collector",),
        "cisco-webex-xapi": ("distinct Webex handoff",),
        "cisco-roomos-thousandeyes-handoff": ("distinct ThousandEyes handoff",),
        "splunk-fields-command-10-5-2605": (
            "retains the internal _raw and _time fields",
            "timechart requires _time",
            "removes _raw as the final pre-aggregation step",
        ),
        "splunk-dashboard-studio-current": ("starter SPL search", "does not claim or install"),
    }
    for claim_id, fragments in required_claim_text.items():
        claim = str(by_id.get(claim_id, {}).get("claim", ""))
        missing_fragments = [fragment for fragment in fragments if fragment not in claim]
        if missing_fragments:
            raise SpecError(
                f"source ledger claim {claim_id} is missing gated content: {', '.join(missing_fragments)}"
            )
    return ledger


def validated_output_path(raw: str | Path) -> Path:
    lexical = lexical_absolute(raw)
    if lexical.is_symlink():
        raise SpecError(f"output directory must not be a symlink: {lexical}")
    reject_symlink_components(lexical, label="output directory")
    resolved = lexical.resolve(strict=False)
    reject_copied_sensitive_text(str(resolved), "resolved output directory")
    forbidden = {Path("/").resolve(), Path.home().resolve(), REPO_ROOT.resolve(), SKILL_DIR.resolve()}
    if resolved in forbidden:
        raise SpecError(f"refusing unsafe output directory: {resolved}")
    if lexical.exists() and not lexical.is_dir():
        raise SpecError(f"output path must be a directory: {lexical}")
    if not lexical.parent.exists():
        raise SpecError(f"output parent must already exist so ownership can be verified: {lexical.parent}")
    require_owned_directory(lexical.parent, label="output parent", private=False)
    return resolved


def marker_payload(out: Path, artifact_commitments: dict[str, str]) -> dict[str, Any]:
    reject_copied_sensitive_text(str(out), "marker-bound output directory")
    if set(artifact_commitments) != EXPECTED_ARTIFACTS or any(
        not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
        for digest in artifact_commitments.values()
    ):
        raise SpecError("output marker requires one SHA-256 commitment for every rendered artifact")
    return {
        "schema": BUNDLE_SCHEMA,
        "skill": SKILL_NAME,
        "bundle_root": str(out),
        "artifact_commitments": dict(sorted(artifact_commitments.items())),
        "provenance_boundary": "unkeyed_integrity_only_external_trusted_spec_required",
    }


def inspect_bundle_tree(out: Path) -> set[str]:
    root_metadata = require_owned_directory(out, label="output bundle root", private=True)
    root_device = root_metadata.st_dev
    found_files: set[str] = set()
    for current, dirs, files in os.walk(out, topdown=True, followlinks=False):
        current_path = Path(current)
        current_meta = current_path.lstat()
        if not stat.S_ISDIR(current_meta.st_mode) or current_meta.st_dev != root_device:
            raise SpecError(f"unsafe output directory encountered: {current_path}")
        if current_meta.st_uid != current_uid() or stat.S_IMODE(current_meta.st_mode) != 0o700:
            raise SpecError(f"output directories must be current-user-owned mode 0700: {current_path}")
        for name in [*dirs, *files]:
            child = current_path / name
            metadata = child.lstat()
            rel = child.relative_to(out).as_posix()
            if stat.S_ISLNK(metadata.st_mode):
                raise SpecError(f"output bundle contains a symlink: {child}")
            if metadata.st_dev != root_device:
                raise SpecError(f"output bundle crosses a filesystem boundary: {child}")
            if metadata.st_uid != current_uid():
                raise SpecError(f"output bundle entry must be owned by the current user: {child}")
            if name in dirs:
                if not stat.S_ISDIR(metadata.st_mode):
                    raise SpecError(f"output bundle contains a non-directory in its directory list: {child}")
                if stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise SpecError(f"output bundle directories must have mode 0700: {child}")
            else:
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise SpecError(f"output bundle files must be single-link regular files: {child}")
                if metadata.st_size > MAX_ARTIFACT_BYTES:
                    raise SpecError(f"output artifact exceeds size limit: {child}")
                if stat.S_IMODE(metadata.st_mode) != 0o600:
                    raise SpecError(f"output bundle files must have mode 0600: {child}")
                found_files.add(rel)
    return found_files


def read_marker(marker: Path, out: Path) -> dict[str, Any]:
    payload = read_regular_bytes(marker, label="output marker", max_bytes=4096)
    actual = strict_load_json_bytes(payload, source=str(marker))
    actual = expect_mapping(
        actual,
        "output marker",
        allowed={
            "schema",
            "skill",
            "bundle_root",
            "artifact_commitments",
            "provenance_boundary",
        },
    )
    commitments = expect_mapping(
        actual["artifact_commitments"],
        "output marker.artifact_commitments",
        allowed=set(EXPECTED_ARTIFACTS),
    )
    expected = marker_payload(out, commitments)
    if not type_aware_equal(actual, expected):
        raise SpecError(f"output marker does not own this exact {SKILL_NAME} bundle: {marker}")
    return actual


def create_marker(marker: Path, out: Path, artifact_commitments: dict[str, str]) -> None:
    payload = canonical_json(marker_payload(out, artifact_commitments)).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(marker, flags, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(marker, 0o600, follow_symlinks=False)


def ensure_private_artifact_parent(out: Path, destination: Path) -> None:
    try:
        relative_parent = destination.parent.relative_to(out)
    except ValueError as exc:
        raise SpecError(f"artifact parent escapes the private staging root: {destination.parent}") from exc
    current = out
    require_owned_directory(current, label="private staging root", private=True)
    for part in relative_parent.parts:
        current /= part
        if not current.exists() and not current.is_symlink():
            os.mkdir(current, 0o700)
        require_owned_directory(current, label="artifact directory", private=True)


def existing_identity(path: Path) -> tuple[int, int, int, int]:
    metadata = require_owned_directory(path, label="output bundle root", private=True)
    return (metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_ctime_ns)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_bundle_tree(root: Path) -> None:
    """Flush a renderer-owned private stage without following links."""
    inspect_bundle_tree(root)
    directories: list[Path] = []
    for current, dirs, _files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories.append(current_path)
        for name in dirs:
            child = current_path / name
            if child.is_symlink():
                raise SpecError(f"private staging bundle contains a symlink: {child}")
    for directory in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(directory)


def new_backup_path(out: Path) -> Path:
    for _ in range(100):
        suffix = os.urandom(8).hex()
        candidate = out.parent / f".{out.name}.backup-{suffix}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise SpecError(f"could not allocate a unique backup name beside {out}")


@contextmanager
def output_lock(out: Path) -> Iterable[Path]:
    """Serialize one target using an exclusive private sibling lock file."""
    parent = out.parent
    require_owned_directory(parent, label="output parent", private=False)
    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    parent_fd = os.open(parent, parent_flags)
    lock_name = f".{out.name}.lock"
    lock_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        lock_flags |= os.O_NOFOLLOW
    lock_fd = -1
    lock_identity: tuple[int, int] | None = None
    try:
        try:
            lock_fd = os.open(lock_name, lock_flags, 0o600, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise SpecError(f"another render or stale private lock exists for {out}: {parent / lock_name}") from exc
        lock_metadata = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(lock_metadata.st_mode)
            or lock_metadata.st_nlink != 1
            or lock_metadata.st_uid != current_uid()
            or stat.S_IMODE(lock_metadata.st_mode) != 0o600
        ):
            raise SpecError(f"render lock failed ownership/mode validation: {parent / lock_name}")
        lock_identity = (lock_metadata.st_dev, lock_metadata.st_ino)
        os.write(
            lock_fd,
            canonical_json({"schema": BUNDLE_SCHEMA, "target": out.name, "pid": os.getpid()}).encode("utf-8"),
        )
        os.fsync(lock_fd)
        fsync_directory(parent)
        yield parent / lock_name
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        if lock_identity is not None:
            try:
                current = os.stat(lock_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (current.st_dev, current.st_ino) != lock_identity or not stat.S_ISREG(current.st_mode):
                    os.close(parent_fd)
                    raise SpecError(f"render lock changed while held and was not removed: {parent / lock_name}")
                os.unlink(lock_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
        os.close(parent_fd)


def publish_staged_bundle(
    stage: Path,
    out: Path,
    *,
    replace_existing: bool,
    inspected_identity: tuple[int, int, int, int] | None,
) -> Path | None:
    """Publish by rename; preserve old output and never recursively delete it."""
    if stage.parent != out.parent:
        raise SpecError("staging and publication targets must be siblings on one filesystem")
    backup: Path | None = None
    current_exists = out.exists() or out.is_symlink()
    new_published = False
    try:
        if inspected_identity is None:
            if current_exists:
                raise SpecError(f"output appeared after preflight; refusing publication: {out}")
        else:
            if not current_exists:
                raise SpecError(f"existing output disappeared after preflight; refusing publication: {out}")
            current_identity = existing_identity(out)
            if current_identity != inspected_identity:
                raise SpecError(f"existing output changed after preflight; refusing publication: {out}")
            if not replace_existing:
                raise SpecError(f"output already exists; review it and rerun with --replace-existing: {out}")
            backup = new_backup_path(out)
            os.rename(out, backup)
            if existing_identity(backup)[:2] != inspected_identity[:2]:
                raise SpecError(f"existing output identity changed during recoverable rename; preserved at {backup}")
            fsync_directory(out.parent)
        if out.exists() or out.is_symlink():
            raise SpecError(f"publication target is no longer empty: {out}")
        os.rename(stage, out)
        new_published = True
        fsync_directory(out.parent)
    except Exception:
        if new_published and (out.exists() or out.is_symlink()) and not stage.exists() and not stage.is_symlink():
            os.rename(out, stage)
        if backup is not None and not out.exists() and not out.is_symlink():
            os.rename(backup, out)
        fsync_directory(out.parent)
        raise
    return backup


def create_private_stage(out: Path, artifact_commitments: dict[str, str]) -> Path:
    reject_symlink_components(out.parent, label="output parent")
    require_owned_directory(out.parent, label="output parent", private=False)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.stage-", dir=out.parent))
    stage.chmod(0o700)
    require_owned_directory(stage, label="private staging root", private=True)
    create_marker(stage / MARKER_NAME, out, artifact_commitments)
    return stage


def remove_private_stage(stage: Path, expected_identity: tuple[int, int, int, int]) -> None:
    """Remove only the exact renderer-created unpublished private stage via dirfds."""
    parent = stage.parent
    parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        parent_flags |= os.O_NOFOLLOW
    directory_flags = parent_flags
    parent_fd = os.open(parent, parent_flags)

    def clear_directory(fd: int) -> None:
        for name in os.listdir(fd):
            metadata = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if metadata.st_uid != current_uid():
                raise SpecError(f"refusing to clean an unowned staging entry: {stage / name}")
            if stat.S_ISDIR(metadata.st_mode):
                if stat.S_IMODE(metadata.st_mode) != 0o700:
                    raise SpecError(f"refusing to clean a non-private staging directory: {stage / name}")
                child_fd = os.open(name, directory_flags, dir_fd=fd)
                try:
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
                        raise SpecError(f"staging directory changed during cleanup: {stage / name}")
                    clear_directory(child_fd)
                finally:
                    os.close(child_fd)
                os.rmdir(name, dir_fd=fd)
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and stat.S_IMODE(metadata.st_mode) == 0o600:
                os.unlink(name, dir_fd=fd)
            else:
                raise SpecError(f"refusing to clean an unexpected staging entry: {stage / name}")

    try:
        metadata = os.stat(stage.name, dir_fd=parent_fd, follow_symlinks=False)
        identity = (metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_ctime_ns)
        if identity[:2] != expected_identity[:2] or not stat.S_ISDIR(metadata.st_mode):
            raise SpecError(f"unpublished stage changed identity and was preserved for review: {stage}")
        stage_fd = os.open(stage.name, directory_flags, dir_fd=parent_fd)
        try:
            clear_directory(stage_fd)
        finally:
            os.close(stage_fd)
        os.rmdir(stage.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def safe_write(out: Path, relative: str, content: str) -> None:
    if relative not in EXPECTED_ARTIFACTS:
        raise SpecError(f"renderer attempted an undeclared artifact: {relative}")
    destination = out / relative
    ensure_private_artifact_parent(out, destination)
    if destination.exists() or destination.is_symlink():
        raise SpecError(f"artifact already exists after bundle preparation: {destination}")
    payload = content.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(destination, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise SpecError(f"short write for artifact: {destination}")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(destination, 0o600, follow_symlinks=False)


def readiness_status(enabled: bool, *, local_evidence: bool = False) -> str:
    if not enabled:
        return "disabled"
    return "locally_evidence_qualified" if local_evidence else "planned_render_handoff"


def offline_state(
    enabled: bool,
    *,
    local_sample_validated: bool = False,
    operator_asserted: bool = False,
) -> dict[str, Any]:
    return {
        "status": readiness_status(enabled, local_evidence=local_sample_validated),
        "planned": enabled,
        "local_sample_validated": bool(enabled and local_sample_validated),
        "operator_asserted": bool(enabled and operator_asserted),
        "live_verified": False,
    }


def build_sc4s_plan(spec: dict[str, Any]) -> dict[str, Any]:
    products = spec["products"]
    expressway_enabled = products["expressway"]["syslog"]["enabled"]
    cms_enabled = products["cms"]["syslog"]["enabled"]
    cmm_enabled = (
        products["meeting_management"]["system_syslog"]["enabled"]
        or products["meeting_management"]["audit_syslog"]["enabled"]
    )
    routes: list[dict[str, Any]] = []
    routes.append(
        {
            "product": "cucm",
            "enabled": products["cucm"]["syslog"]["enabled"],
            "device_scope": products["cucm"]["syslog"]["scope"],
            "transport": products["cucm"]["syslog"]["transport"],
            "device_port": products["cucm"]["syslog"]["receiver_port"],
            "port_origin": "operator_selected_not_cisco_default",
            "tls_authentication": products["cucm"]["syslog"]["tls_authentication"],
            "device_trust_requirements_reviewed": products["cucm"]["syslog"]["trust_requirements_reviewed"],
            "listener_readiness": (
                "unresolved_handoff_gap"
                if products["cucm"]["syslog"]["enabled"]
                else "disabled"
            ),
            "listener_capability_boundary": "CUCM remote-audit protocol and operator-selected port do not prove a matching SC4S listener. No CUCM vendor-port, source-TLS flag, or certificate setting is generated.",
            "index": "ucm",
            "sourcetypes": ["cisco:ucm"],
            "classification": "built_in_parser_detection",
            "vendor_product_by_source_required": False,
        }
    )
    routes.append(
        {
            "product": "expressway",
            "enabled": expressway_enabled,
            "transport": products["expressway"]["syslog"]["transport"],
            "device_format": products["expressway"]["syslog"]["format"],
            "device_port": products["expressway"]["syslog"]["port"],
            "device_trust_requirements_reviewed": products["expressway"]["syslog"]["trust_requirements_reviewed"],
            "index": "main",
            "sourcetypes": ["cisco:tvcs"],
            "classification": "built_in_parser_detection",
            "vendor_product_by_source_required": False,
            "listener_readiness": (
                "disabled"
                if not expressway_enabled
                else "unresolved_handoff_gap"
                if products["expressway"]["syslog"]["transport"] == "tls"
                else "planned_render_handoff"
            ),
            "listener_capability_boundary": "Expressway device TLS support does not prove SC4S TLS listener or certificate readiness; no source-TLS flag/certificate setting is generated.",
            "documented_inconsistency": "Mutable SC4S human documentation contains cisco:vcs in one table; the commit-pinned implemented parser and test use cisco:tvcs.",
        }
    )
    routes.append(
        {
            "product": "cms",
            "enabled": cms_enabled,
            "transport": "tcp",
            "wire_protocol": products["cms"]["syslog"]["wire_protocol"],
            "tls_server_prefix": products["cms"]["syslog"]["tls_server_prefix"],
            "listener_readiness": (
                "disabled"
                if not cms_enabled
                else "unresolved_handoff_gap"
                if products["cms"]["syslog"]["wire_protocol"] == "tls"
                else "planned_render_handoff"
            ),
            "index": "netops",
            "sourcetypes": ["cisco:ms"],
            "classification": products["cms"]["syslog"]["classifier"],
            "vendor_product_by_source_required": True,
            "vendor": "cisco",
            "sc4s_product": "ms",
        }
    )
    routes.append(
        {
            "product": "meeting_management",
            "enabled": cmm_enabled,
            "transport": "tcp",
            "system_wire_protocol": products["meeting_management"]["system_syslog"]["wire_protocol"],
            "audit_wire_protocol": products["meeting_management"]["audit_syslog"]["wire_protocol"],
            "index": "netops",
            "sourcetypes": (
                (["cisco:mm:system:*"] if products["meeting_management"]["system_syslog"]["enabled"] else [])
                + (["cisco:mm:audit"] if products["meeting_management"]["audit_syslog"]["enabled"] else [])
            ),
            "classification": products["meeting_management"]["classifier"],
            "system_enabled": products["meeting_management"]["system_syslog"]["enabled"],
            "audit_enabled": products["meeting_management"]["audit_syslog"]["enabled"],
            "listener_readiness": (
                "disabled"
                if not cmm_enabled
                else "unresolved_handoff_gap"
                if any(
                    route["enabled"] and route["wire_protocol"] == "tls"
                    for route in (
                        products["meeting_management"]["system_syslog"],
                        products["meeting_management"]["audit_syslog"],
                    )
                )
                else "planned_render_handoff"
            ),
            "supported_tls_version": "TLS1.2",
            "receiver_max_bytes": 8192,
            "system_planned_server_count": products["meeting_management"]["system_syslog"]["planned_server_count"],
            "audit_planned_server_count": products["meeting_management"]["audit_syslog"]["planned_server_count"],
            "documented_max_servers_per_path": 5,
            "vendor_product_by_source_required": True,
            "vendor": "cisco",
            "sc4s_product": "mm",
        }
    )
    return {
        "schema_version": 1,
        "status": "planned_render_handoff",
        "sc4s_upstream_commit": SC4S_COMMIT,
        "human_documentation_checked_date": CHECKED_DATE,
        "routes": routes,
        "overlap_check": "offline_disjointness_checked",
        "generated_config_applied": False,
    }


def build_handoff_plan(spec: dict[str, Any], out: Path) -> dict[str, Any]:
    reject_copied_sensitive_text(str(out), "handoff parent output directory")
    child_out = out.parent / f"{out.name}-sc4s-child-render"
    reject_copied_sensitive_text(str(child_out), "SC4S child output directory")
    requested = [row["name"] for row in spec["delegation"]["sections"]]
    syslog_enabled = any(
        route["enabled"]
        for route in (
            spec["products"]["cucm"]["syslog"],
            spec["products"]["expressway"]["syslog"],
            spec["products"]["cms"]["syslog"],
            spec["products"]["meeting_management"]["system_syslog"],
            spec["products"]["meeting_management"]["audit_syslog"],
        )
    )
    sections: list[dict[str, Any]] = []
    for name in requested:
        commands: list[list[str]] = []
        boundary = "Review the packet; no child apply or device mutation is generated."
        if name == "collaboration-syslog":
            if not syslog_enabled:
                boundary = "No collaboration syslog route is enabled; no SC4S child render command is emitted."
                sections.append(
                    {
                        "name": name,
                        "disposition": "handoff_only",
                        "commands": commands,
                        "boundary": boundary,
                    }
                )
                continue
            mode = "--render-host" if spec["project"]["sc4s_deployment"] == "host" else "--render-k8s"
            command = [
                "bash",
                "skills/splunk-connect-for-syslog-setup/scripts/setup.sh",
                mode,
                "--output-dir",
                str(child_out),
                "--hec-url",
                "https://hec.invalid",
            ]
            cms_syslog = spec["products"]["cms"]["syslog"]
            if (
                cms_syslog["enabled"]
                and cms_syslog["wire_protocol"] == "tcp"
                and cms_syslog["classifier"]["mode"] == "dedicated_port"
            ):
                command.extend(["--vendor-port", f"cisco_ms:tcp:{cms_syslog['classifier']['value']}"])
            cmm = spec["products"]["meeting_management"]
            if (
                cmm["system_syslog"]["enabled"] or cmm["audit_syslog"]["enabled"]
            ) and all(
                not route["enabled"] or route["wire_protocol"] == "tcp"
                for route in (cmm["system_syslog"], cmm["audit_syslog"])
            ) and cmm["classifier"]["mode"] == "dedicated_port":
                command.extend(["--vendor-port", f"cisco_mm:tcp:{cmm['classifier']['value']}"])
            commands.append(command)
            boundary = "Child command renders credential-placeholder SC4S assets to a separate sibling outside this evidence packet. The child renderer currently emits some 0755 directories/0644 non-secret files, so operator privacy hardening remains required. Exact-source and Expressway TLS listener/certificate plans remain unresolved; no SC4S apply is emitted."
        elif name == "cdr-cmr-collection":
            commands.append(["bash", "skills/splunk-agent-management-setup/scripts/setup.sh", "--help"])
            boundary = "Help-only handoff. Choose and review a file-monitor/deployment workflow after the independent CDR and CMR evidence gates pass."
        elif name == "roomos-webex":
            commands.append(["bash", "skills/cisco-webex-setup/scripts/setup.sh", "--help"])
            boundary = "Help-only Webex handoff; RoomOS remains unsupported_roadmap in this router."
        elif name == "roomos-thousandeyes":
            commands.append(["bash", "skills/cisco-thousandeyes-setup/scripts/setup.sh", "--help"])
            boundary = "Help-only ThousandEyes handoff; endpoint/network evidence remains distinct from Webex evidence."
        elif name == "downstream-readiness":
            commands.append(["bash", "skills/splunk-data-source-readiness-doctor/scripts/setup.sh", "--help"])
            boundary = "Help-only downstream readiness handoff after an operator applies independently reviewed collection assets."
        sections.append(
            {
                "name": name,
                "disposition": "handoff_only",
                "commands": commands,
                "boundary": boundary,
            }
        )
    return {
        "schema_version": 1,
        "mode": "handoff_only",
        "offline_default": True,
        "child_apply_allowed": False,
        "device_mutation_allowed": False,
        "commands_are_argv_arrays": True,
        "child_output_must_be_separately_owned": True,
        "child_output_privacy_status": "operator_hardening_required",
        "sections": sections,
    }


def build_readiness(spec: dict[str, Any]) -> dict[str, Any]:
    p = spec["products"]
    cmm = p["meeting_management"]
    rows = [
        {
            "path": "cucm.syslog",
            **offline_state(
                p["cucm"]["syslog"]["enabled"],
                operator_asserted=p["cucm"]["syslog"]["trust_requirements_reviewed"],
            ),
            "profile": "remote_audit_logging",
            "transport": p["cucm"]["syslog"]["transport"],
            "receiver_port": p["cucm"]["syslog"]["receiver_port"],
            "receiver_port_origin": "operator_selected_not_cisco_default",
            "sc4s_listener_gap": p["cucm"]["syslog"]["enabled"],
            "index": "ucm",
            "sourcetypes": ["cisco:ucm"],
        },
        {"path": "cucm.cdr", **offline_state(p["cucm"]["cdr"]["enabled"], local_sample_validated=p["cucm"]["cdr"]["enabled"]), "index": p["cucm"]["cdr"]["index"], "sourcetypes": [p["cucm"]["cdr"]["sourcetype"]] if p["cucm"]["cdr"]["enabled"] else []},
        {"path": "cucm.cmr", **offline_state(p["cucm"]["cmr"]["enabled"], local_sample_validated=p["cucm"]["cmr"]["enabled"]), "index": p["cucm"]["cmr"]["index"], "sourcetypes": [p["cucm"]["cmr"]["sourcetype"]] if p["cucm"]["cmr"]["enabled"] else []},
        {
            "path": "cucm.axl",
            **offline_state(
                p["cucm"]["axl"]["enabled"],
                operator_asserted=p["cucm"]["axl"]["operator_metadata"]["operator_metadata_present"],
            ),
            "operator_metadata_present": p["cucm"]["axl"]["operator_metadata"]["operator_metadata_present"],
            "boundary": "configuration enrichment only; no source-backed event schema is claimed",
        },
        {"path": "expressway.syslog", **offline_state(p["expressway"]["syslog"]["enabled"], operator_asserted=p["expressway"]["syslog"]["trust_requirements_reviewed"]), "index": "main", "sourcetypes": ["cisco:tvcs"], "sc4s_tls_listener_gap": p["expressway"]["syslog"]["enabled"] and p["expressway"]["syslog"]["transport"] == "tls"},
        {
            "path": "expressway.cdr_readiness",
            **offline_state(
                p["expressway"]["cdr_readiness"]["enabled"],
                operator_asserted=p["expressway"]["cdr_readiness"]["operator_metadata"]["operator_metadata_present"],
            ),
            "operator_metadata_present": p["expressway"]["cdr_readiness"]["operator_metadata"]["operator_metadata_present"],
        },
        {
            "path": "expressway.media_readiness",
            **offline_state(
                p["expressway"]["media_readiness"]["enabled"],
                operator_asserted=p["expressway"]["media_readiness"]["operator_metadata"]["operator_metadata_present"],
            ),
            "operator_metadata_present": p["expressway"]["media_readiness"]["operator_metadata"]["operator_metadata_present"],
            "facility": "local2",
        },
        {"path": "cms.syslog", **offline_state(p["cms"]["syslog"]["enabled"]), "index": "netops", "sourcetypes": ["cisco:ms"], "sc4s_tls_listener_gap": p["cms"]["syslog"]["enabled"] and p["cms"]["syslog"]["wire_protocol"] == "tls"},
        {"path": "cms.xml_cdr_receiver", "status": "gap", "planned": False, "local_sample_validated": False, "operator_asserted": False, "live_verified": False, "receiver_implementation": "UNKNOWN"},
        {"path": "meeting_management.system_syslog", **offline_state(cmm["system_syslog"]["enabled"], operator_asserted=cmm["system_syslog"]["operator_attested_metadata_validated"]), "operator_attested_metadata_validated": cmm["system_syslog"]["operator_attested_metadata_validated"], "index": "netops", "sourcetypes": ["cisco:mm:system:*"], "sc4s_tls_listener_gap": cmm["system_syslog"]["enabled"] and cmm["system_syslog"]["wire_protocol"] == "tls"},
        {"path": "meeting_management.audit_syslog", **offline_state(cmm["audit_syslog"]["enabled"], operator_asserted=cmm["audit_syslog"]["operator_attested_metadata_validated"]), "operator_attested_metadata_validated": cmm["audit_syslog"]["operator_attested_metadata_validated"], "index": "netops", "sourcetypes": ["cisco:mm:audit"], "sc4s_tls_listener_gap": cmm["audit_syslog"]["enabled"] and cmm["audit_syslog"]["wire_protocol"] == "tls"},
        {"path": "roomos", "status": "unsupported_roadmap", "planned": False, "local_sample_validated": False, "operator_asserted": False, "live_verified": False},
        {"path": "broadworks", "status": "unsupported_roadmap", "planned": False, "local_sample_validated": False, "operator_asserted": False, "live_verified": False},
        {"path": "uccx_ucce", "status": "UNKNOWN", "planned": False, "local_sample_validated": False, "operator_asserted": False, "live_verified": False},
    ]
    return {
        "schema_version": 1,
        "overall_status": "partial",
        "completed": False,
        "live_verified": False,
        "routes": rows,
        "completion_boundary": "Offline structure is validated; live ingest, dashboards, and roadmap gaps remain open.",
    }


def build_index_plan(spec: dict[str, Any]) -> dict[str, Any]:
    p = spec["products"]
    rows: list[dict[str, Any]] = []
    for name, index, source, enabled in (
        ("cucm_syslog", "ucm", "cisco:ucm", p["cucm"]["syslog"]["enabled"]),
        ("expressway_syslog", "main", "cisco:tvcs", p["expressway"]["syslog"]["enabled"]),
        ("cms_syslog", "netops", "cisco:ms", p["cms"]["syslog"]["enabled"]),
        ("cmm_system", "netops", "cisco:mm:system:*", p["meeting_management"]["system_syslog"]["enabled"]),
        ("cmm_audit", "netops", "cisco:mm:audit", p["meeting_management"]["audit_syslog"]["enabled"]),
    ):
        rows.append({"route": name, "enabled": enabled, "index": index, "sourcetype": source, "action": "handoff_only", "status": readiness_status(enabled), "live_verified": False})
    for name in ("cdr", "cmr"):
        block = p["cucm"][name]
        rows.append(
            {
                "route": f"cucm_{name}",
                "enabled": block["enabled"],
                "index": block["index"],
                "sourcetype": block["sourcetype"] if block["enabled"] else "UNKNOWN until enabled with evidence",
                "action": "handoff_only",
                "status": readiness_status(block["enabled"], local_evidence=block["enabled"]),
                "live_verified": False,
            }
        )
    return {"schema_version": 1, "indexes": rows, "index_creation_performed": False}


def build_privacy_plan(spec: dict[str, Any]) -> dict[str, Any]:
    privacy = spec["privacy"]
    return {
        "schema_version": 1,
        "dashboard_mode": "masked",
        "mask_phone_numbers": True,
        "mask_user_ids": True,
        "privacy_boundary": "allowlist_projection_then_explicit_raw_removal_immediately_before_aggregation",
        "raw_field_explicitly_removed": True,
        "aggregation_allowlist": ["_time", "collaboration_route"],
        "all_other_fields_discarded": True,
        "identifier_hashes_retained": False,
        "evidence_values_displayed": False,
        "retention_reviewed": privacy["retention_reviewed"],
        "retention_review_is_operator_asserted_only": True,
        "restricted_role": privacy["restricted_role"],
        "raw_dashboard_supported": False,
        "artifact_type": "starter_search_readiness",
        "dashboard_studio_definition_emitted": False,
        "live_verified": False,
    }


def dashboard_search(index_plan: dict[str, Any]) -> str:
    rows = {row["route"]: row for row in index_plan["indexes"]}
    clauses: list[str] = []
    for route_name in (
        "cucm_syslog",
        "cucm_cdr",
        "cucm_cmr",
        "expressway_syslog",
        "cms_syslog",
        "cmm_system",
        "cmm_audit",
    ):
        route = rows[route_name]
        if route["enabled"]:
            clauses.append(
                f'(index={route["index"]} sourcetype="{route["sourcetype"]}")'
            )
    base = " OR ".join(clauses) if clauses else "index=_internal | head 0"
    return f"""# Privacy-bounded starter search; this is not a Dashboard Studio definition.
{base}
| eval collaboration_route=case(
    sourcetype=="cisco:ucm", "CUCM syslog",
    sourcetype=="cisco:tvcs", "Expressway syslog",
    sourcetype=="cisco:ms", "CMS syslog",
    like(sourcetype, "cisco:mm:system:%"), "Meeting Management system",
    sourcetype=="cisco:mm:audit", "Meeting Management audit",
    true(), "evidenced custom call record")
| fields _time collaboration_route
| fields - _raw
| timechart span=5m count by collaboration_route useother=f
"""


def cim_review_spl(mappings: list[dict[str, Any]]) -> str:
    searches: list[str] = [
        "# No Telephony or VoIP CIM mapping is claimed.",
        "# Call analytics remain in a product-specific normalized schema.",
    ]
    for row in mappings:
        searches.extend(
            [
                "",
                f"# {row['model']} candidate: operator query retained outside this bundle.",
                f"# qualifying_search_sha256={row['qualifying_search_sha256']}",
                "search index=netops sourcetype=cisco:mm:audit",
                "| head 0",
            ]
        )
    return "\n".join(searches) + "\n"


def build_cim_plan(spec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    mappings: list[dict[str, Any]] = []
    for model in ("authentication", "change"):
        block = spec["cim"][model]
        if block["enabled"]:
            mappings.append(
                {
                    "model": "Authentication" if model == "authentication" else "Change",
                    "status": "unverified_candidate",
                    "route": "meeting_management.audit_syslog",
                    "index": "netops",
                    "sourcetype": "cisco:mm:audit",
                    "qualifying_search_sha256": sha256_bytes(block["qualifying_search"].encode("utf-8")),
                    "qualifying_search_persisted": False,
                    "structural_review": "read_only_exact_route_checked",
                    "verified_fields": block["verified_fields"],
                    "evidence_sha256": block["evidence_sha256"],
                    "applied": False,
                    "live_verified": False,
                }
            )
    payload = {
        "schema_version": 1,
        "call_analytics_schema": "product_specific_normalized",
        "telephony_cim_claimed": False,
        "voip_cim_claimed": False,
        "network_traffic_inferred": False,
        "mappings": mappings,
    }
    return payload, cim_review_spl(mappings)


def build_evidence_requirements(spec: dict[str, Any]) -> dict[str, Any]:
    p = spec["products"]
    flat_files = []
    for name in ("cdr", "cmr"):
        block = p["cucm"][name]
        evidence = block["evidence"]
        flat_files.append(
            {
                "path": f"cucm.{name}",
                "enabled": block["enabled"],
                "status": "locally_evidence_qualified" if block["enabled"] else "disabled",
                "planned": block["enabled"],
                "local_sample_validated": block["enabled"],
                "operator_asserted": bool(block["enabled"]),
                "live_verified": False,
                "sample_sha256": evidence["sha256"] if block["enabled"] else "",
                "file_type": evidence["file_type"],
                "header_rows": evidence["header_rows"],
                "record_count": evidence["record_count"] if block["enabled"] else 0,
                "observed_fields": evidence["observed_fields"] if block["enabled"] else [],
                "sample_contents_copied": False,
                "independently_evidenced": bool(block["enabled"]),
            }
        )
    return {
        "schema_version": 1,
        "flat_file_paths": flat_files,
        "cms_xml_cdr_receiver": {"status": "gap", "implementation": "UNKNOWN", "transport": "https"},
        "expressway": {
            "cdr_readiness": {
                **offline_state(
                    p["expressway"]["cdr_readiness"]["enabled"],
                    operator_asserted=p["expressway"]["cdr_readiness"]["operator_metadata"]["operator_metadata_present"],
                ),
                "operator_metadata_present": p["expressway"]["cdr_readiness"]["operator_metadata"]["operator_metadata_present"],
                "event_derived_evidence_schema": "UNKNOWN",
            },
            "media_readiness": {
                **offline_state(
                    p["expressway"]["media_readiness"]["enabled"],
                    operator_asserted=p["expressway"]["media_readiness"]["operator_metadata"]["operator_metadata_present"],
                ),
                "operator_metadata_present": p["expressway"]["media_readiness"]["operator_metadata"]["operator_metadata_present"],
                "event_derived_evidence_schema": "UNKNOWN",
            },
        },
        "cucm_axl": {
            **offline_state(
                p["cucm"]["axl"]["enabled"],
                operator_asserted=p["cucm"]["axl"]["operator_metadata"]["operator_metadata_present"],
            ),
            "operator_metadata_present": p["cucm"]["axl"]["operator_metadata"]["operator_metadata_present"],
            "event_derived_evidence_schema": "UNKNOWN",
        },
        "meeting_management": {
            "system": {
                **offline_state(
                    p["meeting_management"]["system_syslog"]["enabled"],
                    operator_asserted=p["meeting_management"]["system_syslog"]["operator_attested_metadata_validated"],
                ),
                "operator_attested_metadata_validated": p["meeting_management"]["system_syslog"]["operator_attested_metadata_validated"],
            },
            "audit": {
                **offline_state(
                    p["meeting_management"]["audit_syslog"]["enabled"],
                    operator_asserted=p["meeting_management"]["audit_syslog"]["operator_attested_metadata_validated"],
                ),
                "operator_attested_metadata_validated": p["meeting_management"]["audit_syslog"]["operator_attested_metadata_validated"],
            },
        },
        "live_evidence_collected": False,
    }


def build_package_review(spec: dict[str, Any]) -> dict[str, Any]:
    selected = []
    for row in spec["partner_packages"]["selections"]:
        facts = PARTNER_PACKAGES[row["app_id"]]
        selected.append(
            {
                "app_id": row["app_id"],
                "version": row["version"],
                "tier": row["tier"],
                "publisher": "Sideview",
                "ownership": "partner-built; not a Splunk-owned official TA",
                "support": "developer-supported",
                "entitlement": facts["entitlement"],
                "entitlement_evidence_sha256": row["entitlement_evidence_sha256"],
                "package_metadata_evidence_sha256": row["package_metadata_evidence_sha256"],
                "installation_command_generated": False,
            }
        )
    return {
        "schema_version": 1,
        "mode": spec["partner_packages"]["mode"],
        "selections": selected,
        "install_commands": [],
        "app_8413_gap": "receiver implementation and tier placement UNKNOWN",
        "app_8592_active_sourcetype": "UNKNOWN; CSV/JSON source types are described as under development",
    }


def validate_rendered_package_review(value: Any) -> dict[str, Any]:
    """Validate every partner-package field against the renderer-owned registry."""
    packages = expect_mapping(
        value,
        "partners/package-review.json",
        allowed={
            "schema_version",
            "mode",
            "selections",
            "install_commands",
            "app_8413_gap",
            "app_8592_active_sourcetype",
        },
    )
    if type(packages["schema_version"]) is not int or packages["schema_version"] != 1:
        raise SpecError("partner package review schema_version must be integer 1")
    if packages["mode"] not in {"disabled", "evidence_only"}:
        raise SpecError("partner package review mode is invalid")
    if not type_aware_equal(packages["install_commands"], []):
        raise SpecError("partner package review must never contain install commands")
    if packages["app_8413_gap"] != "receiver implementation and tier placement UNKNOWN":
        raise SpecError("partner app 8413 gap state changed")
    if packages["app_8592_active_sourcetype"] != "UNKNOWN; CSV/JSON source types are described as under development":
        raise SpecError("partner app 8592 source-type gap state changed")
    selections = packages["selections"]
    if not isinstance(selections, list):
        raise SpecError("partner package selections must be a list")
    if packages["mode"] != ("evidence_only" if selections else "disabled"):
        raise SpecError("partner package mode contradicts its selections")
    selected_ids: list[str] = []
    for index, raw in enumerate(selections):
        path = f"partners/package-review.json.selections[{index}]"
        row = expect_mapping(
            raw,
            path,
            allowed={
                "app_id",
                "version",
                "tier",
                "publisher",
                "ownership",
                "support",
                "entitlement",
                "entitlement_evidence_sha256",
                "package_metadata_evidence_sha256",
                "installation_command_generated",
            },
        )
        app_id = row["app_id"]
        if not isinstance(app_id, str) or app_id not in PARTNER_PACKAGES:
            raise SpecError(f"{path}.app_id is not in the renderer-owned partner allowlist")
        facts = PARTNER_PACKAGES[app_id]
        expected_constants = {
            "version": facts["version"],
            "publisher": "Sideview",
            "ownership": "partner-built; not a Splunk-owned official TA",
            "support": "developer-supported",
            "entitlement": facts["entitlement"],
            "installation_command_generated": False,
        }
        for key, expected_value in expected_constants.items():
            if not type_aware_equal(row[key], expected_value):
                raise SpecError(f"{path}.{key} differs from renderer-owned package evidence")
        if not isinstance(row["tier"], str) or row["tier"] not in facts["tiers"]:
            raise SpecError(f"{path}.tier is not a verified placement for app {app_id}")
        for key in ("entitlement_evidence_sha256", "package_metadata_evidence_sha256"):
            if not isinstance(row[key], str) or not SHA256_RE.fullmatch(row[key]):
                raise SpecError(f"{path}.{key} must be a lowercase SHA-256")
        selected_ids.append(app_id)
    if len(selected_ids) != len(set(selected_ids)):
        raise SpecError("partner package review contains duplicate app IDs")
    selected = set(selected_ids)
    for app_id in selected_ids:
        missing = PARTNER_PACKAGES[app_id]["dependencies"] - selected
        if missing:
            raise SpecError(
                f"rendered partner app {app_id} is missing dependency selection(s): {', '.join(sorted(missing))}"
            )
    return packages


def build_gaps(spec: dict[str, Any]) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = [
        {
            "id": "cms_xml_cdr_receiver",
            "severity": "error",
            "status": "gap",
            "blocking": True,
            "detail": "CMS sends XML CDR to an external HTTP(S) receiver; this repo has no verified receiver implementation.",
        },
        {
            "id": "expressway_sourcetype_inconsistency",
            "severity": "info",
            "status": "documented_typo_resolved_by_pinned_implementation",
            "blocking": False,
            "detail": "Mutable SC4S human documentation says cisco:vcs in one table; the commit-pinned implemented parser and test use cisco:tvcs.",
        },
        {
            "id": "roomos",
            "severity": "warning",
            "status": "unsupported_roadmap",
            "blocking": True,
            "detail": "Only distinct Webex and ThousandEyes evidence handoffs are rendered.",
        },
        {
            "id": "broadworks",
            "severity": "warning",
            "status": "unsupported_roadmap",
            "blocking": True,
            "detail": "Vendor documentation handoff only; TA, parser, source type, and collector remain unverified.",
        },
        {
            "id": "uccx_ucce",
            "severity": "warning",
            "status": "UNKNOWN",
            "blocking": True,
            "detail": "No verified local product-specific workflow is claimed.",
        },
        {
            "id": "sideview_8413_receiver_and_tier",
            "severity": "warning",
            "status": "UNKNOWN",
            "blocking": True,
            "detail": "Public listing evidence does not confirm the CMS XML receiver implementation or tier placement.",
        },
    ]
    if spec["products"]["cucm"]["syslog"]["enabled"]:
        gaps.append(
            {
                "id": "cucm_sc4s_listener",
                "severity": "error",
                "status": "gap",
                "blocking": True,
                "detail": "CUCM remote-audit sender protocol and operator-selected receiver port have no matching reviewed SC4S listener argv; no generic-UCM transport readiness is implied.",
            }
        )
    if (
        spec["products"]["expressway"]["syslog"]["enabled"]
        and spec["products"]["expressway"]["syslog"]["transport"] == "tls"
    ):
        gaps.append(
            {
                "id": "expressway_sc4s_tls_listener",
                "severity": "error",
                "status": "gap",
                "blocking": True,
                "detail": "Expressway TLS device support does not prove SC4S TLS listener/certificate readiness; no source-TLS or certificate argv is generated.",
            }
        )
    if (
        spec["products"]["cms"]["syslog"]["enabled"]
        and spec["products"]["cms"]["syslog"]["wire_protocol"] == "tls"
    ):
        gaps.append(
            {
                "id": "cms_sc4s_tls_listener",
                "severity": "error",
                "status": "gap",
                "blocking": True,
                "detail": "CMS tls: sender selection has no matching SC4S TLS listener/certificate argv; plaintext vendor-port generation is suppressed.",
            }
        )
    cmm_routes = (
        spec["products"]["meeting_management"]["system_syslog"],
        spec["products"]["meeting_management"]["audit_syslog"],
    )
    if any(route["enabled"] and route["wire_protocol"] == "tls" for route in cmm_routes):
        gaps.append(
            {
                "id": "cmm_sc4s_tls_listener",
                "severity": "error",
                "status": "gap",
                "blocking": True,
                "detail": "CMM TLS sender selection has no matching SC4S TLS listener/certificate argv; plaintext vendor-port generation is suppressed.",
            }
        )
    if not spec["privacy"]["retention_reviewed"]:
        gaps.append(
            {
                "id": "privacy_retention_review",
                "severity": "warning",
                "status": "open",
                "blocking": False,
                "detail": "Retention policy has not been marked reviewed.",
            }
        )
    return {"schema_version": 1, "overall_status": "partial", "gaps": gaps}


def markdown_readiness(readiness: dict[str, Any]) -> str:
    lines = [
        "# Cisco Collaboration Readiness",
        "",
        "Overall status: **partial**. This packet proves offline structure only.",
        "",
        "| Path | Status |",
        "|---|---|",
    ]
    for row in readiness["routes"]:
        lines.append(f"| `{row['path']}` | `{row['status']}` |")
    lines.extend(
        [
            "",
            "No live device, SC4S, Splunk, Splunkbase, or credential check was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def markdown_gaps(gaps: dict[str, Any]) -> str:
    lines = ["# Gap Register", "", "| Gap | Status | Blocking | Detail |", "|---|---|---|---|"]
    for gap in gaps["gaps"]:
        detail = gap["detail"].replace("|", "\\|")
        lines.append(f"| `{gap['id']}` | `{gap['status']}` | `{str(gap['blocking']).lower()}` | {detail} |")
    lines.append("")
    return "\n".join(lines)


def sc4s_handoff_markdown() -> str:
    return (
        "# SC4S Handoff\n\nReview `../sc4s/classifier-plan.json`, then review the argv arrays in "
        "`handoff-plan.json`. The SC4S render target is a separately owned sibling outside this evidence "
        "packet. It is not claimed private: the current child renderer emits some 0755 directories and 0644 "
        "non-secret files, so operator hardening is required. The command uses a non-routable HEC placeholder "
        "and never uses `--apply-host`, `--apply-k8s`, `--splunk-prep`, source-TLS flags, certificate settings, "
        "or credentials. Exact-source mappings and Expressway TLS require separately reviewed SC4S configuration.\n"
    )


def privacy_plan_markdown(privacy: dict[str, Any]) -> str:
    return (
        "# Privacy Plan\n\nThe starter search derives `collaboration_route`, applies `fields _time "
        "collaboration_route`, then explicitly removes `_raw` as the final step before aggregation. "
        "`_time` is preserved for `timechart`; every other field is discarded, no raw or hashed "
        "identifier is retained, and evidence values are never copied or displayed.\n\n"
        f"Restricted role: `{privacy['restricted_role']}`. Retention reviewed: "
        f"`{str(privacy['retention_reviewed']).lower()}`.\n"
    )


def starter_search_readiness_markdown() -> str:
    return (
        "# Starter Search Readiness\n\nThis is a privacy-bounded SPL starter, not a Dashboard Studio "
        "definition and not completion evidence. `live_verified` remains false. After independently "
        "applying collection, validate source-constrained event counts, role access, and the allowlist "
        "boundary before building or installing any dashboard.\n"
    )


def classifier_review_markdown() -> str:
    return (
        "# SC4S Classifier Review\n\nCMS and Meeting Management use deterministic exact host, exact IP, "
        "or unique dedicated-port classification. Regex is forbidden and enabled CMS/CMM routes use "
        "the same selector mode with distinct values. Plain-TCP dedicated ports are included in the "
        "child render argv; enabled TLS-selected routes retain blocking listener/certificate gaps and "
        "emit no plaintext vendor port. Disabled routes retain `listener_readiness: disabled`. "
        "Exact-source mappings remain operator-reviewed handoffs. CUCM device protocol claims are "
        "limited to the remote-audit profile; every enabled CUCM remote-audit route retains a blocking "
        f"listener gap. Parser source is pinned to `{SC4S_COMMIT}`; mutable human documentation was "
        f"checked on `{CHECKED_DATE}`.\n\nExpressway note: mutable human documentation contains a `cisco:vcs` "
        "table typo, while the pinned implemented parser and test use `cisco:tvcs`. Expressway TLS "
        "listener/certificate readiness remains an explicit handoff gap and the child argv emits no "
        "source-TLS/certificate settings.\n"
    )


def cdr_cmr_evidence_markdown() -> str:
    return (
        "# CUCM CDR and CMR Evidence\n\nCDR and CMR are independent flat-file paths. Enabling either "
        "requires its own local UTF-8 sample, exact SHA-256, nonzero record count, observed header "
        "fields, normalized export path, receiver owner, collection evidence, and source-type origin. "
        "Samples are validated locally and never copied into this bundle. AXL is configuration "
        "enrichment and cannot replace either path.\n"
    )


def roomos_webex_handoff_markdown() -> str:
    return (
        "# RoomOS to Webex Handoff\n\nRoomOS remains `unsupported_roadmap` here. Use "
        "`cisco-webex-setup` only for verified Webex REST/device data paths. The stored argv displays "
        "child help and performs no install, input enablement, API call, or device mutation.\n"
    )


def roomos_thousandeyes_handoff_markdown() -> str:
    return (
        "# RoomOS to ThousandEyes Handoff\n\nKeep ThousandEyes endpoint/network assurance evidence "
        "distinct from Webex device evidence. Use `cisco-thousandeyes-setup` after product ownership "
        "is confirmed. The stored argv displays child help and performs no HEC, input, API, or device "
        "change.\n"
    )


def broadworks_handoff_markdown(primary_interface_url: str) -> str:
    return (
        "# BroadWorks Handoff\n\nStatus remains `unsupported_roadmap` and collection executable status "
        "remains `gap`. Review Cisco's primary BroadWorks developer interface at "
        f"{primary_interface_url}. This packet claims no Splunk TA, parser, source type, collection "
        "method, install command, or license entitlement.\n"
    )


def build_artifacts(
    spec: dict[str, Any],
    spec_path: Path,
    spec_hash: str,
    out: Path,
    ledger: dict[str, Any],
) -> dict[str, str]:
    sc4s = build_sc4s_plan(spec)
    handoffs = build_handoff_plan(spec, out)
    readiness = build_readiness(spec)
    index_plan = build_index_plan(spec)
    privacy = build_privacy_plan(spec)
    cim, cim_spl = build_cim_plan(spec)
    evidence = build_evidence_requirements(spec)
    packages = build_package_review(spec)
    gaps = build_gaps(spec)
    metadata = {
        "schema": BUNDLE_SCHEMA,
        "skill": SKILL_NAME,
        "api_version": API_VERSION,
        "repository_base_commit": BASE_COMMIT,
        "sc4s_upstream_commit": SC4S_COMMIT,
        "source_checked_date": CHECKED_DATE,
        "source_spec": {
            "sha256": spec_hash,
            "name_persisted": False,
        },
        "source_ledger_sha256": sha256_bytes(canonical_json(ledger).encode("utf-8")),
        "offline_only": True,
        "live_service_calls": 0,
        "credential_files_read": 0,
        "device_mutations": 0,
        "child_apply_commands": 0,
        "overall_readiness": "partial",
        "live_verified": False,
    }
    plan = {
        "schema_version": 1,
        "project": {
            "name": spec["project"]["name"],
            "environment": spec["project"]["environment"],
            "owner": spec["project"]["owner"],
        },
        "mode": "render_only",
        "completed": False,
        "live_verified": False,
        "sc4s": sc4s,
        "handoffs": handoffs,
        "readiness": readiness,
    }
    artifacts: dict[str, str] = {
        "metadata.json": canonical_json(metadata),
        "plan.json": canonical_json(plan),
        "source-ledger.json": canonical_json(ledger),
        "readiness/readiness-report.json": canonical_json(readiness),
        "readiness/readiness-report.md": markdown_readiness(readiness),
        "readiness/index-plan.json": canonical_json(index_plan),
        "privacy/privacy-plan.json": canonical_json(privacy),
        "privacy/privacy-plan.md": privacy_plan_markdown(privacy),
        "dashboards/cisco-collaboration-dashboard.spl": dashboard_search(index_plan),
        "dashboards/starter-search-readiness.md": starter_search_readiness_markdown(),
        "sc4s/classifier-plan.json": canonical_json(sc4s),
        "sc4s/classifier-review.md": classifier_review_markdown(),
        "evidence/requirements.json": canonical_json(evidence),
        "evidence/cdr-cmr.md": cdr_cmr_evidence_markdown(),
        "evidence/cms-xml-cdr.json": canonical_json(
            {
                "status": "gap",
                "transport": "https",
                "format": "XML",
                "receiver_implementation": "UNKNOWN",
                "external_receivers_supported_by_cisco": 4,
                "long_term_internal_storage": False,
                "implemented_by_this_skill": False,
            }
        ),
        "evidence/roomos.json": canonical_json(
            {
                "status": "unsupported_roadmap",
                "webex_handoff": "handoffs/roomos-webex.md",
                "thousandeyes_handoff": "handoffs/roomos-thousandeyes.md",
                "paths_are_distinct": True,
                "collector_claimed": False,
            }
        ),
        "evidence/broadworks.json": canonical_json(
            {
                "status": "unsupported_roadmap",
                "primary_interface_url": spec["products"]["broadworks"]["vendor_url"],
                "collection_executable_status": "gap",
                "ta": "UNKNOWN",
                "parser": "UNKNOWN",
                "sourcetype": "UNKNOWN",
                "collector": "UNKNOWN",
            }
        ),
        "evidence/uccx-ucce.json": canonical_json(
            {"status": "UNKNOWN", "ta": "UNKNOWN", "collector": "UNKNOWN", "implementation_claimed": False}
        ),
        "handoffs/handoff-plan.json": canonical_json(handoffs),
        "handoffs/sc4s.md": sc4s_handoff_markdown(),
        "handoffs/roomos-webex.md": roomos_webex_handoff_markdown(),
        "handoffs/roomos-thousandeyes.md": roomos_thousandeyes_handoff_markdown(),
        "handoffs/broadworks.md": broadworks_handoff_markdown(
            spec["products"]["broadworks"]["vendor_url"]
        ),
        "cim/mappings.json": canonical_json(cim),
        "cim/mappings.spl": cim_spl,
        "partners/package-review.json": canonical_json(packages),
        "gaps/gap-register.json": canonical_json(gaps),
        "gaps/gap-register.md": markdown_gaps(gaps),
    }
    manifest_entries = {
        relative: sha256_bytes(content.encode("utf-8"))
        for relative, content in sorted(artifacts.items())
    }
    artifacts["artifact-manifest.json"] = canonical_json(
        {
            "schema": "cisco-collaboration-setup/artifact-manifest/v1",
            "algorithm": "sha256",
            "self_excluded": True,
            "marker_excluded": True,
            "artifacts": manifest_entries,
        }
    )
    if set(artifacts) != EXPECTED_ARTIFACTS:
        missing = sorted(EXPECTED_ARTIFACTS - set(artifacts))
        extra = sorted(set(artifacts) - EXPECTED_ARTIFACTS)
        raise SpecError(f"internal artifact contract mismatch; missing={missing}, extra={extra}")
    return artifacts


def validate_command_plan(plan: dict[str, Any], out: Path) -> None:
    plan = expect_mapping(
        plan,
        "handoff plan",
        allowed={
            "schema_version",
            "mode",
            "offline_default",
            "child_apply_allowed",
            "device_mutation_allowed",
            "commands_are_argv_arrays",
            "child_output_must_be_separately_owned",
            "child_output_privacy_status",
            "sections",
        },
    )
    require_schema_version(plan, "handoff plan")
    if (
        plan.get("mode") != "handoff_only"
        or plan.get("child_apply_allowed") is not False
        or plan.get("device_mutation_allowed") is not False
        or plan.get("commands_are_argv_arrays") is not True
        or plan.get("child_output_must_be_separately_owned") is not True
        or plan.get("child_output_privacy_status") != "operator_hardening_required"
    ):
        raise SpecError("handoff plan safety metadata is invalid")
    sections = plan.get("sections")
    if not isinstance(sections, list):
        raise SpecError("handoff plan sections must be a list")
    dispositions: set[str] = set()
    section_names: set[str] = set()
    for section in sections:
        section = expect_mapping(
            section,
            "handoff plan section",
            allowed={"name", "disposition", "commands", "boundary"},
        )
        dispositions.add(str(section.get("disposition", "")))
        name = section.get("name")
        if name not in DELEGATION_SECTIONS or name in section_names:
            raise SpecError("handoff plan contains an unsupported or duplicate section")
        section_names.add(name)
        if section.get("disposition") != "handoff_only":
            raise SpecError("handoff plan contains an executable or mixed section")
        commands = section.get("commands")
        if not isinstance(commands, list):
            raise SpecError("handoff plan commands must be a list")
        for command in commands:
            if not isinstance(command, list) or not command or not all(isinstance(arg, str) and arg for arg in command):
                raise SpecError("every delegated command must be a nonempty argv array")
            for arg in command:
                flag = arg.split("=", 1)[0]
                if flag in FORBIDDEN_ARG_FLAGS or SECRET_KEY_RE.search(flag):
                    raise SpecError(
                        f"handoff plan argument is outside the render-only allowlist: {flag}"
                    )
            if command[0] != "bash" or len(command) < 3:
                raise SpecError("delegated commands must invoke a reviewed repo-local Bash child")
            script = command[1]
            script_path = REPO_ROOT / script
            if not script.startswith("skills/") or not script_path.is_file():
                raise SpecError(f"delegated command references an unknown child script: {script}")
            if name == "collaboration-syslog":
                if script != "skills/splunk-connect-for-syslog-setup/scripts/setup.sh":
                    raise SpecError("collaboration syslog must hand off only to the SC4S renderer")
                if sum(arg in {"--render-host", "--render-k8s"} for arg in command) != 1:
                    raise SpecError("SC4S handoff must select exactly one render-only mode")
                if "--output-dir" not in command or command.count("--output-dir") != 1:
                    raise SpecError("SC4S handoff must use one separate output directory")
                output_index = command.index("--output-dir") + 1
                if output_index >= len(command):
                    raise SpecError("SC4S handoff output directory is missing")
                child_out = lexical_absolute(command[output_index])
                reject_copied_sensitive_text(str(child_out), "rendered SC4S child output directory")
                expected_child = out.parent / f"{out.name}-sc4s-child-render"
                if child_out != expected_child or child_out == out or out in child_out.parents:
                    raise SpecError("SC4S child output must be the exact separate sibling outside the parent packet")
                if "--hec-url" not in command or command[command.index("--hec-url") + 1] != "https://hec.invalid":
                    raise SpecError("SC4S child render must use the credential-free non-routable HEC placeholder")
                if "--enable-source-tls" in command or "--existing-cert" in command:
                    raise SpecError("Expressway SC4S TLS listener/certificate readiness must remain an unresolved handoff gap")
            elif command[-1] != "--help":
                raise SpecError("non-SC4S child handoffs must remain help-only")
    if dispositions and dispositions != {"handoff_only"}:
        raise SpecError("handoff plan mixes executable and handoff-only sections")


def validate_rendered_bundle(
    out: Path,
    ledger: dict[str, Any],
    *,
    marker_target: Path | None = None,
    trusted_spec: dict[str, Any] | None = None,
    trusted_spec_path: Path | None = None,
    trusted_spec_hash: str | None = None,
    replacement_preflight_only: bool = False,
) -> dict[str, Any]:
    out = validated_output_path(out)
    if not out.exists():
        raise SpecError(f"rendered output directory does not exist: {out}")
    found = inspect_bundle_tree(out)
    expected = EXPECTED_ARTIFACTS | {MARKER_NAME}
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        raise SpecError(f"rendered artifact set mismatch; missing={missing}, extra={extra}")
    logical_out = marker_target or out
    marker = read_marker(out / MARKER_NAME, logical_out)
    artifact_bytes: dict[str, bytes] = {}
    artifact_text: dict[str, str] = {}
    for relative in EXPECTED_ARTIFACTS:
        path = out / relative
        metadata = path.lstat()
        if stat.S_IMODE(metadata.st_mode) & 0o111:
            raise SpecError(f"rendered artifacts must never be executable: {path}")
        payload = read_regular_bytes(path, label=f"rendered artifact {relative}", max_bytes=MAX_ARTIFACT_BYTES)
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SpecError(f"rendered artifact must be UTF-8 text: {path}") from exc
        artifact_bytes[relative] = payload
        artifact_text[relative] = text
        reject_copied_sensitive_text(text, f"rendered artifact {relative}")
        if "-----BEGIN" in text and "PRIVATE KEY-----" in text:
            raise SpecError(f"rendered artifact contains private-key material: {path}")
        if re.search(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{8,}", text):
            raise SpecError(f"rendered artifact contains bearer credential material: {path}")

    decoded_json: dict[str, Any] = {
        relative: strict_load_json_bytes(payload, source=str(out / relative))
        for relative, payload in artifact_bytes.items()
        if relative.endswith(".json")
    }
    marker_commitments = marker["artifact_commitments"]
    for relative, payload in artifact_bytes.items():
        if marker_commitments.get(relative) != sha256_bytes(payload):
            raise SpecError(
                f"artifact differs from the renderer-created marker commitment: {relative}"
            )
    manifest = decoded_json["artifact-manifest.json"]
    manifest = expect_mapping(
        manifest,
        "artifact-manifest",
        allowed={"schema", "algorithm", "self_excluded", "marker_excluded", "artifacts"},
    )
    if (
        manifest["schema"] != "cisco-collaboration-setup/artifact-manifest/v1"
        or manifest["algorithm"] != "sha256"
        or manifest["self_excluded"] is not True
        or manifest["marker_excluded"] is not True
    ):
        raise SpecError("artifact manifest metadata is invalid")
    hashes = manifest["artifacts"]
    if not isinstance(hashes, dict) or set(hashes) != EXPECTED_ARTIFACTS - {"artifact-manifest.json"}:
        raise SpecError("artifact manifest paths must exactly cover every non-manifest artifact")
    for relative, expected_hash in hashes.items():
        if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
            raise SpecError(f"artifact manifest hash is invalid for {relative}")
        if sha256_bytes(artifact_bytes[relative]) != expected_hash:
            raise SpecError(f"artifact hash mismatch: {relative}")

    def reject_rendered_upgrade_spoof(value: Any, path: str = "bundle") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key == "status" and isinstance(child, str) and child.lower() in {
                    "ready",
                    "complete",
                    "completed",
                    "validated",
                    "live",
                    "live_verified",
                }:
                    raise SpecError(f"offline artifact status cannot claim {child!r}: {child_path}")
                if key == "disposition" and child != "handoff_only":
                    raise SpecError(f"rendered disposition must remain handoff_only: {child_path}")
                if key == "receiver_implementation" and child != "UNKNOWN":
                    raise SpecError(f"receiver implementation must remain UNKNOWN: {child_path}")
                if key == "live_verified" and child is not False:
                    raise SpecError(f"offline artifacts must keep live_verified false: {child_path}")
                if key == "completed" and child is not False:
                    raise SpecError(f"offline artifacts must keep completed false: {child_path}")
                reject_rendered_upgrade_spoof(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                reject_rendered_upgrade_spoof(child, f"{path}[{index}]")

    for relative, document in decoded_json.items():
        reject_rendered_upgrade_spoof(document, relative)

    metadata = decoded_json["metadata.json"]
    required_metadata = {
        "schema": BUNDLE_SCHEMA,
        "skill": SKILL_NAME,
        "api_version": API_VERSION,
        "repository_base_commit": BASE_COMMIT,
        "sc4s_upstream_commit": SC4S_COMMIT,
        "source_checked_date": CHECKED_DATE,
        "offline_only": True,
        "live_service_calls": 0,
        "credential_files_read": 0,
        "device_mutations": 0,
        "child_apply_commands": 0,
        "overall_readiness": "partial",
        "live_verified": False,
    }
    metadata = expect_mapping(
        metadata,
        "metadata.json",
        allowed=set(required_metadata) | {"source_spec", "source_ledger_sha256"},
    )
    for key, expected_value in required_metadata.items():
        if not type_aware_equal(metadata.get(key), expected_value):
            raise SpecError(f"metadata.{key} must equal {expected_value!r}")
    source_spec = metadata.get("source_spec")
    if (
        not isinstance(source_spec, dict)
        or set(source_spec) != {"sha256", "name_persisted"}
        or not isinstance(source_spec.get("sha256"), str)
        or not SHA256_RE.fullmatch(source_spec["sha256"])
        or source_spec.get("name_persisted") is not False
        or "spec_name" in metadata
        or "spec_sha256" in metadata
    ):
        raise SpecError("metadata.source_spec must retain only a digest with name_persisted false")
    rendered_ledger = decoded_json["source-ledger.json"]
    if not type_aware_equal(rendered_ledger, ledger):
        raise SpecError("rendered source ledger differs from the pinned checked-in ledger")
    expected_ledger_hash = sha256_bytes(canonical_json(ledger).encode("utf-8"))
    if metadata.get("source_ledger_sha256") != expected_ledger_hash:
        raise SpecError("metadata.source_ledger_sha256 does not match the pinned ledger")

    plan = decoded_json["plan.json"]
    plan = expect_mapping(
        plan,
        "plan.json",
        allowed={"schema_version", "project", "mode", "completed", "live_verified", "sc4s", "handoffs", "readiness"},
    )
    require_schema_version(plan, "plan.json")
    expect_mapping(plan["project"], "plan.json.project", allowed={"name", "environment", "owner"})
    if plan.get("mode") != "render_only" or plan.get("completed") is not False or plan.get("live_verified") is not False:
        raise SpecError("plan must remain incomplete and render-only")
    handoffs = decoded_json["handoffs/handoff-plan.json"]
    validate_command_plan(handoffs, logical_out)
    if not type_aware_equal(plan.get("handoffs"), handoffs):
        raise SpecError("plan and handoff-plan command data differ")

    sc4s = decoded_json["sc4s/classifier-plan.json"]
    sc4s = expect_mapping(
        sc4s,
        "sc4s/classifier-plan.json",
        allowed={
            "schema_version",
            "status",
            "sc4s_upstream_commit",
            "human_documentation_checked_date",
            "routes",
            "overlap_check",
            "generated_config_applied",
        },
    )
    require_schema_version(sc4s, "sc4s/classifier-plan.json")
    if (
        sc4s.get("status") != "planned_render_handoff"
        or sc4s.get("sc4s_upstream_commit") != SC4S_COMMIT
        or sc4s.get("human_documentation_checked_date") != CHECKED_DATE
        or sc4s.get("overlap_check") != "offline_disjointness_checked"
        or sc4s.get("generated_config_applied") is not False
    ):
        raise SpecError("SC4S classifier plan is not pinned or overlap-validated")
    sc4s_route_keys = {
        "cucm": {
            "product", "enabled", "device_scope", "transport", "device_port", "port_origin",
            "tls_authentication", "device_trust_requirements_reviewed", "listener_readiness",
            "listener_capability_boundary", "index", "sourcetypes", "classification",
            "vendor_product_by_source_required",
        },
        "expressway": {
            "product", "enabled", "transport", "device_format", "device_port",
            "device_trust_requirements_reviewed", "index", "sourcetypes", "classification",
            "vendor_product_by_source_required", "listener_readiness",
            "listener_capability_boundary", "documented_inconsistency",
        },
        "cms": {
            "product", "enabled", "transport", "wire_protocol", "tls_server_prefix",
            "listener_readiness", "index", "sourcetypes", "classification",
            "vendor_product_by_source_required", "vendor", "sc4s_product",
        },
        "meeting_management": {
            "product", "enabled", "transport", "system_wire_protocol", "audit_wire_protocol",
            "index", "sourcetypes", "classification", "system_enabled", "audit_enabled",
            "listener_readiness", "supported_tls_version", "receiver_max_bytes",
            "system_planned_server_count", "audit_planned_server_count",
            "documented_max_servers_per_path", "vendor_product_by_source_required", "vendor",
            "sc4s_product",
        },
    }
    expected_sc4s_products = ["cucm", "expressway", "cms", "meeting_management"]
    raw_sc4s_routes = expect_list(sc4s["routes"], "sc4s/classifier-plan.json.routes")
    routes: dict[str, dict[str, Any]] = {}
    route_products: list[str] = []
    for index, raw_route in enumerate(raw_sc4s_routes):
        route_path = f"sc4s/classifier-plan.json.routes[{index}]"
        if not isinstance(raw_route, dict):
            raise SpecError(f"{route_path} must be an object")
        product = raw_route.get("product")
        if not isinstance(product, str) or product not in sc4s_route_keys:
            raise SpecError(f"{route_path}.product is unsupported")
        route = expect_mapping(raw_route, route_path, allowed=sc4s_route_keys[product])
        if product in routes:
            raise SpecError(f"SC4S classifier plan contains duplicate product route: {product}")
        if type(route["enabled"]) is not bool:
            raise SpecError(f"{route_path}.enabled must be an exact JSON boolean")
        if product in {"cms", "meeting_management"}:
            expect_mapping(
                route["classification"],
                f"{route_path}.classification",
                allowed={"mode", "value"},
            )
        routes[product] = route
        route_products.append(product)
    if route_products != expected_sc4s_products:
        raise SpecError(
            "SC4S classifier plan must contain exactly one route for each collaboration product in canonical order"
        )
    if not type_aware_equal(plan.get("sc4s"), sc4s):
        raise SpecError("plan.sc4s differs from the canonical classifier-plan projection")
    fixed_sc4s = {
        "cucm": ("ucm", ["cisco:ucm"]),
        "expressway": ("main", ["cisco:tvcs"]),
        "cms": ("netops", ["cisco:ms"]),
    }
    for product, (index, sourcetypes) in fixed_sc4s.items():
        route = routes[product]
        if route.get("index") != index or route.get("sourcetypes") != sourcetypes:
            raise SpecError(f"SC4S {product} route index/source types differ from pinned implementation evidence")
    if (
        routes["cucm"]["classification"] != "built_in_parser_detection"
        or routes["expressway"]["classification"] != "built_in_parser_detection"
    ):
        raise SpecError("CUCM and Expressway must retain built-in parser classification")
    ucm_route = routes["cucm"]
    if (
        ucm_route.get("device_scope") != "remote_audit_logging"
        or ucm_route.get("transport") not in {"udp", "tcp", "tls"}
        or not isinstance(ucm_route.get("device_port"), int)
        or isinstance(ucm_route.get("device_port"), bool)
        or not 1 <= ucm_route["device_port"] <= 65535
        or ucm_route.get("port_origin") != "operator_selected_not_cisco_default"
    ):
        raise SpecError("CUCM device transport must remain scoped to an explicit remote-audit profile and operator-selected port")
    expected_ucm_trust = ucm_route.get("enabled") is True and ucm_route["transport"] == "tls"
    if ucm_route.get("device_trust_requirements_reviewed") is not expected_ucm_trust:
        raise SpecError("CUCM remote-audit trust review must equal enabled && transport == tls")
    if ucm_route["transport"] == "tls":
        if (
            ucm_route.get("tls_authentication") not in {"unidirectional_x509", "bidirectional_x509"}
        ):
            raise SpecError("CUCM remote-audit TLS profile must retain x.509 authentication")
    elif (
        ucm_route.get("tls_authentication") != "none"
        or ucm_route.get("device_trust_requirements_reviewed") is not False
    ):
        raise SpecError("CUCM non-TLS remote-audit profile contains inconsistent TLS state")
    expected_ucm_listener = "unresolved_handoff_gap" if ucm_route.get("enabled") else "disabled"
    if ucm_route.get("listener_readiness") != expected_ucm_listener:
        raise SpecError("CUCM remote-audit route must retain an unresolved SC4S listener gap for every enabled operator-selected port")
    for product in ("cms", "meeting_management"):
        route = routes.get(product, {})
        if route.get("transport") != "tcp" or route.get("vendor_product_by_source_required") is not True:
            raise SpecError(f"SC4S {product} route must require TCP and deterministic source mapping")
        classifier = route.get("classification")
        if not isinstance(classifier, dict) or classifier.get("mode") not in {"exact_host", "exact_ip", "dedicated_port"}:
            raise SpecError(f"SC4S {product} classifier is invalid")
    cms_route = routes["cms"]
    cmm_route = routes["meeting_management"]
    if cms_route.get("enabled") and cmm_route.get("enabled"):
        cms_classifier = cms_route["classification"]
        cmm_classifier = cmm_route["classification"]
        if cms_classifier.get("mode") != cmm_classifier.get("mode") or cms_classifier == cmm_classifier:
            raise SpecError("rendered CMS and Meeting Management classifiers are mixed-mode or overlapping")
    if type(cms_route.get("tls_server_prefix")) is not bool:
        raise SpecError("CMS tls: server-prefix option must be explicitly modeled")
    if cms_route.get("wire_protocol") not in {"tcp", "tls"} or cms_route.get("tls_server_prefix") is not (cms_route.get("wire_protocol") == "tls"):
        raise SpecError("CMS wire protocol and tls: prefix are inconsistent")
    expected_cms_listener = (
        "disabled"
        if not cms_route.get("enabled")
        else "unresolved_handoff_gap"
        if cms_route["wire_protocol"] == "tls"
        else "planned_render_handoff"
    )
    if cms_route.get("listener_readiness") != expected_cms_listener:
        raise SpecError("CMS listener readiness does not preserve the wire-protocol boundary")
    if (
        type(cmm_route.get("receiver_max_bytes")) is not int
        or cmm_route.get("receiver_max_bytes") != 8192
        or cmm_route.get("supported_tls_version") != "TLS1.2"
        or type(cmm_route.get("system_enabled")) is not bool
        or type(cmm_route.get("audit_enabled")) is not bool
        or type(cmm_route.get("system_planned_server_count")) is not int
        or type(cmm_route.get("audit_planned_server_count")) is not int
    ):
        raise SpecError("Meeting Management protocol profile is incomplete")
    expected_cmm_sources = (
        (["cisco:mm:system:*"] if cmm_route["system_enabled"] else [])
        + (["cisco:mm:audit"] if cmm_route["audit_enabled"] else [])
    )
    if cmm_route.get("sourcetypes") != expected_cmm_sources:
        raise SpecError("Meeting Management source types must follow independent system/audit enablement")
    for key in ("system_wire_protocol", "audit_wire_protocol"):
        if cmm_route.get(key) not in {"tcp", "tls"}:
            raise SpecError("Meeting Management wire protocol must be explicit tcp or tls")
    cmm_tls_selected = (
        (cmm_route["system_enabled"] and cmm_route["system_wire_protocol"] == "tls")
        or (cmm_route["audit_enabled"] and cmm_route["audit_wire_protocol"] == "tls")
    )
    expected_cmm_listener = (
        "disabled"
        if not cmm_route.get("enabled")
        else "unresolved_handoff_gap"
        if cmm_tls_selected
        else "planned_render_handoff"
    )
    if cmm_route.get("listener_readiness") != expected_cmm_listener:
        raise SpecError("Meeting Management listener readiness does not preserve the wire-protocol boundary")
    expressway_route = routes["expressway"]
    expected_expressway_trust = (
        expressway_route.get("enabled") is True
        and expressway_route.get("transport") == "tls"
    )
    if expressway_route.get("device_trust_requirements_reviewed") is not expected_expressway_trust:
        raise SpecError("Expressway trust review must equal enabled && transport == tls")
    expected_expressway_listener = (
        "disabled"
        if not expressway_route.get("enabled")
        else "unresolved_handoff_gap"
        if expressway_route.get("transport") == "tls"
        else "planned_render_handoff"
    )
    if expressway_route.get("listener_readiness") != expected_expressway_listener:
        raise SpecError("Expressway listener readiness does not preserve disabled/TLS/plaintext state")
    collaboration_sections = [
        section
        for section in handoffs.get("sections", [])
        if section.get("name") == "collaboration-syslog"
    ]
    if len(collaboration_sections) != 1:
        raise SpecError("handoff plan must contain exactly one collaboration-syslog section")
    collaboration_commands = collaboration_sections[0].get("commands")
    if not isinstance(collaboration_commands, list):
        raise SpecError("collaboration-syslog commands must be a list")
    any_syslog_enabled = any(route.get("enabled") is True for route in routes.values())
    if any_syslog_enabled and len(collaboration_commands) != 1:
        raise SpecError("enabled collaboration syslog routes require one render-only SC4S handoff")
    if not any_syslog_enabled and collaboration_commands:
        raise SpecError("disabled collaboration syslog routes must not emit an SC4S child render")
    collaboration_command = collaboration_commands[0] if collaboration_commands else []
    if ucm_route.get("enabled"):
        if any(
            isinstance(argument, str)
            and ("source-tls" in argument or "certificate" in argument or "cisco_ucm:" in argument)
            for argument in collaboration_command
        ):
            raise SpecError("CUCM remote-audit listener gap must not be represented by an invented SC4S listener argv")
    if cms_route.get("enabled") and cms_route.get("wire_protocol") == "tls":
        forbidden_port = f"cisco_ms:tcp:{cms_route['classification']['value']}"
        if forbidden_port in collaboration_command:
            raise SpecError("TLS-selected CMS must not be pointed at a plaintext SC4S vendor port")
    if cmm_route.get("enabled") and (
        (cmm_route.get("system_enabled") and cmm_route.get("system_wire_protocol") == "tls")
        or (cmm_route.get("audit_enabled") and cmm_route.get("audit_wire_protocol") == "tls")
    ):
        forbidden_port = f"cisco_mm:tcp:{cmm_route['classification']['value']}"
        if forbidden_port in collaboration_command:
            raise SpecError("TLS-selected CMM must not be pointed at a plaintext SC4S vendor port")

    privacy = decoded_json["privacy/privacy-plan.json"]
    privacy = expect_mapping(
        privacy,
        "privacy/privacy-plan.json",
        allowed={
            "schema_version", "dashboard_mode", "mask_phone_numbers", "mask_user_ids",
            "privacy_boundary", "raw_field_explicitly_removed", "aggregation_allowlist",
            "all_other_fields_discarded", "identifier_hashes_retained", "evidence_values_displayed",
            "retention_reviewed", "retention_review_is_operator_asserted_only", "restricted_role",
            "raw_dashboard_supported", "artifact_type", "dashboard_studio_definition_emitted",
            "live_verified",
        },
    )
    require_schema_version(privacy, "privacy/privacy-plan.json")
    if (
        privacy.get("dashboard_mode") != "masked"
        or privacy.get("mask_phone_numbers") is not True
        or privacy.get("mask_user_ids") is not True
        or privacy.get("raw_dashboard_supported") is not False
        or privacy.get("privacy_boundary") != "allowlist_projection_then_explicit_raw_removal_immediately_before_aggregation"
        or privacy.get("raw_field_explicitly_removed") is not True
        or privacy.get("aggregation_allowlist") != ["_time", "collaboration_route"]
        or privacy.get("all_other_fields_discarded") is not True
        or privacy.get("identifier_hashes_retained") is not False
        or privacy.get("artifact_type") != "starter_search_readiness"
        or privacy.get("dashboard_studio_definition_emitted") is not False
        or privacy.get("live_verified") is not False
    ):
        raise SpecError("privacy plan must remain masked and raw-dashboard-disabled")
    dashboard = artifact_text["dashboards/cisco-collaboration-dashboard.spl"]
    if (
        dashboard.count("| fields - _raw") != 1
        or dashboard.count("| fields _time collaboration_route") != 1
        or not re.search(
        r"\| fields _time collaboration_route\n\| fields - _raw\n\| timechart\b",
        dashboard,
        )
    ):
        raise SpecError("starter SPL must remove _raw, preserve _time, and apply its exact allowlist immediately before aggregation")
    privacy_canaries = {
        "originalCalledPartyNumber",
        "lastRedirectDn",
        "outpulsedCallingPartyNumber",
        "outpulsedCalledPartyNumber",
        "callingPartyNumberPartition",
        "finalCalledPartyNumberPartition",
        "sessionIdentifier",
        "meetingIdentifier",
        "sha256(",
        "masked_",
    }
    if any(canary.lower() in dashboard.lower() for canary in privacy_canaries):
        raise SpecError("starter SPL retains or references a forbidden identifier/hash canary")
    if FORBIDDEN_SPL_RE.search(dashboard):
        raise SpecError("dashboard SPL contains a write-capable or privileged command")

    readiness = decoded_json["readiness/readiness-report.json"]
    readiness = expect_mapping(
        readiness,
        "readiness/readiness-report.json",
        allowed={"schema_version", "overall_status", "completed", "live_verified", "routes", "completion_boundary"},
    )
    require_schema_version(readiness, "readiness/readiness-report.json")
    if readiness.get("overall_status") != "partial" or readiness.get("live_verified") is not False:
        raise SpecError("readiness report must remain partial and not live-verified")
    status_contract = {
        "cucm.syslog": {"disabled", "planned_render_handoff"},
        "cucm.cdr": {"disabled", "locally_evidence_qualified"},
        "cucm.cmr": {"disabled", "locally_evidence_qualified"},
        "cucm.axl": {"disabled", "planned_render_handoff"},
        "expressway.syslog": {"disabled", "planned_render_handoff"},
        "expressway.cdr_readiness": {"disabled", "planned_render_handoff"},
        "expressway.media_readiness": {"disabled", "planned_render_handoff"},
        "cms.syslog": {"disabled", "planned_render_handoff"},
        "cms.xml_cdr_receiver": {"gap"},
        "meeting_management.system_syslog": {"disabled", "planned_render_handoff"},
        "meeting_management.audit_syslog": {"disabled", "planned_render_handoff"},
        "roomos": {"unsupported_roadmap"},
        "broadworks": {"unsupported_roadmap"},
        "uccx_ucce": {"UNKNOWN"},
    }
    readiness_common_keys = {
        "path", "status", "planned", "local_sample_validated", "operator_asserted",
        "live_verified",
    }
    readiness_route_keys = {
        "cucm.syslog": readiness_common_keys | {
            "profile", "transport", "receiver_port", "receiver_port_origin",
            "sc4s_listener_gap", "index", "sourcetypes",
        },
        "cucm.cdr": readiness_common_keys | {"index", "sourcetypes"},
        "cucm.cmr": readiness_common_keys | {"index", "sourcetypes"},
        "cucm.axl": readiness_common_keys | {"operator_metadata_present", "boundary"},
        "expressway.syslog": readiness_common_keys | {
            "index", "sourcetypes", "sc4s_tls_listener_gap",
        },
        "expressway.cdr_readiness": readiness_common_keys | {"operator_metadata_present"},
        "expressway.media_readiness": readiness_common_keys | {
            "operator_metadata_present", "facility",
        },
        "cms.syslog": readiness_common_keys | {
            "index", "sourcetypes", "sc4s_tls_listener_gap",
        },
        "cms.xml_cdr_receiver": readiness_common_keys | {"receiver_implementation"},
        "meeting_management.system_syslog": readiness_common_keys | {
            "operator_attested_metadata_validated", "index", "sourcetypes",
            "sc4s_tls_listener_gap",
        },
        "meeting_management.audit_syslog": readiness_common_keys | {
            "operator_attested_metadata_validated", "index", "sourcetypes",
            "sc4s_tls_listener_gap",
        },
        "roomos": readiness_common_keys,
        "broadworks": readiness_common_keys,
        "uccx_ucce": readiness_common_keys,
    }
    expected_readiness_paths = list(status_contract)
    raw_readiness_routes = expect_list(
        readiness["routes"], "readiness/readiness-report.json.routes"
    )
    readiness_routes: dict[str, dict[str, Any]] = {}
    readiness_paths: list[str] = []
    for index, raw_route in enumerate(raw_readiness_routes):
        route_path = f"readiness/readiness-report.json.routes[{index}]"
        if not isinstance(raw_route, dict):
            raise SpecError(f"{route_path} must be an object")
        path = raw_route.get("path")
        if not isinstance(path, str) or path not in readiness_route_keys:
            raise SpecError(f"{route_path}.path is unsupported")
        route = expect_mapping(raw_route, route_path, allowed=readiness_route_keys[path])
        if path in readiness_routes:
            raise SpecError(f"readiness report contains duplicate route path: {path}")
        for boolean_key in ("planned", "local_sample_validated", "operator_asserted", "live_verified"):
            if type(route[boolean_key]) is not bool:
                raise SpecError(f"{route_path}.{boolean_key} must be an exact JSON boolean")
        readiness_routes[path] = route
        readiness_paths.append(path)
    if readiness_paths != expected_readiness_paths:
        raise SpecError(
            "readiness routes must contain exactly one canonical row for every supported path"
        )
    for path, allowed_statuses in status_contract.items():
        row = readiness_routes[path]
        if row.get("status") not in allowed_statuses or row.get("live_verified") is not False:
            raise SpecError(f"readiness status contract failed for {path}")
        if path in {"cucm.axl", "expressway.cdr_readiness", "expressway.media_readiness"}:
            if row.get("local_sample_validated") is not False:
                raise SpecError(f"operator metadata cannot qualify a local readiness sample: {path}")
            if type(row.get("operator_metadata_present")) is not bool:
                raise SpecError(f"operator metadata presence must be explicit: {path}")
        if path.startswith("meeting_management.") and row.get("local_sample_validated") is not False:
            raise SpecError(f"CMM operator-attested metadata cannot claim a validated local sample: {path}")
        if path.startswith("meeting_management.") and row.get("operator_asserted") is not row.get("operator_attested_metadata_validated"):
            raise SpecError(f"CMM operator assertion must derive only from validated metadata: {path}")
    fixed_readiness_sources = {
        "cucm.syslog": ("ucm", ["cisco:ucm"]),
        "expressway.syslog": ("main", ["cisco:tvcs"]),
        "cms.syslog": ("netops", ["cisco:ms"]),
        "meeting_management.system_syslog": ("netops", ["cisco:mm:system:*"]),
        "meeting_management.audit_syslog": ("netops", ["cisco:mm:audit"]),
    }
    for path, (index, source_types) in fixed_readiness_sources.items():
        if readiness_routes[path].get("index") != index or readiness_routes[path].get("sourcetypes") != source_types:
            raise SpecError(f"readiness index/source-type contract failed for {path}")
    expected_listener_gaps = {
        "cucm.syslog": ucm_route.get("enabled") is True,
        "expressway.syslog": (
            expressway_route.get("enabled") is True
            and expressway_route.get("transport") == "tls"
        ),
        "cms.syslog": (
            cms_route.get("enabled") is True
            and cms_route.get("wire_protocol") == "tls"
        ),
        "meeting_management.system_syslog": (
            cmm_route.get("system_enabled") is True
            and cmm_route.get("system_wire_protocol") == "tls"
        ),
        "meeting_management.audit_syslog": (
            cmm_route.get("audit_enabled") is True
            and cmm_route.get("audit_wire_protocol") == "tls"
        ),
    }
    for path, expected_gap in expected_listener_gaps.items():
        gap_key = "sc4s_listener_gap" if path == "cucm.syslog" else "sc4s_tls_listener_gap"
        if readiness_routes[path].get(gap_key) is not expected_gap:
            raise SpecError(f"readiness listener-gap state contradicts route enablement: {path}")
    route_readiness_pairs = {
        "cucm.syslog": ucm_route,
        "expressway.syslog": expressway_route,
        "cms.syslog": cms_route,
        "meeting_management.system_syslog": {
            "enabled": cmm_route.get("system_enabled"),
        },
        "meeting_management.audit_syslog": {
            "enabled": cmm_route.get("audit_enabled"),
        },
    }
    for path, route in route_readiness_pairs.items():
        expected_status = "planned_render_handoff" if route.get("enabled") else "disabled"
        if readiness_routes[path].get("status") != expected_status:
            raise SpecError(f"readiness status contradicts route enablement: {path}")
    expected_operator_assertions = {
        "cucm.syslog": expected_ucm_trust,
        "expressway.syslog": expected_expressway_trust,
        "cms.syslog": False,
    }
    for path, expected_assertion in expected_operator_assertions.items():
        if readiness_routes[path].get("operator_asserted") is not expected_assertion:
            raise SpecError(f"readiness operator assertion contradicts normalized protocol state: {path}")
    if not type_aware_equal(plan.get("readiness"), readiness):
        raise SpecError("plan and readiness-report data differ")

    index_plan = decoded_json["readiness/index-plan.json"]
    index_plan = expect_mapping(
        index_plan,
        "readiness/index-plan.json",
        allowed={"schema_version", "indexes", "index_creation_performed"},
    )
    require_schema_version(index_plan, "readiness/index-plan.json")
    if index_plan["index_creation_performed"] is not False:
        raise SpecError("index plan must keep index_creation_performed false")
    expected_index_routes = [
        "cucm_syslog", "expressway_syslog", "cms_syslog", "cmm_system", "cmm_audit",
        "cucm_cdr", "cucm_cmr",
    ]
    raw_index_rows = expect_list(index_plan["indexes"], "readiness/index-plan.json.indexes")
    index_rows: dict[str, dict[str, Any]] = {}
    index_route_names: list[str] = []
    for index, raw_row in enumerate(raw_index_rows):
        row_path = f"readiness/index-plan.json.indexes[{index}]"
        row = expect_mapping(
            raw_row,
            row_path,
            allowed={"route", "enabled", "index", "sourcetype", "action", "status", "live_verified"},
        )
        route_name = row["route"]
        if not isinstance(route_name, str) or route_name not in expected_index_routes:
            raise SpecError(f"{row_path}.route is unsupported")
        if route_name in index_rows:
            raise SpecError(f"index plan contains duplicate route: {route_name}")
        if type(row["enabled"]) is not bool or type(row["live_verified"]) is not bool:
            raise SpecError(f"{row_path} enabled/live_verified values must be exact JSON booleans")
        validate_index(row["index"], f"{row_path}.index")
        if row["enabled"]:
            validate_sourcetype(row["sourcetype"], f"{row_path}.sourcetype", wildcard=True)
        index_rows[route_name] = row
        index_route_names.append(route_name)
    if index_route_names != expected_index_routes:
        raise SpecError("index plan must contain exactly one canonical row for every route")
    for row in index_rows.values():
        if row.get("action") != "handoff_only" or row.get("live_verified") is not False:
            raise SpecError("index plan must remain a non-live handoff")
    fixed_index_rows = {
        "cucm_syslog": ("ucm", "cisco:ucm"),
        "expressway_syslog": ("main", "cisco:tvcs"),
        "cms_syslog": ("netops", "cisco:ms"),
        "cmm_system": ("netops", "cisco:mm:system:*"),
        "cmm_audit": ("netops", "cisco:mm:audit"),
    }
    for route, (index, source_type) in fixed_index_rows.items():
        if index_rows[route].get("index") != index or index_rows[route].get("sourcetype") != source_type:
            raise SpecError(f"index plan fixed route changed: {route}")
    expected_dashboard = dashboard_search(index_plan)
    if not dashboard.strip() or dashboard != expected_dashboard:
        raise SpecError("starter dashboard SPL differs from its exact read-only canonical projection")

    evidence = decoded_json["evidence/requirements.json"]
    evidence = expect_mapping(
        evidence,
        "evidence/requirements.json",
        allowed={
            "schema_version", "flat_file_paths", "cms_xml_cdr_receiver", "expressway",
            "cucm_axl", "meeting_management", "live_evidence_collected",
        },
    )
    require_schema_version(evidence, "evidence/requirements.json")
    if evidence["live_evidence_collected"] is not False:
        raise SpecError("evidence requirements must keep live_evidence_collected false")
    expected_flat_file_paths = ["cucm.cdr", "cucm.cmr"]
    raw_flat_files = expect_list(
        evidence["flat_file_paths"], "evidence/requirements.json.flat_file_paths"
    )
    flat_files: dict[str, dict[str, Any]] = {}
    flat_file_paths: list[str] = []
    flat_file_keys = {
        "path", "enabled", "status", "planned", "local_sample_validated",
        "operator_asserted", "live_verified", "sample_sha256", "file_type", "header_rows",
        "record_count", "observed_fields", "sample_contents_copied", "independently_evidenced",
    }
    for index, raw_row in enumerate(raw_flat_files):
        row_path = f"evidence/requirements.json.flat_file_paths[{index}]"
        row = expect_mapping(raw_row, row_path, allowed=flat_file_keys)
        path = row["path"]
        if not isinstance(path, str) or path not in expected_flat_file_paths:
            raise SpecError(f"{row_path}.path is unsupported")
        if path in flat_files:
            raise SpecError(f"flat-file evidence contains duplicate path: {path}")
        for boolean_key in (
            "enabled", "planned", "local_sample_validated", "operator_asserted",
            "live_verified", "sample_contents_copied", "independently_evidenced",
        ):
            if type(row[boolean_key]) is not bool:
                raise SpecError(f"{row_path}.{boolean_key} must be an exact JSON boolean")
        if type(row["record_count"]) is not int or row["record_count"] < 0:
            raise SpecError(f"{row_path}.record_count must be a nonnegative integer")
        expect_string_list(row["observed_fields"], f"{row_path}.observed_fields")
        flat_files[path] = row
        flat_file_paths.append(path)
    if flat_file_paths != expected_flat_file_paths:
        raise SpecError("CDR/CMR evidence must contain exactly one canonical row per path")
    for path, row in flat_files.items():
        expected_type = path.rsplit(".", 1)[1]
        if (
            row.get("file_type") != expected_type
            or type(row.get("header_rows")) is not int
            or row.get("header_rows") != 2
            or row.get("live_verified") is not False
        ):
            raise SpecError(f"flat-file evidence contract changed for {path}")
    xml_cdr = decoded_json["evidence/cms-xml-cdr.json"]
    if not type_aware_equal(xml_cdr, {
        "status": "gap",
        "transport": "https",
        "format": "XML",
        "receiver_implementation": "UNKNOWN",
        "external_receivers_supported_by_cisco": 4,
        "long_term_internal_storage": False,
        "implemented_by_this_skill": False,
    }):
        raise SpecError("CMS XML CDR receiver must remain an explicit HTTPS implementation gap")
    roomos = decoded_json["evidence/roomos.json"]
    if not type_aware_equal(roomos, {
        "collector_claimed": False,
        "paths_are_distinct": True,
        "status": "unsupported_roadmap",
        "thousandeyes_handoff": "handoffs/roomos-thousandeyes.md",
        "webex_handoff": "handoffs/roomos-webex.md",
    }):
        raise SpecError("RoomOS evidence handoffs must remain distinct unsupported_roadmap paths")
    broadworks = decoded_json["evidence/broadworks.json"]
    if not type_aware_equal(broadworks, {
        "status": "unsupported_roadmap",
        "primary_interface_url": "https://developer.cisco.com/docs/broadworks/getting-started/",
        "collection_executable_status": "gap",
        "ta": "UNKNOWN",
        "parser": "UNKNOWN",
        "sourcetype": "UNKNOWN",
        "collector": "UNKNOWN",
    }):
        raise SpecError("BroadWorks evidence must remain an unsupported collection gap")

    uccx_ucce = decoded_json["evidence/uccx-ucce.json"]
    if not type_aware_equal(uccx_ucce, {
        "status": "UNKNOWN",
        "ta": "UNKNOWN",
        "collector": "UNKNOWN",
        "implementation_claimed": False,
    }):
        raise SpecError("UCCX/UCCE evidence must remain UNKNOWN and unimplemented")

    cim = decoded_json["cim/mappings.json"]
    cim = expect_mapping(
        cim,
        "cim/mappings.json",
        allowed={
            "schema_version", "call_analytics_schema", "telephony_cim_claimed",
            "voip_cim_claimed", "network_traffic_inferred", "mappings",
        },
    )
    require_schema_version(cim, "cim/mappings.json")
    if (
        cim.get("telephony_cim_claimed") is not False
        or cim.get("voip_cim_claimed") is not False
        or cim.get("network_traffic_inferred") is not False
    ):
        raise SpecError("Telephony/VoIP CIM must not be claimed")
    raw_cim_mappings = expect_list(cim["mappings"], "cim/mappings.json.mappings")
    cim_mappings: list[dict[str, Any]] = []
    models: list[str] = []
    for index, raw_row in enumerate(raw_cim_mappings):
        row_path = f"cim/mappings.json.mappings[{index}]"
        row = expect_mapping(
            raw_row,
            row_path,
            allowed={
                "model", "status", "route", "index", "sourcetype",
                "qualifying_search_sha256", "qualifying_search_persisted", "structural_review",
                "verified_fields", "evidence_sha256", "applied", "live_verified",
            },
        )
        model = row["model"]
        if not isinstance(model, str) or model not in {"Authentication", "Change"}:
            raise SpecError("only Authentication or Change CIM candidates may be rendered")
        if model in models:
            raise SpecError(f"CIM mappings contain duplicate model: {model}")
        for boolean_key in ("qualifying_search_persisted", "applied", "live_verified"):
            if type(row[boolean_key]) is not bool:
                raise SpecError(f"{row_path}.{boolean_key} must be an exact JSON boolean")
        expect_string_list(row["verified_fields"], f"{row_path}.verified_fields", allow_empty=False)
        if not isinstance(row["evidence_sha256"], str) or not SHA256_RE.fullmatch(row["evidence_sha256"]):
            raise SpecError(f"{row_path}.evidence_sha256 must be a lowercase SHA-256")
        cim_mappings.append(row)
        models.append(model)
    expected_model_order = [model for model in ("Authentication", "Change") if model in models]
    if models != expected_model_order:
        raise SpecError("CIM mappings must use unique canonical model order")
    for row in cim_mappings:
        if row.get("status") != "unverified_candidate" or row.get("live_verified") is not False:
            raise SpecError("CIM candidates must remain unverified until live tags/data-model validation")
        if (
            row.get("route") != "meeting_management.audit_syslog"
            or row.get("index") != "netops"
            or row.get("sourcetype") != "cisco:mm:audit"
            or row.get("qualifying_search_persisted") is not False
            or row.get("structural_review") != "read_only_exact_route_checked"
            or not isinstance(row.get("qualifying_search_sha256"), str)
            or not SHA256_RE.fullmatch(row["qualifying_search_sha256"])
            or "qualifying_search" in row
        ):
            raise SpecError("rendered CIM candidate escaped the supported CMM audit route")
    cim_skeleton = artifact_text["cim/mappings.spl"]
    if FORBIDDEN_SPL_RE.search(cim_skeleton):
        raise SpecError("CIM review SPL contains a write-capable or privileged command")
    if not cim_skeleton.strip() or cim_skeleton != cim_review_spl(cim_mappings):
        raise SpecError("CIM artifact must equal the nonempty exact-route read-only review skeleton")
    packages = validate_rendered_package_review(decoded_json["partners/package-review.json"])
    gaps = decoded_json["gaps/gap-register.json"]
    gaps = expect_mapping(
        gaps,
        "gaps/gap-register.json",
        allowed={"schema_version", "overall_status", "gaps"},
    )
    require_schema_version(gaps, "gaps/gap-register.json")
    raw_gaps = expect_list(gaps["gaps"], "gaps/gap-register.json.gaps")
    if gaps["overall_status"] != "partial":
        raise SpecError("gap register must remain a partial list")
    gap_ids: list[str] = []
    by_gap: dict[str, dict[str, Any]] = {}
    for index, gap in enumerate(raw_gaps):
        gap = expect_mapping(
            gap,
            f"gaps/gap-register.json.gaps[{index}]",
            allowed={"id", "severity", "status", "blocking", "detail"},
        )
        gap_id = gap["id"]
        if not isinstance(gap_id, str) or not gap_id:
            raise SpecError("gap IDs must be nonempty strings")
        if gap_id in by_gap:
            raise SpecError(f"gap register contains duplicate ID: {gap_id}")
        if type(gap["blocking"]) is not bool:
            raise SpecError("gap blocking values must be exact JSON booleans")
        gap_ids.append(gap_id)
        by_gap[gap_id] = gap
    if by_gap.get("cms_xml_cdr_receiver", {}).get("status") != "gap":
        raise SpecError("CMS XML CDR receiver gap is missing")
    if by_gap.get("roomos", {}).get("status") != "unsupported_roadmap" or by_gap.get("broadworks", {}).get("status") != "unsupported_roadmap":
        raise SpecError("RoomOS/BroadWorks gap states changed")
    if by_gap.get("uccx_ucce", {}).get("status") != "UNKNOWN":
        raise SpecError("UCCX/UCCE gap must remain UNKNOWN")
    if by_gap.get("expressway_sourcetype_inconsistency", {}).get("status") != "documented_typo_resolved_by_pinned_implementation":
        raise SpecError("Expressway source-type typo resolution evidence changed")
    expected_gap_presence = {
        "cucm_sc4s_listener": ucm_route.get("enabled") is True,
        "expressway_sc4s_tls_listener": expected_listener_gaps["expressway.syslog"],
        "cms_sc4s_tls_listener": expected_listener_gaps["cms.syslog"],
        "cmm_sc4s_tls_listener": (
            expected_listener_gaps["meeting_management.system_syslog"]
            or expected_listener_gaps["meeting_management.audit_syslog"]
        ),
    }
    expected_gap_ids = [
        "cms_xml_cdr_receiver",
        "expressway_sourcetype_inconsistency",
        "roomos",
        "broadworks",
        "uccx_ucce",
        "sideview_8413_receiver_and_tier",
    ]
    expected_gap_ids.extend(
        gap_id for gap_id, expected_present in expected_gap_presence.items() if expected_present
    )
    if privacy["retention_reviewed"] is False:
        expected_gap_ids.append("privacy_retention_review")
    if gap_ids != expected_gap_ids:
        raise SpecError("gap register must contain exactly one canonical row for every active gap")
    for gap_id, expected_present in expected_gap_presence.items():
        present = by_gap.get(gap_id, {}).get("status") == "gap"
        if present is not expected_present:
            raise SpecError(f"listener gap register contradicts route state: {gap_id}")
    expected_blocking = {
        "cms_xml_cdr_receiver": True,
        "expressway_sourcetype_inconsistency": False,
        "roomos": True,
        "broadworks": True,
        "uccx_ucce": True,
        "sideview_8413_receiver_and_tier": True,
        "cucm_sc4s_listener": True,
        "expressway_sc4s_tls_listener": True,
        "cms_sc4s_tls_listener": True,
        "cmm_sc4s_tls_listener": True,
        "privacy_retention_review": False,
    }
    for gap_id, row in by_gap.items():
        if gap_id not in expected_blocking or row.get("blocking") is not expected_blocking[gap_id]:
            raise SpecError(f"gap blocking semantics changed: {gap_id}")

    if artifact_text["readiness/readiness-report.md"] != markdown_readiness(readiness):
        raise SpecError("readiness Markdown differs from its canonical JSON projection")
    if artifact_text["gaps/gap-register.md"] != markdown_gaps(gaps):
        raise SpecError("gap Markdown differs from its canonical JSON projection")
    if artifact_text["handoffs/sc4s.md"] != sc4s_handoff_markdown():
        raise SpecError("SC4S handoff Markdown differs from its fixed render-only template")
    deterministic_markdown = {
        "privacy/privacy-plan.md": privacy_plan_markdown(privacy),
        "dashboards/starter-search-readiness.md": starter_search_readiness_markdown(),
        "sc4s/classifier-review.md": classifier_review_markdown(),
        "evidence/cdr-cmr.md": cdr_cmr_evidence_markdown(),
        "handoffs/roomos-webex.md": roomos_webex_handoff_markdown(),
        "handoffs/roomos-thousandeyes.md": roomos_thousandeyes_handoff_markdown(),
        "handoffs/broadworks.md": broadworks_handoff_markdown(
            broadworks["primary_interface_url"]
        ),
    }
    for relative, expected_markdown in deterministic_markdown.items():
        if artifact_text[relative] != expected_markdown:
            raise SpecError(f"{relative} differs from its deterministic renderer-owned template")
    historical_evidence_claims_present = bool(
        any(
            row.get("status") == "locally_evidence_qualified"
            or row.get("local_sample_validated") is True
            for row in flat_files.values()
        )
        or cim.get("mappings")
        or packages.get("selections")
        or evidence.get("meeting_management", {}).get("system", {}).get("operator_attested_metadata_validated") is True
        or evidence.get("meeting_management", {}).get("audit", {}).get("operator_attested_metadata_validated") is True
    )
    provenance_status = "not_required"
    status = "offline_structure_checked"
    if trusted_spec is not None:
        if trusted_spec_path is None or trusted_spec_hash is None:
            raise SpecError("trusted-spec validation requires its path and SHA-256")
        if metadata["source_spec"]["sha256"] != trusted_spec_hash:
            raise SpecError("trusted spec SHA-256 does not match the bundle source-spec commitment")
        expected_artifacts = build_artifacts(
            trusted_spec,
            trusted_spec_path,
            trusted_spec_hash,
            logical_out,
            ledger,
        )
        for relative, expected_text in expected_artifacts.items():
            if artifact_text.get(relative) != expected_text:
                raise SpecError(
                    f"rendered artifact differs from deterministic trusted-spec recomputation: {relative}"
                )
        provenance_status = "verified_against_trusted_spec_and_local_evidence"
        status = "offline_structure_and_provenance_checked"
    elif historical_evidence_claims_present and not replacement_preflight_only:
        raise SpecError(
            "historical/local evidence claims require --spec for trusted spec and evidence recomputation"
        )
    elif historical_evidence_claims_present:
        provenance_status = "not_evaluated_replacement_preflight_only"
        status = "internal_structure_checked_without_provenance"
    return {
        "status": status,
        "skill": SKILL_NAME,
        "output_dir": str(out),
        "artifact_count": len(EXPECTED_ARTIFACTS) + 1,
        "offline_only": True,
        "overall_readiness": "partial",
        "provenance_status": provenance_status,
    }


def inspect_existing_bundle_for_replacement(out: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    """Internal-only ownership/integrity preflight; never reports provenance success."""
    return validate_rendered_bundle(
        out,
        ledger,
        replacement_preflight_only=True,
    )


def render(args: argparse.Namespace) -> dict[str, Any]:
    spec, spec_path, spec_hash = load_spec(args.spec or DEFAULT_SPEC)
    expected_spec_sha256 = getattr(args, "expected_spec_sha256", None)
    if expected_spec_sha256 is not None:
        expected_spec_hash = validate_hash(
            expected_spec_sha256,
            "--expected-spec-sha256",
        )
        if spec_hash != expected_spec_hash:
            raise SpecError("render spec does not match --expected-spec-sha256")
    ledger = load_source_ledger()
    out = validated_output_path(args.output_dir)
    artifacts = build_artifacts(spec, spec_path, spec_hash, out, ledger)
    inspected_identity: tuple[int, int, int, int] | None = None
    if out.exists() or out.is_symlink():
        if out.is_symlink():
            raise SpecError(f"output directory must not be a symlink: {out}")
        inspect_existing_bundle_for_replacement(out, ledger)
        inspected_identity = existing_identity(out)
        if not args.dry_run and not args.replace_existing:
            raise SpecError(f"output already exists; review it and rerun with --replace-existing: {out}")
    if args.dry_run:
        return {
            "status": "preview",
            "skill": SKILL_NAME,
            "output_dir": str(out),
            "artifact_count": len(artifacts) + 1,
            "offline_only": True,
            "overall_readiness": "partial",
            "writes": 0,
            "live_service_calls": 0,
        }
    with output_lock(out):
        inspected_identity = None
        if out.exists() or out.is_symlink():
            if out.is_symlink():
                raise SpecError(f"output directory must not be a symlink: {out}")
            inspect_existing_bundle_for_replacement(out, ledger)
            inspected_identity = existing_identity(out)
            if not args.replace_existing:
                raise SpecError(f"output already exists; review it and rerun with --replace-existing: {out}")
        stage: Path | None = None
        stage_identity: tuple[int, int, int, int] | None = None
        try:
            artifact_commitments = {
                relative: sha256_bytes(content.encode("utf-8"))
                for relative, content in artifacts.items()
            }
            stage = create_private_stage(out, artifact_commitments)
            stage_identity = existing_identity(stage)
            for relative in sorted(artifacts):
                safe_write(stage, relative, artifacts[relative])
            fsync_bundle_tree(stage)
            validate_rendered_bundle(
                stage,
                ledger,
                marker_target=out,
                trusted_spec=spec,
                trusted_spec_path=spec_path,
                trusted_spec_hash=spec_hash,
            )
            fsync_directory(stage)
            backup = publish_staged_bundle(
                stage,
                out,
                replace_existing=args.replace_existing,
                inspected_identity=inspected_identity,
            )
            stage = None
        except Exception:
            if stage is not None and stage_identity is not None and stage.exists() and not stage.is_symlink():
                remove_private_stage(stage, stage_identity)
            raise
    result = validate_rendered_bundle(
        out,
        ledger,
        trusted_spec=spec,
        trusted_spec_path=spec_path,
        trusted_spec_hash=spec_hash,
    )
    validation_status = result["status"]
    result["status"] = "rendered"
    result["validation_status"] = validation_status
    result["backup_dir"] = str(backup) if backup is not None else ""
    return result


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        ledger = load_source_ledger()
        if args.validate_only:
            if args.dry_run:
                raise SpecError("--validate-only and --dry-run cannot be combined")
            trusted_spec = None
            trusted_spec_path = None
            trusted_spec_hash = None
            if args.spec is not None:
                trusted_spec, trusted_spec_path, trusted_spec_hash = load_spec(args.spec)
                if args.expected_spec_sha256 is not None:
                    expected_spec_hash = validate_hash(
                        args.expected_spec_sha256,
                        "--expected-spec-sha256",
                    )
                    if trusted_spec_hash != expected_spec_hash:
                        raise SpecError("trusted spec does not match --expected-spec-sha256")
            elif args.expected_spec_sha256 is not None:
                raise SpecError("--expected-spec-sha256 requires --spec")
            result = validate_rendered_bundle(
                validated_output_path(args.output_dir),
                ledger,
                trusted_spec=trusted_spec,
                trusted_spec_path=trusted_spec_path,
                trusted_spec_hash=trusted_spec_hash,
            )
        else:
            result = render(args)
    except (SpecError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        if args.json:
            print(canonical_json({"status": "error", "error": str(exc)}), end="")
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(canonical_json(result), end="")
    else:
        print(
            f"Cisco collaboration {result['status']}: {result['artifact_count']} local artifact(s); "
            f"readiness={result['overall_readiness']}; output={result['output_dir']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
