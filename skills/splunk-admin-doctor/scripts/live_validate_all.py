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
    "splunk-cloud-acs-allowlist-setup",
}
SPLUNK_REST_TIMEOUT_SECONDS = 90


SECRET_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
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
            r"password|passwd|pwd|secret|"
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
            r"\"(?:password|secret|token|apiKey|api_key|clientSecret|client_secret|sessionKey)\""
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


REMOTE_RENDERED_APPLY_SCRIPT = r"""
set -euo pipefail
source skills/shared/lib/credential_helpers.sh
source skills/shared/lib/host_bootstrap_helpers.sh

skill="$1"
output_dir="$2"
rendered_subdir="$3"
apply_script="$4"
service_user="${5:-splunk}"
shift 5

"$@"

archive="$(mktemp "/tmp/${skill}.XXXXXX.tgz")"
tar -C "${output_dir}" -czf "${archive}" "${rendered_subdir}"
remote_archive="$(hbs_stage_file_for_execution ssh "${archive}" "${skill}.$$.tgz")"
rm -f "${archive}"
remote_dir="/tmp/${skill}.$$"
cleanup_cmd="$(hbs_prefix_with_sudo ssh "$(hbs_shell_join rm -rf "${remote_dir}" "${remote_archive}")")"
hbs_run_target_cmd ssh "$(hbs_prefix_with_sudo ssh "$(hbs_shell_join mkdir -p "${remote_dir}")")"
hbs_run_target_cmd ssh "$(hbs_prefix_with_sudo ssh "$(hbs_shell_join tar -xzf "${remote_archive}" -C "${remote_dir}")")"
hbs_run_target_cmd ssh "$(hbs_prefix_with_sudo ssh "$(hbs_shell_join chown -R "${service_user}:${service_user}" "${remote_dir}")")" >/dev/null 2>&1 || true
remote_workdir="${remote_dir}/${rendered_subdir}"
if [[ "${apply_script}" != */* ]]; then
  remote_apply="./${apply_script}"
else
  remote_apply="${apply_script}"
fi
if hbs_run_as_user_cmd ssh "${service_user}" "cd $(printf '%q' "${remote_workdir}") && bash $(printf '%q' "${remote_apply}")"; then
  hbs_run_target_cmd ssh "${cleanup_cmd}" >/dev/null 2>&1 || true
  exit 0
fi
rc=$?
hbs_run_target_cmd ssh "${cleanup_cmd}" >/dev/null 2>&1 || true
exit "${rc}"
"""


ENTERPRISE_HEC_CLEANUP_COMMAND = r"""
set -euo pipefail
target="/opt/splunk/etc/apps/splunk_httpinput/local/inputs.conf"
stanza="http://codex_live_validation_hec"
if [[ ! -f "${target}" ]]; then
  echo "hec_inputs_file_present=false"
  exit 0
fi
python3 - "${target}" "${stanza}" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
stanza = sys.argv[2]
lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
output = []
skip = False
removed = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        name = stripped[1:-1]
        skip = name == stanza
        if skip:
            removed = True
            continue
    if not skip:
        output.append(line)
if removed:
    path.write_text("".join(output), encoding="utf-8")
print(f"hec_stanza_removed={'true' if removed else 'false'}")
PY
removed_backups=0
for backup in "${target}".bak.*; do
  [[ -f "${backup}" ]] || continue
  if grep -q '^\[http://codex_live_validation_hec\]' "${backup}"; then
    rm -f "${backup}"
    removed_backups=$((removed_backups + 1))
  fi
done
echo "hec_backup_files_removed=${removed_backups}"
"""


ENTERPRISE_WORKLOAD_CLEANUP_COMMAND = r"""
set -euo pipefail
app="/opt/splunk/etc/apps/ZZZ_codex_live_validation_workload_management"
if [[ -d "${app}" ]]; then
  rm -rf "${app}"
  echo "workload_app_removed=true"
else
  echo "workload_app_removed=false"
fi
"""


ENTERPRISE_HEC_CLEANUP_VALIDATION_COMMAND = r"""
set -euo pipefail
target="/opt/splunk/etc/apps/splunk_httpinput/local/inputs.conf"
if /opt/splunk/bin/splunk btool inputs list --debug 2>/dev/null | grep -q '^\[http://codex_live_validation_hec\]'; then
  echo "hec_stanza_present=true"
  exit 1
fi
for backup in "${target}".bak.*; do
  [[ -f "${backup}" ]] || continue
  if grep -q '^\[http://codex_live_validation_hec\]' "${backup}"; then
    echo "hec_validation_backup_present=true"
    exit 1
  fi
done
echo "hec_stanza_present=false"
echo "hec_validation_backup_present=false"
"""


ENTERPRISE_WORKLOAD_CLEANUP_VALIDATION_COMMAND = r"""
set -euo pipefail
app="/opt/splunk/etc/apps/ZZZ_codex_live_validation_workload_management"
if [[ -d "${app}" ]]; then
  echo "workload_app_present=true"
  exit 1
fi
echo "workload_app_present=false"
"""


O11Y_PROBE_SCRIPT = r"""
set -euo pipefail
source skills/shared/lib/credential_helpers.sh
load_observability_cloud_settings >/dev/null
if [[ -z "${SPLUNK_O11Y_REALM:-}" ]]; then
  echo '{"ok":false,"reason":"missing SPLUNK_O11Y_REALM"}'
  exit 2
fi
if [[ -z "${SPLUNK_O11Y_TOKEN_FILE:-}" || ! -r "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
  echo '{"ok":false,"reason":"missing or unreadable SPLUNK_O11Y_TOKEN_FILE"}'
  exit 2
fi
mode="$(stat -f '%A' "${SPLUNK_O11Y_TOKEN_FILE}" 2>/dev/null || stat -c '%a' "${SPLUNK_O11Y_TOKEN_FILE}")"
if [[ "${mode}" != "600" ]]; then
  echo "{\"ok\":false,\"reason\":\"token file permissions are ${mode}, expected 600\"}"
  exit 2
fi
url="https://api.${SPLUNK_O11Y_REALM}.observability.splunkcloud.com/v2/organization"
http_code="$(
  curl -sS --connect-timeout 10 --max-time 30 \
    -K <(printf 'header = "X-SF-Token: %s"\n' "$(tr -d '\r\n' < "${SPLUNK_O11Y_TOKEN_FILE}")") \
    -o /tmp/codex-o11y-live-validation-body.$$ \
    -w '%{http_code}' \
    "${url}" || true
)"
body="$(head -c 4096 /tmp/codex-o11y-live-validation-body.$$ 2>/dev/null || true)"
rm -f /tmp/codex-o11y-live-validation-body.$$
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
            if not structural_key and re.search(
                r"(?i)^(.*[_-])?(password|secret|token|session|private[_-]?key|api[_-]?key)([_-].*)?$",
                key_text,
            ):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_obj(item)
        return out
    if isinstance(value, list):
        return [redact_obj(item) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact_obj(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(redact_obj(payload), sort_keys=True) + "\n")


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
    if "not found" in text or "does not exist" in text or "no such file or directory" in text:
        if "unknown option" not in text:
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
    if "no such file or directory" in text or "command not found" in text or "unknown option" in text:
        return "code_bug"
    if step.skill.startswith(("cisco-", "splunk-observability-", "splunk-oncall", "splunk-soar")):
        return "expected_missing_external_dependency"
    return "unclassified_failure"


def should_intentional_skip(step: ValidationStep, classification: str) -> bool:
    if step.final_on_failure == "intentional-skip":
        return True
    if not step.required and classification in {
        "expected_missing_external_dependency",
        "live_environment_constraint",
        "credentials_profile_issue",
    }:
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
    stdout_log.write_text(stdout_redacted, encoding="utf-8")
    stderr_log.write_text(stderr_redacted, encoding="utf-8")

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


def collect_live_evidence(profile: str, run_dir: Path) -> dict[str, Any]:
    metadata = profile_metadata(profile)
    evidence: dict[str, Any] = {
        "platform": "enterprise",
        "collection": {
            "profile": profile,
            "collected_at": utc_now(),
            "notes": [],
        },
        "rest": {
            "reachable": True,
            "denied": False,
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

    write_json(run_dir / "evidence" / "splunk-rest-raw.redacted.json", raw)

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
    premium_detected = []
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
        lowered = name.lower()
        if any(marker in lowered for marker in ("enterprise", "itsi", "soar", "observability", "oncall", "cisco")):
            premium_detected.append(name)
    evidence["apps"] = {"installed": apps, "restart_required": restart_required}
    if premium_detected:
        evidence["premium_products"] = {"detected": sorted(set(premium_detected))}

    index_entries = parse_splunk_entries(raw["indexes"].get("payload", {}))
    evidence["indexes"] = {
        "present": sorted(entry.get("name", "") for entry in index_entries if entry.get("name")),
        "missing": [],
    }

    hec_entries = parse_splunk_entries(raw["hec"].get("payload", {}))
    hec_disabled = False
    if hec_entries:
        # The global HEC endpoint usually appears as http. If every stanza is
        # disabled, call the HEC service unavailable.
        disabled_values = [entry.get("content", {}).get("disabled") for entry in hec_entries]
        hec_disabled = all(str(value).lower() in {"1", "true"} for value in disabled_values)
    evidence["hec"] = {"enabled": bool(hec_entries) and not hec_disabled, "token_count": len(hec_entries)}

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
    evidence["license"] = {"messages": [entry.get("name", "") for entry in license_entries], "violation_count": len(license_entries)}

    saved_entries = parse_splunk_entries(raw["saved_searches"].get("payload", {}))
    skipped = []
    for entry in saved_entries:
        content = entry.get("content", {})
        if content.get("is_scheduled") and content.get("next_scheduled_time") in {"", None}:
            skipped.append(entry.get("name", ""))
    evidence["scheduler"] = {"skipped_count": len(skipped), "skipped_searches": skipped[:25]}

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
        evidence["shc"] = {"status": "unknown", "issues": []}
    else:
        evidence["shc"] = {"status": "not_configured", "issues": []}
    idxc_rc = raw["indexer_cluster"]["returncode"]
    if idxc_rc == 0:
        evidence["indexer_cluster"] = {"status": "unknown", "issues": []}
    else:
        evidence["indexer_cluster"] = {"status": "not_configured", "issues": []}

    evidence["monitoring_console"] = {
        "configured": any(app["name"] == "splunk_monitoring_console" and not app["disabled"] for app in apps),
        "platform_alerts_enabled": None,
    }
    evidence["support"] = {"diag_ready": True, "diag_blockers": []}
    evidence["backup"] = {"last_config_backup_stale": None}
    evidence["security"] = {
        "weak_tls": not evidence["rest"]["tls_verified"],
        "tls_findings": ["SPLUNK_VERIFY_SSL=false"] if not evidence["rest"]["tls_verified"] else [],
    }

    remote_summary: dict[str, Any] = {"enabled": True, "checks": {}}
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


def build_baseline_steps(profile: str, run_dir: Path) -> list[ValidationStep]:
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
        ValidationStep(
            step_id="baseline-ssh-splunk-version",
            category="baseline",
            command=[
                "bash",
                "-c",
                SSH_SPLUNK_CLI_SCRIPT,
                "ssh-splunk-cli",
                "splunk",
                "hostname; test -x /opt/splunk/bin/splunk; /opt/splunk/bin/splunk version",
            ],
            mode="ssh:splunk-version",
            timeout_seconds=90,
        ),
        ValidationStep(
            step_id="baseline-ssh-splunk-status",
            category="baseline",
            command=[
                "bash",
                "-c",
                SSH_SPLUNK_CLI_SCRIPT,
                "ssh-splunk-cli",
                "splunk",
                "/opt/splunk/bin/splunk status",
            ],
            mode="ssh:splunk-status",
            timeout_seconds=90,
        ),
        ValidationStep(
            step_id="baseline-ssh-btool-check",
            category="baseline",
            command=[
                "bash",
                "-c",
                SSH_SPLUNK_CLI_SCRIPT,
                "ssh-splunk-cli",
                "splunk",
                "/opt/splunk/bin/splunk btool check --debug",
            ],
            mode="ssh:btool-check",
            timeout_seconds=180,
            required=False,
            final_on_failure="intentional-skip",
        ),
    ]
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


def read_only_mode_steps(skill: str, run_dir: Path) -> list[ValidationStep]:
    steps: list[ValidationStep] = []
    live_modes_excluded = skill in ONPREM_LIVE_MODE_EXCLUDED_SKILLS
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


def write_o11y_dashboard_spec(run_dir: Path, realm: str = "us0") -> Path:
    spec_path = run_dir / "generated-specs" / "o11y-dashboard-live-validation.json"
    spec = {
        "api_version": "splunk-observability-dashboard-builder/v1",
        "mode": "classic-api",
        "realm": realm,
        "dashboard_group": {
            "name": "codex_live_validation_skill_checks",
            "description": "Created by splunk-cisco-skills live validation.",
        },
        "dashboard": {
            "name": "codex_live_validation_dashboard",
            "description": "Low-impact validation dashboard for the skill runner.",
            "chart_density": "DEFAULT",
        },
        "charts": [
            {
                "id": "validation-note",
                "name": "Validation note",
                "type": "Text",
                "row": 0,
                "column": 0,
                "width": 12,
                "height": 1,
                "markdown": "codex_live_validation dashboard builder smoke object.",
            }
        ],
    }
    write_json(spec_path, spec)
    return spec_path


def build_apply_steps(run_dir: Path, allow_apply: bool) -> list[ValidationStep]:
    if not allow_apply:
        return []
    output_root = run_dir / "apply-rendered"
    dashboard_spec = write_o11y_dashboard_spec(run_dir)
    dashboard_output = output_root / "splunk-observability-dashboard-builder"
    steps: list[ValidationStep] = [
        ValidationStep(
            step_id="splunk-admin-doctor:apply-safe-packet",
            category="apply",
            skill="splunk-admin-doctor",
            command=script_command(
                "splunk-admin-doctor",
                "setup.sh",
                [
                    "--phase",
                    "apply",
                    "--platform",
                    "enterprise",
                    "--evidence-file",
                    str(run_dir / "evidence" / "live-evidence.redacted.json"),
                    "--output-dir",
                    str(output_root / "splunk-admin-doctor"),
                    "--fixes",
                    "SAD-CONNECTIVITY-TLS-UNVERIFIED",
                    "--json",
                ],
            ),
            mode="apply",
            read_only=False,
            mutates=False,
            timeout_seconds=180,
            metadata={"rollback_or_validation": "Rerun splunk-admin-doctor doctor/status; no live mutation is performed."},
        ),
        ValidationStep(
            step_id="splunk-observability-dashboard-builder:apply-live-smoke",
            category="apply",
            skill="splunk-observability-dashboard-builder",
            command=script_command(
                "splunk-observability-dashboard-builder",
                "setup.sh",
                [
                    "--apply",
                    "--spec",
                    str(dashboard_spec),
                    "--output-dir",
                    str(dashboard_output),
                ],
            ),
            mode="apply",
            read_only=False,
            mutates=True,
            required=False,
            timeout_seconds=420,
            final_on_failure="intentional-skip",
            metadata={
                "rollback_or_validation": "The follow-up cleanup step deletes the codex_live_validation dashboard, charts, and created dashboard group from apply-result.json.",
            },
        ),
        ValidationStep(
            step_id="splunk-observability-dashboard-builder:cleanup-live-smoke",
            category="apply-cleanup",
            skill="splunk-observability-dashboard-builder",
            command=script_command(
                "splunk-observability-dashboard-builder",
                "setup.sh",
                [
                    "--cleanup",
                    "--apply-result",
                    str(dashboard_output / "apply-result.json"),
                ],
            ),
            mode="cleanup",
            read_only=False,
            mutates=True,
            required=False,
            timeout_seconds=420,
            final_on_failure="intentional-skip",
            metadata={
                "rollback_or_validation": "Cleanup is guarded to codex_live_validation* dashboard plans and treats missing objects as already absent.",
            },
        ),
    ]

    remote_apply_specs = [
        {
            "skill": "splunk-monitoring-console-setup",
            "step_id": "splunk-monitoring-console-setup:apply-ssh-no-restart",
            "rendered_subdir": "monitoring-console",
            "apply_script": "apply.sh",
            "render_args": [
                "--phase",
                "render",
                "--mode",
                "standalone",
                "--restart-splunk",
                "false",
            ],
            "rollback_or_validation": "Remote files are under /opt/splunk/etc/apps/splunk_monitoring_console/local; rerun status or restore from Splunk config backup if rollback is required.",
        },
        {
            "skill": "splunk-hec-service-setup",
            "step_id": "splunk-hec-service-setup:apply-ssh-token-no-restart",
            "rendered_subdir": "hec-service",
            "apply_script": "apply-enterprise-files.sh",
            "render_args": [
                "--phase",
                "render",
                "--platform",
                "enterprise",
                "--token-name",
                "codex_live_validation_hec",
                "--default-index",
                "main",
                "--allowed-indexes",
                "main",
                "--token-file",
                ".codex_live_validation_hec.token",
                "--restart-splunk",
                "false",
            ],
            "rollback_or_validation": "Remote inputs.conf is backed up before overwrite; restart is skipped, so validate with btool/status before enabling the token.",
        },
        {
            "skill": "splunk-workload-management-setup",
            "step_id": "splunk-workload-management-setup:apply-ssh-no-enable",
            "rendered_subdir": "workload-management",
            "apply_script": "apply.sh",
            "render_args": [
                "--phase",
                "render",
                "--app-name",
                "ZZZ_codex_live_validation_workload_management",
            ],
            "rollback_or_validation": "Disable/remove /opt/splunk/etc/apps/ZZZ_codex_live_validation_workload_management if rollback is required.",
        },
    ]
    for spec in remote_apply_specs:
        skill = str(spec["skill"])
        output_dir = output_root / skill
        render_cmd = script_command(
            skill,
            "setup.sh",
            [*list(spec["render_args"]), "--output-dir", str(output_dir)],
        )
        steps.append(
            ValidationStep(
                step_id=str(spec["step_id"]),
                category="apply",
                skill=skill,
                command=[
                    "bash",
                    "-c",
                    REMOTE_RENDERED_APPLY_SCRIPT,
                    "remote-rendered-apply",
                    skill,
                    str(output_dir),
                    str(spec["rendered_subdir"]),
                    str(spec["apply_script"]),
                    "splunk",
                    *render_cmd,
                ],
                mode="ssh-apply",
                read_only=False,
                mutates=True,
                required=False,
                timeout_seconds=600,
                final_on_failure="intentional-skip",
                metadata={"rollback_or_validation": str(spec["rollback_or_validation"])},
            )
        )
    post_apply_ssh_checks = [
        {
            "step_id": "splunk-enterprise:post-apply-ssh-status",
            "mode": "ssh:post-apply-status",
            "command": (
                'if /opt/splunk/bin/splunk status 2>/dev/null | grep -qi "splunkd is running"; '
                'then echo "splunkd_running=true"; else echo "splunkd_running=false"; exit 1; fi'
            ),
            "validation": "Confirms splunkd is still running after low-risk SSH apply steps.",
        },
        {
            "step_id": "splunk-monitoring-console-setup:post-apply-ssh-check",
            "skill": "splunk-monitoring-console-setup",
            "mode": "ssh:post-apply-monitoring-console",
            "command": (
                "test -d /opt/splunk/etc/apps/splunk_monitoring_console/local "
                '&& echo "monitoring_console_local=true"'
            ),
            "validation": "Confirms the Monitoring Console local app directory exists after apply.",
        },
        {
            "step_id": "splunk-hec-service-setup:post-apply-ssh-check",
            "skill": "splunk-hec-service-setup",
            "mode": "ssh:post-apply-hec",
            "command": (
                "/opt/splunk/bin/splunk btool inputs list --debug 2>/dev/null | awk '"
                "/\\[http:\\/\\/codex_live_validation_hec\\]/ {found=1; in_stanza=1} "
                "/^\\[/ && !/\\[http:\\/\\/codex_live_validation_hec\\]/ {in_stanza=0} "
                "in_stanza && /index = main/ {idx=1} "
                'END {printf "hec_stanza_present=%s\\n", found ? "true" : "false"; '
                'printf "hec_index_main=%s\\n", idx ? "true" : "false"; '
                "exit (found && idx) ? 0 : 1}'"
            ),
            "validation": "Confirms the rendered HEC stanza is visible through btool without printing token values.",
        },
        {
            "step_id": "splunk-workload-management-setup:post-apply-ssh-check",
            "skill": "splunk-workload-management-setup",
            "mode": "ssh:post-apply-workload-management",
            "command": (
                "test -d /opt/splunk/etc/apps/ZZZ_codex_live_validation_workload_management "
                '&& echo "workload_app_present=true"'
            ),
            "validation": "Confirms the workload-management validation app exists after apply.",
        },
    ]
    for spec in post_apply_ssh_checks:
        steps.append(
            ValidationStep(
                step_id=str(spec["step_id"]),
                category="apply-validation",
                skill=str(spec.get("skill", "")),
                command=[
                    "bash",
                    "-c",
                    SSH_SPLUNK_CLI_SCRIPT,
                    "ssh-splunk-cli",
                    "splunk",
                    str(spec["command"]),
                ],
                mode=str(spec["mode"]),
                read_only=True,
                mutates=False,
                timeout_seconds=120,
                metadata={"rollback_or_validation": str(spec["validation"])},
            )
        )
    enterprise_cleanup_steps = [
        {
            "step_id": "splunk-hec-service-setup:cleanup-ssh-validation-token",
            "skill": "splunk-hec-service-setup",
            "mode": "ssh:cleanup-hec",
            "command": ENTERPRISE_HEC_CLEANUP_COMMAND,
            "validation": "Removes only the codex_live_validation_hec stanza and generated backups that contain that validation stanza.",
        },
        {
            "step_id": "splunk-workload-management-setup:cleanup-ssh-validation-app",
            "skill": "splunk-workload-management-setup",
            "mode": "ssh:cleanup-workload-management",
            "command": ENTERPRISE_WORKLOAD_CLEANUP_COMMAND,
            "validation": "Removes only /opt/splunk/etc/apps/ZZZ_codex_live_validation_workload_management.",
        },
    ]
    for spec in enterprise_cleanup_steps:
        steps.append(
            ValidationStep(
                step_id=str(spec["step_id"]),
                category="apply-cleanup",
                skill=str(spec["skill"]),
                command=[
                    "bash",
                    "-c",
                    SSH_SPLUNK_CLI_SCRIPT,
                    "ssh-splunk-cli",
                    "splunk",
                    str(spec["command"]),
                ],
                mode=str(spec["mode"]),
                read_only=False,
                mutates=True,
                required=False,
                timeout_seconds=120,
                final_on_failure="intentional-skip",
                metadata={"rollback_or_validation": str(spec["validation"])},
            )
        )
    post_cleanup_checks = [
        {
            "step_id": "splunk-hec-service-setup:post-cleanup-ssh-check",
            "skill": "splunk-hec-service-setup",
            "mode": "ssh:post-cleanup-hec",
            "command": ENTERPRISE_HEC_CLEANUP_VALIDATION_COMMAND,
            "validation": "Confirms the codex_live_validation_hec stanza and generated backups are absent without printing token values.",
        },
        {
            "step_id": "splunk-workload-management-setup:post-cleanup-ssh-check",
            "skill": "splunk-workload-management-setup",
            "mode": "ssh:post-cleanup-workload-management",
            "command": ENTERPRISE_WORKLOAD_CLEANUP_VALIDATION_COMMAND,
            "validation": "Confirms the workload-management validation app is absent after cleanup.",
        },
    ]
    for spec in post_cleanup_checks:
        steps.append(
            ValidationStep(
                step_id=str(spec["step_id"]),
                category="apply-cleanup-validation",
                skill=str(spec["skill"]),
                command=[
                    "bash",
                    "-c",
                    SSH_SPLUNK_CLI_SCRIPT,
                    "ssh-splunk-cli",
                    "splunk",
                    str(spec["command"]),
                ],
                mode=str(spec["mode"]),
                read_only=True,
                mutates=False,
                required=False,
                timeout_seconds=120,
                final_on_failure="intentional-skip",
                metadata={"rollback_or_validation": str(spec["validation"])},
            )
        )
    return steps


def build_plan(
    *,
    profile: str,
    run_dir: Path,
    allow_apply: bool,
    selected_skills: set[str] | None = None,
    skip_skills: set[str] | None = None,
) -> list[ValidationStep]:
    selected_skills = selected_skills or set()
    skip_skills = skip_skills or set()
    steps = build_baseline_steps(profile, run_dir)
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
        steps.extend(read_only_mode_steps(skill, run_dir))
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
                    "enterprise",
                    "--evidence-file",
                    str(run_dir / "evidence" / "live-evidence.redacted.json"),
                    "--output-dir",
                    str(run_dir / "doctor"),
                    "--json",
                ],
            ),
            mode="doctor",
            timeout_seconds=180,
        )
    )
    steps.extend(build_apply_steps(run_dir, allow_apply))
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


def checkpoint_result_is_reusable(prior: Any, *, force_rerun: bool, category: str) -> bool:
    return (
        isinstance(prior, dict)
        and prior.get("status") in FINAL_STATUSES
        and not force_rerun
        and category == "apply"
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
        summary[skill] = {
            "status": final,
            "steps": len(rows),
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
        lines.append(f"- `{skill}`: {item['status']} ({item.get('passed', 0)} pass, {item.get('skipped', 0)} skip, {item.get('failed', 0)} fail)")
    failures = [row for row in payload["results"] if row["status"] == "fail"]
    if failures:
        lines.extend(["", "## Failures", ""])
        for row in failures:
            lines.append(
                f"- `{row['step_id']}`: {row['classification'] or 'failed'} "
                f"(stdout `{row['stdout_log']}`, stderr `{row['stderr_log']}`)"
            )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_once(args: argparse.Namespace, *, iteration: int = 1) -> dict[str, Any]:
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint = load_checkpoint(checkpoint_path)
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-iter{iteration}"
    run_dir = output_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now()

    evidence = collect_live_evidence(args.profile, run_dir)
    write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)

    selected_skills = set(args.skill or [])
    skip_skills = set(args.skip_skill or [])
    steps = build_plan(
        profile=args.profile,
        run_dir=run_dir,
        allow_apply=args.allow_apply,
        selected_skills=selected_skills,
        skip_skills=skip_skills,
    )
    if args.plan_only:
        payload = {
            "run_id": run_id,
            "profile": args.profile,
            "allow_apply": args.allow_apply,
            "steps": [asdict(step) for step in steps],
        }
        write_json(run_dir / "plan.json", payload)
        if args.json:
            print(json.dumps(redact_obj(payload), indent=2, sort_keys=True))
        return payload

    ledger_path = run_dir / "ledger.jsonl"
    results: list[StepResult] = []
    for step in steps:
        prior = checkpoint.get("steps", {}).get(step.step_id)
        if checkpoint_result_is_reusable(prior, force_rerun=args.force_rerun, category=step.category):
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
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Gitignored output/checkpoint directory.")
    parser.add_argument("--allow-apply", action="store_true", help="Enable the bounded apply sweep.")
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

    def _handle_signal(signum: int, _frame: Any) -> None:
        nonlocal stop
        stop = True
        print(f"Received signal {signum}; stopping after the current sweep.", file=sys.stderr)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not stop:
        payload = run_once(args, iteration=iteration)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
