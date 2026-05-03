"""Core implementation for the repo-local Splunk Cisco skills MCP server.

This module intentionally has no MCP SDK dependency so the command planning and
safety gates can be tested with the repo's normal Python test environment.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import threading
from collections import OrderedDict
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
MAX_TIMEOUT_SECONDS = int(os.environ.get("MCP_MAX_TIMEOUT_SECONDS", "7200"))
RESOLVE_TIMEOUT_SECONDS = int(os.environ.get("MCP_RESOLVE_TIMEOUT_SECONDS", "60"))
# Max characters of stdout/stderr returned per stream. The bounded subprocess
# wrapper enforces this at the byte level during execution to prevent unbounded
# memory growth from chatty scripts.
MAX_OUTPUT_CHARS = 40000
# Hard byte cap per stream during execution. Exceeding either MAX_OUTPUT_CHARS
# or MAX_OUTPUT_BYTES causes further stream data to be discarded; the recorded
# output is suffixed with a truncation marker.
MAX_OUTPUT_BYTES = 256 * 1024
MAX_STORED_PLANS = 256

# Scripts whose --dry-run / --list-products invocation is genuinely read-only.
# Any (skill, script) pair NOT in this set is treated as mutating regardless of
# argv flags, even if the script silently ignores unknown flags.
READ_ONLY_DRY_RUN_SCRIPTS: set[tuple[str, str]] = {
    ("cisco-product-setup", "setup.sh"),
    ("splunk-agent-management-setup", "setup.sh"),
    ("splunk-workload-management-setup", "setup.sh"),
    ("splunk-hec-service-setup", "setup.sh"),
    ("splunk-index-lifecycle-smartstore-setup", "setup.sh"),
    ("splunk-monitoring-console-setup", "setup.sh"),
    ("splunk-enterprise-kubernetes-setup", "setup.sh"),
    ("splunk-observability-otel-collector-setup", "setup.sh"),
    ("splunk-observability-dashboard-builder", "setup.sh"),
}
READ_ONLY_LIST_SCRIPTS: set[tuple[str, str]] = {
    ("cisco-product-setup", "setup.sh"),
    ("cisco-product-setup", "resolve_product.sh"),
}
READ_ONLY_PHASE_SCRIPTS: dict[tuple[str, str], set[str]] = {
    ("splunk-agent-management-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-workload-management-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-hec-service-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-index-lifecycle-smartstore-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-monitoring-console-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-enterprise-kubernetes-setup", "setup.sh"): {"render", "preflight", "status"},
}
# Scripts that are read-only by definition (their entire purpose is to inspect
# state). Validate scripts only check Splunk and never mutate it.
READ_ONLY_SCRIPT_NAMES: set[str] = {
    "validate.sh",
    "list_apps.sh",
    "resolve_product.sh",
}

DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--activation-code",
    "--analytics-secret",
    "--api-key",
    "--api-secret",
    "--api-token",
    "--bearer-token",
    "--client-secret",
    "--hec-token",
    "--o11y-token",
    "--password",
    "--platform-hec-token",
    "--proxy-password",
    "--refresh-token",
    "--secret",
    "--skey",
    "--sf-token",
    "--token",
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

SECRET_FILE_FLAGS = {
    "--access-token-file",
    "--activation-code-file",
    "--analytics-secret-file",
    "--api-key-file",
    "--api-secret-file",
    "--api-token-file",
    "--bearer-token-file",
    "--client-secret-file",
    "--cloudlock-token-file",
    "--discovery-secret-file",
    "--hec-token-file",
    "--idxc-secret-file",
    "--o11y-token-file",
    "--password-file",
    "--platform-hec-token-file",
    "--pkcs-certificate-file",
    "--proxy-password-file",
    "--secret-file",
    "--shc-secret-file",
    "--snmpv3-secrets-file",
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


_PLANS: "OrderedDict[str, PlannedCommand]" = OrderedDict()
_PLANS_LOCK = Lock()


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
    if not (path / "SKILL.md").is_file():
        raise SkillMCPError(f"Unknown skill: {skill}")
    return path


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


def _looks_secret_key(key: str) -> bool:
    if normalize_key := re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower():
        if normalize_key in NON_SECRET_VALUE_KEYS:
            return False
    return bool(SECRET_KEY_RE.search(key.replace("-", "_")))


def _validate_timeout(timeout_seconds: int) -> int:
    if not isinstance(timeout_seconds, int):
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
        return ["python3", rel_path, *args]
    if suffix == ".rb":
        return ["ruby", rel_path, *args]
    if os.access(path, os.X_OK):
        return [rel_path, *args]
    raise SkillMCPError(f"Unsupported non-executable script type: {path.name}")


def _validate_args(args: list[str]) -> list[str]:
    safe_args: list[str] = []
    index = 0
    while index < len(args):
        arg = _safe_text(args[index], label=f"args[{index}]")
        flag = arg.split("=", 1)[0] if arg.startswith("--") else arg
        if flag in DIRECT_SECRET_FLAGS:
            raise SkillMCPError(
                f"Direct secret flag {flag} is blocked. Use the matching *-file flag."
            )
        if arg.startswith("--") and "=" in arg and flag in SECRET_FILE_FLAGS:
            path_value = arg.split("=", 1)[1]
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


def _arg_value(args: list[str], flag_name: str) -> str | None:
    for index, arg in enumerate(args):
        if arg == flag_name and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith(f"{flag_name}="):
            return arg.split("=", 1)[1]
    return None


def _phase_invocation_is_read_only(pair: tuple[str, str], args: list[str]) -> bool:
    allowed_phases = READ_ONLY_PHASE_SCRIPTS.get(pair)
    if not allowed_phases:
        return False
    if "--apply" in args:
        return False
    phase = _arg_value(args, "--phase") or "render"
    return phase in allowed_phases


def _hash_plan(command: list[str], kind: str, timeout_seconds: int) -> str:
    payload = {
        "command": command,
        "cwd": str(REPO_ROOT),
        "kind": kind,
        "timeout_seconds": timeout_seconds,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:PLAN_HASH_CHARS]


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
    plan_hash = _hash_plan(command, kind, timeout_seconds)
    plan = PlannedCommand(
        plan_hash=plan_hash,
        kind=kind,
        command=command,
        cwd=str(REPO_ROOT),
        summary=summary,
        read_only=read_only,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
    )
    with _PLANS_LOCK:
        # Re-storing the same hash refreshes recency (move to end).
        if plan_hash in _PLANS:
            _PLANS.move_to_end(plan_hash)
        _PLANS[plan_hash] = plan
        # LRU eviction: drop the least-recently-used plan when over capacity.
        while len(_PLANS) > MAX_STORED_PLANS:
            _PLANS.popitem(last=False)
    return asdict(plan)


def _consume_plan(plan_hash: str) -> PlannedCommand | None:
    """Atomically remove and return a plan, or None if absent.

    Plans are single-use: once a client invokes execute_plan with a valid
    hash, the plan is consumed regardless of whether the subprocess succeeds
    or fails. This prevents replay of destructive commands and serializes
    concurrent execute_plan calls for the same hash (only the first wins).
    """
    with _PLANS_LOCK:
        return _PLANS.pop(plan_hash, None)


@dataclass(frozen=True)
class _BoundedResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


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


def _run_command(command: list[str], *, timeout_seconds: int) -> _BoundedResult:
    """Run a command with bounded stdout/stderr buffering.

    Unlike subprocess.run(capture_output=True), this wrapper reads child
    output through worker threads with a hard byte cap per stream, so a
    runaway script cannot grow the parent process to gigabytes of RSS
    while waiting for the timeout.
    """
    timeout_seconds = _validate_timeout(timeout_seconds)
    proc = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
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
    try:
        returncode = proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        # Send SIGTERM, then SIGKILL after a grace period if needed.
        try:
            proc.terminate()
            try:
                returncode = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                returncode = proc.wait(timeout=5)
        except (OSError, ProcessLookupError):
            returncode = -signal.SIGKILL
    finally:
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
    return _BoundedResult(
        returncode=returncode,
        stdout=stdout_text,
        stderr=stderr_text,
        timed_out=timed_out,
    )


def _truncate(value: str) -> str:
    if len(value) <= MAX_OUTPUT_CHARS:
        return value
    omitted = len(value) - MAX_OUTPUT_CHARS
    return value[:MAX_OUTPUT_CHARS] + f"\n...[truncated {omitted} chars]"


def _skill_reference_files(skill_dir: Path) -> list[Path]:
    files: list[Path] = []
    primary = skill_dir / "reference.md"
    if primary.is_file():
        files.append(primary)
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        files.extend(
            sorted(path for path in references_dir.glob("*.md") if path.is_file())
        )
    return files


def list_skills() -> dict[str, Any]:
    skills: list[dict[str, Any]] = []
    for skill_dir in _skill_dirs():
        skill_md = skill_dir / "SKILL.md"
        metadata = _frontmatter(skill_md.read_text(encoding="utf-8"))
        scripts_dir = skill_dir / "scripts"
        scripts = (
            sorted(path.name for path in scripts_dir.iterdir() if path.is_file())
            if scripts_dir.exists()
            else []
        )
        reference_files = _skill_reference_files(skill_dir)
        skills.append(
            {
                "name": metadata.get("name", skill_dir.name),
                "description": metadata.get("description", ""),
                "path": str(skill_md.relative_to(REPO_ROOT)),
                "has_template": (skill_dir / "template.example").is_file(),
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
            return reference_files[0].read_text(encoding="utf-8")
        chunks = []
        for path in reference_files:
            rel_path = path.relative_to(skill_dir)
            text = path.read_text(encoding="utf-8")
            chunks.append(f"# {rel_path}\n\n{text}")
        return "\n\n".join(chunks)
    path = skill_dir / allowed[file_name]
    if not path.is_file():
        raise SkillMCPError(f"{skill} does not have {allowed[file_name]}")
    return path.read_text(encoding="utf-8")


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
    try:
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SkillMCPError(f"Cisco product catalog JSON is corrupted: {exc}") from exc
    products = catalog.get("products", [])
    if state:
        products = [item for item in products if item.get("automation_state") == state]
    return {"products": products}


def resolve_cisco_product(query: str) -> dict[str, Any]:
    query = _safe_text(query, label="query")
    command = ["bash", str(CISCO_RESOLVE_SCRIPT), "--json", query]
    result = _run_command(command, timeout_seconds=RESOLVE_TIMEOUT_SECONDS)
    payload: dict[str, Any]
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        payload = {
            "status": "error",
            "raw_stdout": _truncate(result.stdout),
            "returncode": result.returncode,
        }
        if result.stderr:
            payload["stderr"] = _truncate(result.stderr)
        return payload
    payload["returncode"] = result.returncode
    if result.stderr:
        payload["stderr"] = _truncate(result.stderr)
    return payload


def _catalog_keys_for_product(product_query: str) -> dict[str, set[str]]:
    """Best-effort lookup of accepted keys for a product, by query string.

    Returns a dict with 'non_secret' and 'secret' sets containing the union
    of accepted keys across the top-level product entry and any route
    variants. Returns empty sets if resolution fails for any reason; the
    orchestrator's own validate_known_keys will then catch unknown keys
    server-side.
    """
    try:
        result = resolve_cisco_product(product_query)
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
    commands = []
    for raw_key in secret_keys:
        key = _safe_text(raw_key, label="secret key")
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
) -> dict[str, Any]:
    product = _safe_text(product, label="product")
    timeout_seconds = _validate_timeout(timeout_seconds)
    set_values = set_values or {}
    secret_files = secret_files or {}

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
    allowlist = _catalog_keys_for_product(product)

    for key, value in sorted(set_values.items()):
        key = _safe_text(key, label="set_values key")
        value = _safe_text(value, label=f"set_values[{key}]")
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").lower()
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

    dry_run_result = _run_command(dry_run_command, timeout_seconds=timeout_seconds)
    try:
        dry_run = json.loads(dry_run_result.stdout or "{}")
    except json.JSONDecodeError as exc:
        detail = _truncate(dry_run_result.stderr or dry_run_result.stdout)
        raise SkillMCPError(
            f"Cisco product dry-run did not return JSON: {detail}"
        ) from exc
    dry_run["returncode"] = dry_run_result.returncode
    if dry_run_result.stderr:
        dry_run["stderr"] = _truncate(dry_run_result.stderr)
    if dry_run_result.returncode != 0:
        message = dry_run.get("stderr") or _truncate(dry_run_result.stdout)
        raise SkillMCPError(f"Cisco product dry-run failed: {message}")

    summary = f"Cisco product setup for {product} ({phase})"
    automation_state = (
        dry_run.get("resolved_product", {}).get("automation_state")
        if isinstance(dry_run.get("resolved_product"), dict)
        else ""
    )
    plan = _store_plan(
        kind="cisco_product_setup",
        command=execute_command,
        summary=summary,
        read_only=phase == "validate" or automation_state != "automated",
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
    safe_args = _validate_args(args or [])
    command = _script_command(path, safe_args)
    script_name = path.name
    pair = (skill, script_name)
    # A plan is read-only only when we can be certain the underlying script
    # cannot mutate state. We classify four cases:
    #   1. Scripts that are read-only by name (validate.sh, list_apps.sh, ...).
    #   2. Any script invoked with --help (universally a usage print).
    #   3. Scripts with explicitly allowlisted --dry-run / --list-products
    #      semantics.
    #   4. Render-first setup wrappers invoked in render, preflight, or status
    #      phases without --apply.
    if script_name in READ_ONLY_SCRIPT_NAMES:
        read_only = True
    elif "--help" in safe_args:
        read_only = True
    elif "--dry-run" in safe_args and pair in READ_ONLY_DRY_RUN_SCRIPTS:
        read_only = True
    elif "--list-products" in safe_args and pair in READ_ONLY_LIST_SCRIPTS:
        read_only = True
    elif _phase_invocation_is_read_only(pair, safe_args):
        read_only = True
    else:
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
) -> dict[str, Any]:
    plan_hash = _safe_text(plan_hash, label="plan_hash")
    if not PLAN_HASH_RE.match(plan_hash):
        raise SkillMCPError("plan_hash must be a 64-character lowercase hex string.")

    # Peek at the plan to validate. We do not consume the plan on validation
    # failure: a wrong expected_kind, missing confirm, or a misconfigured
    # mutation gate is a recoverable client/operator error, and forcing a
    # re-plan would be hostile and would also expose a destructive race
    # between the validation error and a retry.
    with _PLANS_LOCK:
        plan = _PLANS.get(plan_hash)
    if plan is None:
        raise SkillMCPError(f"Unknown plan_hash: {plan_hash}")
    if not confirm:
        raise SkillMCPError("Execution requires confirm=true.")
    if expected_kind is not None and plan.kind != expected_kind:
        raise SkillMCPError(f"Plan {plan_hash} is {plan.kind}, not {expected_kind}.")
    if not plan.read_only and os.environ.get("SPLUNK_SKILLS_MCP_ALLOW_MUTATION") != "1":
        raise SkillMCPError(
            "Mutating execution is disabled. Set SPLUNK_SKILLS_MCP_ALLOW_MUTATION=1 "
            "in the MCP server environment."
        )

    # All checks passed. Atomically consume the plan so it cannot be replayed
    # and so concurrent execute_plan calls for the same hash cannot both run
    # the command. The loser of the race gets a generic "no longer available"
    # error, which also covers the (much rarer) case of LRU eviction between
    # the peek and the consume.
    plan = _consume_plan(plan_hash)
    if plan is None:
        raise SkillMCPError(
            f"Plan {plan_hash} is no longer available; re-run the plan step."
        )

    result = _run_command(plan.command, timeout_seconds=plan.timeout_seconds)
    return {
        "plan_hash": plan_hash,
        "returncode": result.returncode,
        "stdout": _truncate(result.stdout),
        "stderr": _truncate(result.stderr),
        "command": plan.command,
        "cwd": plan.cwd,
        "timed_out": result.timed_out,
    }
