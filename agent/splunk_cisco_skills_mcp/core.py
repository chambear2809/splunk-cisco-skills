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
import time
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
# Maximum age (in seconds) of a stored plan before execute_plan refuses to
# run it. Plans older than this are treated as expired so that a hash that
# was generated, then sat unexecuted across a long pause / context switch,
# cannot be quietly applied later — the operator must regenerate the plan
# from the current state. Override at deployment time with
# MCP_PLAN_TTL_SECONDS=<int>; values <= 0 disable the TTL guard entirely.
PLAN_TTL_SECONDS = int(os.environ.get("MCP_PLAN_TTL_SECONDS", "3600"))

# Scripts whose --dry-run / --list-products invocation is genuinely read-only.
# Any (skill, script) pair NOT in this set is treated as mutating regardless of
# argv flags, even if the script silently ignores unknown flags.
READ_ONLY_DRY_RUN_SCRIPTS: set[tuple[str, str]] = {
    ("cisco-product-setup", "setup.sh"),
    ("splunk-agent-management-setup", "setup.sh"),
    ("splunk-asset-risk-intelligence-setup", "setup.sh"),
    ("splunk-attack-analyzer-setup", "setup.sh"),
    # splunk-cloud-acs-allowlist-setup, splunk-edge-processor-setup,
    # splunk-federated-search-setup, splunk-indexer-cluster-setup,
    # splunk-license-manager-setup, splunk-soar-setup all share the same
    # render-first --dry-run contract: the renderer runs with --dry-run,
    # any rendered script is only logged ("DRY RUN: ..."), and the wrapper
    # exits 0 before any mutating step. Allowlisting them here lets
    # operators preview --phase apply / --phase rolling-restart / etc.
    # under the read-only classification.
    ("splunk-cloud-acs-allowlist-setup", "setup.sh"),
    ("splunk-edge-processor-setup", "setup.sh"),
    ("splunk-enterprise-kubernetes-setup", "setup.sh"),
    # splunk-enterprise-public-exposure-hardening uses --phase + --dry-run.
    # The --dry-run preview always exits before any rendered script runs.
    ("splunk-enterprise-public-exposure-hardening", "setup.sh"),
    ("splunk-federated-search-setup", "setup.sh"),
    ("splunk-hec-service-setup", "setup.sh"),
    ("splunk-index-lifecycle-smartstore-setup", "setup.sh"),
    ("splunk-indexer-cluster-setup", "setup.sh"),
    ("splunk-itsi-setup", "setup.sh"),
    ("splunk-license-manager-setup", "setup.sh"),
    ("splunk-monitoring-console-setup", "setup.sh"),
    ("splunk-observability-cloud-integration-setup", "setup.sh"),
    ("splunk-observability-dashboard-builder", "setup.sh"),
    # splunk-observability-native-ops --dry-run is forwarded into
    # o11y_native_api.py, which skips live SignalFx / Splunk On-Call API
    # writes. The token-file readability check is also short-circuited
    # when --dry-run is set, so --apply --dry-run is a true preview path.
    ("splunk-observability-native-ops", "setup.sh"),
    ("splunk-observability-otel-collector-setup", "setup.sh"),
    # splunk-oncall-setup --dry-run skips API/HEC writes even when the
    # caller also passes --apply, --send-alert, or --install-splunk-app.
    ("splunk-oncall-setup", "setup.sh"),
    ("splunk-security-essentials-setup", "setup.sh"),
    ("splunk-security-portfolio-setup", "setup.sh"),
    ("splunk-soar-setup", "setup.sh"),
    ("splunk-admin-doctor", "doctor.py"),
    ("splunk-admin-doctor", "setup.sh"),
    ("splunk-uba-setup", "setup.sh"),
    ("splunk-universal-forwarder-setup", "setup.sh"),
    ("splunk-workload-management-setup", "setup.sh"),
    # New TE / MCP / Isovalent / AI Pod skills (eight). Each is render-first;
    # --apply (or --apply STEPS) opts in to mutating action and is separately
    # gated by the READ_ONLY_UNLESS_FLAG_SCRIPTS map below.
    ("cisco-thousandeyes-mcp-setup", "setup.sh"),
    ("splunk-observability-thousandeyes-integration", "setup.sh"),
    ("cisco-isovalent-platform-setup", "setup.sh"),
    ("splunk-observability-isovalent-integration", "setup.sh"),
    ("splunk-observability-cisco-nexus-integration", "setup.sh"),
    ("splunk-observability-cisco-intersight-integration", "setup.sh"),
    ("splunk-observability-nvidia-gpu-integration", "setup.sh"),
    ("splunk-observability-cisco-ai-pod-integration", "setup.sh"),
    # splunk-observability-k8s-auto-instrumentation-setup is render-first with
    # --apply-instrumentation / --apply-annotations / --uninstall-instrumentation
    # gates; --dry-run is a pure preview (no cluster writes, no file writes beyond
    # the plan text).
    ("splunk-observability-k8s-auto-instrumentation-setup", "setup.sh"),
}
READ_ONLY_LIST_SCRIPTS: set[tuple[str, str]] = {
    ("cisco-product-setup", "setup.sh"),
    ("cisco-product-setup", "resolve_product.sh"),
}
READ_ONLY_PHASE_SCRIPTS: dict[tuple[str, str], set[str]] = {
    ("splunk-agent-management-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-admin-doctor", "doctor.py"): {"doctor", "fix-plan", "validate", "status"},
    ("splunk-admin-doctor", "setup.sh"): {"doctor", "fix-plan", "validate", "status"},
    ("splunk-workload-management-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-hec-service-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-index-lifecycle-smartstore-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-monitoring-console-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-enterprise-kubernetes-setup", "setup.sh"): {"render", "preflight", "status"},
    ("splunk-universal-forwarder-setup", "setup.sh"): {"render", "download", "status"},
    ("splunk-cloud-acs-allowlist-setup", "setup.sh"): {
        "render",
        "preflight",
        "status",
        "audit",
        "validate",
    },
    # splunk-edge-processor-setup status/validate phases re-render assets and
    # then run validate.sh on the control plane. validate.sh only reads via
    # the EP API and never writes back, so these phases are pure inspection.
    ("splunk-edge-processor-setup", "setup.sh"): {
        "render",
        "preflight",
        "status",
        "validate",
    },
    # splunk-enterprise-public-exposure-hardening render/preflight/validate
    # phases only render assets or run rendered preflight/validate scripts,
    # which inspect the search head without changing it. apply/all run the
    # search-head apply script and remain mutating.
    ("splunk-enterprise-public-exposure-hardening", "setup.sh"): {
        "render",
        "preflight",
        "validate",
    },
    ("splunk-federated-search-setup", "setup.sh"): {
        "render",
        "preflight",
        "status",
    },
    ("splunk-indexer-cluster-setup", "setup.sh"): {
        "render",
        "preflight",
        "bundle-validate",
        "bundle-status",
        "status",
        "validate",
    },
    ("splunk-license-manager-setup", "setup.sh"): {
        "render",
        "preflight",
        "status",
        "validate",
    },
    ("splunk-soar-setup", "setup.sh"): {"render", "preflight", "cloud-onboard"},
}
# Scripts that use flag-based mode toggles (not --phase) and are read-only
# whenever none of the listed mutation flag patterns are present. Each entry
# maps (skill, script) to a tuple of patterns; a pattern ending in "-" is a
# prefix match against the flag-only portion of the argv token (so "--apply-"
# matches both "--apply-k8s" and "--apply-host"), otherwise it is an exact
# flag match. The flag-only portion is the substring before "=" so that
# "--flag=value" forms are also detected.
#
# Any matching invocation is still treated as mutating UNLESS the same
# invocation also includes --dry-run AND the (skill, script) is in
# READ_ONLY_DRY_RUN_SCRIPTS — that combined case is handled earlier in
# plan_skill_script() and exists so operators can preview an --apply call
# safely. That is why splunk-observability-dashboard-builder and
# splunk-observability-otel-collector-setup appear in both this map and
# READ_ONLY_DRY_RUN_SCRIPTS; do not "deduplicate" without first updating
# plan_skill_script().
READ_ONLY_UNLESS_FLAG_SCRIPTS: dict[tuple[str, str], tuple[str, ...]] = {
    # The live validator is a read-only baseline/help/status sweep unless the
    # operator explicitly enables its bounded apply catalog.
    ("splunk-admin-doctor", "live_validate_all.py"): ("--allow-apply",),
    ("splunk-observability-native-ops", "setup.sh"): ("--apply",),
    ("splunk-observability-dashboard-builder", "setup.sh"): ("--apply",),
    # splunk-oncall-setup mutates Splunk On-Call (or the Splunk-side companion
    # apps, or the REST endpoint) only when --apply, --send-alert,
    # --install-splunk-app, --uninstall, or --self-test is passed. Without
    # any of those, the script renders + validates only. --self-test is a
    # mutation gate because the script's own argv parser flips SEND_ALERT
    # to true on --self-test, which fires synthetic INFO + RECOVERY alerts
    # against the live On-Call REST endpoint.
    ("splunk-oncall-setup", "setup.sh"): (
        "--apply",
        "--send-alert",
        "--install-splunk-app",
        "--uninstall",
        "--self-test",
    ),
    ("splunk-oncall-setup", "splunk_side_install.sh"): (
        "--apply",
        "--uninstall",
    ),
    # otel-collector mutates with --apply-k8s / --apply-linux only.
    ("splunk-observability-otel-collector-setup", "setup.sh"): ("--apply-",),
    # splunk-observability-cloud-integration-setup mutates only when --apply,
    # --quickstart, --quickstart-enterprise, or --enable-token-auth is passed.
    # All other modes (--render, --validate, --doctor, --discover, --explain,
    # --rollback, --list-sim-templates, --make-default-deeplink) are
    # render/inspect-only.
    ("splunk-observability-cloud-integration-setup", "setup.sh"): (
        "--apply",
        "--quickstart",
        "--quickstart-enterprise",
        "--enable-token-auth",
    ),
    # SC4S / SC4SNMP mutate Splunk via --splunk-prep (creates indexes / HEC
    # tokens) and the host with --apply-host / --apply-k8s / --apply-compose.
    # Either gate triggers full mutation classification.
    ("splunk-connect-for-syslog-setup", "setup.sh"): (
        "--apply-",
        "--splunk-prep",
    ),
    ("splunk-connect-for-snmp-setup", "setup.sh"): (
        "--apply-",
        "--splunk-prep",
    ),
    # cisco-thousandeyes-mcp-setup, splunk-observability-thousandeyes-integration,
    # and cisco-isovalent-platform-setup expose --apply; the other five
    # observability-* integration wrappers only render manifests/helpers that
    # the operator applies separately (helm install, kubectl apply, etc.) and
    # therefore have no --apply flag in their argv parser. Listing those five
    # with the ("--apply",) sentinel is correct and intentional: the pattern
    # never matches an argv token they accept, so they are always classified
    # as read-only when invoked through the MCP wrapper. Keep the entry so
    # the (skill, script) pair is allowlisted explicitly and so adding a
    # future --apply mode to one of these scripts immediately re-enables the
    # mutation gate without code changes here.
    ("cisco-thousandeyes-mcp-setup", "setup.sh"): ("--apply",),
    ("splunk-observability-thousandeyes-integration", "setup.sh"): ("--apply",),
    ("cisco-isovalent-platform-setup", "setup.sh"): ("--apply",),
    ("splunk-observability-isovalent-integration", "setup.sh"): ("--apply",),
    ("splunk-observability-cisco-nexus-integration", "setup.sh"): ("--apply",),
    ("splunk-observability-cisco-intersight-integration", "setup.sh"): ("--apply",),
    ("splunk-observability-nvidia-gpu-integration", "setup.sh"): ("--apply",),
    ("splunk-observability-cisco-ai-pod-integration", "setup.sh"): ("--apply",),
    # splunk-observability-k8s-auto-instrumentation-setup mutates via the three
    # apply modes (--apply-instrumentation / --apply-annotations, both matched by
    # the --apply- prefix) and the uninstall mode. The --discover-workloads,
    # --render, --dry-run, --json, --explain, and --gitops-mode paths are read-only.
    ("splunk-observability-k8s-auto-instrumentation-setup", "setup.sh"): (
        "--apply-",
        "--uninstall-instrumentation",
    ),
}
# Scripts that are read-only by definition (their entire purpose is to inspect
# state). Validate scripts only check Splunk and never mutate it. The smoke_*
# helpers render to a temp directory and assert the rendered artifacts; they
# never touch live Splunk or the real filesystem outside their tmp tree.
READ_ONLY_SCRIPT_NAMES: set[str] = {
    "validate.sh",
    "list_apps.sh",
    "resolve_product.sh",
    "smoke_latest_resolution.sh",
    "smoke_offline.sh",
}

DIRECT_SECRET_FLAGS = {
    "--access-token",
    "--activation-code",
    "--admin-token",
    "--analytics-secret",
    "--api-key",
    "--api-secret",
    "--api-token",
    "--bearer-token",
    "--client-secret",
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
    "--proxy-password",
    "--pull-secret",
    "--refresh-token",
    "--rest-key",
    "--secret",
    "--service-account-password",
    "--skey",
    "--sf-token",
    # ThousandEyes bearer token rejected by cisco-thousandeyes-mcp-setup and
    # splunk-observability-thousandeyes-integration.
    "--te-token",
    "--token",
    "--vo-api-key",
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

SECRET_FILE_FLAGS = {
    "--access-token-file",
    "--activation-code-file",
    "--admin-token-file",
    "--analytics-secret-file",
    "--api-key-file",
    "--api-secret-file",
    "--api-token-file",
    "--automation-token-file",
    "--bearer-token-file",
    "--client-secret-file",
    "--cloudlock-token-file",
    "--discovery-secret-file",
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
    "--secret-file",
    "--service-account-password-file",
    "--shc-secret-file",
    "--snmpv3-secrets-file",
    "--soar-automation-token-file",
    "--splunk-cloud-admin-jwt-file",
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
    # Monotonic creation time; used by _consume_plan to enforce
    # PLAN_TTL_SECONDS so an old hash cannot be replayed indefinitely.
    # Defaulted via field(default_factory=) since this is a frozen dataclass.
    created_at: float = 0.0


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


def _matches_mutation_flag(args: list[str], patterns: tuple[str, ...]) -> bool:
    """Return True if any argv token matches a mutation flag pattern.

    Patterns ending in ``-`` are prefix matches (e.g. ``--apply-`` matches
    ``--apply-k8s``, ``--apply-host``, ``--apply-linux``). All other patterns
    must match the flag-only portion of the argv token exactly. The flag-only
    portion is the substring before ``=`` so that ``--flag=value`` forms are
    detected the same way as ``--flag value`` forms.
    """
    for arg in args:
        flag = arg.split("=", 1)[0] if arg.startswith("--") else arg
        for pattern in patterns:
            if pattern.endswith("-"):
                if flag.startswith(pattern):
                    return True
            elif flag == pattern:
                return True
    return False


def _phase_invocation_is_read_only(pair: tuple[str, str], args: list[str]) -> bool:
    # Flag-based mode skills: read-only whenever none of the configured
    # mutation flag patterns are present. Applies to skills that don't take
    # a --phase argument and instead gate live mutations behind one or more
    # explicit toggles (e.g. --apply, --apply-k8s, --splunk-prep).
    flag_patterns = READ_ONLY_UNLESS_FLAG_SCRIPTS.get(pair)
    if flag_patterns is not None:
        return not _matches_mutation_flag(args, flag_patterns)
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
        created_at=time.monotonic(),
    )
    with _PLANS_LOCK:
        # Re-storing the same hash refreshes recency (move to end) AND its
        # created_at timestamp, so the TTL clock restarts whenever the plan
        # is re-confirmed by a fresh planner call.
        if plan_hash in _PLANS:
            _PLANS.move_to_end(plan_hash)
        _PLANS[plan_hash] = plan
        # LRU eviction: drop the least-recently-used plan when over capacity.
        while len(_PLANS) > MAX_STORED_PLANS:
            _PLANS.popitem(last=False)
    return asdict(plan)


def _consume_plan(plan_hash: str) -> PlannedCommand | None:
    """Atomically remove and return a plan, or None if absent or expired.

    Plans are single-use: once a client invokes execute_plan with a valid
    hash, the plan is consumed regardless of whether the subprocess succeeds
    or fails. This prevents replay of destructive commands and serializes
    concurrent execute_plan calls for the same hash (only the first wins).

    Plans older than PLAN_TTL_SECONDS are also evicted on consume so a hash
    that was generated and then sat unused across a long pause cannot be
    silently applied later. Set MCP_PLAN_TTL_SECONDS=0 to disable.
    """
    with _PLANS_LOCK:
        plan = _PLANS.pop(plan_hash, None)
    if plan is None:
        return None
    if PLAN_TTL_SECONDS > 0 and time.monotonic() - plan.created_at > PLAN_TTL_SECONDS:
        # Treat an expired plan the same as a missing one: the operator must
        # re-run the planner step to get a fresh hash. The plan was already
        # popped above so there is nothing to clean up.
        return None
    return plan


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
        "-----BEGIN PRIVATE KEY-----[REDACTED]-----END PRIVATE KEY-----",
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
            r"(?i)("
            r"splunk[_-]?pass|splunk[_-]?password|sb[_-]?pass|sb[_-]?password|"
            r"password|passwd|pwd|secret|"
            r"api[_-]?key|api[_-]?secret|"
            r"client[_-]?secret|access[_-]?token|refresh[_-]?token|"
            r"bearer[_-]?token|hec[_-]?token|"
            r"auth[_-]?token|session[_-]?key|skey|ikey|"
            r"private[_-]?key"
            r")"
            r"(\s*[:=]\s*['\"]?)"
            r"[^\s'\",&]{6,}"
        ),
        r"\1\2[REDACTED]",
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
        files.append(primary)
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        files.extend(
            sorted(path for path in references_dir.glob("*.md") if path.is_file())
        )
    return files


# Maximum size of any individual template file aggregated into the
# skills://{skill}/template resource. Defends against a future skill
# that ships a very large fixture under templates/. Individual file reads
# via list_skill_template_files / read_skill_template_file are not
# bounded by this constant.
MAX_AGGREGATED_TEMPLATE_BYTES = 256 * 1024


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
        files.append(primary)
    templates_dir = skill_dir / "templates"
    if templates_dir.is_dir():
        for path in sorted(templates_dir.rglob("*")):
            if not path.is_file():
                continue
            if any(part.startswith(".") for part in path.relative_to(templates_dir).parts):
                continue
            files.append(path)
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
            return reference_files[0].read_text(encoding="utf-8")
        chunks = []
        for path in reference_files:
            rel_path = path.relative_to(skill_dir)
            text = path.read_text(encoding="utf-8")
            chunks.append(f"# {rel_path}\n\n{text}")
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
        for path in template_files:
            rel_path = path.relative_to(skill_dir)
            text = _read_bounded_text(path, MAX_AGGREGATED_TEMPLATE_BYTES)
            chunks.append(f"# {rel_path}\n\n{text}")
        return "\n\n".join(chunks)
    path = skill_dir / allowed[file_name]
    if not path.is_file():
        raise SkillMCPError(f"{skill} does not have {allowed[file_name]}")
    return path.read_text(encoding="utf-8")


def _read_bounded_text(path: Path, max_bytes: int) -> str:
    """Read a text file, truncating the body once max_bytes is exceeded.

    Falls back to ``utf-8`` decoding with ``replace`` errors so a binary
    blob accidentally checked into ``templates/`` does not crash the
    aggregation. The truncation marker preserves the operator's ability to
    notice that the file was clipped.
    """
    raw = path.read_bytes()
    if len(raw) <= max_bytes:
        return raw.decode("utf-8", errors="replace")
    return (
        raw[:max_bytes].decode("utf-8", errors="replace")
        + f"\n...[truncated {len(raw) - max_bytes} bytes from {path.name}]"
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
        "stdout": _truncate_and_redact(result.stdout),
        "stderr": _truncate_and_redact(result.stderr),
        "command": plan.command,
        "cwd": plan.cwd,
        "timed_out": result.timed_out,
    }
