"""Core implementation for the repo-local Splunk Cisco skills MCP server.

This module intentionally has no MCP SDK dependency so the command planning and
safety gates can be tested with the repo's normal Python test environment.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
CATALOG_PATH = SKILLS_DIR / "cisco-product-setup" / "catalog.json"
CISCO_SETUP_SCRIPT = SKILLS_DIR / "cisco-product-setup" / "scripts" / "setup.sh"
CISCO_RESOLVE_SCRIPT = SKILLS_DIR / "cisco-product-setup" / "scripts" / "resolve_product.sh"

PLAN_HASH_CHARS = 64
PLAN_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_TIMEOUT_SECONDS = 1800
MIN_TIMEOUT_SECONDS = 1


def _env_int(name: str, default: int, *, min_value: int | None = None) -> int:
    """Read an integer env var without letting bad config crash import."""
    raw_value = os.environ.get(name)
    if raw_value in (None, ""):
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    if min_value is not None and value < min_value:
        return default
    return value


MAX_TIMEOUT_SECONDS = _env_int(
    "MCP_MAX_TIMEOUT_SECONDS",
    7200,
    min_value=MIN_TIMEOUT_SECONDS,
)
RESOLVE_TIMEOUT_SECONDS = _env_int(
    "MCP_RESOLVE_TIMEOUT_SECONDS",
    60,
    min_value=MIN_TIMEOUT_SECONDS,
)
# Max characters of stdout/stderr returned per stream. The bounded subprocess
# wrapper enforces this at the byte level during execution to prevent unbounded
# memory growth from chatty scripts.
MAX_OUTPUT_CHARS = 40000
# Hard byte cap per stream during execution. Exceeding either MAX_OUTPUT_CHARS
# or MAX_OUTPUT_BYTES causes further stream data to be discarded; the recorded
# output is suffixed with a truncation marker.
MAX_OUTPUT_BYTES = 256 * 1024
MAX_STORED_PLANS = 256
MAX_RESOURCE_BYTES = 1024 * 1024
MAX_RESOURCE_FILES = 256
MAX_ARG_COUNT = 256
MAX_MAPPING_ENTRIES = 256
MAX_SECRET_KEYS = 128
MAX_KEY_CHARS = 255
MAX_ARG_CHARS = 16 * 1024
MAX_TOTAL_ARG_CHARS = 128 * 1024
MAX_SNAPSHOT_FILES = 10_000
MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024
CANCEL_KILL_GRACE_SECONDS = 1.0
# Maximum age (in seconds) of a stored plan before execute_plan refuses to
# run it. Plans older than this are treated as expired so that a hash that
# was generated, then sat unexecuted across a long pause / context switch,
# cannot be quietly applied later — the operator must regenerate the plan
# from the current state. Override at deployment time with
# MCP_PLAN_TTL_SECONDS=<int>; values <= 0 disable the TTL guard entirely.
PLAN_TTL_SECONDS = _env_int("MCP_PLAN_TTL_SECONDS", 3600)

DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--activation-code",
    "--admin-token",
    "--analytics-secret",
    "--authorization",
    "--api-key",
    "--api-secret",
    "--api-token",
    "--aws-access-key-id",
    "--aws-secret-access-key",
    "--aws-secret-key",
    "--bearer-token",
    "--client-secret",
    "--connection-string",
    "--controller-password",
    "--datasource",
    "--db-password",
    "--agent-control-admin-key",
    "--agent-control-api-key",
    "--external-id",
    "--events-api-key",
    "--galileo-api-key",
    "--galileo-bearer-token",
    "--hec-token",
    "--integration-key",
    # Intersight API key flags rejected by splunk-observability-cisco-intersight-integration
    # and splunk-observability-cisco-ai-pod-integration umbrella (the intersight key ID is
    # not strictly secret, but key material always flows through file-based flags).
    "--intersight-key",
    "--intersight-key-id",
    # Isovalent license key rejected by cisco-isovalent-platform-setup.
    "--isovalent-license",
    "--isovalent-pull-secret",
    "--license",
    "--license-key",
    "--o11y-token",
    "--on-call-api-key",
    "--oncall-api-key",
    "--org-token",
    "--password",
    "--platform-hec-token",
    "--project-key",
    "--proxy-password",
    "--pull-secret",
    "--refresh-token",
    "--rest-key",
    "--rum-token",
    "--secret",
    "--service-account-password",
    "--service-account",
    "--session-key",
    "--skey",
    "--sf-token",
    "--splunk-hec-token",
    # ThousandEyes bearer token rejected by cisco-thousandeyes-mcp-setup and
    # splunk-observability-thousandeyes-integration.
    "--te-token",
    "--token",
    "--vo-api-key",
    "--wif-config",
    "--x-vo-api-key",
}

NON_SECRET_VALUE_KEYS = {
    # Keys whose values are not secrets even though their names match the
    # SECRET_KEY_RE pattern below. Add product-specific non-secret keys
    # here only after confirming they are URL/identifier/policy fields and
    # never carry secret material; the catalog integrity test in
    # tests/test_agent_mcp_core.py will fail if a new such key is added
    # to a catalog `accepted_non_secret_keys` list without being exempted.
    "cii_token_url",
    "hec_token",
    "hec_token_name",
    "legacy_token_grace_days",
    "require_encrypted_token",
    "token_default_lifetime_seconds",
    "token_expires_on",
    "token_key_reload_interval_seconds",
    "token_max_lifetime_seconds",
    "token_not_before",
    "token_user",
}

# Secret-shaped option names whose values are identifiers, policy settings, or
# explicit consent markers rather than credential material. Keep this list
# narrow: unknown secret-shaped flags fail closed in _validate_args().
NON_SECRET_FLAG_KEYS = NON_SECRET_VALUE_KEYS | {
    "accept_ta_token_in_conf",
    "allow_loose_token_perms",
    "confirm_token",
    "enable_token_auth",
    "expect_require_encrypted_token",
    "expire_password_days",
    "hec_token_name",
    "image_pull_secret",
    "min_password_length",
    "password_history_count",
    "rum_token_ref",
    "rum_token_reference",
    "sc4s_token_name",
    "sc4snmp_token_name",
    "smartstore_secret_ref",
    "secret_id",
    "secret_placeholder",
    "ta_secret_mode",
    "token_disabled",
    "token_env_var",
    "token_name",
}

SECRET_FILE_FLAGS = {
    "--access-token-file",
    "--activation-code-file",
    "--admin-token-file",
    "--agent-control-admin-key-file",
    "--agent-control-api-key-file",
    "--analytics-secret-file",
    "--api-key-file",
    "--api-secret-file",
    "--api-token-file",
    "--automation-token-file",
    "--aws-access-key-id-file",
    "--aws-secret-access-key-file",
    "--bearer-token-file",
    "--client-secret-file",
    "--cloudlock-token-file",
    "--controller-password-file",
    "--discovery-secret-file",
    "--events-api-key-file",
    "--galileo-api-key-file",
    "--hec-token-file",
    "--idxc-secret-file",
    "--integration-key-file",
    # Intersight API credential file refs (used by splunk-observability-cisco-intersight-integration
    # and the splunk-observability-cisco-ai-pod-integration umbrella).
    "--intersight-key-file",
    "--intersight-key-id-file",
    # Isovalent Enterprise license + pull-secret file refs (cisco-isovalent-platform-setup).
    "--isovalent-license-file",
    "--isovalent-pull-secret-file",
    # Splunk O11y access token, split by scope. The Org access token is for
    # ingest paths; the User API access token is for admin/dashboard/SignalFlow
    # calls (see splunk-observability-thousandeyes-integration).
    "--o11y-api-token-file",
    "--o11y-ingest-token-file",
    "--o11y-token-file",
    "--oncall-api-key-file",
    "--org-token-file",
    "--password-file",
    "--platform-hec-token-file",
    "--pkcs-certificate-file",
    "--proxy-password-file",
    "--rum-token-file",
    "--secret-file",
    "--service-account-password-file",
    "--session-key-file",
    "--shc-secret-file",
    "--snmpv3-secrets-file",
    "--soar-automation-token-file",
    "--splunk-cloud-admin-jwt-file",
    "--splunk-hec-token-file",
    # ThousandEyes bearer token file ref (cisco-thousandeyes-mcp-setup +
    # splunk-observability-thousandeyes-integration).
    "--te-token-file",
    "--token-file",
    "--write-hec-token-file",
    "--write-token-file",
}

SECRET_KEY_RE = re.compile(
    r"(^|_)(api[_-]?key|api[_-]?secret|bearer|client[_-]?secret|"
    r"hec[_-]?token|ikey|password|private[_-]?key|refresh[_-]?token|"
    r"secret|skey|token)($|_)",
    re.IGNORECASE,
)
INLINE_SECRET_RE = re.compile(
    r"(?i)(?:"
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|"
    r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b|"
    r"\bAuthorization\s*:\s*(?:Bearer|Basic|Splunk|Token)\s+\S{6,}|"
    r"[\"']?(?:password|passwd|api[_-]?key|api[_-]?secret|client[_-]?secret|"
    r"access[_-]?token|refresh[_-]?token|hec[_-]?token|session[_-]?key|"
    r"private[_-]?key)[\"']?\s*[:=]\s*[\"']?[^\s'\",&]{6,}"
    r")"
)


class SkillMCPError(ValueError):
    """Raised when a requested MCP operation violates repo safety rules."""


@dataclass(frozen=True)
class PlannedCommand:
    plan_hash: str
    kind: str
    command: list[str]
    cwd: str
    summary: str
    read_only: bool
    timeout_seconds: int
    dry_run: dict[str, Any] | None = None
    # Monotonic creation time; checked by execute_plan to enforce
    # PLAN_TTL_SECONDS so an old hash cannot be replayed indefinitely.
    # Defaulted via field(default_factory=) since this is a frozen dataclass.
    created_at: float = 0.0
    executable_path: str = ""
    executable_sha256: str = ""
    repository_sha256: str = ""


_PLANS: "OrderedDict[str, PlannedCommand]" = OrderedDict()
_PLANS_LOCK = Lock()
_EXECUTION_LOCK = Lock()
_SNAPSHOT_CACHE_LOCK = Lock()
_SNAPSHOT_FILE_CACHE: dict[
    str,
    tuple[tuple[int, int, int, int, int, int], bytes],
] = {}


def _force_kill_after_cancel(process: subprocess.Popen[bytes]) -> None:
    """Escalate cancellation so a SIGTERM-ignoring child cannot run on."""
    time.sleep(CANCEL_KILL_GRACE_SECONDS)
    # Always target the process group on POSIX. The group leader may have
    # exited on SIGTERM while a descendant in the same group ignored it.
    _terminate_process(process, force=True)


def _request_process_cancel(process: subprocess.Popen[bytes]) -> None:
    _terminate_process(process, force=False)
    threading.Thread(
        target=_force_kill_after_cancel,
        args=(process,),
        daemon=True,
    ).start()


class CommandCancellation:
    """Thread-safe handle used by async MCP handlers to stop a subprocess."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._cancelled = False

    def attach(self, process: subprocess.Popen[bytes]) -> bool:
        with self._lock:
            self._process = process
            cancelled = self._cancelled
        if cancelled:
            _request_process_cancel(process)
        return cancelled

    def detach(self, process: subprocess.Popen[bytes]) -> None:
        with self._lock:
            if self._process is process:
                self._process = None

    def cancel(self) -> None:
        with self._lock:
            was_cancelled = self._cancelled
            self._cancelled = True
            process = self._process
        if process is not None and not was_cancelled:
            _request_process_cancel(process)

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled


def _frontmatter(text: str) -> dict[str, str]:
    """Parse YAML frontmatter from a SKILL.md-style document.

    Returns a flat string-to-string map. Non-string values are coerced via
    str() so callers can rely on a uniform shape; nested structures are
    rendered as their string repr (callers shouldn't be using nested keys).
    """
    match = re.match(r"\A---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    metadata: dict[str, str] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            continue
        if value is None:
            metadata[key] = ""
        elif isinstance(value, str):
            metadata[key] = value
        else:
            metadata[key] = str(value)
    return metadata


def _skill_dirs() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_DIR.iterdir()
        if path.is_dir() and path.name != "shared" and (path / "SKILL.md").is_file()
    )


def _skill_dir(skill: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", skill or ""):
        raise SkillMCPError(f"Invalid skill name: {skill!r}")
    path = SKILLS_DIR / skill
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(SKILLS_DIR.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise SkillMCPError(f"Unknown or unsafe skill: {skill}") from exc
    if not (resolved / "SKILL.md").is_file():
        raise SkillMCPError(f"Unknown skill: {skill}")
    return resolved


def _script_path(skill: str, script: str) -> Path:
    """Resolve a (skill, script) pair to a fully-resolved file path.

    Returns the resolved path so that later subprocess execution does not
    re-traverse a possibly-changed symlink. Raises SkillMCPError if the
    resolved path escapes the skill's scripts directory.
    """
    skill_path = _skill_dir(skill)
    script_name = script.removeprefix("scripts/")
    if "/" in script_name or script_name in {"", ".", ".."}:
        raise SkillMCPError(f"Invalid script name for {skill}: {script!r}")
    path = skill_path / "scripts" / script_name
    if not path.is_file():
        raise SkillMCPError(f"Unknown script for {skill}: {script}")
    resolved = path.resolve()
    scripts_root = (skill_path / "scripts").resolve()
    try:
        resolved.relative_to(scripts_root)
    except ValueError as exc:
        raise SkillMCPError(f"Script escapes skill scripts directory: {script}") from exc
    return resolved


def _safe_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise SkillMCPError(f"{label} must be a string")
    if "\x00" in value:
        raise SkillMCPError(f"{label} contains a NUL byte")
    return value


def _safe_string_mapping(
    value: Mapping[Any, Any] | None,
    *,
    label: str,
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise SkillMCPError(f"{label} must be an object of string keys and values")
    if len(value) > MAX_MAPPING_ENTRIES:
        raise SkillMCPError(
            f"{label} cannot contain more than {MAX_MAPPING_ENTRIES} entries"
        )
    safe: dict[str, str] = {}
    total_chars = 0
    for raw_key, raw_value in value.items():
        key = _safe_text(raw_key, label=f"{label} key")
        item = _safe_text(raw_value, label=f"{label}[{key}]")
        if len(key) > MAX_KEY_CHARS:
            raise SkillMCPError(
                f"{label} key exceeds the {MAX_KEY_CHARS}-character limit"
            )
        if len(item) > MAX_ARG_CHARS:
            raise SkillMCPError(
                f"{label}[{key}] exceeds the {MAX_ARG_CHARS}-character limit"
            )
        if INLINE_SECRET_RE.search(item):
            raise SkillMCPError(
                f"{label}[{key}] appears to contain inline secret material. "
                "Use secret_files instead."
            )
        total_chars += len(key) + len(item)
        if total_chars > MAX_TOTAL_ARG_CHARS:
            raise SkillMCPError(
                f"{label} exceeds the {MAX_TOTAL_ARG_CHARS}-character aggregate limit"
            )
        safe[key] = item
    return safe


def _normalize_key(key: str) -> str:
    """Normalize snake, kebab, dotted, and camelCase option/key names."""
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()


def _looks_secret_key(key: str) -> bool:
    if normalize_key := _normalize_key(key):
        if normalize_key in NON_SECRET_VALUE_KEYS:
            return False
    return bool(SECRET_KEY_RE.search(normalize_key))


def _is_secret_file_flag(flag: str) -> bool:
    if flag in SECRET_FILE_FLAGS:
        return True
    if not flag.startswith("--") or not flag.endswith("-file"):
        return False
    return _looks_secret_key(flag[2:-5])


def _validate_timeout(timeout_seconds: int) -> int:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise SkillMCPError("timeout_seconds must be an integer")
    if timeout_seconds < MIN_TIMEOUT_SECONDS or timeout_seconds > MAX_TIMEOUT_SECONDS:
        raise SkillMCPError(
            f"timeout_seconds must be between {MIN_TIMEOUT_SECONDS} and {MAX_TIMEOUT_SECONDS}"
        )
    return timeout_seconds


def _script_command(path: Path, args: list[str]) -> list[str]:
    try:
        rel_path = str(path.relative_to(REPO_ROOT))
    except ValueError as exc:
        # Defensive: _script_path resolves the path and verifies it stays
        # under the skill's scripts directory, but if a `skills/<X>` entry
        # is itself a symlink that points outside the repo, the resolved
        # path can be outside REPO_ROOT. Refuse to construct a command
        # outside the repo rather than letting the orchestrator run it.
        raise SkillMCPError(
            f"Script path resolves outside the repository: {path}"
        ) from exc
    suffix = path.suffix.lower()
    if suffix == ".sh":
        return ["bash", rel_path, *args]
    if suffix == ".py":
        return [sys.executable, rel_path, *args]
    if suffix == ".rb":
        return ["ruby", rel_path, *args]
    if os.access(path, os.X_OK):
        return [rel_path, *args]
    raise SkillMCPError(f"Unsupported non-executable script type: {path.name}")


def _validate_args(args: list[str]) -> list[str]:
    if not isinstance(args, list):
        raise SkillMCPError("args must be a list of strings")
    if len(args) > MAX_ARG_COUNT:
        raise SkillMCPError(f"args cannot contain more than {MAX_ARG_COUNT} entries")
    safe_args: list[str] = []
    total_chars = 0
    index = 0
    while index < len(args):
        arg = _safe_text(args[index], label=f"args[{index}]")
        if len(arg) > MAX_ARG_CHARS:
            raise SkillMCPError(
                f"args[{index}] exceeds the {MAX_ARG_CHARS}-character limit"
            )
        total_chars += len(arg)
        if total_chars > MAX_TOTAL_ARG_CHARS:
            raise SkillMCPError(
                f"args exceed the {MAX_TOTAL_ARG_CHARS}-character aggregate limit"
            )
        flag = arg.split("=", 1)[0] if arg.startswith("--") else arg
        is_option_flag = bool(
            re.fullmatch(r"--[A-Za-z0-9][A-Za-z0-9_-]*", flag)
        )
        normalized_flag = _normalize_key(flag.removeprefix("--"))
        secret_file_flag = _is_secret_file_flag(flag)
        if flag in DIRECT_SECRET_FLAGS or (
            is_option_flag
            and not secret_file_flag
            and normalized_flag not in NON_SECRET_FLAG_KEYS
            and _looks_secret_key(normalized_flag)
        ):
            raise SkillMCPError(
                f"Direct secret flag {flag} is blocked. Use the matching *-file flag."
            )
        if INLINE_SECRET_RE.search(arg):
            raise SkillMCPError(
                f"args[{index}] appears to contain inline secret material. "
                "Use a matching *-file flag."
            )
        if arg.startswith("--") and "=" in arg and secret_file_flag:
            path_value = arg.split("=", 1)[1]
            if not path_value:
                raise SkillMCPError(f"{flag} requires a file path")
        elif secret_file_flag and flag != "--secret-file":
            if index + 1 >= len(args):
                raise SkillMCPError(f"{flag} requires a file path")
            path_value = _safe_text(args[index + 1], label=f"{flag} path")
            if not path_value:
                raise SkillMCPError(f"{flag} requires a file path")
        if arg == "--set":
            if index + 2 >= len(args):
                raise SkillMCPError("--set requires KEY VALUE")
            key = _safe_text(args[index + 1], label="--set key")
            if _looks_secret_key(key):
                raise SkillMCPError(
                    f"--set {key} is blocked because the key looks secret-bearing."
                )
        if arg == "--secret-file":
            if index + 2 >= len(args):
                raise SkillMCPError("--secret-file requires KEY PATH")
            path_value = _safe_text(args[index + 2], label="--secret-file path")
            if not path_value:
                raise SkillMCPError("--secret-file path cannot be empty")
        safe_args.append(arg)
        index += 1
    return safe_args


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _cached_file_digest(path: Path) -> tuple[bytes, int]:
    """Hash a stable file once, reusing it while strong stat identity matches."""
    initial = path.stat(follow_symlinks=False)
    identity = _stat_identity(initial)
    cache_key = str(path)
    with _SNAPSHOT_CACHE_LOCK:
        cached = _SNAPSHOT_FILE_CACHE.get(cache_key)
    if cached is not None and cached[0] == identity:
        return cached[1], initial.st_size

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        opened_identity = _stat_identity(os.fstat(handle.fileno()))
        if opened_identity != identity:
            raise SkillMCPError(f"Skill file changed while opening: {path}")
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
        final_identity = _stat_identity(os.fstat(handle.fileno()))
    current_identity = _stat_identity(path.stat(follow_symlinks=False))
    if final_identity != identity or current_identity != identity:
        raise SkillMCPError(f"Skill file changed while hashing: {path}")

    value = digest.digest()
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_FILE_CACHE[cache_key] = (identity, value)
    return value, initial.st_size


def _skills_snapshot_sha256() -> str:
    """Bind a plan to all executable skill code, helpers, and local policy.

    Skill entrypoints routinely source shared shell libraries, import sibling
    Python modules, consult catalogs, and delegate to other scripts. Hashing
    only the first executable therefore does not preserve reviewed behavior.
    This deterministic snapshot covers every regular file and safe symlink
    below ``skills/`` and fails closed on unexpectedly large trees.
    """
    digest = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    skills_root = SKILLS_DIR.resolve()
    try:
        paths = sorted(SKILLS_DIR.rglob("*"), key=lambda item: item.as_posix())
        for path in paths:
            relative = path.relative_to(SKILLS_DIR).as_posix().encode("utf-8")
            if path.is_symlink():
                target = path.resolve(strict=True)
                target.relative_to(skills_root)
                digest.update(b"L\0" + relative + b"\0")
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
                digest.update(b"\0")
                continue
            if not path.is_file():
                continue
            file_count += 1
            if file_count > MAX_SNAPSHOT_FILES:
                raise SkillMCPError(
                    f"Skill snapshot exceeds {MAX_SNAPSHOT_FILES} files"
                )
            digest.update(b"F\0" + relative + b"\0")
            file_digest, file_size = _cached_file_digest(path)
            total_bytes += file_size
            if total_bytes > MAX_SNAPSHOT_BYTES:
                raise SkillMCPError(
                    f"Skill snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes"
                )
            digest.update(file_digest)
            digest.update(b"\0")
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise SkillMCPError(f"Could not create a stable skill snapshot: {exc}") from exc
    return digest.hexdigest()


def _planned_executable(command: list[str]) -> Path:
    if not command:
        raise SkillMCPError("Cannot store an empty command")
    interpreter_name = Path(command[0]).name
    candidate_index = (
        1
        if interpreter_name in {"bash", "ruby"} or interpreter_name.startswith("python")
        else 0
    )
    if candidate_index >= len(command):
        raise SkillMCPError("Planned command does not include a script path")
    candidate = Path(command[candidate_index])
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise SkillMCPError(f"Planned executable escapes the repository: {resolved}") from exc
    if not resolved.is_file():
        raise SkillMCPError(f"Planned executable is not a file: {resolved}")
    return resolved


def _store_plan(
    *,
    kind: str,
    command: list[str],
    summary: str,
    read_only: bool,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    dry_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timeout_seconds = _validate_timeout(timeout_seconds)
    executable = _planned_executable(command)
    executable_sha256 = _file_sha256(executable)
    repository_sha256 = _skills_snapshot_sha256()
    plan_hash = secrets.token_hex(PLAN_HASH_CHARS // 2)
    plan = PlannedCommand(
        plan_hash=plan_hash,
        kind=kind,
        command=command,
        cwd=str(REPO_ROOT),
        summary=summary,
        read_only=read_only,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        created_at=time.monotonic(),
        executable_path=str(executable),
        executable_sha256=executable_sha256,
        repository_sha256=repository_sha256,
    )
    with _PLANS_LOCK:
        while plan_hash in _PLANS:  # cryptographically implausible, but fail safe
            plan_hash = secrets.token_hex(PLAN_HASH_CHARS // 2)
            plan = PlannedCommand(**{**asdict(plan), "plan_hash": plan_hash})
        _PLANS[plan_hash] = plan
        # LRU eviction: drop the least-recently-used plan when over capacity.
        while len(_PLANS) > MAX_STORED_PLANS:
            _PLANS.popitem(last=False)
    return asdict(plan)


@dataclass(frozen=True)
class _BoundedResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False


def _drain_stream(stream: Any, sink: list[bytes], byte_cap: int, dropped: list[int]) -> None:
    """Read a stream into a byte-capped buffer; remaining bytes are discarded.

    Runs in a worker thread. Reads in 64KiB chunks until EOF. Once the
    accumulated byte count exceeds byte_cap, the chunk is split and only
    the part that fits is appended; further bytes are counted in
    dropped[0] but not retained. The reader continues until EOF so the
    child process can drain its pipe and exit cleanly.
    """
    accumulated = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        if accumulated >= byte_cap:
            dropped[0] += len(chunk)
            continue
        remaining = byte_cap - accumulated
        if len(chunk) <= remaining:
            sink.append(chunk)
            accumulated += len(chunk)
        else:
            sink.append(chunk[:remaining])
            dropped[0] += len(chunk) - remaining
            accumulated = byte_cap


def _terminate_process(process: subprocess.Popen[bytes], *, force: bool) -> None:
    """Terminate a child and, on POSIX, its isolated process group."""
    if os.name == "posix" and hasattr(os, "killpg"):
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.killpg(process.pid, sig)
            return
        except (OSError, ProcessLookupError):
            pass
    if process.poll() is not None:
        return
    try:
        if force:
            process.kill()
        else:
            process.terminate()
    except (OSError, ProcessLookupError):
        pass


def _run_command(
    command: list[str],
    *,
    timeout_seconds: int,
    cancellation: CommandCancellation | None = None,
) -> _BoundedResult:
    """Run a command with bounded stdout/stderr buffering.

    Unlike subprocess.run(capture_output=True), this wrapper reads child
    output through worker threads with a hard byte cap per stream, so a
    runaway script cannot grow the parent process to gigabytes of RSS
    while waiting for the timeout.
    """
    timeout_seconds = _validate_timeout(timeout_seconds)
    if os.environ.get("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION") != "1":
        raise SkillMCPError(
            "Subprocess execution is disabled. Set "
            "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1 in the MCP server environment."
        )
    if cancellation is not None and cancellation.cancelled:
        return _BoundedResult(
            returncode=130,
            stdout="",
            stderr="Command cancelled before start.",
            cancelled=True,
        )
    try:
        proc = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        return _BoundedResult(
            returncode=127,
            stdout="",
            stderr=f"Failed to start command: {exc}",
        )
    if cancellation is not None:
        cancellation.attach(proc)
    stdout_buf: list[bytes] = []
    stderr_buf: list[bytes] = []
    stdout_dropped = [0]
    stderr_dropped = [0]
    stdout_thread = threading.Thread(
        target=_drain_stream,
        args=(proc.stdout, stdout_buf, MAX_OUTPUT_BYTES, stdout_dropped),
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_stream,
        args=(proc.stderr, stderr_buf, MAX_OUTPUT_BYTES, stderr_dropped),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    timed_out = False
    cancelled = False
    try:
        returncode = proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        # Send SIGTERM, then SIGKILL after a grace period if needed. The
        # child is started in a new session so this reaches subprocesses that
        # inherited the script's process group as well as the shell itself.
        _terminate_process(proc, force=False)
        try:
            try:
                returncode = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _terminate_process(proc, force=True)
                try:
                    returncode = proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    returncode = -signal.SIGKILL
        except (OSError, ProcessLookupError):
            returncode = -signal.SIGKILL
    finally:
        if cancellation is not None:
            cancelled = cancellation.cancelled
            cancellation.detach(proc)
        # Reader threads exit when pipes close (process exit closes them).
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        # Defensive: close pipes if still open.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    stdout_text = b"".join(stdout_buf).decode("utf-8", errors="replace")
    stderr_text = b"".join(stderr_buf).decode("utf-8", errors="replace")
    if stdout_dropped[0]:
        stdout_text += f"\n...[dropped {stdout_dropped[0]} bytes from stdout]"
    if stderr_dropped[0]:
        stderr_text += f"\n...[dropped {stderr_dropped[0]} bytes from stderr]"
    if timed_out:
        stderr_text += f"\n...[command exceeded timeout of {timeout_seconds}s and was terminated]"
    if cancelled and not timed_out:
        stderr_text += "\n...[command was cancelled and terminated]"
    return _BoundedResult(
        returncode=returncode,
        stdout=stdout_text,
        stderr=stderr_text,
        timed_out=timed_out,
        cancelled=cancelled,
    )


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    omitted = len(value) - MAX_OUTPUT_CHARS
    return value[:MAX_OUTPUT_CHARS] + f"\n...[truncated {omitted} chars]"


# Defense-in-depth redaction for subprocess output that the MCP server
# returns to the model. Scripts in this repo are expected to use file-based
# secrets and never echo credentials, but a faulty `set -x`, a verbose
# library, or an upstream Splunk REST error body can still leak material.
# Patterns here are intentionally conservative: high-confidence lexical
# secrets only, to avoid mangling legitimate output.
_SECRET_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM private key blocks (any algorithm).
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED-PRIVATE-KEY]",
    ),
    # JWTs (three base64url segments).
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"),
        "[REDACTED-JWT]",
    ),
    # HTTP Authorization headers: keep the scheme, redact the token.
    (
        re.compile(
            r"(?i)(Authorization\s*:\s*(?:Bearer|Basic|Splunk|Token|Digest|MAC)\s+)"
            r"[A-Za-z0-9+/=._\-]{6,}"
        ),
        r"\1[REDACTED]",
    ),
    # Splunk session-key headers in REST calls.
    (
        re.compile(r"(?i)(sessionKey\s*[:=]\s*)[A-Za-z0-9._\-]{6,}"),
        r"\1[REDACTED]",
    ),
    # password=..., token=..., api_key=..., client_secret=..., etc. in URLs,
    # form bodies, KEY=VALUE log lines, or JSON-ish snippets. Allows quotes
    # around the value. Stops at whitespace, quote, comma, or ampersand to
    # leave structure intact.
    (
        re.compile(
            r"(?i)([\"']?(?:"
            r"splunk[_-]?pass|splunk[_-]?password|sb[_-]?pass|sb[_-]?password|"
            r"password|passwd|pwd|secret|"
            r"aws[_-]?secret[_-]?access[_-]?key|"
            r"api[_-]?key|api[_-]?secret|"
            r"client[_-]?secret|access[_-]?token|refresh[_-]?token|"
            r"bearer[_-]?token|hec[_-]?token|"
            r"auth[_-]?token|session[_-]?key|skey|ikey|"
            r"private[_-]?key"
            r")[\"']?)"
            r"(\s*[:=]\s*['\"]?)"
            r"[^\s'\",&]{6,}"
        ),
        r"\1\2[REDACTED]",
    ),
    # A truncated or malformed PEM block may not include its END marker. Do
    # not return the partial private-key body that remains in the bounded
    # output buffer.
    (
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*\Z", re.DOTALL),
        "-----BEGIN PRIVATE KEY-----[REDACTED-UNTERMINATED]",
    ),
)


def _redact_secrets(value: str) -> str:
    """Best-effort redact of credential-looking substrings in script output.

    This is defense-in-depth and is not a guarantee. Callers must still
    follow the repo's "no secrets in argv, file-backed secrets only" rules.
    """
    if not value:
        return value
    redacted = value
    for pattern, replacement in _SECRET_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _truncate_and_redact(value: str) -> str:
    return _truncate(_redact_secrets(value))


def _skill_reference_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    primary = skill_dir / "reference.md"
    if primary.is_file():
        files.append(_contained_skill_file(primary, skill_dir))
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        files.extend(
            _contained_skill_file(path, skill_dir)
            for path in sorted(references_dir.glob("*.md"))
            if path.is_file()
        )
    if len(files) > MAX_RESOURCE_FILES:
        raise SkillMCPError(
            f"{skill_dir.name} has too many reference files ({len(files)} > {MAX_RESOURCE_FILES})"
        )
    return files


# Maximum size of any individual template file aggregated into the
# skills://{skill}/template resource. Defends against a future skill
# that ships a very large fixture under templates/. Individual file reads
# via list_skill_template_files / read_skill_template_file are not
# bounded by this constant.
MAX_AGGREGATED_TEMPLATE_BYTES = MAX_RESOURCE_BYTES


def _contained_skill_file(path: Path, skill_dir: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(skill_dir.resolve())
    except (FileNotFoundError, ValueError) as exc:
        raise SkillMCPError(
            f"Skill file escapes its skill directory: {path}"
        ) from exc
    if not resolved.is_file():
        raise SkillMCPError(f"Skill resource is not a regular file: {path}")
    return resolved


def _skill_template_files(skill_dir: Path) -> list[Path]:
    """Return ordered template files for a skill.

    Always lists ``template.example`` first (when present), then any files
    under ``templates/`` sorted by relative path. Hidden files and binary
    artifacts under ``templates/`` are excluded. Subdirectories are walked
    recursively so multi-file fixtures (e.g. SC4S host vs. kubernetes,
    Splunk Stream Cloud-HF NetFlow bundle) all show up.
    """
    files: list[Path] = []
    primary = skill_dir / "template.example"
    if primary.is_file():
        files.append(_contained_skill_file(primary, skill_dir))
    templates_dir = skill_dir / "templates"
    if templates_dir.is_dir():
        for path in sorted(templates_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(templates_dir).parts):
                continue
            files.append(_contained_skill_file(path, skill_dir))
    if len(files) > MAX_RESOURCE_FILES:
        raise SkillMCPError(
            f"{skill_dir.name} has too many template files ({len(files)} > {MAX_RESOURCE_FILES})"
        )
    return files


def list_skills() -> dict[str, Any]:
    skills: list[dict[str, Any]] = []
    for skill_dir in _skill_dirs():
        skill_md = _contained_skill_file(skill_dir / "SKILL.md", skill_dir)
        metadata = _frontmatter(_read_bounded_text(skill_md, MAX_RESOURCE_BYTES))
        scripts_dir = skill_dir / "scripts"
        scripts = (
            sorted(path.name for path in scripts_dir.iterdir() if path.is_file())
            if scripts_dir.exists()
            else []
        )
        reference_files = _skill_reference_files(skill_dir)
        template_files = _skill_template_files(skill_dir)
        skills.append(
            {
                "name": metadata.get("name", skill_dir.name),
                "description": metadata.get("description", ""),
                "path": str(skill_md.relative_to(REPO_ROOT)),
                "has_template": bool(template_files),
                "template_files": [str(path.relative_to(skill_dir)) for path in template_files],
                "has_reference": bool(reference_files),
                "reference_files": [str(path.relative_to(skill_dir)) for path in reference_files],
                "has_mcp_tools": (skill_dir / "mcp_tools.json").is_file(),
                "scripts": scripts,
            }
        )
    return {"skills": skills}


def read_skill_file(skill: str, file_name: str) -> str:
    allowed = {
        "instructions": "SKILL.md",
        "reference": "reference.md",
        "template": "template.example",
    }
    if file_name not in allowed:
        raise SkillMCPError(f"Unsupported skill resource: {file_name}")
    skill_dir = _skill_dir(skill)
    if file_name == "reference":
        reference_files = _skill_reference_files(skill_dir)
        if not reference_files:
            raise SkillMCPError(f"{skill} does not have reference.md or references/*.md")
        if len(reference_files) == 1:
            return _read_bounded_text(reference_files[0], MAX_RESOURCE_BYTES)
        chunks = []
        remaining = MAX_RESOURCE_BYTES
        for path in reference_files:
            rel_path = path.relative_to(skill_dir)
            header = f"# {rel_path}\n\n"
            text = _read_bounded_text(path, max(0, remaining - len(header.encode())))
            chunk = f"{header}{text}"
            chunks.append(chunk)
            remaining -= len(chunk.encode("utf-8"))
            if remaining <= 0:
                chunks.append("\n...[aggregate resource limit reached]")
                break
        return "\n\n".join(chunks)
    if file_name == "template":
        template_files = _skill_template_files(skill_dir)
        if not template_files:
            raise SkillMCPError(
                f"{skill} does not have template.example or templates/* files"
            )
        if len(template_files) == 1:
            return _read_bounded_text(template_files[0], MAX_AGGREGATED_TEMPLATE_BYTES)
        chunks = []
        remaining = MAX_AGGREGATED_TEMPLATE_BYTES
        for path in template_files:
            rel_path = path.relative_to(skill_dir)
            header = f"# {rel_path}\n\n"
            text = _read_bounded_text(path, max(0, remaining - len(header.encode())))
            chunk = f"{header}{text}"
            chunks.append(chunk)
            remaining -= len(chunk.encode("utf-8"))
            if remaining <= 0:
                chunks.append("\n...[aggregate resource limit reached]")
                break
        return "\n\n".join(chunks)
    path = skill_dir / allowed[file_name]
    if not path.is_file():
        raise SkillMCPError(f"{skill} does not have {allowed[file_name]}")
    return _read_bounded_text(_contained_skill_file(path, skill_dir), MAX_RESOURCE_BYTES)


def _read_bounded_text(path: Path, max_bytes: int) -> str:
    """Read a text file, truncating the body once max_bytes is exceeded.

    Falls back to ``utf-8`` decoding with ``replace`` errors so a binary
    blob accidentally checked into ``templates/`` does not crash the
    aggregation. The truncation marker preserves the operator's ability to
    notice that the file was clipped.
    """
    if max_bytes <= 0:
        return f"...[truncated all bytes from {path.name}]"
    with path.open("rb") as handle:
        raw = handle.read(max_bytes + 1)
    if len(raw) <= max_bytes:
        return raw.decode("utf-8", errors="replace")
    try:
        omitted = max(1, path.stat().st_size - max_bytes)
    except OSError:
        omitted = 1
    return (
        raw[:max_bytes].decode("utf-8", errors="replace")
        + f"\n...[truncated {omitted} bytes from {path.name}]"
    )


def credential_status() -> dict[str, Any]:
    candidates: list[tuple[str, Path]] = []
    env_path = os.environ.get("SPLUNK_CREDENTIALS_FILE")
    if env_path:
        candidates.append(("env", Path(env_path).expanduser()))
    candidates.append(("project", REPO_ROOT / "credentials"))
    candidates.append(("home", Path.home() / ".splunk" / "credentials"))

    entries = []
    active: dict[str, Any] | None = None
    for source, path in candidates:
        exists = path.is_file()
        mode = None
        secure_mode = None
        if exists:
            try:
                mode_int = stat.S_IMODE(path.stat().st_mode)
                mode = oct(mode_int)
                secure_mode = (mode_int & 0o077) == 0
            except OSError:
                mode = None
                secure_mode = None
        entry = {
            "source": source,
            "path": str(path),
            "exists": exists,
            "mode": mode,
            "secure_mode": secure_mode,
        }
        entries.append(entry)
        if active is None and exists:
            active = entry
    return {"active": active, "candidates": entries}


_VALID_PRODUCT_STATES = {
    "automated",
    "partial",
    "manual_gap",
    "no_plans_available",
    "unsupported_legacy",
    "unsupported_roadmap",
}


def list_cisco_products(state: str | None = None) -> dict[str, Any]:
    if state is not None and state not in _VALID_PRODUCT_STATES:
        raise SkillMCPError(
            f"Invalid state: {state!r}. Must be one of: {sorted(_VALID_PRODUCT_STATES)}"
        )
    if not CATALOG_PATH.is_file():
        raise SkillMCPError(
            f"Cisco product catalog not found at {CATALOG_PATH}. "
            "Run skills/cisco-product-setup/scripts/build_catalog.py --write first."
        )
    if CATALOG_PATH.stat().st_size > MAX_RESOURCE_BYTES:
        raise SkillMCPError(
            f"Cisco product catalog exceeds the {MAX_RESOURCE_BYTES}-byte limit"
        )
    try:
        catalog = json.loads(_read_bounded_text(CATALOG_PATH, MAX_RESOURCE_BYTES))
    except json.JSONDecodeError as exc:
        raise SkillMCPError(f"Cisco product catalog JSON is corrupted: {exc}") from exc
    products = catalog.get("products", [])
    if state:
        products = [item for item in products if item.get("automation_state") == state]
    return {"products": products}


def resolve_cisco_product(
    query: str,
    *,
    cancellation: CommandCancellation | None = None,
) -> dict[str, Any]:
    query = _safe_text(query, label="query")
    command = ["bash", str(CISCO_RESOLVE_SCRIPT), "--json", query]
    result = _run_command(
        command,
        timeout_seconds=RESOLVE_TIMEOUT_SECONDS,
        cancellation=cancellation,
    )
    payload: dict[str, Any]
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        payload = {
            "status": "error",
            "raw_stdout": _truncate_and_redact(result.stdout),
            "returncode": result.returncode,
        }
        if result.stderr:
            payload["stderr"] = _truncate_and_redact(result.stderr)
        return payload
    payload["returncode"] = result.returncode
    if result.stderr:
        payload["stderr"] = _truncate_and_redact(result.stderr)
    return payload


def _catalog_keys_for_product(
    product_query: str,
    *,
    cancellation: CommandCancellation | None = None,
) -> dict[str, set[str]]:
    """Best-effort lookup of accepted keys for a product, by query string.

    Returns a dict with 'non_secret' and 'secret' sets containing the union
    of accepted keys across the top-level product entry and any route
    variants. Returns empty sets if resolution fails for any reason; the
    orchestrator's own validate_known_keys will then catch unknown keys
    server-side.
    """
    try:
        result = resolve_cisco_product(product_query, cancellation=cancellation)
    except SkillMCPError:
        return {"non_secret": set(), "secret": set()}
    if result.get("status") != "resolved":
        return {"non_secret": set(), "secret": set()}
    matches = result.get("matches") or []
    if not matches:
        return {"non_secret": set(), "secret": set()}
    product = matches[0]
    non_secret: set[str] = set()
    secret: set[str] = set()
    for key in product.get("accepted_non_secret_keys") or []:
        if isinstance(key, str):
            non_secret.add(key)
    for key in product.get("secret_keys") or []:
        if isinstance(key, str):
            secret.add(key)
    # Walk route variants, if any, so e.g. security_cloud_variant products
    # accept their per-variant keys.
    route = product.get("route") or {}
    for variant in (route.get("variants") or {}).values():
        if not isinstance(variant, dict):
            continue
        for key in variant.get("accepted_non_secret_keys") or []:
            if isinstance(key, str):
                non_secret.add(key)
        for key in variant.get("secret_keys") or []:
            if isinstance(key, str):
                secret.add(key)
    # Also include the variant selector itself (e.g. "variant" or
    # "security_cloud_variant") which the orchestrator accepts.
    selector = route.get("variant_key")
    if isinstance(selector, str) and selector:
        non_secret.add(selector)
    return {"non_secret": non_secret, "secret": secret}


def secret_file_instructions(secret_keys: list[str], prefix: str = "/tmp/splunk_skill") -> dict[str, Any]:
    prefix = _safe_text(prefix, label="prefix")
    if len(prefix) > 4096:
        raise SkillMCPError("prefix exceeds the 4096-character limit")
    if not isinstance(secret_keys, list):
        raise SkillMCPError("secret_keys must be a list of strings")
    if len(secret_keys) > MAX_SECRET_KEYS:
        raise SkillMCPError(
            f"secret_keys cannot contain more than {MAX_SECRET_KEYS} entries"
        )
    commands = []
    for raw_key in secret_keys:
        key = _safe_text(raw_key, label="secret key")
        if not key or len(key) > MAX_KEY_CHARS:
            raise SkillMCPError(
                f"secret key must contain 1 to {MAX_KEY_CHARS} characters"
            )
        safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("_") or "secret"
        path = f"{prefix}_{safe_key}"
        argv = ["bash", "skills/shared/scripts/write_secret_file.sh", path]
        commands.append(
            {
                "key": key,
                "path": path,
                "argv": argv,
                "command": " ".join(shlex.quote(part) for part in argv),
            }
        )
    return {
        "instructions": "Run these commands in a terminal. Do not paste secret values into chat.",
        "commands": commands,
    }


def plan_cisco_product_setup(
    product: str,
    set_values: dict[str, str] | None = None,
    secret_files: dict[str, str] | None = None,
    phase: str = "full",
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    *,
    cancellation: CommandCancellation | None = None,
) -> dict[str, Any]:
    product = _safe_text(product, label="product")
    timeout_seconds = _validate_timeout(timeout_seconds)
    set_values = _safe_string_mapping(set_values, label="set_values")
    secret_files = _safe_string_mapping(secret_files, label="secret_files")

    phase_flags = {
        "full": [],
        "install": ["--install-only"],
        "configure": ["--configure-only"],
        "validate": ["--validate-only"],
    }
    if phase not in phase_flags:
        raise SkillMCPError("phase must be one of: full, install, configure, validate")

    dry_run_command = [
        "bash",
        str(CISCO_SETUP_SCRIPT.relative_to(REPO_ROOT)),
        "--product",
        product,
        "--dry-run",
        "--json",
        *phase_flags[phase],
    ]

    execute_command = [
        "bash",
        str(CISCO_SETUP_SCRIPT.relative_to(REPO_ROOT)),
        "--product",
        product,
        *phase_flags[phase],
    ]

    # Catalog-aware allowlist: resolve the product (best-effort) and get the
    # union of accepted non-secret and secret keys across all route variants.
    # The catalog wins over the regex heuristic, so a non-secret config field
    # whose name happens to match the secret regex (e.g., a future
    # "password_policy_id") is allowed through if the catalog says it is
    # non-secret.
    allowlist = _catalog_keys_for_product(product, cancellation=cancellation)

    for key, value in sorted(set_values.items()):
        key = _safe_text(key, label="set_values key")
        value = _safe_text(value, label=f"set_values[{key}]")
        normalized = _normalize_key(key)
        accepted_keys = allowlist["non_secret"]
        # Treat keys allowed by the catalog as authoritatively non-secret.
        if key in accepted_keys or normalized in accepted_keys:
            pass
        elif _looks_secret_key(key):
            raise SkillMCPError(
                f"set_values[{key}] is blocked because the key looks secret-bearing."
            )
        dry_run_command.extend(["--set", key, value])
        execute_command.extend(["--set", key, value])

    for key, path in sorted(secret_files.items()):
        key = _safe_text(key, label="secret_files key")
        path = _safe_text(path, label=f"secret_files[{key}]")
        if not path:
            raise SkillMCPError(f"secret_files[{key}] path cannot be empty")
        dry_run_command.extend(["--secret-file", key, path])
        execute_command.extend(["--secret-file", key, path])

    dry_run_result = _run_command(
        dry_run_command,
        timeout_seconds=timeout_seconds,
        cancellation=cancellation,
    )
    try:
        dry_run = json.loads(dry_run_result.stdout or "{}")
    except json.JSONDecodeError as exc:
        detail = _truncate_and_redact(dry_run_result.stderr or dry_run_result.stdout)
        raise SkillMCPError(
            f"Cisco product dry-run did not return JSON: {detail}"
        ) from exc
    dry_run["returncode"] = dry_run_result.returncode
    if dry_run_result.stderr:
        dry_run["stderr"] = _truncate_and_redact(dry_run_result.stderr)
    if dry_run_result.returncode != 0:
        message = dry_run.get("stderr") or _truncate_and_redact(dry_run_result.stdout)
        raise SkillMCPError(f"Cisco product dry-run failed: {message}")

    summary = f"Cisco product setup for {product} ({phase})"
    plan = _store_plan(
        kind="cisco_product_setup",
        command=execute_command,
        summary=summary,
        # Only the typed validate-only route is allowed through without the
        # mutation gate. Manual/partial routes may still write handoff assets
        # or delegate work, so catalog status is not an authorization signal.
        read_only=phase == "validate",
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
    )
    plan["dry_run_command"] = dry_run_command
    return plan


def plan_skill_script(
    skill: str,
    script: str,
    args: list[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    path = _script_path(skill, script)
    timeout_seconds = _validate_timeout(timeout_seconds)
    safe_args = _validate_args([] if args is None else args)
    command = _script_command(path, safe_args)
    script_name = path.name
    # Free-form argv cannot be used as an authorization boundary. Across this
    # repository, similarly named flags have different arity, aliases, default
    # modes, and side effects; validators may also write files or send supplied
    # secret files to a configured endpoint. Treat every generic script as
    # mutating. Typed workflows (currently plan_cisco_product_setup) can retain
    # narrower, schema-backed read-only behavior.
    read_only = False
    return _store_plan(
        kind="skill_script",
        command=command,
        summary=f"Run {skill}/scripts/{script_name}",
        read_only=read_only,
        timeout_seconds=timeout_seconds,
    )


def execute_plan(
    plan_hash: str,
    confirm: bool = False,
    expected_kind: str | None = None,
    *,
    cancellation: CommandCancellation | None = None,
) -> dict[str, Any]:
    plan_hash = _safe_text(plan_hash, label="plan_hash")
    if not PLAN_HASH_RE.match(plan_hash):
        raise SkillMCPError("plan_hash must be a 64-character lowercase hex string.")

    # Validate and consume the exact same immutable object under one lock.
    # Validation errors leave the plan available for a corrected retry.
    with _PLANS_LOCK:
        plan = _PLANS.get(plan_hash)
        if plan is None:
            raise SkillMCPError(f"Unknown plan_hash: {plan_hash}")
        if PLAN_TTL_SECONDS > 0 and time.monotonic() - plan.created_at > PLAN_TTL_SECONDS:
            _PLANS.pop(plan_hash, None)
            raise SkillMCPError(
                f"Plan {plan_hash} has expired; re-run the plan step."
            )
        if not confirm:
            raise SkillMCPError("Execution requires confirm=true.")
        if expected_kind is not None and plan.kind != expected_kind:
            raise SkillMCPError(f"Plan {plan_hash} is {plan.kind}, not {expected_kind}.")
        if os.environ.get("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION") != "1":
            raise SkillMCPError(
                "Subprocess execution is disabled. Set "
                "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1 in the MCP server environment."
            )
        if not plan.read_only and os.environ.get("SPLUNK_SKILLS_MCP_ALLOW_MUTATION") != "1":
            raise SkillMCPError(
                "Mutating execution is disabled. Set SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1 "
                "in the MCP server environment."
            )
        plan = _PLANS.pop(plan_hash)

    while not _EXECUTION_LOCK.acquire(timeout=0.1):
        if cancellation is not None and cancellation.cancelled:
            return {
                "ok": False,
                "plan_hash": plan_hash,
                "returncode": 130,
                "stdout": "",
                "stderr": "Command cancelled before execution.",
                "command": plan.command,
                "cwd": plan.cwd,
                "timed_out": False,
                "cancelled": True,
            }
    try:
        current_path = Path(plan.executable_path)
        if not current_path.is_file() or _file_sha256(current_path) != plan.executable_sha256:
            raise SkillMCPError(
                "The planned script changed after review; the plan was invalidated. "
                "Re-run the plan step."
            )
        if _skills_snapshot_sha256() != plan.repository_sha256:
            raise SkillMCPError(
                "The skill repository changed after review; the plan was invalidated. "
                "Re-run the plan step."
            )
        result = _run_command(
            plan.command,
            timeout_seconds=plan.timeout_seconds,
            cancellation=cancellation,
        )
    finally:
        _EXECUTION_LOCK.release()
    return {
        "ok": result.returncode == 0 and not result.timed_out and not result.cancelled,
        "plan_hash": plan_hash,
        "returncode": result.returncode,
        "stdout": _truncate_and_redact(result.stdout),
        "stderr": _truncate_and_redact(result.stderr),
        "command": plan.command,
        "cwd": plan.cwd,
        "timed_out": result.timed_out,
        "cancelled": result.cancelled,
    }
