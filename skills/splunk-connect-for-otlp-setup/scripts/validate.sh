#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="splunk-connect-for-otlp"
APP_VERSION="0.4.1"
INPUT_TYPE="splunk-connect-for-otlp"
KNOWN_SHA256="fde0d93532703e04ab5aa544815d52232ef62afae2c0a55e374dc74d2d58f9d1"

INPUT_NAME="default"
EXPECTED_INDEX="otlp_events"
GRPC_PORT="4317"
HTTP_PORT="4318"
PACKAGE_FILE=""
JSON_OUTPUT=false
DRY_RUN=false
SMOKE_SEARCH=false
CHECKS_FILE="$(mktemp)"
trap 'rm -f "${CHECKS_FILE}"' EXIT

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Connect for OTLP Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --input-name NAME       Input stanza name (default: default)
  --expected-index INDEX  Expected routed index (default: otlp_events)
  --grpc-port PORT        Expected gRPC port (default: 4317)
  --http-port PORT        Expected HTTP port (default: 4318)
  --package-file PATH     Inspect a local package file
  --smoke-search          Run a read-only smoke search for expected-index visibility
  --dry-run               Validate static arguments and show planned checks
  --json                  Emit JSON
  --help

No HEC token values are accepted or required by validation.
EOF
    exit "${exit_code}"
}

require_value() {
    require_arg "$1" "$2" || exit 1
}

reject_secret_flag() {
    log "ERROR: Direct token values are not accepted by validation."
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input-name) require_value "$1" $#; INPUT_NAME="$2"; shift 2 ;;
        --expected-index) require_value "$1" $#; EXPECTED_INDEX="$2"; shift 2 ;;
        --grpc-port) require_value "$1" $#; GRPC_PORT="$2"; shift 2 ;;
        --http-port) require_value "$1" $#; HTTP_PORT="$2"; shift 2 ;;
        --package-file) require_value "$1" $#; PACKAGE_FILE="$2"; shift 2 ;;
        --smoke-search) SMOKE_SEARCH=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --token|--hec-token|--authorization|--splunk-token) reject_secret_flag ;;
        --token=*|--hec-token=*|--authorization=*|--splunk-token=*) reject_secret_flag ;;
        --help) usage 0 ;;
        *) log "ERROR: Unknown option: $1"; usage 1 ;;
    esac
done

positive_port() {
    local value="$1" option="$2"
    if [[ ! "${value}" =~ ^[0-9]+$ ]]; then
        log "ERROR: ${option} must be a TCP port number."
        exit 1
    fi
    if (( value < 1 || value > 65535 )); then
        log "ERROR: ${option} must be between 1 and 65535; port 0 is test-only."
        exit 1
    fi
}

add_check() {
    local name="$1" status="$2" detail="$3"
    python3 - "${CHECKS_FILE}" "${name}" "${status}" "${detail}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
record = {"name": sys.argv[2], "status": sys.argv[3], "detail": sys.argv[4]}
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True) + "\n")
PY
}

emit_results() {
    local output_json="$1"
    python3 - "${CHECKS_FILE}" "${output_json}" <<'PY'
import json
import sys
from pathlib import Path

records = [
    json.loads(line)
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    if line.strip()
]
summary = {
    "app": "splunk-connect-for-otlp",
    "ok": not any(item["status"] == "fail" for item in records),
    "failures": sum(1 for item in records if item["status"] == "fail"),
    "warnings": sum(1 for item in records if item["status"] == "warn"),
    "checks": records,
}
if sys.argv[2] == "true":
    print(json.dumps(summary, indent=2, sort_keys=True))
else:
    for item in records:
        print(f"[{item['status'].upper()}] {item['name']}: {item['detail']}")
    print(f"Result: {'ok' if summary['ok'] else 'failed'}")
raise SystemExit(0 if summary["ok"] else 1)
PY
}

inspect_platform() {
    local os_name machine
    os_name="$(uname -s 2>/dev/null || true)"
    machine="$(uname -m 2>/dev/null || true)"
    case "${os_name}" in
        Linux)
            if [[ "${machine}" == "x86_64" || "${machine}" == "amd64" ]]; then
                add_check "platform-binary" "ok" "Linux x86_64 packaged binary is available."
            else
                add_check "platform-binary" "fail" "Package has Linux x86_64 only; detected ${machine}."
            fi
            ;;
        Darwin)
            add_check "platform-binary" "warn" "Package has no Darwin/macOS binary or default bin/ executable; run the input on a packaged Linux/Windows Splunk tier."
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT)
            add_check "platform-binary" "warn" "Package has a Windows x86_64 binary without a .exe suffix; verify execution."
            ;;
        *)
            add_check "platform-binary" "warn" "Unknown local platform ${os_name}/${machine}; audited package has Linux and Windows x86_64 binaries only."
            ;;
    esac
}

inspect_package() {
    if [[ -z "${PACKAGE_FILE}" ]]; then
        return 0
    fi
    if [[ ! -f "${PACKAGE_FILE}" ]]; then
        add_check "package-file" "fail" "Package file not found: ${PACKAGE_FILE}"
        return 0
    fi
    python3 - "${PACKAGE_FILE}" "${KNOWN_SHA256}" <<'PY' >"${CHECKS_FILE}.package"
import hashlib
import json
import sys
import tarfile
from pathlib import Path

expected_files = {
    "splunk-connect-for-otlp/README/inputs.conf.spec",
    "splunk-connect-for-otlp/default/app.conf",
    "splunk-connect-for-otlp/default/data/ui/manager/splunk-connect-for-otlp.xml",
    "splunk-connect-for-otlp/default/inputs.conf",
    "splunk-connect-for-otlp/default/props.conf",
    "splunk-connect-for-otlp/linux_x86_64/bin/splunk-connect-for-otlp",
    "splunk-connect-for-otlp/metadata/default.meta",
    "splunk-connect-for-otlp/windows_x86_64/bin/splunk-connect-for-otlp",
}
path = Path(sys.argv[1])
expected_hash = sys.argv[2]
data = path.read_bytes()
actual_hash = hashlib.sha256(data).hexdigest()
with tarfile.open(path, "r:*") as archive:
    files = {member.name.lstrip("./") for member in archive.getmembers() if member.isfile()}
print(json.dumps({
    "sha256_matches": actual_hash == expected_hash,
    "missing": sorted(expected_files - files),
    "extra": sorted(files - expected_files),
}))
PY
    python3 - "${CHECKS_FILE}.package" "${CHECKS_FILE}" <<'PY'
import json
import sys
from pathlib import Path

info = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
checks = Path(sys.argv[2])
def write(name, status, detail):
    with checks.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"name": name, "status": status, "detail": detail}, sort_keys=True) + "\n")
write("package-sha256", "ok" if info["sha256_matches"] else "fail", "SHA256 matches audited 0.4.1 package." if info["sha256_matches"] else "SHA256 does not match audited 0.4.1 package.")
write("package-file-list", "ok" if not info["missing"] else "fail", "Package file list matches audited contents." if not info["missing"] else "Package is missing expected files: " + ", ".join(info["missing"]))
PY
    rm -f "${CHECKS_FILE}.package"
}

rest_json_field() {
    local field="$1"
    local payload
    payload="$(cat)"
    python3 - "${field}" "${payload}" <<'PY'
import json
import sys

field = sys.argv[1]
try:
    data = json.loads(sys.argv[2])
    print(data.get(field, ""), end="")
except Exception:
    print("", end="")
PY
}

port_listens_in_text() {
    local payload="$1" port="$2"
    grep -Eq "(^|[[:space:]])[^[:space:]]*:${port}([[:space:]]|$)" <<<"${payload}"
}

tcp_port_reachable() {
    local host="$1" port="$2"
    python3 - "${host}" "${port}" >/dev/null 2>&1 <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
with socket.create_connection((host, port), timeout=3):
    pass
PY
}

check_bound_ports() {
    local input_summary="$1"
    local found disabled
    local ssh_host ssh_user ssh_port listeners="" host
    local listener_source="none"

    found="$(printf '%s' "${input_summary}" | rest_json_field found)"
    disabled="$(printf '%s' "${input_summary}" | rest_json_field disabled)"
    if [[ "${found}" != "True" && "${found}" != "true" ]]; then
        return 0
    fi
    if [[ "${disabled}" == "1" || "${disabled}" == "true" || "${disabled}" == "True" ]]; then
        return 0
    fi

    ssh_host="${SPLUNK_SSH_HOST:-${SPLUNK_HOST:-$(splunk_host_from_uri "${SPLUNK_URI}")}}"
    ssh_user="${SPLUNK_SSH_USER:-splunk}"
    ssh_port="${SPLUNK_SSH_PORT:-22}"
    if [[ -n "${ssh_host}" && -n "${ssh_user}" ]] && command -v ssh >/dev/null 2>&1; then
        listeners="$(ssh -o BatchMode=yes -o ConnectTimeout=5 -p "${ssh_port}" "${ssh_user}@${ssh_host}" \
            'if command -v ss >/dev/null 2>&1; then ss -ltn; elif command -v netstat >/dev/null 2>&1; then netstat -ltn; else exit 3; fi' \
            2>/dev/null || true)"
        if [[ -n "${listeners}" ]]; then
            listener_source="ssh"
        fi
    fi

    if [[ "${listener_source}" == "ssh" ]]; then
        if port_listens_in_text "${listeners}" "${GRPC_PORT}"; then
            add_check "grpc-listener" "ok" "gRPC receiver port ${GRPC_PORT} is listening on ${ssh_host}."
        else
            add_check "grpc-listener" "fail" "Input is enabled, but gRPC receiver port ${GRPC_PORT} is not listening on ${ssh_host}."
        fi
        if port_listens_in_text "${listeners}" "${HTTP_PORT}"; then
            add_check "http-listener" "ok" "HTTP receiver port ${HTTP_PORT} is listening on ${ssh_host}."
        else
            add_check "http-listener" "fail" "Input is enabled, but HTTP receiver port ${HTTP_PORT} is not listening on ${ssh_host}."
        fi
        return 0
    fi

    host="${SPLUNK_HOST:-$(splunk_host_from_uri "${SPLUNK_URI}")}"
    if [[ -z "${host}" ]]; then
        add_check "grpc-listener" "warn" "Unable to determine a target host for gRPC receiver port ${GRPC_PORT} reachability."
        add_check "http-listener" "warn" "Unable to determine a target host for HTTP receiver port ${HTTP_PORT} reachability."
        return 0
    fi
    if tcp_port_reachable "${host}" "${GRPC_PORT}"; then
        add_check "grpc-listener" "ok" "gRPC receiver port ${GRPC_PORT} is reachable from the validator host."
    else
        add_check "grpc-listener" "warn" "Could not confirm gRPC receiver port ${GRPC_PORT}; SSH listener check unavailable and TCP probe to ${host} failed."
    fi
    if tcp_port_reachable "${host}" "${HTTP_PORT}"; then
        add_check "http-listener" "ok" "HTTP receiver port ${HTTP_PORT} is reachable from the validator host."
    else
        add_check "http-listener" "warn" "Could not confirm HTTP receiver port ${HTTP_PORT}; SSH listener check unavailable and TCP probe to ${host} failed."
    fi
}

validate_live() {
    local app_version input_json input_summary hec_json hec_summary errors_count smoke_count
    local input_json_file hec_json_file

    if ! load_splunk_credentials >/dev/null 2>&1; then
        add_check "credentials" "fail" "Splunk credentials are not configured; run skills/shared/scripts/setup_credentials.sh."
        return 0
    fi
    SK="$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)"
    if [[ -z "${SK}" ]]; then
        add_check "session" "fail" "Unable to obtain Splunk REST session key."
        return 0
    fi
    add_check "session" "ok" "Splunk REST session established."

    app_version="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || true)"
    if [[ -z "${app_version}" || "${app_version}" == "unknown" ]]; then
        add_check "app-installed" "fail" "App ${APP_NAME} is not visible through /services/apps/local."
    else
        add_check "app-installed" "ok" "Installed version ${app_version}."
        if [[ "${app_version}" == "${APP_VERSION}" ]]; then
            add_check "app-version" "ok" "Installed version matches audited ${APP_VERSION}."
        else
            add_check "app-version" "warn" "Installed version ${app_version}; audited version is ${APP_VERSION}."
        fi
    fi

    input_json="$(splunk_curl "${SK}" "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/inputs/${INPUT_TYPE}?output_mode=json&count=0" 2>/dev/null || true)"
    input_json_file="$(mktemp)"
    printf '%s' "${input_json}" > "${input_json_file}"
    input_summary="$(python3 - "${input_json_file}" "${INPUT_NAME}" "${GRPC_PORT}" "${HTTP_PORT}" <<'PY'
import json
import sys
from pathlib import Path

path, target, grpc, http = sys.argv[1:5]
try:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
except Exception:
    print(json.dumps({"found": False, "parse_error": True}))
    raise SystemExit
for entry in data.get("entry", []):
    name = entry.get("name", "")
    short = name.split("://", 1)[-1]
    if short == target or name == target:
        content = entry.get("content", {})
        print(json.dumps({
            "found": True,
            "disabled": str(content.get("disabled", "")),
            "grpc_port": str(content.get("grpc_port", "")),
            "http_port": str(content.get("http_port", "")),
            "listen_address": str(content.get("listen_address", "")),
            "grpc_matches": str(content.get("grpc_port", "")) == grpc,
            "http_matches": str(content.get("http_port", "")) == http,
        }))
        break
else:
    print(json.dumps({"found": False}))
PY
)"
    rm -f "${input_json_file}"
    if [[ "$(printf '%s' "${input_summary}" | rest_json_field found)" == "True" || "$(printf '%s' "${input_summary}" | rest_json_field found)" == "true" ]]; then
        add_check "input-stanza" "ok" "Input ${INPUT_TYPE}://${INPUT_NAME} exists."
        if [[ "$(printf '%s' "${input_summary}" | rest_json_field disabled)" == "1" ]]; then
            add_check "input-enabled" "fail" "Input ${INPUT_NAME} is disabled."
        else
            add_check "input-enabled" "ok" "Input ${INPUT_NAME} is enabled or has no disabled=1 flag."
        fi
        if [[ "$(printf '%s' "${input_summary}" | rest_json_field grpc_matches)" == "True" || "$(printf '%s' "${input_summary}" | rest_json_field grpc_matches)" == "true" ]]; then
            add_check "grpc-port" "ok" "gRPC port matches ${GRPC_PORT}."
        else
            add_check "grpc-port" "warn" "gRPC port differs from expected ${GRPC_PORT}."
        fi
        if [[ "$(printf '%s' "${input_summary}" | rest_json_field http_matches)" == "True" || "$(printf '%s' "${input_summary}" | rest_json_field http_matches)" == "true" ]]; then
            add_check "http-port" "ok" "HTTP port matches ${HTTP_PORT}."
        else
            add_check "http-port" "warn" "HTTP port differs from expected ${HTTP_PORT}."
        fi
    else
        add_check "input-stanza" "fail" "Input ${INPUT_TYPE}://${INPUT_NAME} was not found."
    fi
    check_bound_ports "${input_summary}"

    hec_json="$(splunk_curl "${SK}" "${SPLUNK_URI}/servicesNS/-/-/data/inputs/http?output_mode=json&count=0" 2>/dev/null || true)"
    hec_json_file="$(mktemp)"
    printf '%s' "${hec_json}" > "${hec_json_file}"
    hec_summary="$(python3 - "${hec_json_file}" "${EXPECTED_INDEX}" <<'PY'
import json
import sys
from pathlib import Path

path, expected = sys.argv[1:3]
try:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
except Exception:
    print(json.dumps({"parse_error": True, "tokens": 0, "expected_allowed": False}))
    raise SystemExit
tokens = 0
expected_allowed = False
global_disabled = None
for entry in data.get("entry", []):
    name = entry.get("name", "")
    content = entry.get("content", {})
    if name == "http":
        global_disabled = str(content.get("disabled", ""))
    if name.startswith("http://"):
        tokens += 1
        indexes = content.get("indexes", "")
        allowed = [part.strip() for part in str(indexes).split(",") if part.strip()]
        if expected in allowed or "*" in allowed:
            expected_allowed = True
print(json.dumps({"tokens": tokens, "global_disabled": global_disabled, "expected_allowed": expected_allowed}))
PY
)"
    rm -f "${hec_json_file}"
    if [[ "$(printf '%s' "${hec_summary}" | rest_json_field global_disabled)" == "1" ]]; then
        add_check "hec-global" "fail" "HEC global input is disabled."
    else
        add_check "hec-global" "ok" "HEC global input is not reported disabled."
    fi
    if [[ "$(printf '%s' "${hec_summary}" | rest_json_field tokens)" == "0" ]]; then
        add_check "hec-tokens" "fail" "No HEC token stanzas are visible to local REST."
    else
        add_check "hec-tokens" "ok" "At least one HEC token stanza is visible."
    fi
    if [[ "$(printf '%s' "${hec_summary}" | rest_json_field expected_allowed)" == "True" || "$(printf '%s' "${hec_summary}" | rest_json_field expected_allowed)" == "true" ]]; then
        add_check "hec-allowed-index" "ok" "At least one HEC token allows ${EXPECTED_INDEX}."
    else
        add_check "hec-allowed-index" "warn" "No visible HEC token explicitly allows ${EXPECTED_INDEX}; verify token used by senders."
    fi

    errors_count="$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "search index=_internal earliest=-24h (ExecProcessor OR ModularInputs OR ${APP_NAME} OR \"index denied\" OR \"address already in use\") | stats count" "count" 2>/dev/null || echo "0")"
    if [[ "${errors_count}" == "0" ]]; then
        add_check "internal-errors" "ok" "No recent _internal OTLP modular-input errors found by the default search."
    else
        add_check "internal-errors" "warn" "Recent _internal search found ${errors_count} possible OTLP modular-input errors."
    fi

    if [[ "${SMOKE_SEARCH}" == "true" ]]; then
        smoke_count="$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "search index=${EXPECTED_INDEX} earliest=-15m sourcetype=${APP_NAME} | stats count" "count" 2>/dev/null || echo "0")"
        if [[ "${smoke_count}" == "0" ]]; then
            add_check "smoke-search" "warn" "No recent events found in ${EXPECTED_INDEX} for sourcetype ${APP_NAME}."
        else
            add_check "smoke-search" "ok" "Found ${smoke_count} recent events in ${EXPECTED_INDEX}."
        fi
    fi
}

main() {
    positive_port "${GRPC_PORT}" "--grpc-port"
    positive_port "${HTTP_PORT}" "--http-port"
    inspect_platform
    inspect_package
    if [[ "${DRY_RUN}" == "true" ]]; then
        add_check "planned-rest" "ok" "Would check app metadata, modular input stanzas, HEC tokens, _internal errors, and optional smoke-search visibility."
    else
        validate_live
    fi
    emit_results "${JSON_OUTPUT}"
}

main "$@"
