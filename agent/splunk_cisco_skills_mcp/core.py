"""Core implementation for the repo-local Splunk Cisco skills MCP server.

This module intentionally has no MCP SDK dependency so the command planning and
safety gates can be tested with the repo's normal Python test environment.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shlex
import shutil
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
from typing import Any, Callable

import yaml

from . import discovery


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = REPO_ROOT / "skills"
CATALOG_PATH = SKILLS_DIR / "cisco-product-setup" / "catalog.json"
CISCO_SETUP_SCRIPT = SKILLS_DIR / "cisco-product-setup" / "scripts" / "setup.sh"
CISCO_RESOLVE_SCRIPT = (
    SKILLS_DIR / "cisco-product-setup" / "scripts" / "resolve_product.sh"
)

PLAN_HASH_CHARS = 64
PLAN_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MIN_TIMEOUT_SECONDS = 1
ABSOLUTE_MAX_TIMEOUT_SECONDS = 24 * 60 * 60


def _env_int(
    name: str,
    default: int,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
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
    if max_value is not None and value > max_value:
        return default
    return value


MAX_TIMEOUT_SECONDS = _env_int(
    "MCP_MAX_TIMEOUT_SECONDS",
    7200,
    min_value=MIN_TIMEOUT_SECONDS,
    max_value=ABSOLUTE_MAX_TIMEOUT_SECONDS,
)
DEFAULT_TIMEOUT_SECONDS = min(1800, MAX_TIMEOUT_SECONDS)
RESOLVE_TIMEOUT_SECONDS = min(
    _env_int(
        "MCP_RESOLVE_TIMEOUT_SECONDS",
        60,
        min_value=MIN_TIMEOUT_SECONDS,
        max_value=ABSOLUTE_MAX_TIMEOUT_SECONDS,
    ),
    MAX_TIMEOUT_SECONDS,
)
# All subprocess-producing tools share one bounded worker pool. A small queue
# absorbs normal overlap between product resolution, dry-run planning, and
# final execution without allowing untrusted clients to create unbounded
# threads or child processes.
MAX_CONCURRENT_SUBPROCESSES = _env_int(
    "MCP_MAX_CONCURRENT_SUBPROCESSES",
    1,
    min_value=1,
    max_value=32,
)
MAX_QUEUED_SUBPROCESSES = _env_int(
    "MCP_MAX_QUEUED_SUBPROCESSES",
    16,
    min_value=0,
    max_value=1024,
)
SUBPROCESS_QUEUE_TIMEOUT_SECONDS = min(
    _env_int(
        "MCP_SUBPROCESS_QUEUE_TIMEOUT_SECONDS",
        60,
        min_value=MIN_TIMEOUT_SECONDS,
        max_value=ABSOLUTE_MAX_TIMEOUT_SECONDS,
    ),
    MAX_TIMEOUT_SECONDS,
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
MAX_SNAPSHOT_ENTRIES = 20_000
MAX_SNAPSHOT_DIRECTORIES = 2_000
MAX_SNAPSHOT_DEPTH = 32
MAX_PARSED_JSON_ITEMS = 10_000
MAX_PARSED_JSON_DEPTH = 32
MAX_SECRET_FILE_BYTES = 1024 * 1024
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


class _CommandCancelledBeforeStart(RuntimeError):
    """Internal signal used to preserve a queued, unstarted plan."""


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
    interpreter_path: str = ""
    interpreter_sha256: str = ""
    secret_file_identities: tuple[dict[str, Any], ...] = ()


_PLANS: "OrderedDict[str, PlannedCommand]" = OrderedDict()
_PLANS_LOCK = Lock()
_RESERVED_PLANS: set[str] = set()
_EXECUTION_LOCK = Lock()
_SNAPSHOT_CACHE_LOCK = Lock()
_SNAPSHOT_FILE_CACHE: dict[
    str,
    tuple[tuple[int, int, int, int, int, int], bytes],
] = {}
_SUBPROCESS_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_SUBPROCESSES)
_SUBPROCESS_QUEUE_LOCK = Lock()
_SUBPROCESS_QUEUE_WAITERS = 0
_ACTIVE_PROCESSES_LOCK = Lock()
_ACTIVE_PROCESSES: dict[int, subprocess.Popen[bytes]] = {}

_CHILD_ENV_BLOCKLIST = frozenset(
    {
        # Shell startup hooks and option injection.
        "BASH_ENV",
        "ENV",
        "BASHOPTS",
        "SHELLOPTS",
        "CDPATH",
        "GLOBIGNORE",
        "IFS",
        "KSH_ENV",
        "PROMPT_COMMAND",
        "PS4",
        "ZDOTDIR",
        # Language-specific loader/option injection. The deployment-facing
        # environment (AWS_*, KUBECONFIG, SPLUNK_*, proxy settings, etc.) is
        # intentionally retained for skill workflows that require it.
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONINSPECT",
        "PYTHONBREAKPOINT",
        "PYTHONWARNINGS",
        "PYTHONEXECUTABLE",
        "PYTHONPLATLIBDIR",
        "RUBYOPT",
        "RUBYLIB",
        "PERL5OPT",
        "PERL5LIB",
        "PERL5DB",
        "NODE_OPTIONS",
        "NODE_PATH",
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "_JAVA_OPTIONS",
        # Native loader injection and TLS key export.
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "DYLD_FRAMEWORK_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_FALLBACK_FRAMEWORK_PATH",
        "DYLD_IMAGE_SUFFIX",
        "DYLD_ROOT_PATH",
        "GCONV_PATH",
        "SSLKEYLOGFILE",
        # Ambient helper/editor commands are executable hooks, not data.
        "EDITOR",
        "VISUAL",
        "PAGER",
        "GIT_PAGER",
        "MANPAGER",
        "LESSOPEN",
        "LESSCLOSE",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GIT_EXEC_PATH",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_NOSYSTEM",
        "SSH_ASKPASS",
        "SUDO_ASKPASS",
        # MCP authorization belongs to the parent control plane and is never
        # a deployment input for child skill scripts.
        "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION",
        "SPLUNK_SKILLS_MCP_ALLOW_MUTATION",
        "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION",
        "SPLUNK_CISCO_SKILLS_MCP_NO_VENV",
        "SPLUNK_CISCO_SKILLS_MCP_REEXECED",
    }
)

_SNAPSHOT_EXCLUDED_DIR_NAMES = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
_SNAPSHOT_EXCLUDED_FILE_NAMES = frozenset({".DS_Store"})
_SNAPSHOT_EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".swp", ".swo", ".tmp", "~")
_CHILD_ENV_BLOCKED_PREFIXES = (
    "BASH_FUNC_",
    "GIT_CONFIG_KEY_",
    "GIT_CONFIG_VALUE_",
)


def _child_environment() -> dict[str, str]:
    """Return a deployment-capable environment without loader injection hooks."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _CHILD_ENV_BLOCKLIST
        and not key.startswith(_CHILD_ENV_BLOCKED_PREFIXES)
    }
    # Empty and relative PATH entries implicitly search the repository cwd.
    # Preserve absolute deployment-tool paths (including the repo venv) while
    # removing that ambient current-directory execution behavior.
    path_entries = []
    for entry in env.get("PATH", os.defpath).split(os.pathsep):
        if not entry:
            continue
        candidate = Path(entry)
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except OSError:
            continue
        if not stat.S_ISDIR(metadata.st_mode):
            continue
        if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o022:
            continue
        normalized = str(resolved)
        if normalized not in path_entries:
            path_entries.append(normalized)
    env["PATH"] = os.pathsep.join(path_entries) or os.defpath
    env["PWD"] = str(REPO_ROOT)
    # Prevent user-site imports while retaining packages from the interpreter's
    # selected virtual environment.
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _interpreter_path(command: list[str]) -> Path | None:
    """Resolve a supported interpreter to a stable absolute executable."""
    if not command:
        raise SkillMCPError("Cannot execute an empty command")
    requested = _safe_text(command[0], label="command interpreter")
    name = Path(requested).name.lower()
    if name not in {"bash", "ruby"} and not name.startswith("python"):
        return None

    child_env = _child_environment()
    if Path(requested).is_absolute():
        candidate = Path(requested)
    else:
        located = shutil.which(requested, path=child_env["PATH"])
        if not located:
            raise SkillMCPError(f"Required interpreter is not available: {requested}")
        candidate = Path(located)
    try:
        resolved = candidate.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise SkillMCPError(
            f"Could not resolve interpreter {requested!r}: {exc}"
        ) from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise SkillMCPError(
            f"Interpreter is not an executable regular file: {resolved}"
        )
    # The interpreter that is already executing this MCP process is an
    # established process boundary.  Hosted CI images may intentionally make
    # that binary's tool-cache group writable, but that cannot retroactively
    # replace the interpreter image running this process.  Keep the stricter
    # ownership and ancestry checks for every separately selected interpreter.
    try:
        running_interpreter = Path(sys.executable).resolve(strict=True)
    except OSError:
        running_interpreter = None
    is_running_interpreter = resolved == running_interpreter
    if (
        os.name == "posix"
        and not is_running_interpreter
        and stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise SkillMCPError(
            f"Interpreter is group/world writable and cannot be trusted: {resolved}"
        )
    if os.name == "posix" and not is_running_interpreter:
        for parent in resolved.parents:
            try:
                parent_metadata = parent.stat()
                parent_mode = stat.S_IMODE(parent_metadata.st_mode)
            except OSError as exc:
                raise SkillMCPError(
                    f"Could not inspect interpreter ancestry {parent}: {exc}"
                ) from exc
            if parent_mode & 0o002 or (
                parent_mode & 0o020 and parent_metadata.st_uid not in {0, os.geteuid()}
            ):
                raise SkillMCPError(
                    "Interpreter ancestry is writable by an untrusted group/world "
                    "principal and cannot be "
                    f"trusted: {parent}"
                )
    return resolved


def _resolved_command(command: list[str]) -> list[str]:
    resolved = list(command)
    interpreter = _interpreter_path(resolved)
    if interpreter is not None:
        resolved[0] = str(interpreter)
    return resolved


def _register_active_process(process: subprocess.Popen[bytes]) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        _ACTIVE_PROCESSES[process.pid] = process


def _unregister_active_process(process: subprocess.Popen[bytes]) -> None:
    with _ACTIVE_PROCESSES_LOCK:
        if _ACTIVE_PROCESSES.get(process.pid) is process:
            _ACTIVE_PROCESSES.pop(process.pid, None)


def shutdown_active_processes() -> int:
    """Terminate every child process group still owned by the MCP server.

    This is intended for the server lifespan shutdown hook. It returns the
    number of process groups that were active when shutdown began.
    """
    with _ACTIVE_PROCESSES_LOCK:
        active = list(_ACTIVE_PROCESSES.values())
    for process in active:
        _terminate_process(process, force=False)
    if active:
        time.sleep(CANCEL_KILL_GRACE_SECONDS)
    # Always target each process group with SIGKILL. Its leader may already
    # have exited while a descendant ignored SIGTERM.
    for process in active:
        _terminate_process(process, force=True)
    wait_deadline = time.monotonic() + 5
    for process in active:
        remaining = wait_deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            process.wait(timeout=remaining)
        except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
            pass
    return len(active)


def _acquire_subprocess_slot(
    *,
    deadline: float,
    cancellation: CommandCancellation | None,
) -> tuple[bool, str]:
    """Acquire the global worker semaphore through a bounded wait queue."""
    global _SUBPROCESS_QUEUE_WAITERS

    if _SUBPROCESS_SEMAPHORE.acquire(blocking=False):
        return True, ""
    with _SUBPROCESS_QUEUE_LOCK:
        if _SUBPROCESS_QUEUE_WAITERS >= MAX_QUEUED_SUBPROCESSES:
            raise SkillMCPError(
                "The MCP subprocess queue is full; retry after active work completes."
            )
        _SUBPROCESS_QUEUE_WAITERS += 1
    queue_deadline = min(
        deadline,
        time.monotonic() + SUBPROCESS_QUEUE_TIMEOUT_SECONDS,
    )
    try:
        while True:
            if cancellation is not None and cancellation.cancelled:
                return False, "Command cancelled while waiting for a subprocess slot."
            remaining = queue_deadline - time.monotonic()
            if remaining <= 0:
                return False, "Timed out while waiting for a subprocess slot."
            if _SUBPROCESS_SEMAPHORE.acquire(timeout=min(0.1, remaining)):
                return True, ""
    finally:
        with _SUBPROCESS_QUEUE_LOCK:
            _SUBPROCESS_QUEUE_WAITERS -= 1


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
        self._plan_hashes: set[str] = set()

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
            plan_hashes = tuple(self._plan_hashes)
            self._plan_hashes.clear()
        if process is not None and not was_cancelled:
            _request_process_cancel(process)
        if plan_hashes:
            with _PLANS_LOCK:
                for plan_hash in plan_hashes:
                    _PLANS.pop(plan_hash, None)
                    _RESERVED_PLANS.discard(plan_hash)

    def track_plan(self, plan_hash: str) -> bool:
        """Track a newly stored plan, or reject it if cancellation already won."""
        with self._lock:
            if self._cancelled:
                return False
            self._plan_hashes.add(plan_hash)
            return True

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
        raise SkillMCPError(
            f"Script escapes skill scripts directory: {script}"
        ) from exc
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
        is_option_flag = bool(re.fullmatch(r"--[A-Za-z0-9][A-Za-z0-9_-]*", flag))
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
            if flag == "--secret-file":
                raise SkillMCPError(
                    "--secret-file requires separate KEY PATH arguments"
                )
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


def _secret_file_arguments(command: list[str]) -> list[tuple[str, str]]:
    """Extract secret-file flag/path pairs without opening the files."""
    bindings: list[tuple[str, str]] = []
    index = 0
    while index < len(command):
        argument = command[index]
        if not isinstance(argument, str) or not argument.startswith("--"):
            index += 1
            continue
        flag, separator, inline_value = argument.partition("=")
        if flag == "--secret-file":
            if separator:
                raise SkillMCPError(
                    "--secret-file requires separate KEY PATH arguments"
                )
            if index + 2 >= len(command):
                raise SkillMCPError("--secret-file requires KEY PATH")
            key = _safe_text(command[index + 1], label="--secret-file key")
            path = _safe_text(command[index + 2], label="--secret-file path")
            bindings.append((f"--secret-file:{key}", path))
            index += 3
            continue
        if _is_secret_file_flag(flag):
            if separator:
                path = inline_value
                index += 1
            else:
                if index + 1 >= len(command):
                    raise SkillMCPError(f"{flag} requires a file path")
                path = _safe_text(command[index + 1], label=f"{flag} path")
                index += 2
            if not path:
                raise SkillMCPError(f"{flag} requires a file path")
            bindings.append((flag, path))
            continue
        index += 1
    return bindings


def _secret_file_identity(
    path_value: str,
    *,
    label: str,
    require_exists: bool,
) -> dict[str, Any]:
    """Validate secret-file metadata without reading credential contents."""
    path_value = _safe_text(path_value, label=f"{label} path")
    if not path_value:
        raise SkillMCPError(f"{label} path cannot be empty")
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    absolute = Path(os.path.abspath(candidate))
    try:
        metadata = absolute.lstat()
    except FileNotFoundError:
        if require_exists:
            raise SkillMCPError(
                f"{label} does not exist; create it securely and re-run the plan: {absolute}"
            ) from None
        return {"path": str(absolute), "exists": False}
    except OSError as exc:
        raise SkillMCPError(f"Could not inspect {label} at {absolute}: {exc}") from exc

    if stat.S_ISLNK(metadata.st_mode):
        raise SkillMCPError(f"{label} must not be a symbolic link: {absolute}")
    if not stat.S_ISREG(metadata.st_mode):
        raise SkillMCPError(f"{label} must be a regular file: {absolute}")
    mode = stat.S_IMODE(metadata.st_mode)
    if os.name == "posix":
        if metadata.st_uid != os.geteuid():
            raise SkillMCPError(
                f"{label} must be owned by the MCP server user: {absolute}"
            )
        if mode & 0o077:
            raise SkillMCPError(
                f"{label} must not be accessible by group or other users: {absolute}"
            )
        if not mode & stat.S_IRUSR:
            raise SkillMCPError(f"{label} must be owner-readable: {absolute}")
        if metadata.st_nlink != 1:
            raise SkillMCPError(
                f"{label} must not have multiple hard links: {absolute}"
            )
    if metadata.st_size > MAX_SECRET_FILE_BYTES:
        raise SkillMCPError(
            f"{label} exceeds the {MAX_SECRET_FILE_BYTES}-byte secret-file limit: {absolute}"
        )
    return {
        "path": str(absolute),
        "exists": True,
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "mode": mode,
        "uid": getattr(metadata, "st_uid", None),
        "gid": getattr(metadata, "st_gid", None),
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "ctime_ns": metadata.st_ctime_ns,
    }


def _secret_file_identities(
    command: list[str],
    *,
    require_exists: bool = False,
) -> tuple[dict[str, Any], ...]:
    identities = []
    for label, path in _secret_file_arguments(command):
        identities.append(
            {
                "argument": label,
                "identity": _secret_file_identity(
                    path,
                    label=label,
                    require_exists=require_exists,
                ),
            }
        )
    return tuple(identities)


def _verify_secret_file_identities(plan: PlannedCommand) -> None:
    current = _secret_file_identities(plan.command, require_exists=True)
    if current != plan.secret_file_identities:
        raise SkillMCPError(
            "A planned secret file changed after review; the plan was invalidated. "
            "Re-run the plan step."
        )


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


def _bounded_snapshot_paths() -> list[Path]:
    """Enumerate the snapshot tree with bounds before allocating path state."""
    paths: list[Path] = []
    directory_count = 0
    entry_count = 0
    for current, directories, files in os.walk(SKILLS_DIR, followlinks=False):
        directory_count += 1
        current_path = Path(current)
        depth = len(current_path.relative_to(SKILLS_DIR).parts)
        if directory_count > MAX_SNAPSHOT_DIRECTORIES:
            raise SkillMCPError(
                f"Skill snapshot exceeds {MAX_SNAPSHOT_DIRECTORIES} directories"
            )
        if depth > MAX_SNAPSHOT_DEPTH:
            raise SkillMCPError(
                f"Skill snapshot exceeds traversal depth {MAX_SNAPSHOT_DEPTH}"
            )
        entry_count += len(directories) + len(files)
        if entry_count > MAX_SNAPSHOT_ENTRIES:
            raise SkillMCPError(
                f"Skill snapshot exceeds {MAX_SNAPSHOT_ENTRIES} entries"
            )
        kept_directories: list[str] = []
        for name in sorted(directories):
            if name in _SNAPSHOT_EXCLUDED_DIR_NAMES:
                continue
            path = current_path / name
            if path.is_symlink():
                paths.append(path)
            else:
                kept_directories.append(name)
        directories[:] = kept_directories
        paths.extend(current_path / name for name in sorted(files))
    return sorted(paths, key=lambda item: item.as_posix())


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
        for path in _bounded_snapshot_paths():
            relative_path = path.relative_to(SKILLS_DIR)
            if any(
                part in _SNAPSHOT_EXCLUDED_DIR_NAMES for part in relative_path.parts
            ):
                continue
            if path.name in _SNAPSHOT_EXCLUDED_FILE_NAMES or path.name.endswith(
                _SNAPSHOT_EXCLUDED_SUFFIXES
            ):
                continue
            relative = relative_path.as_posix().encode("utf-8")
            if path.is_symlink():
                target = path.resolve(strict=True)
                target.relative_to(skills_root)
                digest.update(b"L\0" + relative + b"\0")
                digest.update(
                    os.readlink(path).encode("utf-8", errors="surrogateescape")
                )
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
        raise SkillMCPError(
            f"Planned executable escapes the repository: {resolved}"
        ) from exc
    if not resolved.is_file():
        raise SkillMCPError(f"Planned executable is not a file: {resolved}")
    return resolved


def _plan_expired(plan: PlannedCommand, now: float | None = None) -> bool:
    if PLAN_TTL_SECONDS <= 0:
        return False
    checked_at = time.monotonic() if now is None else now
    return checked_at - plan.created_at > PLAN_TTL_SECONDS


def _purge_expired_plans_locked(now: float | None = None) -> int:
    """Remove expired plans. Caller must hold ``_PLANS_LOCK``."""
    checked_at = time.monotonic() if now is None else now
    expired = [
        plan_hash
        for plan_hash, plan in _PLANS.items()
        if _plan_expired(plan, checked_at)
    ]
    for plan_hash in expired:
        _PLANS.pop(plan_hash, None)
        _RESERVED_PLANS.discard(plan_hash)
    return len(expired)


def _store_plan(
    *,
    kind: str,
    command: list[str],
    summary: str,
    read_only: bool,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    dry_run: dict[str, Any] | None = None,
    expected_repository_sha256: str | None = None,
    cancellation: CommandCancellation | None = None,
) -> dict[str, Any]:
    if cancellation is not None and cancellation.cancelled:
        raise SkillMCPError("Plan creation was cancelled.")
    timeout_seconds = _validate_timeout(timeout_seconds)
    executable = _planned_executable(command)
    executable_sha256 = _file_sha256(executable)
    interpreter = _interpreter_path(command)
    interpreter_sha256 = _file_sha256(interpreter) if interpreter is not None else ""
    secret_file_identities = _secret_file_identities(command)
    repository_sha256 = _skills_snapshot_sha256()
    if (
        expected_repository_sha256 is not None
        and repository_sha256 != expected_repository_sha256
    ):
        raise SkillMCPError(
            "The skill repository changed after the reviewed dry-run; re-run the plan step."
        )
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
        interpreter_path=str(interpreter) if interpreter is not None else "",
        interpreter_sha256=interpreter_sha256,
        secret_file_identities=secret_file_identities,
    )
    with _PLANS_LOCK:
        _purge_expired_plans_locked()
        while plan_hash in _PLANS:  # cryptographically implausible, but fail safe
            plan_hash = secrets.token_hex(PLAN_HASH_CHARS // 2)
            plan = PlannedCommand(**{**asdict(plan), "plan_hash": plan_hash})
        _PLANS[plan_hash] = plan
        # LRU eviction: drop the least-recently-used plan when over capacity.
        while len(_PLANS) > MAX_STORED_PLANS:
            evicted = next(
                (candidate for candidate in _PLANS if candidate not in _RESERVED_PLANS),
                None,
            )
            if evicted is None:
                _PLANS.pop(plan_hash, None)
                raise SkillMCPError(
                    "All stored plan slots are currently reserved; retry later."
                )
            _PLANS.pop(evicted, None)
    if cancellation is not None and not cancellation.track_plan(plan_hash):
        with _PLANS_LOCK:
            _PLANS.pop(plan_hash, None)
            _RESERVED_PLANS.discard(plan_hash)
        raise SkillMCPError("Plan creation was cancelled.")
    return asdict(plan)


@dataclass(frozen=True)
class _BoundedResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False


def _drain_stream(
    stream: Any, sink: list[bytes], byte_cap: int, dropped: list[int]
) -> None:
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
    before_spawn: Callable[[], None] | None = None,
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
    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    acquired, queue_message = _acquire_subprocess_slot(
        deadline=deadline,
        cancellation=cancellation,
    )
    if not acquired:
        cancelled = cancellation is not None and cancellation.cancelled
        return _BoundedResult(
            returncode=130 if cancelled else 124,
            stdout="",
            stderr=queue_message,
            timed_out=not cancelled,
            cancelled=cancelled,
        )
    try:
        # Authorization may have changed while this call was queued.
        if os.environ.get("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION") != "1":
            raise SkillMCPError(
                "Subprocess execution was disabled while the command was queued."
            )
        if cancellation is not None and cancellation.cancelled:
            return _BoundedResult(
                returncode=130,
                stdout="",
                stderr="Command cancelled before start.",
                cancelled=True,
            )
        if time.monotonic() >= deadline:
            return _BoundedResult(
                returncode=124,
                stdout="",
                stderr="Command timed out before a subprocess could start.",
                timed_out=True,
            )
        resolved_command = _resolved_command(command)
        if before_spawn is not None:
            # execute_plan uses this final boundary to recheck its TTL, gates,
            # and reservation, then consume the single-use plan. It runs only
            # after a worker slot exists, so queue cancellation keeps the plan.
            try:
                before_spawn()
            except _CommandCancelledBeforeStart:
                return _BoundedResult(
                    returncode=130,
                    stdout="",
                    stderr="Command cancelled before start.",
                    cancelled=True,
                )
        try:
            proc = subprocess.Popen(
                resolved_command,
                cwd=REPO_ROOT,
                env=_child_environment(),
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
        _register_active_process(proc)
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
            remaining_runtime = max(0.001, deadline - time.monotonic())
            returncode = proc.wait(timeout=remaining_runtime)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Send SIGTERM, allow a short cleanup window, then *always* send
            # SIGKILL to the group. A leader can exit on SIGTERM while a
            # descendant in the same group continues running.
            grace_started = time.monotonic()
            _terminate_process(proc, force=False)
            try:
                returncode = proc.wait(timeout=CANCEL_KILL_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                returncode = -signal.SIGKILL
            except (OSError, ProcessLookupError):
                returncode = -signal.SIGKILL
            grace_remaining = CANCEL_KILL_GRACE_SECONDS - (
                time.monotonic() - grace_started
            )
            if grace_remaining > 0:
                time.sleep(grace_remaining)
            _terminate_process(proc, force=True)
            try:
                returncode = proc.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError, ProcessLookupError):
                returncode = -signal.SIGKILL
        finally:
            if cancellation is not None:
                cancelled = cancellation.cancelled
                cancellation.detach(proc)
            # Reader threads exit when all process-group pipe writers close.
            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            _unregister_active_process(proc)

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
    finally:
        _SUBPROCESS_SEMAPHORE.release()


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
            r"[A-Za-z0-9+/=._\-]+"
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
            r"[^\s'\",&]+"
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


def _json_key_carries_secret_material(key: str) -> bool:
    normalized = _normalize_key(key)
    if not normalized or normalized in NON_SECRET_VALUE_KEYS:
        return False
    if normalized.endswith(
        (
            "_file",
            "_files",
            "_path",
            "_paths",
            "_key_name",
            "_keys",
            "_name",
            "_ref",
            "_reference",
            "_url",
            "_id",
        )
    ):
        return False
    return _looks_secret_key(normalized)


def _sanitize_parsed_json(payload: Any, *, label: str) -> dict[str, Any]:
    """Recursively redact and shape-bound JSON returned by child scripts."""
    if not isinstance(payload, dict):
        raise SkillMCPError(f"{label} must be a JSON object")
    item_count = 0

    def visit(value: Any, *, depth: int, key_hint: str | None = None) -> Any:
        nonlocal item_count
        item_count += 1
        if item_count > MAX_PARSED_JSON_ITEMS:
            raise SkillMCPError(
                f"{label} exceeds the {MAX_PARSED_JSON_ITEMS}-item JSON limit"
            )
        if depth > MAX_PARSED_JSON_DEPTH:
            raise SkillMCPError(
                f"{label} exceeds the {MAX_PARSED_JSON_DEPTH}-level JSON depth limit"
            )
        if key_hint is not None and _json_key_carries_secret_material(key_hint):
            return "[REDACTED]"
        if isinstance(value, str):
            return _truncate_and_redact(value)
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise SkillMCPError(f"{label} contains a non-finite JSON number")
            return value
        if isinstance(value, list):
            return [visit(item, depth=depth + 1) for item in value]
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for raw_key, item in value.items():
                if not isinstance(raw_key, str):
                    raise SkillMCPError(f"{label} contains a non-string object key")
                key = _truncate_and_redact(raw_key)
                if key in sanitized:
                    raise SkillMCPError(
                        f"{label} contains duplicate keys after output sanitization"
                    )
                sanitized[key] = visit(
                    item,
                    depth=depth + 1,
                    key_hint=raw_key,
                )
            return sanitized
        raise SkillMCPError(
            f"{label} contains unsupported value type {type(value).__name__}"
        )

    sanitized_payload = visit(payload, depth=0)
    encoded = json.dumps(
        sanitized_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise SkillMCPError(
            f"{label} exceeds the {MAX_OUTPUT_BYTES}-byte parsed-output limit"
        )
    return sanitized_payload


def _load_subprocess_json(value: str, *, label: str) -> Any:
    """Parse child JSON while rejecting duplicate keys and non-finite values."""

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise SkillMCPError(f"{label} contains duplicate object key {key!r}")
            result[key] = item
        return result

    def reject_constant(constant: str) -> Any:
        raise SkillMCPError(f"{label} contains non-finite number {constant}")

    return json.loads(
        value,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )


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
        raise SkillMCPError(f"Skill file escapes its skill directory: {path}") from exc
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
            if any(
                part.startswith(".") for part in path.relative_to(templates_dir).parts
            ):
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
                "template_files": [
                    str(path.relative_to(skill_dir)) for path in template_files
                ],
                "has_reference": bool(reference_files),
                "reference_files": [
                    str(path.relative_to(skill_dir)) for path in reference_files
                ],
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
            raise SkillMCPError(
                f"{skill} does not have reference.md or references/*.md"
            )
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
    return _read_bounded_text(
        _contained_skill_file(path, skill_dir), MAX_RESOURCE_BYTES
    )


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
    """Report credential-file metadata without following links or reading data."""
    candidates: list[tuple[str, Path]] = []
    env_path = os.environ.get("SPLUNK_CREDENTIALS_FILE")
    if env_path:
        candidates.append(("env", Path(env_path).expanduser()))
    candidates.append(("project", REPO_ROOT / "credentials"))
    candidates.append(("home", Path.home() / ".splunk" / "credentials"))

    entries: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None
    for source, path in candidates:
        exists = False
        mode: str | None = None
        owner_ok: bool | None = None
        single_link: bool | None = None
        regular_file = False
        reasons: list[str] = []
        try:
            metadata = path.lstat()
            exists = True
            mode_int = stat.S_IMODE(metadata.st_mode)
            mode = oct(mode_int)
            if stat.S_ISLNK(metadata.st_mode):
                reasons.append("symbolic link")
            elif not stat.S_ISREG(metadata.st_mode):
                reasons.append("not a regular file")
            else:
                regular_file = True
            if os.name == "posix" and hasattr(os, "geteuid"):
                owner_ok = metadata.st_uid == os.geteuid()
                single_link = metadata.st_nlink == 1
                if not owner_ok:
                    reasons.append("not owned by the MCP server user")
                if not single_link:
                    reasons.append("link count is not one")
                if mode_int & 0o077:
                    reasons.append("accessible by group or other users")
                if not mode_int & stat.S_IRUSR:
                    reasons.append("not owner-readable")
        except FileNotFoundError:
            pass
        except OSError as exc:
            reasons.append(f"metadata unavailable: {type(exc).__name__}")
        secure_mode = exists and regular_file and not reasons
        entry = {
            "source": source,
            "path": str(path),
            "exists": exists,
            "mode": mode,
            "secure_mode": secure_mode,
            "regular_file": regular_file,
            "owner_ok": owner_ok,
            "single_link": single_link,
            "reasons": reasons,
        }
        entries.append(entry)
        if active is None and secure_mode:
            active = entry
    return {"active": active, "candidates": entries}


def get_server_status() -> dict[str, Any]:
    """Return aggregate supervisor state without exposing commands or plan data."""
    with _PLANS_LOCK:
        purged_expired_plans = _purge_expired_plans_locked()
        stored_plans = len(_PLANS)
        reserved_plans = len(_RESERVED_PLANS)
    with _ACTIVE_PROCESSES_LOCK:
        active_processes = len(_ACTIVE_PROCESSES)
    with _SUBPROCESS_QUEUE_LOCK:
        queued_subprocesses = _SUBPROCESS_QUEUE_WAITERS
    return {
        "stored_plans": stored_plans,
        "reserved_plans": reserved_plans,
        "purged_expired_plans": purged_expired_plans,
        "max_stored_plans": MAX_STORED_PLANS,
        "plan_ttl_seconds": PLAN_TTL_SECONDS,
        "active_processes": active_processes,
        "queued_subprocesses": queued_subprocesses,
        "max_concurrent_subprocesses": MAX_CONCURRENT_SUBPROCESSES,
        "max_queued_subprocesses": MAX_QUEUED_SUBPROCESSES,
    }


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
    """Resolve a product from checked-in catalog data without running code."""
    query = _safe_text(query, label="query")
    if cancellation is not None and cancellation.cancelled:
        raise SkillMCPError("Cisco product resolution was cancelled.")
    try:
        return discovery.resolve_cisco_product(query)
    except discovery.DiscoveryError as exc:
        raise SkillMCPError(f"Could not resolve Cisco product: {exc}") from exc


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


def secret_file_instructions(
    secret_keys: list[str], prefix: str = "/tmp/splunk_skill"
) -> dict[str, Any]:
    prefix = _safe_text(prefix, label="prefix")
    if len(prefix) > 4096:
        raise SkillMCPError("prefix exceeds the 4096-character limit")
    if not isinstance(secret_keys, list):
        raise SkillMCPError("secret_keys must be a list of strings")
    if len(secret_keys) > MAX_SECRET_KEYS:
        raise SkillMCPError(
            f"secret_keys cannot contain more than {MAX_SECRET_KEYS} entries"
        )
    prepared: list[tuple[str, str]] = []
    seen_keys: set[str] = set()
    for raw_key in secret_keys:
        key = _safe_text(raw_key, label="secret key")
        if not key or len(key) > MAX_KEY_CHARS:
            raise SkillMCPError(
                f"secret key must contain 1 to {MAX_KEY_CHARS} characters"
            )
        if key in seen_keys:
            raise SkillMCPError(f"secret_keys contains duplicate key: {key}")
        seen_keys.add(key)
        safe_key = re.sub(r"[^A-Za-z0-9._-]+", "_", key).strip("_") or "secret"
        prepared.append((key, safe_key))

    normalized_counts: dict[str, int] = {}
    for _, safe_key in prepared:
        normalized_counts[safe_key] = normalized_counts.get(safe_key, 0) + 1

    commands = []
    used_paths: set[str] = set()
    for key, safe_key in prepared:
        if normalized_counts[safe_key] > 1:
            suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
            safe_key = f"{safe_key}_{suffix}"
        path = f"{prefix}_{safe_key}"
        counter = 1
        unique_path = path
        while unique_path in used_paths:
            counter += 1
            unique_path = f"{path}_{counter}"
        path = unique_path
        used_paths.add(path)
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

    # Refuse unsafe existing secret paths before the dry-run can inspect them.
    # Missing files remain representable so the dry-run can report its normal
    # missing-value guidance, but such a plan cannot execute until replanned.
    _secret_file_identities(dry_run_command)
    snapshot_before_dry_run = _skills_snapshot_sha256()
    dry_run_result = _run_command(
        dry_run_command,
        timeout_seconds=timeout_seconds,
        cancellation=cancellation,
    )
    snapshot_after_dry_run = _skills_snapshot_sha256()
    if snapshot_after_dry_run != snapshot_before_dry_run:
        raise SkillMCPError(
            "The skill repository changed during the reviewed dry-run; "
            "the result was discarded. Re-run the plan step."
        )
    try:
        parsed_dry_run = _load_subprocess_json(
            dry_run_result.stdout or "{}",
            label="Cisco product dry-run output",
        )
        dry_run = _sanitize_parsed_json(
            parsed_dry_run,
            label="Cisco product dry-run output",
        )
    except (json.JSONDecodeError, SkillMCPError) as exc:
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
        # Phase names are not an authorization boundary. Some validators
        # create reports, caches, or sessions, so every executable product
        # plan remains mutation-gated. The dry-run above is the only operation
        # enabled by the normal execution-on/mutation-off registration.
        read_only=False,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        expected_repository_sha256=snapshot_after_dry_run,
        cancellation=cancellation,
    )
    plan["dry_run_command"] = dry_run_command
    return plan


def plan_skill_script(
    skill: str,
    script: str,
    args: list[str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    *,
    cancellation: CommandCancellation | None = None,
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
        cancellation=cancellation,
    )


def _check_plan_execution_gates(
    plan: PlannedCommand,
    *,
    expected_kind: str | None,
) -> None:
    if expected_kind is not None and plan.kind != expected_kind:
        raise SkillMCPError(
            f"Plan {plan.plan_hash} is {plan.kind}, not {expected_kind}."
        )
    if os.environ.get("SPLUNK_SKILLS_MCP_ENABLE_EXECUTION") != "1":
        raise SkillMCPError(
            "Subprocess execution is disabled. Set "
            "SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1 in the MCP server environment."
        )
    if (
        plan.kind == "skill_script"
        and os.environ.get("SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION") != "1"
    ):
        raise SkillMCPError(
            "Generic skill-script execution is disabled. Set "
            "SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION=1 in addition to the "
            "execution and mutation gates only after reviewing this arbitrary-script risk."
        )
    if not plan.read_only and os.environ.get("SPLUNK_SKILLS_MCP_ALLOW_MUTATION") != "1":
        raise SkillMCPError(
            "Mutating execution is disabled. Set SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1 "
            "in the MCP server environment."
        )


def _verify_plan_integrity(plan: PlannedCommand) -> None:
    current_path = Path(plan.executable_path)
    if (
        not current_path.is_file()
        or _file_sha256(current_path) != plan.executable_sha256
    ):
        raise SkillMCPError(
            "The planned script changed after review; the plan was invalidated. "
            "Re-run the plan step."
        )
    if plan.interpreter_path:
        interpreter = Path(plan.interpreter_path)
        if (
            not interpreter.is_file()
            or _file_sha256(interpreter) != plan.interpreter_sha256
        ):
            raise SkillMCPError(
                "The planned interpreter changed after review; the plan was "
                "invalidated. Re-run the plan step."
            )
    if _skills_snapshot_sha256() != plan.repository_sha256:
        raise SkillMCPError(
            "The skill repository changed after review; the plan was invalidated. "
            "Re-run the plan step."
        )
    _verify_secret_file_identities(plan)


def _cancelled_execution_payload(
    plan: PlannedCommand,
    *,
    plan_hash: str,
    message: str,
) -> dict[str, Any]:
    return {
        "ok": False,
        "plan_hash": plan_hash,
        "returncode": 130,
        "stdout": "",
        "stderr": message,
        "command": plan.command,
        "cwd": plan.cwd,
        "timed_out": False,
        "cancelled": True,
    }


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
    if confirm is not True:
        raise SkillMCPError("Execution requires confirm=true.")

    # Reserve (but do not consume) the exact immutable plan. Queue
    # cancellation, an authorization change, or shutdown before spawn leaves
    # the plan available for a corrected retry.
    with _PLANS_LOCK:
        plan = _PLANS.get(plan_hash)
        if plan is None:
            raise SkillMCPError(f"Unknown plan_hash: {plan_hash}")
        if _plan_expired(plan):
            _PLANS.pop(plan_hash, None)
            _RESERVED_PLANS.discard(plan_hash)
            raise SkillMCPError(f"Plan {plan_hash} has expired; re-run the plan step.")
        _purge_expired_plans_locked()
        _check_plan_execution_gates(plan, expected_kind=expected_kind)
        if plan_hash in _RESERVED_PLANS:
            raise SkillMCPError(f"Plan {plan_hash} is already queued for execution.")
        _RESERVED_PLANS.add(plan_hash)

    execution_lock_acquired = False
    try:
        while not _EXECUTION_LOCK.acquire(timeout=0.1):
            if cancellation is not None and cancellation.cancelled:
                return _cancelled_execution_payload(
                    plan,
                    plan_hash=plan_hash,
                    message="Command cancelled before execution.",
                )
        execution_lock_acquired = True

        # Recheck mutable authorization and plan lifetime after queueing.
        with _PLANS_LOCK:
            current = _PLANS.get(plan_hash)
            if current is None or current is not plan:
                raise SkillMCPError(
                    f"Plan {plan_hash} expired or was invalidated while queued."
                )
            if _plan_expired(plan):
                _PLANS.pop(plan_hash, None)
                _RESERVED_PLANS.discard(plan_hash)
                raise SkillMCPError(
                    f"Plan {plan_hash} has expired; re-run the plan step."
                )
            _check_plan_execution_gates(plan, expected_kind=expected_kind)
        if cancellation is not None and cancellation.cancelled:
            return _cancelled_execution_payload(
                plan,
                plan_hash=plan_hash,
                message="Command cancelled before execution.",
            )

        # Integrity failures permanently invalidate the reviewed plan. Gate,
        # queue, and cancellation failures above intentionally do not.
        try:
            _verify_plan_integrity(plan)
        except SkillMCPError:
            with _PLANS_LOCK:
                _PLANS.pop(plan_hash, None)
                _RESERVED_PLANS.discard(plan_hash)
            raise

        execution_command = list(plan.command)
        if plan.interpreter_path:
            execution_command[0] = plan.interpreter_path

        def consume_immediately_before_spawn() -> None:
            # A resolver or dry-run may have occupied the subprocess worker
            # after the first verification. Rebind the complete plan after
            # that queue wait, immediately before consuming it.
            try:
                _verify_plan_integrity(plan)
            except SkillMCPError:
                with _PLANS_LOCK:
                    _PLANS.pop(plan_hash, None)
                    _RESERVED_PLANS.discard(plan_hash)
                raise
            with _PLANS_LOCK:
                current = _PLANS.get(plan_hash)
                if current is None or current is not plan:
                    raise SkillMCPError(
                        f"Plan {plan_hash} expired or was invalidated before execution."
                    )
                if _plan_expired(plan):
                    _PLANS.pop(plan_hash, None)
                    _RESERVED_PLANS.discard(plan_hash)
                    raise SkillMCPError(
                        f"Plan {plan_hash} has expired; re-run the plan step."
                    )
                _check_plan_execution_gates(plan, expected_kind=expected_kind)
                if cancellation is not None and cancellation.cancelled:
                    raise _CommandCancelledBeforeStart
                _PLANS.pop(plan_hash, None)
                _RESERVED_PLANS.discard(plan_hash)

        result = _run_command(
            execution_command,
            timeout_seconds=plan.timeout_seconds,
            cancellation=cancellation,
            before_spawn=consume_immediately_before_spawn,
        )
    finally:
        if execution_lock_acquired:
            _EXECUTION_LOCK.release()
        with _PLANS_LOCK:
            _RESERVED_PLANS.discard(plan_hash)
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
