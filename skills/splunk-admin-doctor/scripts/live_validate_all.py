#!/usr/bin/env python3
"""Continuous live validation runner for the Splunk Cisco skills repo.

The runner is intentionally orchestration-only: it executes existing skill
entrypoints, captures sanitized evidence, and writes bounded checkpoint audit
history. It never reads secret values directly from credentials. Splunk and
Observability credentials are loaded by the existing repo helpers or by
token-file paths from the credentials file.
"""

from __future__ import annotations

import argparse
import fcntl
import ipaddress
import json
import os
import re
import selectors
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "skills"
DEFAULT_PROFILE = "onprem_2535"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "splunk-live-validation-runs"
REPORT_SCHEMA_VERSION = 1
FINAL_STATUSES = {"pass", "fixed-pass", "intentional-skip"}
SPLUNK_REST_TIMEOUT_SECONDS = 90
MAX_OUTPUT_BYTES = 512 * 1024
MAX_CHECKPOINT_RUNS = 100
MAX_REST_BODY_BYTES = 4 * 1024 * 1024
MAX_REST_ENVELOPE_BYTES = (MAX_REST_BODY_BYTES * 6) + MAX_OUTPUT_BYTES
DEFAULT_MAX_RETAINED_RUNS = 50
MAX_RETAIN_RUNS = 10_000
PROCESS_TERM_GRACE_SECONDS = 2.0
PROCESS_PIPE_GRACE_SECONDS = 0.25
PROFILE_BOUND_ENV_KEYS = {
    "ACS_SERVER",
    "SB_PASS",
    "SB_USER",
    "SPLUNK_ALLOW_INSECURE_HTTP",
    "SPLUNK_CA_CERT",
    "SPLUNK_CLOUD_SEARCH_HEAD",
    "SPLUNK_CLOUD_STACK",
    "SPLUNK_HOST",
    "SPLUNK_MGMT_PORT",
    "SPLUNK_PASS",
    "SPLUNK_PASSWORD",
    "SPLUNK_PLATFORM",
    "SPLUNK_SEARCH_API_URI",
    "SPLUNK_SEARCH_PROFILE",
    "SPLUNK_SEARCH_TARGET_ROLE",
    "SPLUNK_SSH_ALLOW_TOFU",
    "SPLUNK_SSH_HOST",
    "SPLUNK_SSH_HOST_KEY_FINGERPRINT",
    "SPLUNK_SSH_KNOWN_HOSTS_FILE",
    "SPLUNK_SSH_PASS",
    "SPLUNK_SSH_PORT",
    "SPLUNK_SSH_USER",
    "SPLUNK_TARGET_ROLE",
    "SPLUNK_URI",
    "SPLUNK_USER",
    "SPLUNK_USERNAME",
    "SPLUNK_VERIFY_SSL",
    "STACK_PASSWORD",
    "STACK_TOKEN",
    "STACK_TOKEN_USER",
    "STACK_USERNAME",
}


SECRET_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.-]{0,31}://)([^/@\s]{1,4096})@"),
        r"\1[REDACTED]@",
    ),
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]{0,80}PRIVATE KEY-----[\s\S]{0,4194304}?"
            r"-----END [A-Z0-9 ]{0,80}PRIVATE KEY-----"
        ),
        "-----BEGIN PRIVATE KEY-----[REDACTED]-----END PRIVATE KEY-----",
    ),
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{4,16384}\."
            r"[A-Za-z0-9_-]{4,1048576}\."
            r"[A-Za-z0-9_-]{4,16384}\b"
        ),
        "[REDACTED-JWT]",
    ),
    (
        re.compile(
            r"(?i)(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9_]{20,512}|"
            r"github_pat_[A-Za-z0-9_]{20,512})(?![A-Za-z0-9_])"
        ),
        "[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(?<![A-Z0-9])(?:AKIA|ASIA)[0-9A-Z]{12,28}(?![A-Z0-9])"
        ),
        "[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9-]{8,512}"
            r"(?![A-Za-z0-9-])"
        ),
        "[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(?<![A-Za-z0-9._~+/=-])Splunk[ \t]+"
            r"(?=[A-Za-z0-9._~+/=-]{16,512}(?![A-Za-z0-9._~+/=-]))"
            r"(?=[A-Za-z0-9._~+/=-]{0,511}[0-9._~+/=-])"
            r"[A-Za-z0-9._~+/=-]{16,512}(?![A-Za-z0-9._~+/=-])"
        ),
        "[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)(?<!\S)(-(?:p|P|t)|--(?:access-token|admin-token|api-key|api-secret|"
            r"api-token|bearer-token|client-secret|hec-token|o11y-token|on-call-api-key|"
            r"password|secret|session-key|sf-token|token))"
            r"(\s*=\s*|\s+)([^\s'\";,]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|api[_ -]?key|api[_ -]?secret|api[_ -]?token|"
            r"access[_ -]?token|refresh[_ -]?token|session[_ -]?key|session[_ -]?token|"
            r"auth[_ -]?token|hec[_ -]?token|token)"
            r"(\s+(?:is\s+)?)([^\s'\";,:=]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)([?&](?:password|passwd|pwd|secret|api[_-]?key|api[_-]?secret|api[_-]?token|"
            r"access[_-]?token|refresh[_-]?token|session[_-]?key|session[_-]?token|"
            r"auth[_-]?token|hec[_-]?token|token)=)([^&#\s]+)"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(r"(?is)(<sessionKey>)[^<]{1,65536}(</sessionKey>)"),
        r"\1[REDACTED]\2",
    ),
)

AUTHORIZATION_REDACTION = re.compile(
    r"(?is)(\bAuthorization(?:[_-]?Header)?\s*[:=]\s*"
    r"(?:(?:Bearer|Basic|Splunk|Token|Digest|MAC)\s+)?)"
    r"(?:\"(?:\\[\s\S]|[^\"\\])*\"|'(?:\\[\s\S]|[^'\\])*'|[^\s,;]+)"
)
COOKIE_HEADER_REDACTION = re.compile(
    r"(?im)^([ \t]*(?:[<>*][ \t]*)?(?:Cookie|Set-Cookie)[ \t]*:[ \t]*)[^\r\n]*$"
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?is)(?<![A-Za-z0-9_-])(?P<key_quote>[\"']?)"
    r"(?P<key>[A-Za-z][A-Za-z0-9_-]{0,127})"
    r"(?P=key_quote)(?P<separator>\s*[:=]\s*)"
    r"(?P<value>\"(?:\\[\s\S]|[^\"\\])*\"|'(?:\\[\s\S]|[^'\\])*'|[^\s,;&]+)"
)


SPLUNK_REST_PROBE_SCRIPT = r"""
set -euo pipefail
umask 077
source skills/shared/lib/credential_helpers.sh
load_splunk_credentials >/dev/null
endpoint="$1"
case "${endpoint}" in
  /services/*|/servicesNS/*) ;;
  *) echo "ERROR: endpoint must begin with /services/ or /servicesNS/" >&2; exit 2 ;;
esac
curl() (
  # Bash uses 1024-byte units for -f outside POSIX mode. Keep an OS-backed
  # file limit in addition to curl's byte-precise transfer limit.
  ulimit -f 4096
  command curl --max-filesize 4194304 "$@"
)
SK="$(get_session_key "${SPLUNK_URI}")"
body_file="$(mktemp "${TMPDIR:-/tmp}/splunk-doctor-rest.XXXXXX")"
chmod 600 "${body_file}"
trap 'rm -f "${body_file}"' EXIT
set +e
http_code="$(
  splunk_curl "${SK}" -o "${body_file}" -w '%{http_code}' "${SPLUNK_URI%/}${endpoint}"
)"
curl_rc=$?
set -e
python3 - "${curl_rc}" "${http_code}" "${body_file}" <<'PY'
import json
import os
import sys

curl_rc = int(sys.argv[1])
http_text = sys.argv[2].strip()
body_path = sys.argv[3]
http_status = int(http_text) if http_text.isdigit() else None
size = os.path.getsize(body_path)
payload = None
error = ""
json_valid = False
entry_schema_valid = False
if size > 4 * 1024 * 1024:
    error = "response exceeded the 4 MiB probe limit"
else:
    with open(body_path, "rb") as handle:
        raw = handle.read(4 * 1024 * 1024 + 1)
    try:
        decoded = json.loads(raw.decode("utf-8")) if raw else None
    except (UnicodeError, json.JSONDecodeError) as exc:
        error = f"response was not valid JSON: {exc}"
    else:
        json_valid = True
        if isinstance(decoded, dict):
            payload = decoded
            entry_schema_valid = isinstance(decoded.get("entry"), list)
        else:
            error = "response JSON root was not an object"

ok = (
    curl_rc == 0
    and http_status is not None
    and 200 <= http_status < 300
    and json_valid
    and isinstance(payload, dict)
)
print(json.dumps({
    "ok": ok,
    "curl_returncode": curl_rc,
    "http_status": http_status,
    "json_valid": json_valid,
    "entry_schema_valid": entry_schema_valid,
    "payload": payload,
    "error": error,
}, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
raise SystemExit(0 if ok else 22)
PY
"""


SPLUNK_PROFILE_METADATA_SCRIPT = r"""
set -euo pipefail
source skills/shared/lib/credential_helpers.sh
allow_flat_credentials="${1:-false}"
python3 - "${_CRED_FILE}" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit("ERROR: secure credentials require O_NOFOLLOW support.")
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
except OSError as exc:
    raise SystemExit(f"ERROR: cannot securely open credential file: {exc}")
try:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
        or metadata.st_size < 1
        or metadata.st_size > 1024 * 1024
    ):
        raise SystemExit(
            "ERROR: credential file must be a non-empty, single-link, owner-owned "
            "mode-0400/0600 regular file no larger than 1 MiB."
        )
finally:
    os.close(descriptor)
PY
if [[ -n "${SPLUNK_PROFILE:-}" ]]; then
  profile_found=false
  profile_count=0
  while IFS= read -r -d '' candidate; do
    profile_count=$((profile_count + 1))
    [[ "${candidate}" == "${SPLUNK_PROFILE}" ]] && profile_found=true
  done < <(_list_credential_profiles_from_file "${_CRED_FILE}")
  if [[ "${profile_found}" != "true" ]]; then
    if [[ "${allow_flat_credentials}" != "true" ]]; then
      echo "ERROR: credential profile '${SPLUNK_PROFILE}' does not exist in ${_CRED_FILE}." >&2
      exit 2
    fi
    if (( profile_count > 0 )); then
      echo "ERROR: --allow-flat-credentials cannot select a missing name when profiled credentials exist." >&2
      exit 2
    fi
    if ! _credential_file_has_flat_target_entries "${_CRED_FILE}"; then
      echo "ERROR: --allow-flat-credentials requires an existing flat credential file with target settings." >&2
      exit 2
    fi
  fi
fi
load_splunk_connection_settings >/dev/null
load_splunk_platform_settings >/dev/null || true
export SPLUNK_PROFILE SPLUNK_PLATFORM SPLUNK_TARGET_ROLE SPLUNK_SEARCH_TARGET_ROLE
export SPLUNK_URI SPLUNK_VERIFY_SSL SPLUNK_O11Y_REALM SPLUNK_O11Y_TOKEN_FILE
python3 - <<'PY'
import json
import os

print(json.dumps({
    "profile": os.environ.get("SPLUNK_PROFILE", ""),
    "platform": os.environ.get("SPLUNK_PLATFORM", ""),
    "target_role": os.environ.get("SPLUNK_TARGET_ROLE", ""),
    "search_target_role": os.environ.get("SPLUNK_SEARCH_TARGET_ROLE", ""),
    "splunk_uri": os.environ.get("SPLUNK_URI", ""),
    "verify_ssl": os.environ.get("SPLUNK_VERIFY_SSL", "true"),
    "o11y_realm_present": bool(os.environ.get("SPLUNK_O11Y_REALM")),
    "o11y_token_file_present": bool(os.environ.get("SPLUNK_O11Y_TOKEN_FILE")),
}, sort_keys=True))
PY
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
umask 077
source skills/shared/lib/credential_helpers.sh
source skills/shared/lib/credential_curl_helpers.sh
load_observability_cloud_settings >/dev/null
if [[ -z "${SPLUNK_O11Y_REALM:-}" ]]; then
  echo '{"ok":false,"reason":"missing SPLUNK_O11Y_REALM"}'
  exit 2
fi
[[ "${SPLUNK_O11Y_REALM}" == "us2-gcp" ]] && SPLUNK_O11Y_REALM="us2"
case "${SPLUNK_O11Y_REALM}" in
  us0|us1|us2|eu0|eu1|eu2|au0|jp0|sg0) ;;
  *)
    echo '{"ok":false,"reason":"unsupported SPLUNK_O11Y_REALM"}'
    exit 2
    ;;
esac
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
auth_config="$(mktemp "${TMPDIR:-/tmp}/codex-o11y-live-auth.XXXXXX")"
chmod 600 "${body_file}" "${auth_config}"
trap 'rm -f "${body_file}" "${auth_config}"' EXIT
if ! credential_curl_write_header_config \
  "${SPLUNK_O11Y_TOKEN_FILE}" "X-SF-Token" "${auth_config}"; then
  echo '{"ok":false,"reason":"SPLUNK_O11Y_TOKEN_FILE failed descriptor-bound validation"}'
  exit 2
fi
credential_curl_prepare_transport false
set +e
http_code="$(
  (
    ulimit -f 4096
    curl -q -sS --connect-timeout 10 --max-time 30 --max-filesize 4194304 \
    -K "${auth_config}" \
    -o "${body_file}" \
    -w '%{http_code}' \
    "${url}" \
    "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"
  )
)"
curl_rc=$?
set -e
body_size="$(wc -c < "${body_file}" | tr -d '[:space:]')"
rm -f "${body_file}" "${auth_config}"
trap - EXIT
python3 - "${curl_rc}" "${http_code}" "${body_size}" "${SPLUNK_O11Y_REALM}" <<'PY'
import json
import sys

curl_rc = int(sys.argv[1])
http_code = sys.argv[2]
body_size = int(sys.argv[3])
realm = sys.argv[4]
ok = curl_rc == 0 and http_code.startswith("2") and body_size <= 4 * 1024 * 1024
print(json.dumps({
    "ok": ok,
    "realm": realm,
    "http_code": http_code,
    "curl_returncode": curl_rc,
    "body_bytes": body_size,
}))
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


@dataclass(frozen=True)
class RestProbeResult:
    payload: dict[str, Any]
    process_returncode: int | None
    curl_returncode: int | None
    http_status: int | None
    json_valid: bool
    entry_schema_valid: bool
    error: str = ""

    @property
    def ok(self) -> bool:
        return (
            self.process_returncode == 0
            and self.curl_returncode == 0
            and self.http_status is not None
            and 200 <= self.http_status < 300
            and self.json_valid
            and isinstance(self.payload, dict)
        )


class RunnerInterrupted(RuntimeError):
    """Raised after an operator interrupt has stopped the active command."""

    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        super().__init__("live validation interrupted")
        self.stdout = stdout
        self.stderr = stderr


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
    redacted = AUTHORIZATION_REDACTION.sub(r"\1[REDACTED]", redacted)
    redacted = COOKIE_HEADER_REDACTION.sub(r"\1[REDACTED]", redacted)

    def redact_assignment(match: re.Match[str]) -> str:
        key = match.group("key")
        # Authorization values are handled as a unit above so that schemes
        # such as ``Basic`` cannot leave the credential fragment behind.
        if re.sub(r"[^a-z0-9]", "", key.lower()) in {
            "authorization",
            "authorizationheader",
        }:
            return match.group(0)
        if not is_secret_structured_key(key):
            return match.group(0)
        raw_value = match.group("value")
        replacement = "[REDACTED]"
        if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] and raw_value[0] in {'\"', "'"}:
            replacement = f"{raw_value[0]}[REDACTED]{raw_value[-1]}"
        return (
            f"{match.group('key_quote')}{key}{match.group('key_quote')}"
            f"{match.group('separator')}{replacement}"
        )

    redacted = SECRET_ASSIGNMENT_RE.sub(redact_assignment, redacted)
    return redacted


def is_secret_structured_key(value: str) -> bool:
    exact = {
        "password", "passwd", "pwd", "credential", "credentials", "secret",
        "secretkey", "token", "authtoken", "accesstoken", "refreshtoken",
        "sessiontoken", "sessionkey", "authorization", "authorizationheader",
        "privatekey", "privatekeypassword", "apikey", "apisecret", "clientsecret",
        "sslpassword", "pass4symmkey", "hectoken", "awsaccesskeyid",
        "awssecretaccesskey", "awssessiontoken", "ghtoken", "githubtoken",
        "cookie", "setcookie",
    }
    suffixes = (
        "password", "passwd", "secret", "secretkey", "apikey", "apisecret",
        "token", "authtoken", "accesstoken", "refreshtoken", "sessiontoken", "sessionkey",
        "authorization", "authorizationheader", "privatekey",
        "cookie",
    )
    candidates = [value, *re.split(r"[:/]", value)]
    normalized_candidates = [re.sub(r"[^a-z0-9]", "", item.lower()) for item in candidates]
    return any(
        normalized in exact or normalized.endswith(suffixes)
        for normalized in normalized_candidates
        if normalized
    )


def redact_obj(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            # Step identifiers are map keys, not field names. Exempt only the
            # explicitly known checkpoint step map rather than every key that
            # happens to contain punctuation.
            structural_key = parent_key == "steps"
            if not structural_key and is_secret_structured_key(key_text):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_obj(item, key_text)
        return out
    if isinstance(value, list):
        return [redact_obj(item, parent_key) for item in value]
    if isinstance(value, str):
        return redact(value)
    return value


def _open_secure_parent(path: Path) -> tuple[int, str]:
    """Open ``path.parent`` without following any directory symlink."""
    if not path.name or path.name in {".", ".."}:
        raise ValueError(f"invalid evidence file name: {path}")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise RuntimeError("secure evidence writes require O_NOFOLLOW support")

    parent = path.parent
    # macOS exposes /var and /tmp as root-owned aliases into /private. Resolve
    # only those fixed OS aliases; all user-controlled parent symlinks still
    # fail O_NOFOLLOW below.
    if sys.platform == "darwin" and parent.is_absolute() and len(parent.parts) > 1:
        first_component = parent.parts[1]
        if first_component in {"tmp", "var"}:
            alias = Path(os.path.sep) / first_component
            try:
                alias_metadata = alias.lstat()
                alias_target = alias.resolve(strict=True)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISLNK(alias_metadata.st_mode)
                    and alias_metadata.st_uid == 0
                    and alias_target.is_dir()
                    and alias_target.parts[:2] == (os.path.sep, "private")
                ):
                    parent = alias_target.joinpath(*parent.parts[2:])
    if parent.is_absolute():
        descriptor = os.open(os.path.sep, directory_flags | nofollow)
        components = parent.parts[1:]
    else:
        descriptor = os.open(".", directory_flags | nofollow)
        components = parent.parts

    try:
        for component in components:
            if component in {"", "."}:
                continue
            if component == "..":
                raise ValueError(f"parent traversal is not allowed in evidence paths: {path}")
            try:
                child = os.open(component, directory_flags | nofollow, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    # Another runner may have created the same output
                    # component after our failed open. Reopen it using the
                    # descriptor-relative O_NOFOLLOW path below; a competing
                    # symlink or non-directory still fails closed.
                    pass
                child = os.open(component, directory_flags | nofollow, dir_fd=descriptor)
            child_stat = os.fstat(child)
            if not stat.S_ISDIR(child_stat.st_mode):
                os.close(child)
                raise OSError(f"evidence parent component is not a directory: {component}")
            os.close(descriptor)
            descriptor = child
        return descriptor, path.name
    except BaseException:
        os.close(descriptor)
        raise


def _validate_existing_secure_file(parent_fd: int, name: str) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"evidence destination is not a regular file: {name}")
        if metadata.st_nlink != 1:
            raise OSError(f"evidence destination must have exactly one hard link: {name}")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise PermissionError(f"evidence destination must be mode 0600: {name}")
        chunks: list[bytes] = []
        remaining = 64 * 1024 * 1024 + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise OSError(f"evidence destination exceeds the 64 MiB safety limit: {name}")
        after = os.fstat(descriptor)
        if (
            after.st_dev != metadata.st_dev
            or after.st_ino != metadata.st_ino
            or after.st_nlink != 1
            or after.st_size != metadata.st_size
            or after.st_mtime_ns != metadata.st_mtime_ns
        ):
            raise OSError(f"evidence destination changed while it was being read: {name}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def read_secure_bytes(path: Path) -> bytes | None:
    parent_fd, name = _open_secure_parent(path)
    try:
        return _validate_existing_secure_file(parent_fd, name)
    finally:
        os.close(parent_fd)


def _atomic_write_secure(path: Path, content: bytes) -> None:
    parent_fd, name = _open_secure_parent(path)
    temporary = f".{name}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
    descriptor: int | None = None
    created = False
    try:
        _validate_existing_secure_file(parent_fd, name)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | os.O_NOFOLLOW
        )
        descriptor = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
        created = True
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise OSError(f"unsafe temporary evidence file: {temporary}")
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError(f"short write for evidence file: {name}")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        created = False
        os.fsync(parent_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def write_text_secure(path: Path, content: str) -> None:
    _atomic_write_secure(path, content.encode("utf-8"))


def write_json(path: Path, payload: Any) -> None:
    write_text_secure(path, json.dumps(redact_obj(payload), indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, payload: Any) -> None:
    parent_fd, name = _open_secure_parent(path)
    try:
        existing = _validate_existing_secure_file(parent_fd, name) or b""
    finally:
        os.close(parent_fd)
    row = (json.dumps(redact_obj(payload), sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_secure(path, existing + row)


def skill_dirs() -> list[Path]:
    return sorted(
        path
        for path in SKILLS_DIR.iterdir()
        if path.is_dir() and path.name != "shared" and (path / "SKILL.md").is_file()
    )


def validate_skill_selectors(selected_skills: set[str], skip_skills: set[str]) -> None:
    known = {path.name for path in skill_dirs()}
    unknown = sorted((selected_skills | skip_skills) - known)
    if unknown:
        raise ValueError("unknown skill selector(s): " + ", ".join(unknown))
    overlap = sorted(selected_skills & skip_skills)
    if overlap:
        raise ValueError("skills cannot be both selected and skipped: " + ", ".join(overlap))


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


def command_uses_direct_secret(argv: list[str]) -> bool:
    direct_flags = {
        "-P",
        "-p",
        "-t",
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
        flag = item.split("=", 1)[0] if item.startswith("-") else item
        if flag in direct_flags:
            return True
    return False


def validation_env(profile: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in PROFILE_BOUND_ENV_KEYS:
        env.pop(key, None)
    for key in list(env):
        normalized = re.sub(r"[^A-Z0-9]", "_", key.upper())
        secret_shaped = re.search(
            r"(^|_)(PASSWORD|PASSWD|PWD|SECRET|TOKEN|API_KEY|API_SECRET|PRIVATE_KEY|"
            r"SESSION_KEY|AUTHORIZATION|AUTH_HEADER|ACCESS_KEY)($|_)",
            normalized,
        )
        file_reference = normalized.endswith(("_FILE", "_PATH", "_NAME", "_ID", "_SOCK"))
        credential_id = normalized in {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
        if (secret_shaped and not file_reference) or credential_id:
            env.pop(key, None)
    env["SPLUNK_PROFILE"] = profile
    env["PYTHONUNBUFFERED"] = "1"
    env["SPLUNK_SKILLS_LIVE_VALIDATION"] = "1"
    env["SPLUNK_NONINTERACTIVE"] = "1"
    return env


_STOP_REQUESTED = False


def _stop_requested() -> bool:
    return _STOP_REQUESTED


def _append_bounded_output(
    sink: bytearray,
    chunk: bytes,
    *,
    dropped: list[int],
    max_output_bytes: int,
) -> None:
    remaining = max_output_bytes - len(sink)
    if remaining > 0:
        sink.extend(chunk[:remaining])
    dropped[0] += max(0, len(chunk) - max(0, remaining))


def _terminate_process(process: subprocess.Popen[bytes], *, force: bool) -> None:
    if os.name == "posix" and hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            return
        except (OSError, ProcessLookupError):
            pass
    if process.poll() is None:
        try:
            process.kill() if force else process.terminate()
        except (OSError, ProcessLookupError):
            pass


def run_command(
    argv: list[str],
    *,
    profile: str,
    timeout_seconds: int,
    cwd: Path = REPO_ROOT,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
) -> subprocess.CompletedProcess[str]:
    if _stop_requested():
        raise RunnerInterrupted(stderr="interrupt requested before command start")
    if max_output_bytes < 1 or max_output_bytes > MAX_REST_ENVELOPE_BYTES:
        raise ValueError("max_output_bytes is outside the bounded runner limit")
    if command_uses_direct_secret(argv):
        raise ValueError(
            f"Refusing command with direct secret-bearing argv: {redact(shell_join(argv))}"
        )
    process: subprocess.Popen[bytes] = subprocess.Popen(
        argv,
        cwd=cwd,
        env=validation_env(profile),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    selector = selectors.DefaultSelector()
    streams = {"stdout": process.stdout, "stderr": process.stderr}
    for name, stream in streams.items():
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, name)
    stdout_buf = bytearray()
    stderr_buf = bytearray()
    stdout_dropped = [0]
    stderr_dropped = [0]
    deadline = time.monotonic() + timeout_seconds
    termination_reason = ""
    termination_started: float | None = None
    force_sent = False
    exit_seen: float | None = None

    def begin_termination(reason: str) -> None:
        nonlocal termination_reason, termination_started
        if termination_reason:
            return
        termination_reason = reason
        termination_started = time.monotonic()
        _terminate_process(process, force=False)

    try:
        while process.poll() is None or selector.get_map():
            now = time.monotonic()
            if _stop_requested():
                begin_termination("interrupted")
            elif now >= deadline:
                begin_termination("timeout")

            returncode = process.poll()
            if returncode is not None and exit_seen is None:
                exit_seen = now
            if (
                returncode is not None
                and selector.get_map()
                and not termination_reason
                and exit_seen is not None
                and now - exit_seen >= PROCESS_PIPE_GRACE_SECONDS
            ):
                # The process-group leader is already gone. A detached
                # descendant can keep inherited pipe descriptors open, but it
                # is outside that dead leader's process group. Close our pipe
                # ends immediately and fail instead of waiting through the
                # live-process TERM/KILL grace period.
                termination_reason = "lingering-output-pipe"
                break

            if termination_started is not None:
                elapsed = now - termination_started
                if elapsed >= PROCESS_TERM_GRACE_SECONDS and not force_sent:
                    _terminate_process(process, force=True)
                    force_sent = True
                if elapsed >= PROCESS_TERM_GRACE_SECONDS + PROCESS_PIPE_GRACE_SECONDS:
                    break

            if returncode is not None and not selector.get_map():
                break

            wait_for = 0.05
            if not termination_reason:
                wait_for = min(wait_for, max(0.0, deadline - now))
            events = selector.select(wait_for)
            for key, _mask in events:
                stream = key.fileobj
                # Bound each drain pass so a continuously writing child cannot
                # starve timeout and interrupt checks in the outer loop.
                for _read_attempt in range(16):
                    try:
                        chunk = os.read(stream.fileno(), 65536)
                    except BlockingIOError:
                        break
                    if not chunk:
                        try:
                            selector.unregister(stream)
                        except KeyError:
                            pass
                        stream.close()
                        break
                    if key.data == "stdout":
                        _append_bounded_output(
                            stdout_buf,
                            chunk,
                            dropped=stdout_dropped,
                            max_output_bytes=max_output_bytes,
                        )
                    else:
                        _append_bounded_output(
                            stderr_buf,
                            chunk,
                            dropped=stderr_dropped,
                            max_output_bytes=max_output_bytes,
                        )
    finally:
        for key in list(selector.get_map().values()):
            stream = key.fileobj
            try:
                selector.unregister(stream)
            except KeyError:
                pass
            try:
                stream.close()
            except OSError:
                pass
        selector.close()
        if process.poll() is None:
            _terminate_process(process, force=True)
        try:
            returncode = process.wait(timeout=PROCESS_PIPE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            returncode = -signal.SIGKILL
    stdout = bytes(stdout_buf).decode("utf-8", errors="replace")
    stderr = bytes(stderr_buf).decode("utf-8", errors="replace")
    if stdout_dropped[0]:
        stdout += f"\n...[dropped {stdout_dropped[0]} bytes from stdout]"
    if stderr_dropped[0]:
        stderr += f"\n...[dropped {stderr_dropped[0]} bytes from stderr]"
    if termination_reason == "interrupted":
        raise RunnerInterrupted(stdout=stdout, stderr=stderr or "interrupt requested")
    if termination_reason == "timeout":
        raise subprocess.TimeoutExpired(
            argv,
            timeout_seconds,
            output=stdout,
            stderr=stderr,
        ) from None
    if termination_reason == "lingering-output-pipe":
        stderr += "\nERROR: command exited while a detached descendant retained its output pipe."
        returncode = returncode or 98
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


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


def run_internal_evidence_gate(path: Path) -> subprocess.CompletedProcess[str]:
    try:
        raw = read_secure_bytes(path)
        if raw is None:
            raise ValueError("live evidence file is missing")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("live evidence root must be a JSON object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return subprocess.CompletedProcess(
            ["[internal]", "validate-live-evidence", str(path)],
            2,
            "",
            f"ERROR: unable to validate live evidence: {exc}",
        )
    collection = payload.get("collection")
    rest = payload.get("rest")
    fatal_errors = collection.get("fatal_errors", []) if isinstance(collection, dict) else []
    probe_errors = rest.get("probe_errors", []) if isinstance(rest, dict) else []
    if fatal_errors:
        message = "ERROR: profile safety gate failed: " + "; ".join(map(str, fatal_errors))
        return subprocess.CompletedProcess(
            ["[internal]", "validate-live-evidence", str(path)], 2, "", message
        )
    if not isinstance(rest, dict) or rest.get("reachable") is not True or probe_errors:
        message = (
            "ERROR: required Splunk REST probes were not all successful: "
            + ", ".join(map(str, probe_errors or ["REST reachability unassessed"]))
        )
        return subprocess.CompletedProcess(
            ["[internal]", "validate-live-evidence", str(path)], 2, "", message
        )
    if payload.get("platform") == "enterprise":
        remote = payload.get("remote_splunk_home")
        checks = remote.get("checks") if isinstance(remote, dict) else None
        version = checks.get("version") if isinstance(checks, dict) else None
        if not isinstance(version, dict) or version.get("returncode") != 0:
            return subprocess.CompletedProcess(
                ["[internal]", "validate-live-evidence", str(path)],
                2,
                "",
                "ERROR: required Enterprise SSH Splunk version evidence was not collected successfully.",
            )
    return subprocess.CompletedProcess(
        ["[internal]", "validate-live-evidence", str(path)],
        0,
        json.dumps({"ok": True, "platform": payload.get("platform", "unknown")}),
        "",
    )


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

    if step.skip_reason:
        result = StepResult(
            step_id=step.step_id,
            category=step.category,
            skill=step.skill,
            mode=step.mode,
            status="intentional-skip",
            command=redact(shell_join(step.command)),
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
    interrupted = False
    returncode: int | None
    stdout = ""
    stderr = ""
    try:
        if step.mode == "evidence-gate":
            completed = run_internal_evidence_gate(Path(step.command[-1]))
        else:
            completed = run_command(
                step.command,
                profile=profile,
                timeout_seconds=step.timeout_seconds,
            )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except RunnerInterrupted as exc:
        returncode = 130
        stdout = exc.stdout
        stderr = exc.stderr or "interrupt requested"
        interrupted = True
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

    classification = (
        ""
        if returncode == 0
        else "interrupted"
        if interrupted
        else classify_failure(step, returncode, stdout, stderr)
    )
    if returncode == 0:
        status = "pass"
    elif should_intentional_skip(step, classification):
        status = "intentional-skip"
    else:
        status = "fail"

    notes: list[str] = []
    if timed_out:
        notes.append(f"Timed out after {step.timeout_seconds}s.")
    if interrupted:
        notes.append("Interrupted by operator request.")
    if status == "intentional-skip" and not notes:
        notes.append(f"Classified as {classification}; no repo fix is appropriate without more live configuration.")

    result = StepResult(
        step_id=step.step_id,
        category=step.category,
        skill=step.skill,
        mode=step.mode,
        status=status,
        command=redact(shell_join(step.command)),
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


def parse_json_text(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        # Some Splunk endpoints can emit warnings before JSON. Try the last
        # JSON object in the stream before giving up.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
                return payload if isinstance(payload, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def parse_json_output(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if result.returncode != 0:
        return {}
    return parse_json_text(result.stdout)


def parse_splunk_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    entries = payload.get("entry", [])
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def entry_content(entry: dict[str, Any]) -> dict[str, Any]:
    content = entry.get("content", {})
    return content if isinstance(content, dict) else {}


def rest_probe(endpoint: str, *, profile: str, timeout_seconds: int = SPLUNK_REST_TIMEOUT_SECONDS) -> RestProbeResult:
    try:
        result = run_command(
            ["bash", "-c", SPLUNK_REST_PROBE_SCRIPT, "splunk-rest-probe", endpoint],
            profile=profile,
            timeout_seconds=timeout_seconds,
            max_output_bytes=MAX_REST_ENVELOPE_BYTES,
        )
    except subprocess.TimeoutExpired as exc:
        return RestProbeResult({}, None, None, None, False, False, f"timed out after {exc.timeout}s")
    except (OSError, ValueError) as exc:
        return RestProbeResult({}, None, None, None, False, False, f"probe failed: {exc}")
    envelope = parse_json_text(result.stdout)
    payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
    return RestProbeResult(
        payload=payload,
        process_returncode=result.returncode,
        curl_returncode=envelope.get("curl_returncode") if isinstance(envelope.get("curl_returncode"), int) else None,
        http_status=envelope.get("http_status") if isinstance(envelope.get("http_status"), int) else None,
        json_valid=envelope.get("json_valid") is True,
        entry_schema_valid=envelope.get("entry_schema_valid") is True,
        error=str(envelope.get("error") or redact(result.stderr[-1000:])),
    )


def ssh_cli_probe(
    remote_command: str,
    *,
    profile: str,
    service_user: str = "splunk",
    timeout_seconds: int = SPLUNK_REST_TIMEOUT_SECONDS,
) -> tuple[str, str, int | None]:
    try:
        result = run_command(
            ["bash", "-c", SSH_SPLUNK_CLI_SCRIPT, "ssh-splunk-cli", service_user, remote_command],
            profile=profile,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return redact(stdout), redact(stderr or f"timed out after {exc.timeout}s"), None
    except (OSError, ValueError) as exc:
        return "", redact(f"probe failed: {exc}"), None
    return redact(result.stdout), redact(result.stderr), result.returncode


def profile_metadata(profile: str, *, allow_flat_credentials: bool = False) -> dict[str, Any]:
    try:
        result = run_command(
            [
                "bash",
                "-c",
                SPLUNK_PROFILE_METADATA_SCRIPT,
                "splunk-profile-metadata",
                "true" if allow_flat_credentials else "false",
            ],
            profile=profile,
            timeout_seconds=60,
        )
    except subprocess.TimeoutExpired:
        return {"metadata_error": "profile metadata probe timed out", "metadata_returncode": None}
    payload = parse_json_text(result.stdout)
    if result.returncode != 0:
        payload["metadata_error"] = redact(result.stderr[-2000:]) or "profile metadata probe failed"
        payload["metadata_returncode"] = result.returncode
    return payload


def valid_management_hostname(hostname: str) -> bool:
    candidate = hostname.rstrip(".")
    if not candidate or len(candidate) > 253 or any(character.isspace() for character in candidate):
        return False
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    return all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        is not None
        for label in candidate.split(".")
    )


def profile_gate_evidence(
    profile: str,
    requested_platform: str = "auto",
    *,
    allow_flat_credentials: bool = False,
) -> dict[str, Any]:
    """Resolve and validate target metadata without contacting the target."""
    metadata = profile_metadata(profile, allow_flat_credentials=allow_flat_credentials)
    declared_platform = str(metadata.get("platform", "")).strip().lower()
    fatal_errors: list[str] = []
    if metadata.get("metadata_error"):
        fatal_errors.append(str(metadata["metadata_error"]))
    if declared_platform and declared_platform not in {"cloud", "enterprise"}:
        fatal_errors.append(f"profile declared unsupported platform {declared_platform!r}")
    if (
        requested_platform in {"cloud", "enterprise"}
        and declared_platform in {"cloud", "enterprise"}
        and requested_platform != declared_platform
    ):
        fatal_errors.append(
            f"requested platform {requested_platform!r} conflicts with profile platform {declared_platform!r}"
        )
    if requested_platform in {"cloud", "enterprise"}:
        platform = requested_platform
    elif declared_platform in {"cloud", "enterprise"}:
        platform = declared_platform
    else:
        platform = "enterprise"
        fatal_errors.append("profile must declare cloud or enterprise when --platform=auto")

    splunk_uri = str(metadata.get("splunk_uri", ""))
    verify_ssl_text = str(metadata.get("verify_ssl", "true")).strip().lower()
    if verify_ssl_text in {"true", "1", "yes"}:
        verify_ssl = True
    elif verify_ssl_text in {"false", "0", "no"}:
        verify_ssl = False
    else:
        verify_ssl = False
        fatal_errors.append("profile SPLUNK_VERIFY_SSL must be an explicit true/false value")
    uri_has_unsafe_whitespace = any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in splunk_uri
    )
    if uri_has_unsafe_whitespace:
        fatal_errors.append("Splunk management URI must not contain whitespace or control characters")
    try:
        uri_parts = urlsplit(splunk_uri) if not uri_has_unsafe_whitespace else urlsplit("")
        hostname = uri_parts.hostname or ""
        port = uri_parts.port
    except ValueError:
        uri_parts = urlsplit("")
        hostname = ""
        port = None
        fatal_errors.append("profile contains an invalid Splunk management URI")
    if not splunk_uri or not uri_parts.netloc or not hostname or not valid_management_hostname(hostname):
        fatal_errors.append("profile did not resolve a concrete Splunk management URI")
    elif uri_parts.scheme.lower() != "https":
        fatal_errors.append("live validation requires an HTTPS Splunk management URI")
    if uri_parts.username is not None or uri_parts.password is not None or "@" in uri_parts.netloc:
        fatal_errors.append("Splunk management URI must not embed credentials")
    if uri_parts.path not in {"", "/"}:
        fatal_errors.append("Splunk management URI must not include a path")
    if uri_parts.query or uri_parts.fragment:
        fatal_errors.append("Splunk management URI must not include a query or fragment")
    if uri_parts.netloc.endswith(":") or port == 0:
        fatal_errors.append("Splunk management URI contains an invalid port")
    if not verify_ssl:
        fatal_errors.append("live validation refuses SPLUNK_VERIFY_SSL=false")
    return {
        "platform": platform,
        "collection": {
            "profile": profile,
            "scope": "profile_gate",
            "collected_at": utc_now(),
            "notes": [],
            "fatal_errors": fatal_errors,
        },
        "rest": {
            "reachable": None,
            "denied": None,
            "tls_verified": verify_ssl,
        },
        "inputs": {
            "splunk_uri": splunk_uri,
            "target_role": metadata.get("target_role", ""),
        },
    }


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
    *,
    allow_flat_credentials: bool = False,
) -> dict[str, Any]:
    evidence = profile_gate_evidence(
        profile,
        requested_platform,
        allow_flat_credentials=allow_flat_credentials,
    )
    evidence["collection"]["scope"] = "full_live_evidence"
    platform = str(evidence["platform"])
    fatal_errors = evidence["collection"]["fatal_errors"]
    if fatal_errors:
        evidence["rest"]["probe_errors"] = list(fatal_errors)
        write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)
        return evidence

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
    required_names = ("server_info", "server_sysinfo", "apps")
    raw: dict[str, RestProbeResult] = {}

    def collect_rest_probe(name: str, endpoint: str) -> None:
        if _stop_requested():
            raise RunnerInterrupted(stderr="interrupt requested during REST evidence collection")
        probe = rest_probe(endpoint, profile=profile)
        raw[name] = probe
        if not probe.ok or not probe.entry_schema_valid:
            status = probe.http_status if probe.http_status is not None else "no HTTP status"
            detail = probe.error or "response did not match the expected Splunk entry schema"
            evidence["collection"]["notes"].append(f"{name} endpoint: {status}; {detail}.")

    # The three required probes establish that the selected target is both
    # reachable and authorized. Do not spend time or issue more requests when
    # this baseline is incomplete.
    for name in required_names:
        collect_rest_probe(name, endpoints[name])
    required_ok = [raw[name].ok and raw[name].entry_schema_valid for name in required_names]
    denied_statuses = [
        raw[name].http_status for name in required_names if raw[name].http_status in {401, 403}
    ]
    evidence["rest"]["reachable"] = any(required_ok)
    evidence["rest"]["denied"] = True if denied_statuses else (False if all(required_ok) else None)
    evidence["rest"]["status_code"] = denied_statuses[0] if denied_statuses else None
    evidence["rest"]["probe_errors"] = [name for name, ok in zip(required_names, required_ok) if not ok]

    probe_summary = {
        name: {
            "process_returncode": item.process_returncode,
            "curl_returncode": item.curl_returncode,
            "http_status": item.http_status,
            "json_valid": item.json_valid,
            "entry_schema_valid": item.entry_schema_valid,
            "entry_count": len(parse_splunk_entries(item.payload)),
            "response_present": bool(item.payload),
            "ok": item.ok and item.entry_schema_valid,
            "error": item.error,
        }
        for name, item in raw.items()
    }
    write_json(run_dir / "evidence" / "splunk-rest-probes.redacted.json", probe_summary)

    server_entries = parse_splunk_entries(raw["server_info"].payload) if raw["server_info"].ok else []
    if server_entries:
        content = entry_content(server_entries[0])
        evidence["server"] = {
            "name": content.get("serverName") or server_entries[0].get("name", ""),
            "guid": content.get("guid", ""),
            "version": content.get("version", ""),
            "build": content.get("build", ""),
            "server_roles": content.get("server_roles", []),
        }

    apps_assessed = raw["apps"].ok and raw["apps"].entry_schema_valid
    app_entries = parse_splunk_entries(raw["apps"].payload) if apps_assessed else []
    apps = []
    restart_required = []
    for entry in app_entries:
        name = str(entry.get("name", ""))
        content = entry_content(entry)
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
    evidence["apps"] = {
        "installed": apps if apps_assessed else None,
        "restart_required": restart_required if apps_assessed else None,
    }

    if not all(required_ok):
        evidence["monitoring_console"] = {
            "installed": (
                any(app["name"] == "splunk_monitoring_console" and not app["disabled"] for app in apps)
                if apps_assessed
                else None
            ),
            "configured": None,
            "platform_alerts_enabled": None,
        }
        evidence["remote_splunk_home"] = {
            "enabled": platform == "enterprise",
            "checks": {},
            "reason": "Enterprise SSH probes were not attempted because required REST evidence failed.",
        }
        write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)
        return evidence

    for name, endpoint in endpoints.items():
        if name not in required_names:
            collect_rest_probe(name, endpoint)

    probe_summary = {
        name: {
            "process_returncode": item.process_returncode,
            "curl_returncode": item.curl_returncode,
            "http_status": item.http_status,
            "json_valid": item.json_valid,
            "entry_schema_valid": item.entry_schema_valid,
            "entry_count": len(parse_splunk_entries(item.payload)),
            "response_present": bool(item.payload),
            "ok": item.ok and item.entry_schema_valid,
            "error": item.error,
        }
        for name, item in raw.items()
    }
    write_json(run_dir / "evidence" / "splunk-rest-probes.redacted.json", probe_summary)

    indexes_assessed = raw["indexes"].ok and raw["indexes"].entry_schema_valid
    index_entries = parse_splunk_entries(raw["indexes"].payload) if indexes_assessed else []
    evidence["indexes"] = {
        "present": sorted(entry.get("name", "") for entry in index_entries if entry.get("name"))
        if indexes_assessed
        else None,
    }

    hec_assessed = raw["hec"].ok and raw["hec"].entry_schema_valid
    hec_entries = parse_splunk_entries(raw["hec"].payload) if hec_assessed else []
    if not hec_assessed:
        evidence["hec"] = {"enabled": None, "assessed": False, "token_count": None}
    elif hec_entries:
        # The global HEC endpoint usually appears as http. If every stanza is
        # disabled, call the HEC service unavailable.
        disabled_values = [entry_content(entry).get("disabled") for entry in hec_entries]
        hec_disabled = all(str(value).lower() in {"1", "true"} for value in disabled_values)
        evidence["hec"] = {"enabled": not hec_disabled, "assessed": True, "token_count": len(hec_entries)}
    else:
        evidence["hec"] = {"enabled": False, "assessed": True, "token_count": 0}

    health_payload = raw["splunkd_health"].payload if raw["splunkd_health"].ok else {}
    health_entries = parse_splunk_entries(health_payload)
    health_status = ""
    failures: list[str] = []
    if health_entries:
        health_content = entry_content(health_entries[0])
        health_status = str(
            health_content.get("health") or health_content.get("status") or health_content.get("color") or ""
        ).lower()
        for key, value in health_content.items():
            if isinstance(value, str) and value.lower() in {"red", "yellow", "degraded", "failed"}:
                failures.append(f"{key}={value}")
    evidence["splunkd"] = {"health": {"status": health_status or "unknown", "failures": failures}}

    kv_payload = raw["kvstore"].payload if raw["kvstore"].ok else {}
    kv_entries = parse_splunk_entries(kv_payload)
    kv_status = "unknown"
    if kv_entries:
        kv_content = entry_content(kv_entries[0])
        current = kv_content.get("current", {})
        current_status = current.get("status") if isinstance(current, dict) else None
        kv_status = str(current_status or kv_content.get("status") or "unknown").lower()
    evidence["kvstore"] = {"status": kv_status}

    license_assessed = raw["license_messages"].ok and raw["license_messages"].entry_schema_valid
    license_entries = parse_splunk_entries(raw["license_messages"].payload) if license_assessed else []
    violation_messages = []
    for entry in license_entries:
        content = entry_content(entry)
        classification = " ".join(
            str(content.get(key, "")) for key in ("category", "severity", "type", "message")
        ).lower()
        if any(marker in classification for marker in ("violation", "error", "exceeded")):
            violation_messages.append(entry.get("name", ""))
    evidence["license"] = {
        "messages": violation_messages if license_assessed else None,
        "violation_count": len(violation_messages) if license_assessed else None,
        "message_count": len(license_entries) if license_assessed else None,
    }

    # Saved-search metadata does not prove scheduler skips. Leave the skip
    # signal explicitly unassessed unless scheduler/internal-log evidence is supplied.
    evidence["scheduler"] = {"skipped_count": None, "skipped_searches": None}

    peers_assessed = raw["distsearch"].ok and raw["distsearch"].entry_schema_valid
    peer_entries = parse_splunk_entries(raw["distsearch"].payload) if peers_assessed else []
    peers_down = []
    for entry in peer_entries:
        content = entry_content(entry)
        status = str(content.get("status") or content.get("server_status") or "").lower()
        if status and status not in {"up", "healthy", "ok"}:
            peers_down.append(entry.get("name", ""))
    evidence["distributed_search"] = {"peers_down": peers_down if peers_assessed else None}

    shc_assessed = raw["shc"].ok and raw["shc"].entry_schema_valid
    if shc_assessed:
        shc_payload = raw["shc"].payload
        shc_issues = nested_status_findings(shc_payload)
        replication_healthy = nested_bool(shc_payload, {"replication_healthy", "is_healthy", "service_ready"})
        evidence["shc"] = {
            "status": "degraded" if shc_issues else "healthy",
            "issues": shc_issues,
            "replication_healthy": replication_healthy,
        }
    else:
        evidence["shc"] = {"status": "not_assessed", "issues": None}
    idxc_assessed = raw["indexer_cluster"].ok and raw["indexer_cluster"].entry_schema_valid
    if idxc_assessed:
        idxc_payload = raw["indexer_cluster"].payload
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
        "installed": (
            any(app["name"] == "splunk_monitoring_console" and not app["disabled"] for app in apps)
            if apps_assessed
            else None
        ),
        "configured": None,
        "platform_alerts_enabled": None,
    }
    evidence["support"] = {"diag_ready": None, "diag_blockers": None}
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
    if _stop_requested():
        raise RunnerInterrupted(stderr="interrupt requested before Enterprise SSH evidence collection")
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
        required_error = "Required remote SSH Splunk version check failed."
        evidence["collection"]["notes"].append(required_error)
        evidence["collection"].setdefault("required_errors", []).append(required_error)
        evidence["remote_splunk_home"] = remote_summary
        evidence["btool"] = {"errors": None}
        evidence["support"] = {"diag_ready": None, "diag_blockers": None}
        write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)
        return evidence

    if _stop_requested():
        raise RunnerInterrupted(stderr="interrupt requested during Enterprise SSH evidence collection")
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
    if btool_rc == 0:
        evidence["btool"] = {"errors": []}
    elif btool_rc not in {None, 255} and any(
        marker in (btool_err + "\n" + btool_out).lower()
        for marker in ("invalid key in stanza", "no spec file for:", "error")
    ):
        evidence["btool"] = {"errors": [(btool_err or btool_out)[-4000:]]}
    else:
        evidence["btool"] = {"errors": None}
        evidence["collection"]["notes"].append("Remote btool evidence was not assessed.")

    if _stop_requested():
        raise RunnerInterrupted(stderr="interrupt requested during Enterprise SSH evidence collection")
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

    if _stop_requested():
        raise RunnerInterrupted(stderr="interrupt requested during Enterprise SSH evidence collection")
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
    if diag_rc == 0:
        evidence["support"] = {"diag_ready": True, "diag_blockers": []}
    elif diag_rc not in {None, 255}:
        evidence["support"] = {
            "diag_ready": False,
            "diag_blockers": [(diag_err or diag_out)[-2000:]],
        }
    else:
        evidence["support"] = {"diag_ready": None, "diag_blockers": None}
        evidence["collection"]["notes"].append("Remote diag readiness was not assessed.")

    evidence["remote_splunk_home"] = remote_summary

    write_json(run_dir / "evidence" / "live-evidence.redacted.json", evidence)
    return evidence


def build_baseline_steps(
    profile: str,
    run_dir: Path,
    platform: str = "enterprise",
) -> list[ValidationStep]:
    del profile, platform  # Collection already used the selected profile and platform.
    return [
        ValidationStep(
            step_id="baseline-live-evidence-gate",
            category="baseline",
            command=[
                "[internal]",
                "validate-live-evidence",
                str(run_dir / "evidence" / "live-evidence.redacted.json"),
            ],
            mode="evidence-gate",
            timeout_seconds=30,
            metadata={
                "scope": "Validate the already-collected profile and required REST evidence; no duplicate target probes."
            },
        )
    ]


def read_only_mode_steps(
    skill: str,
    run_dir: Path,
    platform: str = "enterprise",
    *,
    allow_offline_smoke: bool = False,
) -> list[ValidationStep]:
    del run_dir, platform
    steps: list[ValidationStep] = []
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
    if allow_offline_smoke and has_script(skill, "smoke_offline.sh"):
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
    allow_offline_smoke: bool = False,
) -> list[ValidationStep]:
    selected_skills = selected_skills or set()
    skip_skills = skip_skills or set()
    doctor_in_scope = (
        "splunk-admin-doctor" not in skip_skills
        and (not selected_skills or "splunk-admin-doctor" in selected_skills)
    )
    full_sweep = not selected_skills
    steps = build_baseline_steps(profile, run_dir, platform) if full_sweep or doctor_in_scope else []
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
        steps.extend(
            read_only_mode_steps(
                skill,
                run_dir,
                platform,
                allow_offline_smoke=allow_offline_smoke,
            )
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
    raw = read_secure_bytes(path)
    if raw is None:
        return {"version": 1, "steps": {}, "runs": []}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return {"version": 1, "steps": {}, "runs": []}
    if (
        not isinstance(payload, dict)
        or payload.get("version", 1) != 1
        or not isinstance(payload.get("steps", {}), dict)
        or not isinstance(payload.get("runs", []), list)
    ):
        return {"version": 1, "steps": {}, "runs": []}
    payload["version"] = 1
    payload.setdefault("steps", {})
    payload.setdefault("runs", [])
    return payload


def save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    write_json(path, checkpoint)


@contextmanager
def exclusive_output_lock(output_dir: Path):
    lock_path = output_dir / ".live-validation.lock"
    parent_fd, name = _open_secure_parent(lock_path)
    descriptor: int | None = None
    try:
        parent_metadata = os.fstat(parent_fd)
        if parent_metadata.st_uid != os.geteuid() or stat.S_IMODE(parent_metadata.st_mode) & 0o022:
            raise PermissionError(
                f"live validation output directory must be owned by the current user and not group/world writable: {output_dir}"
            )
        lock_flags = os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(
                name,
                lock_flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            # Open a concurrently created persistent lock only after O_EXCL
            # proves that this process did not create it. O_NOFOLLOW keeps a
            # competing symlink from becoming the lock target.
            descriptor = os.open(name, lock_flags, dir_fd=parent_fd)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise OSError(f"unsafe live validation lock file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"another live validation runner is already active for {output_dir}") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(descriptor)
        os.close(parent_fd)


RUN_DIRECTORY_RE = re.compile(
    r"^\d{8}T\d{6}Z-iter[1-9][0-9]*(?:-p[1-9][0-9]*-[0-9a-f]{8})?$"
)


def _remove_tree_at(parent_fd: int, name: str) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    parent_metadata = os.fstat(parent_fd)
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(parent_metadata.st_mode) & 0o022
    ):
        raise PermissionError(f"refusing to prune through an unsafe parent directory: {name}")
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        metadata = os.fstat(descriptor)
        if metadata.st_dev != parent_metadata.st_dev:
            raise OSError(f"refusing to cross a filesystem boundary while pruning: {name}")
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise PermissionError(f"refusing to prune unsafe run directory: {name}")
        with os.scandir(descriptor) as entries:
            for entry in entries:
                entry_metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(entry_metadata.st_mode):
                    _remove_tree_at(descriptor, entry.name)
                else:
                    os.unlink(entry.name, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    os.rmdir(name, dir_fd=parent_fd)


def prune_run_history(output_dir: Path, current_run_dir: Path, retain_runs: int) -> list[str]:
    if retain_runs < 1 or retain_runs > MAX_RETAIN_RUNS:
        raise ValueError(f"retain_runs must be between 1 and {MAX_RETAIN_RUNS}")
    runs_dir = output_dir / "runs"
    parent_fd, _unused = _open_secure_parent(runs_dir / ".retention-sentinel")
    candidates: list[tuple[str, int]] = []
    try:
        parent_metadata = os.fstat(parent_fd)
        if (
            parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) & 0o022
        ):
            raise PermissionError(
                "run-history directory must be owned by the current user and not group/world writable"
            )
        with os.scandir(parent_fd) as entries:
            for entry in entries:
                if not RUN_DIRECTORY_RE.fullmatch(entry.name):
                    continue
                metadata = entry.stat(follow_symlinks=False)
                if not stat.S_ISDIR(metadata.st_mode):
                    continue
                if metadata.st_uid != os.geteuid():
                    raise PermissionError(f"refusing to inspect non-owned run directory: {entry.name}")
                candidates.append((entry.name, metadata.st_mtime_ns))

        current_name = current_run_dir.name
        newest = sorted(candidates, key=lambda item: (item[1], item[0]), reverse=True)
        ordered_names = [current_name, *(name for name, _mtime in newest if name != current_name)]
        keep = set(ordered_names[:retain_runs])
        removed: list[str] = []
        for name, _mtime in newest:
            if name in keep:
                continue
            _remove_tree_at(parent_fd, name)
            removed.append(name)
        return removed
    finally:
        os.close(parent_fd)


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
            summary[skill] = {"status": "not-run", "reason": "No result was recorded."}
            continue
        statuses = {row.status for row in rows}
        interface = [row for row in rows if row.mode.endswith("-help") or row.mode == "setup-help"]
        substantive = [
            row
            for row in rows
            if row not in interface and row.mode != "operator-skip"
        ]
        substantive_successes = [
            row for row in substantive if row.status in {"pass", "fixed-pass"}
        ]
        substantive_skips = [row for row in substantive if row.status == "intentional-skip"]
        interface_successes = [row for row in interface if row.status in {"pass", "fixed-pass"}]
        if "fail" in statuses:
            final = "fail"
        elif substantive_successes and substantive_skips:
            final = "partial-pass"
        elif substantive_successes:
            final = "feature-pass"
        elif substantive:
            final = "unassessed"
        elif interface_successes:
            final = "interface-pass"
        else:
            final = "intentional-skip"
        if substantive:
            validation_depth = "feature_validation"
        elif interface:
            validation_depth = "interface_only"
        else:
            validation_depth = "none"
        summary[skill] = {
            "status": final,
            "validation_depth": validation_depth,
            "steps": len(rows),
            "substantive_steps": len(substantive),
            "passed": sum(1 for row in rows if row.status in {"pass", "fixed-pass"}),
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
        f"- Execution complete: `{payload.get('execution_complete', False)}`",
        f"- Steps executed/planned: `{payload.get('executed_steps', 0)}/{payload.get('planned_steps', 0)}`",
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


def build_rerun_command(
    args: argparse.Namespace,
    *,
    effective_platform: str,
    output_dir: Path,
) -> str:
    command = [
        "python3",
        "skills/splunk-admin-doctor/scripts/live_validate_all.py",
        "--profile",
        args.profile,
        "--platform",
        effective_platform,
        "--output-dir",
        str(output_dir),
        "--max-retained-runs",
        str(args.max_retained_runs),
        "--once",
    ]
    for enabled, flag in (
        (args.allow_apply, "--allow-apply"),
        (args.allow_flat_credentials, "--allow-flat-credentials"),
        (args.force_rerun, "--force-rerun"),
        (args.stop_on_failure, "--stop-on-failure"),
        (args.allow_offline_smoke, "--allow-offline-smoke"),
        (args.quiet, "--quiet"),
        (args.json, "--json"),
    ):
        if enabled:
            command.append(flag)
    for skill in args.skill or []:
        command.extend(["--skill", skill])
    for skill in args.skip_skill or []:
        command.extend(["--skip-skill", skill])
    return shell_join(command)


def internal_failure_result(
    *,
    run_dir: Path,
    ledger_path: Path,
    step_id: str,
    message: str,
    classification: str,
) -> StepResult:
    timestamp = utc_now()
    stderr_log = run_dir / "logs" / f"{safe_name(step_id)}.stderr.log"
    safe_message = redact(message)
    write_text_secure(stderr_log, safe_message.rstrip() + "\n")
    result = StepResult(
        step_id=step_id,
        category="baseline",
        skill="",
        mode="internal-safety-gate",
        status="fail",
        command="[internal runner safety gate]",
        read_only=True,
        mutates=False,
        returncode=None,
        started_at=timestamp,
        ended_at=timestamp,
        duration_seconds=0.0,
        stderr_log=str(stderr_log.relative_to(run_dir)),
        classification=classification,
        notes=[safe_message],
    )
    append_jsonl(ledger_path, asdict(result))
    return result


def not_run_result(step: ValidationStep, *, reason: str) -> StepResult:
    timestamp = utc_now()
    return StepResult(
        step_id=step.step_id,
        category=step.category,
        skill=step.skill,
        mode=step.mode,
        status="intentional-skip",
        command=redact(shell_join(step.command)),
        read_only=step.read_only,
        mutates=step.mutates,
        returncode=None,
        started_at=timestamp,
        ended_at=timestamp,
        duration_seconds=0.0,
        classification="not_run_after_failure",
        notes=[reason],
        metadata=step.metadata,
    )


def finalize_run(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    run_dir: Path,
    run_id: str,
    started: str,
    effective_platform: str,
    steps: list[ValidationStep],
    results: list[StepResult],
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    ledger_path: Path,
) -> dict[str, Any]:
    pruned_runs: list[str] = []
    try:
        pruned_runs = prune_run_history(output_dir, run_dir, args.max_retained_runs)
    except Exception as exc:  # noqa: BLE001 - retention failure is a hard, reportable safety failure.
        results.append(
            internal_failure_result(
                run_dir=run_dir,
                ledger_path=ledger_path,
                step_id="baseline-run-retention",
                message=f"{type(exc).__name__}: {exc}",
                classification="filesystem_safety_gate",
            )
        )
    totals: dict[str, int] = {}
    for result in results:
        totals[result.status] = totals.get(result.status, 0) + 1
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "run_id": run_id,
        "profile": args.profile,
        "platform": effective_platform,
        "allow_apply": args.allow_apply,
        "started_at": started,
        "ended_at": utc_now(),
        "output_dir": str(run_dir),
        "ledger": str(ledger_path),
        "planned_steps": len(steps),
        "executed_steps": sum(
            1 for row in results if row.classification != "not_run_after_failure"
        ),
        "execution_complete": not any(
            row.classification == "not_run_after_failure"
            or row.mode == "internal-safety-gate"
            for row in results
        ),
        "totals": totals,
        "retained_run_limit": args.max_retained_runs,
        "pruned_runs": pruned_runs,
        "skills": summarize_skill_status(results, steps),
        "results": [asdict(result) for result in results],
        "rerun_command": build_rerun_command(
            args,
            effective_platform=effective_platform,
            output_dir=output_dir,
        ),
    }
    write_json(run_dir / "final-report.json", payload)
    write_markdown_report(run_dir / "final-report.md", payload)
    pruned_set = set(pruned_runs)
    checkpoint["runs"] = [
        row
        for row in checkpoint.get("runs", [])
        if isinstance(row, dict) and Path(str(row.get("output_dir", ""))).name not in pruned_set
    ]
    checkpoint.setdefault("runs", []).append(
        {
            "run_id": run_id,
            "started_at": started,
            "ended_at": payload["ended_at"],
            "totals": totals,
            "output_dir": str(run_dir),
        }
    )
    checkpoint["runs"] = checkpoint["runs"][
        -min(MAX_CHECKPOINT_RUNS, args.max_retained_runs):
    ]
    save_checkpoint(checkpoint_path, checkpoint)
    if args.json:
        print(json.dumps(redact_obj(payload), indent=2, sort_keys=True))
    else:
        print(f"Live validation run complete: {run_dir}")
        print(f"Totals: {totals}")
    return payload


def run_once(args: argparse.Namespace, *, iteration: int = 1) -> dict[str, Any]:
    validate_runner_args(args)
    selected_skills = set(args.skill or [])
    skip_skills = set(args.skip_skill or [])
    output_dir = Path(os.path.abspath(os.path.expanduser(args.output_dir)))
    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint = load_checkpoint(checkpoint_path)
    run_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
        f"iter{iteration}-p{os.getpid()}-{secrets.token_hex(4)}"
    )
    run_dir = output_dir / "runs" / run_id
    started = utc_now()
    write_json(
        run_dir / "run-start.json",
        {
            "schema_version": REPORT_SCHEMA_VERSION,
            "run_id": run_id,
            "profile": args.profile,
            "started_at": started,
            "state": "started",
        },
    )
    startup_pruned_runs = prune_run_history(output_dir, run_dir, args.max_retained_runs)

    if args.plan_only:
        effective_platform = args.platform if args.platform != "auto" else "enterprise"
        steps = build_plan(
            profile=args.profile,
            run_dir=run_dir,
            allow_apply=args.allow_apply,
            platform=effective_platform,
            selected_skills=selected_skills,
            skip_skills=skip_skills,
            allow_offline_smoke=args.allow_offline_smoke,
        )
        payload = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "plan_only": True,
            "run_id": run_id,
            "profile": args.profile,
            "platform": effective_platform,
            "allow_apply": args.allow_apply,
            "pruned_runs": startup_pruned_runs,
            "steps": [asdict(step) for step in steps],
        }
        payload["pruned_runs"].extend(
            prune_run_history(output_dir, run_dir, args.max_retained_runs)
        )
        write_json(run_dir / "plan.json", payload)
        if args.json:
            print(json.dumps(redact_obj(payload), indent=2, sort_keys=True))
        return payload

    ledger_path = run_dir / "ledger.jsonl"
    results: list[StepResult] = []
    doctor_in_scope = (
        "splunk-admin-doctor" not in skip_skills
        and (not selected_skills or "splunk-admin-doctor" in selected_skills)
    )
    full_sweep = not selected_skills
    needs_full_evidence = full_sweep or doctor_in_scope
    effective_platform = args.platform if args.platform != "auto" else "enterprise"
    steps: list[ValidationStep] = []
    try:
        if needs_full_evidence:
            evidence = collect_live_evidence(
                args.profile,
                run_dir,
                args.platform,
                allow_flat_credentials=args.allow_flat_credentials,
            )
        else:
            evidence = None
        if evidence is not None:
            effective_platform = str(evidence.get("platform", effective_platform))
        steps = build_plan(
            profile=args.profile,
            run_dir=run_dir,
            allow_apply=args.allow_apply,
            platform=effective_platform,
            selected_skills=selected_skills,
            skip_skills=skip_skills,
            allow_offline_smoke=args.allow_offline_smoke,
        )
        fatal_errors = (
            evidence.get("collection", {}).get("fatal_errors", [])
            if isinstance(evidence, dict) and isinstance(evidence.get("collection"), dict)
            else []
        )
        if fatal_errors:
            results.append(
                internal_failure_result(
                    run_dir=run_dir,
                    ledger_path=ledger_path,
                    step_id="baseline-profile-safety-gate",
                    message="; ".join(str(item) for item in fatal_errors),
                    classification="profile_safety_gate",
                )
            )
            for step in steps:
                skipped = not_run_result(step, reason="Not run because the profile safety gate failed.")
                append_jsonl(ledger_path, asdict(skipped))
                results.append(skipped)
            return finalize_run(
                args=args,
                output_dir=output_dir,
                run_dir=run_dir,
                run_id=run_id,
                started=started,
                effective_platform=effective_platform,
                steps=steps,
                results=results,
                checkpoint=checkpoint,
                checkpoint_path=checkpoint_path,
                ledger_path=ledger_path,
            )
    except RunnerInterrupted as exc:
        if not steps:
            steps = build_plan(
                profile=args.profile,
                run_dir=run_dir,
                allow_apply=args.allow_apply,
                platform=effective_platform,
                selected_skills=selected_skills,
                skip_skills=skip_skills,
                allow_offline_smoke=args.allow_offline_smoke,
            )
        results.append(
            internal_failure_result(
                run_dir=run_dir,
                ledger_path=ledger_path,
                step_id="baseline-runner-interrupted",
                message=exc.stderr or "interrupt requested during evidence collection",
                classification="interrupted",
            )
        )
        for step in steps:
            skipped = not_run_result(step, reason="Not run because an interrupt was requested.")
            append_jsonl(ledger_path, asdict(skipped))
            results.append(skipped)
        return finalize_run(
            args=args,
            output_dir=output_dir,
            run_dir=run_dir,
            run_id=run_id,
            started=started,
            effective_platform=effective_platform,
            steps=steps,
            results=results,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            ledger_path=ledger_path,
        )
    except Exception as exc:  # noqa: BLE001 - preserve an auditable final report.
        results.append(
            internal_failure_result(
                run_dir=run_dir,
                ledger_path=ledger_path,
                step_id="baseline-evidence-collection",
                message=f"{type(exc).__name__}: {exc}",
                classification="code_bug",
            )
        )
        return finalize_run(
            args=args,
            output_dir=output_dir,
            run_dir=run_dir,
            run_id=run_id,
            started=started,
            effective_platform=effective_platform,
            steps=steps,
            results=results,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            ledger_path=ledger_path,
        )

    for index, step in enumerate(steps):
        if _stop_requested():
            results.append(
                internal_failure_result(
                    run_dir=run_dir,
                    ledger_path=ledger_path,
                    step_id="baseline-runner-interrupted",
                    message="interrupt requested before the next validation step",
                    classification="interrupted",
                )
            )
            for remaining in steps[index:]:
                skipped = not_run_result(
                    remaining,
                    reason="Not run because an interrupt was requested.",
                )
                append_jsonl(ledger_path, asdict(skipped))
                results.append(skipped)
            break
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
        required_baseline_failed = (
            result.status == "fail" and step.category == "baseline" and step.required
        )
        should_stop = result.status == "fail" and (
            args.stop_on_failure or required_baseline_failed
        )
        if should_stop or _stop_requested():
            if _stop_requested():
                reason = "Not run because an interrupt was requested."
            elif required_baseline_failed:
                reason = "Not run because a required baseline safety check failed."
            else:
                reason = "Not run because --stop-on-failure was requested."
            for remaining in steps[index + 1 :]:
                skipped = not_run_result(remaining, reason=reason)
                append_jsonl(ledger_path, asdict(skipped))
                results.append(skipped)
            break

    return finalize_run(
        args=args,
        output_dir=output_dir,
        run_dir=run_dir,
        run_id=run_id,
        started=started,
        effective_platform=effective_platform,
        steps=steps,
        results=results,
        checkpoint=checkpoint,
        checkpoint_path=checkpoint_path,
        ledger_path=ledger_path,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run continuous live validation for every repo skill.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="Splunk credential profile to use.")
    parser.add_argument("--platform", choices=("auto", "cloud", "enterprise"), default="auto")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Gitignored directory for bounded run artifacts and checkpoint audit history.",
    )
    parser.add_argument(
        "--allow-apply",
        action="store_true",
        help="Render the bounded local doctor fix plan; live mutation smokes are disabled.",
    )
    parser.add_argument(
        "--allow-flat-credentials",
        action="store_true",
        help=(
            "Allow a secure legacy flat credentials file only when it contains no named profiles. "
            "Named profiles remain the production default."
        ),
    )
    parser.add_argument("--once", action="store_true", help="Run one sweep and exit.")
    parser.add_argument("--watch", action="store_true", help="Repeat sweeps until stopped.")
    parser.add_argument("--watch-interval-seconds", type=int, default=1800, help="Delay between steady-state sweeps.")
    parser.add_argument("--max-iterations", type=int, default=0, help="Maximum watch iterations; 0 means unlimited.")
    parser.add_argument(
        "--force-rerun",
        action="store_true",
        help="Compatibility no-op; local apply renders are always rerun.",
    )
    parser.add_argument(
        "--max-retained-runs",
        "--retain-runs",
        dest="max_retained_runs",
        type=int,
        default=DEFAULT_MAX_RETAINED_RUNS,
        help=f"Retain at most this many complete or incomplete run directories (1-{MAX_RETAIN_RUNS}).",
    )
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop the current sweep after the first hard failure.")
    parser.add_argument("--plan-only", action="store_true", help="Render the execution plan without running steps.")
    parser.add_argument(
        "--allow-offline-smoke",
        action="store_true",
        help="Run checked-in smoke_offline.sh entrypoints in addition to interface checks.",
    )
    parser.add_argument(
        "--allow-heuristic-live-probes",
        action="store_true",
        help=(
            "Legacy compatibility flag. Currently rejected because source-text discovery "
            "is not a mutation-proof safety manifest."
        ),
    )
    parser.add_argument("--skill", action="append", help="Limit the sweep to a skill; repeatable.")
    parser.add_argument("--skip-skill", action="append", help="Skip a skill; repeatable.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-step progress lines.")
    return parser.parse_args(argv)


def validate_runner_args(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", args.profile):
        raise ValueError("--profile must be a 1-128 character profile name")
    if args.watch_interval_seconds < 1:
        raise ValueError("--watch-interval-seconds must be at least 1")
    if args.max_iterations < 0:
        raise ValueError("--max-iterations cannot be negative")
    if args.max_retained_runs < 1 or args.max_retained_runs > MAX_RETAIN_RUNS:
        raise ValueError(f"--max-retained-runs must be between 1 and {MAX_RETAIN_RUNS}")
    if args.once and args.watch:
        raise ValueError("--once cannot be combined with --watch")
    if args.max_iterations and not args.watch:
        raise ValueError("--max-iterations requires --watch")
    if args.plan_only and args.watch:
        raise ValueError("--plan-only cannot be combined with --watch")
    if args.plan_only and args.platform == "auto":
        raise ValueError("--plan-only requires an explicit --platform cloud or enterprise")
    if args.allow_heuristic_live_probes:
        raise ValueError(
            "--allow-heuristic-live-probes is disabled until every live command has an audited, checked-in safety manifest"
        )
    validate_skill_selectors(set(args.skill or []), set(args.skip_skill or []))


def payload_exit_code(payload: dict[str, Any]) -> int:
    if payload.get("plan_only") is True:
        return (
            0
            if payload.get("schema_version") == REPORT_SCHEMA_VERSION
            and isinstance(payload.get("run_id"), str)
            and isinstance(payload.get("steps"), list)
            else 1
        )
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        return 1
    if totals.get("fail", 0) or payload.get("execution_complete") is not True:
        return 1
    return 0


def _run_locked(args: argparse.Namespace) -> int:
    global _STOP_REQUESTED
    _STOP_REQUESTED = False
    if args.watch:
        args.once = False
    elif not args.once and args.max_iterations == 0:
        # Default to one active sweep when invoked manually.
        args.once = True

    iteration = 1
    last_payload: dict[str, Any] | None = None

    def _handle_signal(_signum: int, _frame: Any) -> None:
        global _STOP_REQUESTED
        _STOP_REQUESTED = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    while not _stop_requested():
        payload = run_once(args, iteration=iteration)
        last_payload = payload
        if _stop_requested():
            return 1
        if args.once:
            return payload_exit_code(payload)
        if args.max_iterations and iteration >= args.max_iterations:
            break
        iteration += 1
        # After the active apply pass, steady state is read-only unless the
        # operator forces another apply. This prevents repeated O11y object
        # creation while still keeping the live watch alive.
        args.allow_apply = False
        for _ in range(max(1, args.watch_interval_seconds)):
            if _stop_requested():
                break
            time.sleep(1)
    if last_payload is None:
        return 1
    return payload_exit_code(last_payload)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_runner_args(args)
        output_dir = Path(os.path.abspath(os.path.expanduser(args.output_dir)))
        with exclusive_output_lock(output_dir):
            return _run_locked(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
