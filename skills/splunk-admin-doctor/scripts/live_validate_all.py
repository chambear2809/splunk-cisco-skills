#!/usr/bin/env python3
"""Continuous live validation runner for the Splunk Cisco skills repo.

The runner is intentionally orchestration-only: it executes existing skill
entrypoints, captures sanitized evidence, and writes a resumable checkpoint
ledger. It never reads secret values directly from credentials. Splunk and
Observability credentials are loaded by the existing repo helpers or by
token-file paths from the credentials file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
DEFAULT_PROFILE = "onprem_2535"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-live-validation-runs"
FINAL_STATUSES = {"pass", "fixed-pass", "intentional-skip"}
READ_ONLY_MODE_FLAGS = (
    "--discover-metrics",
    "--discover",
    "--doctor",
    "--list-products",
    "--list-sim-templates",
    "--make-default-deeplink",
    "--render",
    "--status",
    "--validate",
)
ONPREM_LIVE_MODE_EXCLUDED_SKILLS = {
    "splunk-cloud-acs-admin-setup",
}
SPLUNK_REST_TIMEOUT_SECONDS = 90


SECRET_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/@\s]+)@"), r"\1[REDACTED]@"),
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "-----BEGIN PRIVATE KEY-----[REDACTED]-----END PRIVATE KEY-----",
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\b"), "[REDACTED-JWT]"),
    (
        re.compile(
            r"(?i)(Authorization\s*:\s*(?:Bearer|Basic|Splunk|Token|Digest|MAC)\s+)"
            r"[A-Za-z0-9+/=._\-]{6,}"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)(sessionKey\s*[:=]\s*)[A-Za-z0-9._\-]{6,}"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)("
            r"splunk[_-]?pass|splunk[_-]?password|sb[_-]?pass|sb[_-]?password|"
            r"password|passwd|pwd|credential|credentials|secret|sslpassword|"
            r"privatekeypassword|pass4symmkey|"
            r"api[_-]?key|api[_-]?secret|client[_-]?secret|"
            r"access[_-]?token|refresh[_-]?token|bearer[_-]?token|"
            r"hec[_-]?token|auth[_-]?token|session[_-]?key|skey|ikey|"
            r"private[_-]?key"
            r")"
            r"(\s*[:=]\s*['\"]?)"
            r"[^\s'\",&]{6,}"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)("
            r"\"(?:password|credential|credentials|secret|token|authToken|auth_token|apiKey|api_key|clientSecret|client_secret|sessionKey|sslPassword|privateKeyPassword|pass4SymmKey)\""
            r"\s*:\s*\")([^\"]{6,})(\")"
        ),
        r"\1[REDACTED]\3",
    ),
)


SPLUNK_REST_PROBE_SCRIPT = r"""
set -euo pipefail
source skills/shared/lib/credential_helpers.sh
load_splunk_credentials >/dev/null
endpoint="$1"
case "${endpoint}" in
  /services/*|/servicesNS/*) ;;
  *) echo "ERROR: endpoint must begin with /services/ or /servicesNS/" >&2; exit 2 ;;
esac
SK="$(get_session_key "${SPLUNK_URI}")"
splunk_curl "${SK}" "${SPLUNK_URI}${endpoint}"
"""


SPLUNK_PROFILE_METADATA_SCRIPT = r"""
set -euo pipefail
source skills/shared/lib/credential_helpers.sh
load_splunk_connection_settings >/dev/null
load_splunk_platform_settings >/dev/null || true
cat <<EOF
{
  "profile": "${SPLUNK_PROFILE:-}",
  "platform": "${SPLUNK_PLATFORM:-}",
  "target_role": "${SPLUNK_TARGET_ROLE:-}",
  "search_target_role": "${SPLUNK_SEARCH_TARGET_ROLE:-}",
  "splunk_uri": "${SPLUNK_URI:-}",
  "verify_ssl": "${SPLUNK_VERIFY_SSL:-true}",
  "o11y_realm_present": "$(if [[ -n "${SPLUNK_O11Y_REALM:-}" ]]; then printf true; else printf false; fi)",
  "o11y_token_file_present": "$(if [[ -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then printf true; else printf false; fi)"
}
EOF
"""


SSH_SPLUNK_CLI_SCRIPT = r"""
set -euo pipefail
source skills/shared/lib/credential_helpers.sh
source skills/shared/lib/host_bootstrap_helpers.sh
service_user="${1:-splunk}"
shift
raw_cmd="$*"
if [[ -z "${raw_cmd}" ]]; then
  echo "ERROR: remote command is required" >&2
  exit 2
fi
hbs_capture_as_user_cmd ssh "${service_user}" "${raw_cmd}"
"""


O11Y_PROBE_SCRIPT = r"""
set -euo pipefail
source skills/shared/lib/credential_helpers.sh
load_observability_cloud_settings >/dev/null
if [[ -z "${SPLUNK_O11Y_REALM:-}" ]]; then
  echo '{"ok":false,"reason":"missing SPLUNK_O11Y_REALM"}'
  exit 2
fi
if [[ -z "${SPLUNK_O11Y_TOKEN_FILE:-}" || ! -f "${SPLUNK_O11Y_TOKEN_FILE:-}" || -L "${SPLUNK_O11Y_TOKEN_FILE:-}" || ! -r "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
  echo '{"ok":false,"reason":"missing, unreadable, or symlink SPLUNK_O11Y_TOKEN_FILE"}'
  exit 2
fi
mode="$(stat -f '%A' "${SPLUNK_O11Y_TOKEN_FILE}" 2>/dev/null || stat -c '%a' "${SPLUNK_O11Y_TOKEN_FILE}")"
if [[ "${mode}" != "600" ]]; then
  echo "{\"ok\":false,\"reason\":\"token file permissions are ${mode}, expected 600\"}"
  exit 2
fi
url="https://api.${SPLUNK_O11Y_REALM}.observability.splunkcloud.com/v2/organization"
body_file="$(mktemp "${TMPDIR:-/tmp}/codex-o11y-live-validation.XXXXXX")"
token_value="$(cat "${SPLUNK_O11Y_TOKEN_FILE}")"
if [[ -z "${token_value}" || "${token_value}" == *$'\n'* || "${token_value}" == *$'\r'* ]]; then
  echo '{"ok":false,"reason":"empty or multiline SPLUNK_O11Y_TOKEN_FILE"}'
  exit 2
fi
token_value="${token_value//\\/\\\\}"
token_value="${token_value//\"/\\\"}"
trap 'rm -f "${body_file}"' EXIT
http_code="$(
  curl -sS --connect-timeout 10 --max-time 30 \
    -K <(printf 'header = "X-SF-Token: %s"\n' "${token_value}") \
    -o "${body_file}" \
    -w '%{http_code}' \
    "${url}" || true
)"
unset token_value
body="$(head -c 4096 "${body_file}" 2>/dev/null || true)"
rm -f "${body_file}"
trap - EXIT
python3 - "${http_code}" "${SPLUNK_O11Y_REALM}" <<'PY'
import json
import sys

http_code = sys.argv[1]
realm = sys.argv[2]
ok = http_code.startswith("2")
print(json.dumps({"ok": ok, "realm": realm, "http_code": http_code}))
sys.exit(0 if ok else 1)
PY
"""


@dataclass
class ValidationStep:
    step_id: str
    category: str
    command: list[str]
    skill: str = ""
    mode: str = ""
    read_only: bool = True
    mutates: bool = False
    required: bool = True
    timeout_seconds: int = 180
    final_on_failure: str = "fail"
    skip_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    step_id: str
    category: str
    skill: str
    mode: str
    status: str
    command: str
    read_only: bool
    mutates: bool
    returncode: int | None
    started_at: str
    ended_at: str
    duration_seconds: float
    stdout_log: str = ""
    stderr_log: str = ""
    classification: str = ""
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "item"


def shell_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def redact(value: str) -> str:
    if not value:
        return value
    redacted = value
    for pattern, replacement in SECRET_REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            # Do not redact whole checkpoint rows just because a step id
            # contains words like "token". Secret-bearing field names are
            # simple keys; path-like or id-like keys are structural.
            structural_key = ":" in key_text or "/" in key_text
            normalized_key = re.sub(r"[^a-z0-9]", "", key_text.lower())
            if not structural_key and normalized_key in {
                "password", "passwd", "pwd", "credential", "credentials", "secret",
                "token", "authtoken", "accesstoken", "refreshtoken", "sessionkey",
                "privatekey", "privatekeypassword", "apikey", "apisecret", "clientsecret",
                "sslpassword", "pass4symmkey", "hectoken",
            }:
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_obj(item)
        return out
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def write_text_secure(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    path.chmod(0o600)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    write_text_secure(temporary, json.dumps(redact_obj(payload), indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)
    path.chmod(0o600)


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_obj(payload), sort_keys=True) + "\n")
    path.chmod(0o600)


def skill_dirs() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_DIR.iterdir()
        if path.is_dir() and path.name != "shared" and (path / "SKILL.md").is_file()
    )


def script_path(skill: str, script: str) -> Path:
    path = SKILLS_DIR / skill / "scripts" / script
    if not path.is_file():
        raise FileNotFoundError(f"{skill} has no scripts/{script}")
    return path


def script_command(skill: str, script: str, args: list[str] | None = None) -> list[str]:
    path = script_path(skill, script)
    rel = path.relative_to(REPO_ROOT).as_posix()
    suffix = path.suffix.lower()
    base = ["python3", rel] if suffix == ".py" else ["bash", rel]
    return [*base, *(args or [])]


def has_script(skill: str, script: str) -> bool:
    return (SKILLS_DIR / skill / "scripts" / script).is_file()


def output_dir_arg_supported(skill: str, script: str = "setup.sh") -> bool:
    path = SKILLS_DIR / skill / "scripts" / script
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(re.search(r"(?m)^\s*--output-dir(?:\s|,|$)", text))


def flag_supported(text: str, flag: str) -> bool:
    escaped = re.escape(flag)
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){escaped}(?![A-Za-z0-9_-])", text))


def phase_supported(text: str, phase: str) -> bool:
    for line in text.splitlines():
        if "--phase" not in line:
            continue
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(phase)}(?![A-Za-z0-9_-])", line):
            return True
    return False


def default_spec_for_skill(skill: str) -> Path | None:
    skill_dir = SKILLS_DIR / skill
    direct = skill_dir / "template.example"
    if direct.is_file():
        return direct
    templates_dir = skill_dir / "templates"
    if not templates_dir.is_dir():
        return None
    for pattern in ("*.example.json", "*.example.yaml", "*.example.yml", "*.json", "*.yaml", "*.yml"):
        matches = sorted(path for path in templates_dir.glob(pattern) if path.is_file())
        if matches:
            return matches[0]
    return None


def script_mentions(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def command_uses_direct_secret(argv: list[str]) -> bool:
    direct_flags = {
        "--access-token",
        "--admin-token",
        "--api-key",
        "--api-secret",
        "--api-token",
        "--bearer-token",
        "--client-secret",
        "--hec-token",
        "--o11y-token",
        "--on-call-api-key",
        "--password",
        "--secret",
        "--sf-token",
        "--token",
    }
    for item in argv:
        flag = item.split("=", 1)[0] if item.startswith("--") else item
        if flag in direct_flags:
            return True
    return False


def validation_env(profile: str) -> dict[str, str]:
    env = os.environ.copy()
    env["SPLUNK_PROFILE"] = profile
    env["PYTHONUNBUFFERED"] = "1"
    env["SPLUNK_SKILLS_LIVE_VALIDATION"] = "1"
    return env


def run_command(
    argv: list[str],
    *,
    profile: str,
    timeout_seconds: int,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    if command_uses_direct_secret(argv):
        raise ValueError(f"Refusing command with direct secret-bearing argv: {shell_join(argv)}")
    return subprocess.run(
        argv,
        cwd=cwd,
        env=validation_env(profile),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )


def classify_failure(step: ValidationStep, returncode: int | None, stdout: str, stderr: str) -> str:
    text = f"{stdout}\n{stderr}".lower()
    if returncode is None:
        return "timeout"
    if returncode == 255 and not text.strip():
        return "live_environment_constraint"
    if "invalid key in stanza" in text or "no spec file for:" in text:
        return "live_environment_constraint"
    if (
        "could not authenticate" in text
        or "authentication failed" in text
        or "401 unauthorized" in text
        or re.search(r"\bhttp\s+401\b", text)
    ):
        return "credentials_profile_issue"
    if "403" in text or "forbidden" in text or "permission" in text or "capability" in text:
        return "live_environment_constraint"
    if (
        "nodename nor servname provided" in text
        or "could not resolve host" in text
        or "connection refused" in text
        or "timed out" in text
    ):
        return "live_environment_constraint"
    if "command not found" in text or "unknown option" in text:
        return "code_bug"
    if "not found" in text or "does not exist" in text or "no such file or directory" in text:
        return "expected_missing_external_dependency"
    if "rendered script is missing" in text or "checking universal forwarder" in text:
        return "expected_missing_external_dependency"
    if (
        "is required" in text
        or "required for" in text
        or "require explicit" in text
        or "requires explicit" in text
        or "must be readable" in text
    ):
        return "expected_missing_external_dependency"
    if returncode and text.strip().startswith("rendered ") and "error" not in text:
        return "expected_missing_external_dependency"
    return "unclassified_failure"


def should_intentional_skip(step: ValidationStep, classification: str) -> bool:
    skippable = {
        "expected_missing_external_dependency",
        "live_environment_constraint",
        "credentials_profile_issue",
    }
    if step.final_on_failure == "intentional-skip" and classification in skippable:
        return True
    if not step.required and classification in skippable:
        return True
    return False


def execute_step(
    step: ValidationStep,
    *,
    profile: str,
    run_dir: Path,
    ledger_path: Path,
    quiet: bool,
) -> StepResult:
    started = utc_now()
    start_monotonic = time.monotonic()
    stdout_log = run_dir / "logs" / f"{safe_name(step.step_id)}.stdout.log"
    stderr_log = run_dir / "logs" / f"{safe_name(step.step_id)}.stderr.log"
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log.parent.mkdir(parents=True, exist_ok=True)

    if step.skip_reason:
        result = StepResult(
            step_id=step.step_id,
            category=step.category,
            skill=step.skill,
            mode=step.mode,
            status="intentional-skip",
            command=shell_join(step.command),
            read_only=step.read_only,
            mutates=step.mutates,
            returncode=None,
            started_at=started,
            ended_at=utc_now(),
            duration_seconds=0.0,
            classification="expected_missing_external_dependency",
            notes=[step.skip_reason],
            metadata=step.metadata,
        )
        append_jsonl(ledger_path, asdict(result))
        return result

    timed_out = False
    returncode: int | None
    stdout = ""
    stderr = ""
    try:
        completed = run_command(
            step.command,
            profile=profile,
            timeout_seconds=step.timeout_seconds,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        returncode = None
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
    except Exception as exc:  # noqa: BLE001 - keep the runner alive.
        returncode = 99
        stderr = f"{type(exc).__name__}: {exc}"

    stdout_redacted = redact(stdout)
    stderr_redacted = redact(stderr)
    write_text_secure(stdout_log, stdout_redacted)
    write_text_secure(stderr_log, stderr_redacted)

    classification = "" if returncode == 0 else classify_failure(step, returncode, stdout, stderr)
    if returncode == 0:
        status = "pass"
    elif should_intentional_skip(step, classification):
        status = "intentional-skip"
    else:
        status = "fail"

    notes: list[str] = []
    if timed_out:
        notes.append(f"Timed out after {step.timeout_seconds}s.")
    if status == "intentional-skip" and not notes:
        notes.append(f"Classified as {classification}; no repo fix is appropriate without more live configuration.")

    result = StepResult(
        step_id=step.step_id,
        category=step.category,
        skill=step.skill,
        mode=step.mode,
        status=status,
        command=shell_join(step.command),
        read_only=step.read_only,
        mutates=step.mutates,
        returncode=returncode,
        started_at=started,
        ended_at=utc_now(),
        duration_seconds=round(time.monotonic() - start_monotonic, 3),
        stdout_log=str(stdout_log.relative_to(run_dir)),
        stderr_log=str(stderr_log.relative_to(run_dir)),
        classification=classification,
        notes=notes,
        metadata=step.metadata,
    )
    append_jsonl(ledger_path, asdict(result))
    if not quiet:
        label = step.step_id
        print(f"[{result.status}] {label} ({result.duration_seconds:.1f}s)")
    return result


def parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if result.returncode != 0:
        return {}
    text = redact(result.stdout.strip())
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some Splunk endpoints can emit warnings before JSON. Try the last
        # JSON object in the stream before giving up.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return {}
    return {}


def parse_splunk_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("entry", [])
    return entries if isinstance(entries, list) else []


def rest_probe(endpoint: str, *, profile: str, timeout_seconds: int = SPLUNK_REST_TIMEOUT_SECONDS) -> tuple[dict[str, Any], int]:
    result = run_command(
        ["bash", "-c", SPLUNK_REST_PROBE_SCRIPT, "splunk-rest-probe", endpoint],
        profile=profile,
        timeout_seconds=timeout_seconds,
    )
    return parse_json_output(result), result.returncode


def ssh_cli_probe(
    remote_command: str,
    *,
    profile: str,
    service_user: str = "splunk",
    timeout_seconds: int = SPLUNK_REST_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    result = run_command(
        ["bash", "-c", SSH_SPLUNK_CLI_SCRIPT, "ssh-splunk-cli", service_user, remote_command],
        profile=profile,
        timeout_seconds=timeout_seconds,
    )
    return redact(result.stdout), redact(result.stderr), result.returncode


def profile_metadata(profile: str) -> dict[str, Any]:
    result = run_command(
        ["bash", "-c", SPLUNK_PROFILE_METADATA_SCRIPT, "splunk-profile-metadata"],
        profile=profile,
        timeout_seconds=60,
    )
    return parse_json_output(result)


def nested_status_findings(value: Any, prefix: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            normalized_key = str(key).lower()
            normalized_value = str(child).strip().lower() if not isinstance(child, (dict, list)) else ""
            if normalized_value in {"red", "yellow", "degraded", "failed", "down", "unhealthy"}:
                findings.append(f"{path}={child}")
            if normalized_key in {"replication_factor_met", "search_factor_met", "service_ready", "is_healthy"} and child is False:
                findings.append(f"{path}=false")
            findings.extend(nested_status_findings(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(nested_status_findings(child, f"{prefix}[{index}]"))
    return findings


def nested_bool(value: Any, candidate_keys: set[str]) -> bool | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in candidate_keys:
                if isinstance(child, bool):
                    return child
                if str(child).strip().lower() in {"true", "1", "yes"}:
                    return True
                if str(child).strip().lower() in {"false", "0", "no"}:
                    return False
            nested = nested_bool(child, candidate_keys)
            if nested is not None:
                return nested
    elif isinstance(value, list):
        for child in value:
            nested = nested_bool(child, candidate_keys)
            if nested is not None:
                return nested
    return None


def collect_live_evidence(
    profile: str,
    run_dir: Path,
    requested_platform: str = "auto",
) -> dict[str, Any]:
    metadata = profile_metadata(profile)
    declared_platform = str(metadata.get("platform", "")).strip().lower()
    platform = requested_platform if requested_platform in {"cloud", "enterprise"} else (
        "cloud" if "cloud" in declared_platform else "enterprise"
    )
    evidence: dict[str, Any] = {
        "platform": platform,
        "collection": {
            "profile": profile,
            "collected_at": utc_now(),
            "notes": [],
        },
        "rest": {
            "reachable": None,
            "denied": None,
            "tls_verified": str(metadata.get("verify_ssl", "true")).lower() not in {"0", "false", "no"},
        },
        "inputs": {
            "splunk_uri": metadata.get("splunk_uri", ""),
            "target_role": metadata.get("target_role", ""),
        },
    }

    endpoints = {
        "server_info": "/services/server/info?output_mode=json",
        "server_sysinfo": "/services/server/sysinfo?output_mode=json",
        "apps": "/services/apps/local?output_mode=json&count=0",
        "indexes": "/services/data/indexes?output_mode=json&count=0",
        "hec": "/services/data/inputs/http?output_mode=json&count=0",
        "license_messages": "/services/licenser/messages?output_mode=json&count=0",
        "splunkd_health": "/services/server/health/splunkd?output_mode=json",
        "kvstore": "/services/kvstore/status?output_mode=json",
        "saved_searches": "/servicesNS/-/-/saved/searches?output_mode=json&count=0",
        "distsearch": "/services/search/distributed/peers?output_mode=json&count=0",
        "shc": "/services/shcluster/status?output_mode=json",
        "indexer_cluster": "/services/cluster/manager/info?output_mode=json",
    }
    raw: dict[str, Any] = {}
    for name, endpoint in endpoints.items():
        payload, returncode = rest_probe(endpoint, profile=profile)
        raw[name] = {"returncode": returncode, "payload": payload}
        if returncode != 0:
            evidence["collection"]["notes"].append(f"{name} endpoint returned {returncode}.")

    required_probe_codes = [raw[name]["returncode"] for name in ("server_info", "server_sysinfo", "apps")]
    evidence["rest"]["reachable"] = any(code == 0 for code in required_probe_codes)
    evidence["rest"]["denied"] = False if all(code == 0 for code in required_probe_codes) else None
    evidence["rest"]["probe_errors"] = [
        name for name in ("server_info", "server_sysinfo", "apps") if raw[name]["returncode"] != 0
    ]

    probe_summary = {
        name: {
            "returncode": item["returncode"],
            "entry_count": len(parse_splunk_entries(item.get("payload", {}))),
            "response_present": bool(item.get("payload")),
        }
        for name, item in raw.items()
    }
    write_json(run_dir / "evidence" / "splunk-rest-probes.redacted.json", probe_summary)

    server_entries = parse_splunk_entries(raw["server_info"].get("payload", {}))
    if server_entries:
        content = server_entries[0].get("content", {})
        evidence["server"] = {
            "name": content.get("serverName") or server_entries[0].get("name", ""),
            "version": content.get("version", ""),
            "build": content.get("build", ""),
            "server_roles": content.get("server_roles", []),
        }

    app_entries = parse_splunk_entries(raw["apps"].get("payload", {}))
    apps = []
    restart_required = []
    for entry in app_entries:
        name = str(entry.get("name", ""))
        content = entry.get("content", {})
        apps.append(
            {
                "name": name,
                "version": content.get("version", ""),
                "disabled": content.get("disabled", False),
                "visible": content.get("visible", True),
            }
        )
        if content.get("restart_required"):
            restart_required.append(name)
    evidence["apps"] = {"installed": apps, "restart_required": restart_required}

    index_entries = parse_splunk_entries(raw["indexes"].get("payload", {}))
    evidence["indexes"] = {
        "present": sorted(entry.get("name", "") for entry in index_entries if entry.get("name")),
    }

    hec_entries = parse_splunk_entries(raw["hec"].get("payload", {}))
    if raw["hec"]["returncode"] != 0:
        evidence["hec"] = {"enabled": None, "assessed": False, "token_count": None}
    elif hec_entries:
        # The global HEC endpoint usually appears as http. If every stanza is
        # disabled, call the HEC service unavailable.
        disabled_values = [entry.get("content", {}).get("disabled") for entry in hec_entries]
        hec_disabled = all(str(value).lower() in {"1", "true"} for value in disabled_values)
        evidence["hec"] = {"enabled": not hec_disabled, "assessed": True, "token_count": len(hec_entries)}
    else:
        evidence["hec"] = {"enabled": False, "assessed": True, "token_count": 0}

    health_payload = raw["splunkd_health"].get("payload", {})
    health_entries = parse_splunk_entries(health_payload)
    health_status = ""
    failures: list[str] = []
    if health_entries:
        health_content = health_entries[0].get("content", {})
        health_status = str(
            health_content.get("health") or health_content.get("status") or health_content.get("color") or ""
        ).lower()
        for key, value in health_content.items():
            if isinstance(value, str) and value.lower() in {"red", "yellow", "degraded", "failed"}:
                failures.append(f"{key}={value}")
    evidence["splunkd"] = {"health": {"status": health_status or "unknown", "failures": failures}}

    kv_payload = raw["kvstore"].get("payload", {})
    kv_entries = parse_splunk_entries(kv_payload)
    kv_status = "unknown"
    if kv_entries:
        kv_content = kv_entries[0].get("content", {})
        kv_status = str(kv_content.get("current", {}).get("status") or kv_content.get("status") or "unknown").lower()
    evidence["kvstore"] = {"status": kv_status}

    license_entries = parse_splunk_entries(raw["license_messages"].get("payload", {}))
    violation_messages = []
    for entry in license_entries:
        content = entry.get("content", {})
        classification = " ".join(
            str(content.get(key, "")) for key in ("category", "severity", "type", "message")
        ).lower()
        if any(marker in classification for marker in ("violation", "error", "exceeded")):
            violation_messages.append(entry.get("name", ""))
    evidence["license"] = {
        "messages": violation_messages,
        "violation_count": len(violation_messages),
        "message_count": len(license_entries),
    }

    # Saved-search metadata does not prove scheduler skips. Leave the skip
    # signal explicitly unassessed unless scheduler/internal-log evidence is supplied.
    evidence["scheduler"] = {"skipped_count": None, "skipped_searches": None}

    peer_entries = parse_splunk_entries(raw["distsearch"].get("payload", {}))
    peers_down = []
    for entry in peer_entries:
        content = entry.get("content", {})
        status = str(content.get("status") or content.get("server_status") or "").lower()
        if status and status not in {"up", "healthy", "ok"}:
            peers_down.append(entry.get("name", ""))
    evidence["distributed_search"] = {"peers_down": peers_down}

    shc_rc = raw["shc"]["returncode"]
    if shc_rc == 0:
        shc_payload = raw["shc"].get("payload", {})
        shc_issues = nested_status_findings(shc_payload)
        replication_healthy = nested_bool(shc_payload, {"replication_healthy", "is_healthy", "service_ready"})
        evidence["shc"] = {
            "status": "degraded" if shc_issues else "healthy",
            "issues": shc_issues,
            "replication_healthy": replication_healthy,
        }
    else:
        evidence["shc"] = {"status": "not_assessed", "issues": None}
    idxc_rc = raw["indexer_cluster"]["returncode"]
    if idxc_rc == 0:
        idxc_payload = raw["indexer_cluster"].get("payload", {})
        idxc_issues = nested_status_findings(idxc_payload)
        evidence["indexer_cluster"] = {
            "status": "degraded" if idxc_issues else "healthy",
            "issues": idxc_issues,
            "rf_met": nested_bool(idxc_payload, {"replication_factor_met", "rf_met"}),
            "sf_met": nested_bool(idxc_payload, {"search_factor_met", "sf_met"}),
        }
    else:
        evidence["indexer_cluster"] = {"status": "not_assessed", "issues": None}

    evidence["monitoring_console"] = {
        "installed": any(app["name"] == "splunk_monitoring_console" and not app["disabled"] for app in apps),
        "configured": None,
        "platform_alerts_enabled": None,
    }
    evidence["support"] = {"diag_ready": True, "diag_blockers": []}
    evidence["backup"] = {"last_config_backup_stale": None}
    evidence["security"] = {
        "local_tls_verification_disabled": not evidence["rest"]["tls_verified"],
    }

    remote_summary: dict[str, Any] = {"enabled": platform == "enterprise", "checks": {}}
    if platform != "enterprise":
        remote_summary["reason"] = "Enterprise SSH probes are not applicable to a Cloud profile."
        evidence["remote_splunk_home"] = remote_summary
        write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)
        return evidence
    version_out, version_err, version_rc = ssh_cli_probe(
        "hostname; test -x /opt/splunk/bin/splunk; /opt/splunk/bin/splunk version",
        profile=profile,
        timeout_seconds=90,
    )
    remote_summary["checks"]["version"] = {
        "returncode": version_rc,
        "stdout_tail": version_out[-2000:],
        "stderr_tail": version_err[-2000:],
    }
    if version_rc == 0:
        lines = [line.strip() for line in version_out.splitlines() if line.strip()]
        if lines:
            remote_summary["host"] = lines[0]
        if len(lines) > 1:
            remote_summary["splunk_version"] = lines[-1]
    else:
        evidence["collection"]["notes"].append("Remote SSH Splunk version check failed.")

    btool_out, btool_err, btool_rc = ssh_cli_probe(
        "/opt/splunk/bin/splunk btool check --debug",
        profile=profile,
        timeout_seconds=180,
    )
    remote_summary["checks"]["btool_check"] = {
        "returncode": btool_rc,
        "stdout_tail": btool_out[-4000:],
        "stderr_tail": btool_err[-4000:],
    }
    evidence["btool"] = {
        "errors": [] if btool_rc == 0 else [(btool_err or btool_out)[-4000:]],
    }

    health_log_out, health_log_err, health_log_rc = ssh_cli_probe(
        "test -f /opt/splunk/var/log/splunk/health.log && tail -n 200 /opt/splunk/var/log/splunk/health.log || true",
        profile=profile,
        timeout_seconds=90,
    )
    remote_summary["checks"]["health_log_tail"] = {
        "returncode": health_log_rc,
        "stdout_tail": health_log_out[-8000:],
        "stderr_tail": health_log_err[-2000:],
    }
    if health_log_out:
        evidence.setdefault("splunkd", {})["health_log_tail"] = health_log_out[-8000:]

    diag_out, diag_err, diag_rc = ssh_cli_probe(
        "test -x /opt/splunk/bin/splunk && /opt/splunk/bin/splunk diag --help >/dev/null",
        profile=profile,
        timeout_seconds=90,
    )
    remote_summary["checks"]["diag_help"] = {
        "returncode": diag_rc,
        "stdout_tail": diag_out[-1000:],
        "stderr_tail": diag_err[-2000:],
    }
    if diag_rc != 0:
        evidence["support"] = {
            "diag_ready": False,
            "diag_blockers": [(diag_err or diag_out)[-2000:]],
        }

    evidence["remote_splunk_home"] = remote_summary

    write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)
    return evidence


def build_baseline_steps(
    profile: str,
    run_dir: Path,
    platform: str = "enterprise",
) -> list[ValidationStep]:
    endpoints = {
        "server-info": "/services/server/info?output_mode=json",
        "server-sysinfo": "/services/server/sysinfo?output_mode=json",
        "apps": "/services/apps/local?output_mode=json&count=0",
        "indexes": "/services/data/indexes?output_mode=json&count=0",
        "hec": "/services/data/inputs/http?output_mode=json&count=0",
        "license": "/services/licenser/messages?output_mode=json&count=0",
        "splunkd-health": "/services/server/health/splunkd?output_mode=json",
        "kvstore": "/services/kvstore/status?output_mode=json",
        "saved-searches": "/servicesNS/-/-/saved/searches?output_mode=json&count=0",
        "distsearch": "/services/search/distributed/peers?output_mode=json&count=0",
        "shc": "/services/shcluster/status?output_mode=json",
        "idxc": "/services/cluster/manager/info?output_mode=json",
    }
    steps = [
        ValidationStep(
            step_id="baseline-profile-metadata",
            category="baseline",
            command=["bash", "-c", SPLUNK_PROFILE_METADATA_SCRIPT, "splunk-profile-metadata"],
            mode="profile-metadata",
            timeout_seconds=60,
        ),
        ValidationStep(
            step_id="baseline-installed-apps-list",
            category="baseline",
            skill="splunk-app-install",
            command=script_command("splunk-app-install", "list_apps.sh"),
            mode="list-apps",
            timeout_seconds=180,
        ),
        ValidationStep(
            step_id="baseline-o11y-api",
            category="baseline",
            command=["bash", "-c", O11Y_PROBE_SCRIPT, "o11y-probe"],
            mode="o11y-probe",
            timeout_seconds=90,
            required=False,
            final_on_failure="intentional-skip",
        ),
    ]
    if platform == "enterprise":
        steps.extend(
            [
                ValidationStep(
                    step_id="baseline-ssh-splunk-version",
                    category="baseline",
                    command=["bash", "-c", SSH_SPLUNK_CLI_SCRIPT, "ssh-splunk-cli", "splunk", "hostname; test -x /opt/splunk/bin/splunk; /opt/splunk/bin/splunk version"],
                    mode="ssh:splunk-version",
                    timeout_seconds=90,
                ),
                ValidationStep(
                    step_id="baseline-ssh-splunk-status",
                    category="baseline",
                    command=["bash", "-c", SSH_SPLUNK_CLI_SCRIPT, "ssh-splunk-cli", "splunk", "/opt/splunk/bin/splunk status"],
                    mode="ssh:splunk-status",
                    timeout_seconds=90,
                ),
                ValidationStep(
                    step_id="baseline-ssh-btool-check",
                    category="baseline",
                    command=["bash", "-c", SSH_SPLUNK_CLI_SCRIPT, "ssh-splunk-cli", "splunk", "/opt/splunk/bin/splunk btool check --debug"],
                    mode="ssh:btool-check",
                    timeout_seconds=180,
                    required=False,
                    final_on_failure="intentional-skip",
                ),
            ]
        )
    for label, endpoint in endpoints.items():
        required = label in {"server-info", "server-sysinfo", "apps"}
        steps.append(
            ValidationStep(
                step_id=f"baseline-rest-{label}",
                category="baseline",
                command=["bash", "-c", SPLUNK_REST_PROBE_SCRIPT, "splunk-rest-probe", endpoint],
                mode=f"rest:{endpoint}",
                timeout_seconds=SPLUNK_REST_TIMEOUT_SECONDS,
                required=required,
                final_on_failure="fail" if required else "intentional-skip",
            )
        )
    return steps


def read_only_mode_steps(
    skill: str,
    run_dir: Path,
    platform: str = "enterprise",
) -> list[ValidationStep]:
    steps: list[ValidationStep] = []
    live_modes_excluded = platform == "enterprise" and skill in ONPREM_LIVE_MODE_EXCLUDED_SKILLS
    if has_script(skill, "setup.sh"):
        steps.append(
            ValidationStep(
                step_id=f"{skill}:setup-help",
                category="read-only",
                skill=skill,
                command=script_command(skill, "setup.sh", ["--help"]),
                mode="setup-help",
                timeout_seconds=60,
            )
        )
    elif skill == "splunk-app-install":
        for script in ("list_apps.sh", "install_app.sh", "uninstall_app.sh"):
            if has_script(skill, script):
                steps.append(
                    ValidationStep(
                        step_id=f"{skill}:{script}-help",
                        category="read-only",
                        skill=skill,
                        command=script_command(skill, script, ["--help"]),
                        mode=f"{script}-help",
                        timeout_seconds=60,
                    )
                )
    if has_script(skill, "validate.sh"):
        steps.append(
            ValidationStep(
                step_id=f"{skill}:validate-help",
                category="read-only",
                skill=skill,
                command=script_command(skill, "validate.sh", ["--help"]),
                mode="validate-help",
                timeout_seconds=60,
            )
        )
    if has_script(skill, "smoke_offline.sh"):
        steps.append(
            ValidationStep(
                step_id=f"{skill}:smoke-offline",
                category="read-only",
                skill=skill,
                command=script_command(skill, "smoke_offline.sh"),
                mode="smoke-offline",
                timeout_seconds=360,
                required=False,
            )
        )
    if has_script(skill, "setup.sh") and not live_modes_excluded:
        setup = SKILLS_DIR / skill / "scripts" / "setup.sh"
        text = setup.read_text(encoding="utf-8", errors="replace")
        output_dir = run_dir / "rendered" / skill
        if "--phase" in text:
            for phase in ("preflight", "validate", "status"):
                if skill == "splunk-admin-doctor" and phase == "status":
                    continue
                if phase_supported(text, phase):
                    args = ["--phase", phase]
                    if phase == "preflight" and flag_supported(text, "--dry-run"):
                        args.append("--dry-run")
                    if output_dir_arg_supported(skill):
                        args += ["--output-dir", str(output_dir)]
                    steps.append(
                        ValidationStep(
                            step_id=f"{skill}:phase-{phase}",
                            category="read-only",
                            skill=skill,
                            command=script_command(skill, "setup.sh", args),
                            mode=f"phase:{phase}",
                            timeout_seconds=240,
                            required=False,
                            final_on_failure="intentional-skip",
                        )
                    )
        else:
            for flag in READ_ONLY_MODE_FLAGS:
                if flag_supported(text, flag):
                    args = [flag]
                    if output_dir_arg_supported(skill):
                        args += ["--output-dir", str(output_dir)]
                    if "--spec" in text and flag in {"--render", "--validate"}:
                        template = default_spec_for_skill(skill)
                        if template is not None:
                            args += ["--spec", str(template)]
                    steps.append(
                        ValidationStep(
                            step_id=f"{skill}:{flag.lstrip('-')}",
                            category="read-only",
                            skill=skill,
                            command=script_command(skill, "setup.sh", args),
                            mode=flag,
                            timeout_seconds=240,
                            required=False,
                            final_on_failure="intentional-skip",
                        )
                    )
                    break
    return steps


def build_apply_steps(
    run_dir: Path,
    allow_apply: bool,
    platform: str = "enterprise",
) -> list[ValidationStep]:
    if not allow_apply:
        return []
    output_root = run_dir / "apply-rendered"
    # Live mutation smokes are intentionally disabled. The former MC, HEC,
    # WLM, and Observability workflows could overwrite pre-existing state and
    # did not provide byte-for-byte rollback. Keep --allow-apply bounded to a
    # local fix-plan render until target-bound snapshots and cleanup-finally
    # semantics are implemented and tested.
    return [
        ValidationStep(
            step_id="splunk-admin-doctor:render-fix-plan",
            category="apply",
            skill="splunk-admin-doctor",
            command=script_command(
                "splunk-admin-doctor",
                "setup.sh",
                [
                    "--phase",
                    "fix-plan",
                    "--platform",
                    platform,
                    "--evidence-file",
                    str(run_dir / "evidence" / "live-evidence.redacted.json"),
                    "--output-dir",
                    str(output_root / "splunk-admin-doctor"),
                    "--json",
                ],
            ),
            mode="render-fix-plan",
            read_only=False,
            mutates=False,
            timeout_seconds=180,
            metadata={
                "rollback_or_validation": (
                    "Local report and packet files only; no live Splunk or "
                    "Observability mutation is performed."
                )
            },
        )
    ]


def build_plan(
    *,
    profile: str,
    run_dir: Path,
    allow_apply: bool,
    platform: str = "enterprise",
    selected_skills: set[str] | None = None,
    skip_skills: set[str] | None = None,
) -> list[ValidationStep]:
    selected_skills = selected_skills or set()
    skip_skills = skip_skills or set()
    steps = build_baseline_steps(profile, run_dir, platform)
    for skill_dir in skill_dirs():
        skill = skill_dir.name
        if selected_skills and skill not in selected_skills:
            continue
        if skill in skip_skills:
            steps.append(
                ValidationStep(
                    step_id=f"{skill}:operator-skip",
                    category="read-only",
                    skill=skill,
                    command=["true"],
                    mode="operator-skip",
                    skip_reason="Skipped by --skip-skill.",
                    required=False,
                )
            )
            continue
        steps.extend(read_only_mode_steps(skill, run_dir, platform))
    doctor_in_scope = (
        "splunk-admin-doctor" not in skip_skills
        and (not selected_skills or "splunk-admin-doctor" in selected_skills)
    )
    if doctor_in_scope:
        steps.append(
            ValidationStep(
                step_id="splunk-admin-doctor:doctor-live-evidence",
                category="doctor",
                skill="splunk-admin-doctor",
                command=script_command(
                    "splunk-admin-doctor",
                    "setup.sh",
                    [
                        "--phase",
                        "doctor",
                        "--platform",
                        platform,
                        "--evidence-file",
                        str(run_dir / "evidence" / "live-evidence.redacted.json"),
                        "--output-dir",
                        str(run_dir / "doctor"),
                        "--json",
                        "--strict",
                    ],
                ),
                mode="doctor",
                timeout_seconds=180,
            )
        )
        steps.extend(build_apply_steps(run_dir, allow_apply, platform))
    return steps


def load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "steps": {}, "runs": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "steps": {}, "runs": []}
    if not isinstance(payload, dict):
        return {"version": 1, "steps": {}, "runs": []}
    payload.setdefault("version", 1)
    payload.setdefault("steps", {})
    payload.setdefault("runs", [])
    return payload


def save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    write_json(path, checkpoint)


def checkpoint_result_is_reusable(
    prior: Any,
    *,
    force_rerun: bool,
    category: str,
    command: str = "",
) -> bool:
    return (
        isinstance(prior, dict)
        and prior.get("status") in {"pass", "fixed-pass"}
        and not force_rerun
        and category == "apply"
        and bool(command)
        and prior.get("command") == command
    )


def summarize_skill_status(results: list[StepResult], all_steps: list[ValidationStep]) -> dict[str, Any]:
    skills = {step.skill for step in all_steps if step.skill}
    summary: dict[str, Any] = {}
    by_skill: dict[str, list[StepResult]] = {skill: [] for skill in skills}
    for result in results:
        if result.skill:
            by_skill.setdefault(result.skill, []).append(result)
    for skill in sorted(skills):
        rows = by_skill.get(skill, [])
        if not rows:
            summary[skill] = {"status": "intentional-skip", "reason": "No steps selected."}
            continue
        statuses = {row.status for row in rows}
        if "fail" in statuses:
            final = "fail"
        elif "pass" in statuses:
            final = "pass"
        else:
            final = "intentional-skip"
        substantive = [row for row in rows if not row.mode.endswith("-help") and row.mode != "setup-help"]
        summary[skill] = {
            "status": final,
            "validation_depth": "feature_validation" if substantive else "interface_only",
            "steps": len(rows),
            "substantive_steps": len(substantive),
            "passed": sum(1 for row in rows if row.status == "pass"),
            "skipped": sum(1 for row in rows if row.status == "intentional-skip"),
            "failed": sum(1 for row in rows if row.status == "fail"),
        }
    return summary


def write_markdown_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Splunk Skills Live Validation",
        "",
        f"- Run ID: `{payload['run_id']}`",
        f"- Profile: `{payload['profile']}`",
        f"- Platform: `{payload['platform']}`",
        f"- Started: `{payload['started_at']}`",
        f"- Ended: `{payload['ended_at']}`",
        f"- Allow apply: `{payload['allow_apply']}`",
        "",
        "## Totals",
        "",
    ]
    totals = payload["totals"]
    for key in ("pass", "fixed-pass", "intentional-skip", "fail"):
        lines.append(f"- {key}: {totals.get(key, 0)}")
    lines.extend(["", "## Skill Status", ""])
    for skill, item in sorted(payload["skills"].items()):
        lines.append(
            f"- `{skill}`: {item['status']} / {item.get('validation_depth', 'unknown')} "
            f"({item.get('passed', 0)} pass, {item.get('skipped', 0)} skip, "
            f"{item.get('failed', 0)} fail)"
        )
    failures = [row for row in payload["results"] if row["status"] == "fail"]
    if failures:
        lines.extend(["", "## Failures", ""])
        for row in failures:
            lines.append(
                f"- `{row['step_id']}`: {row['classification'] or 'failed'} "
                f"(stdout `{row['stdout_log']}`, stderr `{row['stderr_log']}`)"
            )
    lines.append("")
    write_text_secure(path, "\n".join(lines))


def run_once(args: argparse.Namespace, *, iteration: int = 1) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint = load_checkpoint(checkpoint_path)
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-iter{iteration}"
    run_dir = output_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now()

    selected_skills = set(args.skill or [])
    skip_skills = set(args.skip_skill or [])
    if args.plan_only:
        effective_platform = args.platform if args.platform != "auto" else "enterprise"
        steps = build_plan(
            profile=args.profile,
            run_dir=run_dir,
            allow_apply=args.allow_apply,
            platform=effective_platform,
            selected_skills=selected_skills,
            skip_skills=skip_skills,
        )
        payload = {
            "run_id": run_id,
            "profile": args.profile,
            "platform": effective_platform,
            "allow_apply": args.allow_apply,
            "steps": [asdict(step) for step in steps],
        }
        write_json(run_dir / "plan.json", payload)
        if args.json:
            print(json.dumps(redact_obj(payload), indent=2, sort_keys=True))
        return payload

    evidence = collect_live_evidence(args.profile, run_dir, args.platform)
    write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)
    effective_platform = str(evidence.get("platform", "enterprise"))
    steps = build_plan(
        profile=args.profile,
        run_dir=run_dir,
        allow_apply=args.allow_apply,
        platform=effective_platform,
        selected_skills=selected_skills,
        skip_skills=skip_skills,
    )

    ledger_path = run_dir / "ledger.jsonl"
    results: list[StepResult] = []
    for step in steps:
        prior = checkpoint.get("steps", {}).get(step.step_id)
        if checkpoint_result_is_reusable(
            prior,
            force_rerun=args.force_rerun,
            category=step.category,
            command=shell_join(step.command),
        ):
            skipped = StepResult(
                step_id=step.step_id,
                category=step.category,
                skill=step.skill,
                mode=step.mode,
                status=prior["status"],
                command=shell_join(step.command),
                read_only=step.read_only,
                mutates=step.mutates,
                returncode=prior.get("returncode"),
                started_at=utc_now(),
                ended_at=utc_now(),
                duration_seconds=0.0,
                classification="checkpoint-resume",
                notes=[f"Reused checkpoint result from {prior.get('ended_at', 'previous run')}."],
                metadata=step.metadata,
            )
            append_jsonl(ledger_path, asdict(skipped))
            results.append(skipped)
            continue

        result = execute_step(
            step,
            profile=args.profile,
            run_dir=run_dir,
            ledger_path=ledger_path,
            quiet=args.quiet,
        )
        results.append(result)
        checkpoint.setdefault("steps", {})[step.step_id] = asdict(result)
        save_checkpoint(checkpoint_path, checkpoint)
        if result.status == "fail" and args.stop_on_failure:
            break

    totals: dict[str, int] = {}
    for result in results:
        totals[result.status] = totals.get(result.status, 0) + 1
    payload = {
        "run_id": run_id,
        "profile": args.profile,
        "platform": effective_platform,
        "allow_apply": args.allow_apply,
        "started_at": started,
        "ended_at": utc_now(),
        "output_dir": str(run_dir),
        "ledger": str(ledger_path),
        "totals": totals,
        "skills": summarize_skill_status(results, steps),
        "results": [asdict(result) for result in results],
        "rerun_command": shell_join(
            [
                "python3",
                "skills/splunk-admin-doctor/scripts/live_validate_all.py",
                "--profile",
                args.profile,
                "--platform",
                effective_platform,
                "--output-dir",
                str(output_dir),
                "--allow-apply" if args.allow_apply else "--once",
            ]
        ),
    }
    write_json(run_dir / "final-report.json", payload)
    write_markdown_report(run_dir / "final-report.md", payload)
    checkpoint.setdefault("runs", []).append(
        {
            "run_id": run_id,
            "started_at": started,
            "ended_at": payload["ended_at"],
            "totals": totals,
            "output_dir": str(run_dir),
        }
    )
    save_checkpoint(checkpoint_path, checkpoint)
    if args.json:
        print(json.dumps(redact_obj(payload), indent=2, sort_keys=True))
    else:
        print(f"Live validation run complete: {run_dir}")
        print(f"Totals: {totals}")
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run continuous live validation for every repo skill.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="Splunk credential profile to use.")
    parser.add_argument("--platform", choices=("auto", "cloud", "enterprise"), default="auto")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Gitignored output/checkpoint directory.")
    parser.add_argument(
        "--allow-apply",
        action="store_true",
        help="Render the bounded local doctor fix plan; live mutation smokes are disabled.",
    )
    parser.add_argument("--once", action="store_true", help="Run one sweep and exit.")
    parser.add_argument("--watch", action="store_true", help="Repeat sweeps until stopped.")
    parser.add_argument("--watch-interval-seconds", type=int, default=1800, help="Delay between steady-state sweeps.")
    parser.add_argument("--max-iterations", type=int, default=0, help="Maximum watch iterations; 0 means unlimited.")
    parser.add_argument("--force-rerun", action="store_true", help="Ignore checkpointed final apply step results.")
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop the current sweep after the first hard failure.")
    parser.add_argument("--plan-only", action="store_true", help="Render the execution plan without running steps.")
    parser.add_argument("--skill", action="append", help="Limit the sweep to a skill; repeatable.")
    parser.add_argument("--skip-skill", action="append", help="Skip a skill; repeatable.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-step progress lines.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.watch:
        args.once = False
    elif not args.once and args.max_iterations == 0:
        # Default to one active sweep when invoked manually.
        args.once = True

    iteration = 1
    stop = False
    last_payload: dict[str, Any] | None = None

    def _handle_signal(signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True
        print(f"Received signal {signum}; stopping after the current sweep.", file=sys.stderr)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stop:
        payload = run_once(args, iteration=iteration)
        last_payload = payload
        if args.once:
            return 0 if payload.get("totals", {}).get("fail", 0) == 0 else 1
        if args.max_iterations and iteration >= args.max_iterations:
            break
        iteration += 1
        # After the active apply pass, steady state is read-only unless the
        # operator forces another apply. This prevents repeated O11y object
        # creation while still keeping the live watch alive.
        args.allow_apply = False
        for _ in range(max(1, args.watch_interval_seconds)):
            if stop:
                break
            time.sleep(1)
    if last_payload is None:
        return 1
    return 0 if last_payload.get("totals", {}).get("fail", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
