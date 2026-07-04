#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DOCTOR="${SCRIPT_DIR}/doctor.py"
DEFAULT_RENDER_DIR_NAME="splunk-admin-doctor-rendered"

PHASE="doctor"
PLATFORM="auto"
TARGET_SEARCH_HEAD=""
SPLUNK_URI=""
SPLUNK_HOME_VALUE="/opt/splunk"
OUTPUT_DIR=""
EVIDENCE_FILE=""
FIXES=""
JSON_OUTPUT=false
STRICT=false
REQUIRE_COMPLETE_EVIDENCE=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Admin Doctor + Fixes

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase doctor|fix-plan|apply|validate|status
  --platform auto|cloud|enterprise
                        Select cloud or enterprise explicitly. Auto requires
                        an evidence platform or a strict *.splunkcloud.com URI.
  --target-search-head HOSTNAME
  --splunk-uri HTTPS_ORIGIN
                        Optional management origin only: HTTPS, valid host and
                        optional port; no credentials, non-root path, query,
                        or fragment.
  --splunk-home PATH
  --output-dir PATH
  --evidence-file PATH
  --fixes FIX_ID[,FIX_ID]
  --json
  --strict
  --require-complete-evidence
  --dry-run
  --help

Status fields:
  report_valid / ok (deprecated alias) describe report validity, not health.
  Use healthy, evidence_complete, severity_counts, health_status, and
  strict_ready for gates; integrity_verified confirms the committed bundle.
  A zero status-phase exit means the bundle is valid, not necessarily healthy.

Examples:
  $(basename "$0") --phase doctor --platform enterprise --splunk-home /opt/splunk
  $(basename "$0") --phase fix-plan --platform enterprise --evidence-file skills/splunk-admin-doctor/fixtures/enterprise_unhealthy.json
  $(basename "$0") --phase apply --platform cloud --evidence-file skills/splunk-admin-doctor/fixtures/cloud_acs_rest_denied.json --fixes SAD-CONNECTIVITY-REST-DENIED --dry-run --json

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --target-search-head) require_arg "$1" $# || exit 1; TARGET_SEARCH_HEAD="$2"; shift 2 ;;
        --splunk-uri) require_arg "$1" $# || exit 1; SPLUNK_URI="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --evidence-file) require_arg "$1" $# || exit 1; EVIDENCE_FILE="$2"; shift 2 ;;
        --fixes) require_arg "$1" $# || exit 1; FIXES="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --strict) STRICT=true; shift ;;
        --require-complete-evidence) REQUIRE_COMPLETE_EVIDENCE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    echo "ERROR: Invalid value '${value}'. Expected one of: $*" >&2
    exit 1
}

validate_splunk_uri() {
    [[ -z "${SPLUNK_URI}" ]] && return 0
    python3 -c '
import sys
import ipaddress
import re
from urllib.parse import urlsplit

uri = sys.stdin.read()
if uri.endswith("\n"):
    uri = uri[:-1]
try:
    parsed = urlsplit(uri)
    port = parsed.port
except ValueError:
    print("ERROR: invalid --splunk-uri syntax or port", file=sys.stderr)
    raise SystemExit(1)
errors = []
if parsed.scheme.lower() != "https":
    errors.append("scheme must be https")
hostname = (parsed.hostname or "").rstrip(".")
valid_hostname = False
if hostname and len(hostname) <= 253 and not any(character.isspace() for character in hostname):
    try:
        ipaddress.ip_address(hostname)
        valid_hostname = True
    except ValueError:
        valid_hostname = all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
            is not None
            for label in hostname.split(".")
        )
if not valid_hostname:
    errors.append("valid hostname or IP address is required")
if parsed.username is not None or parsed.password is not None:
    errors.append("embedded credentials are forbidden")
if parsed.path not in {"", "/"}:
    errors.append("path must be empty or /")
if parsed.query:
    errors.append("query strings are forbidden")
if parsed.fragment:
    errors.append("fragments are forbidden")
if parsed.netloc.endswith(":") or port == 0:
    errors.append("port is invalid")
elif port is not None and not 1 <= port <= 65535:
    errors.append("port must be between 1 and 65535")
if any(character.isspace() for character in uri):
    errors.append("whitespace is forbidden")
if errors:
    print("ERROR: invalid --splunk-uri: " + "; ".join(errors), file=sys.stderr)
    raise SystemExit(1)
' <<<"${SPLUNK_URI}"
}

splunk_uri_infers_cloud() {
    [[ -n "${SPLUNK_URI}" ]] || return 1
    python3 -c '
import sys
from urllib.parse import urlsplit

uri = sys.stdin.read()
if uri.endswith("\n"):
    uri = uri[:-1]
try:
    hostname = (urlsplit(uri).hostname or "").rstrip(".").lower()
except ValueError:
    raise SystemExit(1)
raise SystemExit(0 if hostname.endswith(".splunkcloud.com") else 1)
' <<<"${SPLUNK_URI}"
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import os
import sys
print(Path(os.path.abspath(os.path.expanduser(sys.argv[1]))), end="")
PY
}

validate_args() {
    validate_choice "${PHASE}" doctor fix-plan apply validate status
    validate_choice "${PLATFORM}" auto cloud enterprise
    validate_splunk_uri
    if [[ "${PLATFORM}" == "auto" && -z "${EVIDENCE_FILE}" && "${PHASE}" =~ ^(doctor|fix-plan|apply)$ ]] && ! splunk_uri_infers_cloud; then
        echo "ERROR: --platform auto requires evidence JSON that declares platform or a strict HTTPS *.splunkcloud.com management URI; otherwise select --platform cloud or enterprise." >&2
        exit 1
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
    if [[ "${PHASE}" == "apply" && -z "${FIXES}" ]]; then
        echo "ERROR: --phase apply requires --fixes FIX_ID[,FIX_ID]." >&2
        exit 1
    fi
}

build_args() {
    DOCTOR_ARGS=(
        --phase "${PHASE}"
        --platform "${PLATFORM}"
        --target-search-head "${TARGET_SEARCH_HEAD}"
        --splunk-uri "${SPLUNK_URI}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --output-dir "${OUTPUT_DIR}"
    )
    [[ -n "${EVIDENCE_FILE}" ]] && DOCTOR_ARGS+=(--evidence-file "${EVIDENCE_FILE}")
    [[ -n "${FIXES}" ]] && DOCTOR_ARGS+=(--fixes "${FIXES}")
    [[ "${JSON_OUTPUT}" == "true" ]] && DOCTOR_ARGS+=(--json)
    [[ "${STRICT}" == "true" ]] && DOCTOR_ARGS+=(--strict)
    [[ "${REQUIRE_COMPLETE_EVIDENCE}" == "true" ]] && DOCTOR_ARGS+=(--require-complete-evidence)
    [[ "${DRY_RUN}" == "true" ]] && DOCTOR_ARGS+=(--dry-run)
    return 0
}

main() {
    validate_args
    build_args
    python3 "${DOCTOR}" "${DOCTOR_ARGS[@]}"
}

main "$@"
