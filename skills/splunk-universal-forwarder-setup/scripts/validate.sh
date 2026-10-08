#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

TARGET_OS="auto"
EXECUTION_MODE="local"
SPLUNK_HOME=""
SERVICE_USER=""
ENROLL_MODE="none"
DEPLOYMENT_SERVER=""
SERVER_LIST=""
MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"
IPC_PORT="${SPLUNK_IPC_BROKER_PORT:-${SPLUNK_IPC_PORT:-8194}}"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Universal Forwarder Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --target-os auto|linux|macos|windows|freebsd|solaris|aix
  --execution local|ssh|render
  --splunk-home PATH
  --service-user USER
  --enroll none|deployment-server|enterprise-indexers|splunk-cloud
  --deployment-server HOST:PORT
  --server-list HOST:9997[,HOST:9997...]
  --mgmt-port PORT (default: 8089; env: SPLUNK_MGMT_PORT)
  --ipc-port PORT (default: 8194; env: SPLUNK_IPC_PORT)
  --help

Windows v1 validation is render-only; run the generated PowerShell script on
the target and verify the SplunkForwarder service there.
EOF
    exit "${exit_code}"
}

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

detect_defaults() {
    if [[ "${TARGET_OS}" == "auto" ]]; then
        case "$(uname -s 2>/dev/null || printf unknown)" in
            Linux) TARGET_OS="linux" ;;
            Darwin) TARGET_OS="macos" ;;
            FreeBSD) TARGET_OS="freebsd" ;;
            SunOS) TARGET_OS="solaris" ;;
            AIX) TARGET_OS="aix" ;;
            *) TARGET_OS="linux" ;;
        esac
    fi
    if [[ -z "${SPLUNK_HOME}" ]]; then
        case "${TARGET_OS}" in
            macos) SPLUNK_HOME="/Applications/splunkforwarder" ;;
            windows) SPLUNK_HOME='C:\Program Files\SplunkUniversalForwarder' ;;
            *) SPLUNK_HOME="/opt/splunkforwarder" ;;
        esac
    fi
    if [[ -z "${SERVICE_USER}" ]]; then
        case "${TARGET_OS}" in
            linux) SERVICE_USER="splunkfwd" ;;
            macos) SERVICE_USER="$(id -un)" ;;
            *) SERVICE_USER="" ;;
        esac
    fi
}

splunk_cli_cmd() {
    hbs_shell_join "${SPLUNK_HOME}/bin/splunk" "$@"
}

capture_splunk() {
    local raw_cmd="${1:-}"
    if [[ -n "${SERVICE_USER}" ]]; then
        hbs_capture_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}"
    else
        hbs_capture_target_cmd "${EXECUTION_MODE}" "${raw_cmd}"
    fi
}

assert_target_command() {
    local description="$1"
    local command_text="$2"
    local output
    if ! output="$(hbs_capture_target_cmd "${EXECUTION_MODE}" "${command_text}" 2>&1)"; then
        log "ERROR: ${description} failed."
        printf '%s\n' "${output}" >&2
        exit 1
    fi
    log "OK: ${description}"
}

assert_output_contains() {
    local description="$1"
    local command_text="$2"
    local pattern="$3"
    local output
    output="$(capture_splunk "${command_text}" 2>&1 || true)"
    if [[ "${output}" != *"${pattern}"* ]]; then
        log "ERROR: ${description} did not include expected pattern '${pattern}'."
        printf '%s\n' "${output}" >&2
        exit 1
    fi
    log "OK: ${description}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-os) require_arg "$1" $# || exit 1; TARGET_OS="$2"; shift 2 ;;
        --execution) require_arg "$1" $# || exit 1; EXECUTION_MODE="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME="$2"; shift 2 ;;
        --service-user) require_arg "$1" $# || exit 1; SERVICE_USER="$2"; shift 2 ;;
        --enroll) require_arg "$1" $# || exit 1; ENROLL_MODE="$2"; shift 2 ;;
        --deployment-server) require_arg "$1" $# || exit 1; DEPLOYMENT_SERVER="$2"; shift 2 ;;
        --server-list) require_arg "$1" $# || exit 1; SERVER_LIST="$2"; shift 2 ;;
        --mgmt-port) require_arg "$1" $# || exit 1; MGMT_PORT="$2"; shift 2 ;;
        --ipc-port|--ipc-broker-port) require_arg "$1" $# || exit 1; IPC_PORT="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

detect_defaults
validate_choice "${TARGET_OS}" linux macos windows freebsd solaris aix
validate_choice "${EXECUTION_MODE}" local ssh render
validate_choice "${ENROLL_MODE}" none deployment-server enterprise-indexers splunk-cloud
if [[ ! "${MGMT_PORT}" =~ ^[0-9]+$ ]] || (( 10#${MGMT_PORT} < 1 || 10#${MGMT_PORT} > 65535 )); then
    log "ERROR: Management port must be a numeric value from 1 through 65535."; exit 1
fi
if [[ ! "${IPC_PORT}" =~ ^[0-9]+$ ]] || (( 10#${IPC_PORT} < 1025 || 10#${IPC_PORT} > 65535 )); then
    log "ERROR: IPC port must be a numeric value from 1025 through 65535."; exit 1
fi
MGMT_PORT=$((10#${MGMT_PORT}))
IPC_PORT=$((10#${IPC_PORT}))
if [[ "${MGMT_PORT}" == "${IPC_PORT}" ]]; then
    log "ERROR: Management and IPC ports must be different."; exit 1
fi

if [[ "${TARGET_OS}" == "windows" || "${TARGET_OS}" =~ ^(freebsd|solaris|aix)$ || "${EXECUTION_MODE}" == "render" ]]; then
    log "HANDOFF: ${TARGET_OS}/${EXECUTION_MODE} validation cannot inspect the target from this process."
    log "Run the generated target-side validator and capture SplunkForwarder service, version, status, and enrollment evidence before declaring completion."
    exit 2
fi

if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
    if ! load_splunk_ssh_credentials; then
        log "ERROR: Could not load the selected Splunk SSH target credentials."
        exit 1
    fi
fi

assert_target_command "Universal Forwarder binary exists" "$(hbs_shell_join test -x "${SPLUNK_HOME}/bin/splunk")"
assert_output_contains "Splunk version identifies Universal Forwarder" "$(splunk_cli_cmd version)" "Universal Forwarder"
assert_output_contains "Universal Forwarder status command succeeds" "$(splunk_cli_cmd status)" "splunkd"
if ! web_config_output="$(capture_splunk "$(splunk_cli_cmd btool web list settings --debug)" 2>&1)"; then
    log "ERROR: Could not read effective web.conf management port."
    printf '%s\n' "${web_config_output}" >&2
    exit 1
fi
if ! awk -F= -v expected_port="${MGMT_PORT}" '
    /mgmtHostPort[[:space:]]*=/ {
        value = $2
        if (value ~ ("^[[:space:]]*(.*:)?" expected_port "[[:space:]]*$")) found = 1
    }
    END { exit(found ? 0 : 1) }
' <<<"${web_config_output}"; then
    log "ERROR: web.conf management port did not contain the exact effective port ${MGMT_PORT}."
    printf '%s\n' "${web_config_output}" >&2
    exit 1
fi
log "OK: web.conf management port ${MGMT_PORT}"
if ! management_mode_output="$(capture_splunk "$(splunk_cli_cmd btool server list httpServer --debug)" 2>&1)"; then
    log "ERROR: Could not read effective server.conf management mode."
    printf '%s\n' "${management_mode_output}" >&2
    exit 1
fi
if awk -F= '/(^|[[:space:]])mgmtMode[[:space:]]*=/ { if ($2 ~ /^[[:space:]]*tcp[[:space:]]*$/) found = 1 } END { exit(found ? 0 : 1) }' <<<"${management_mode_output}"; then
    management_mode="tcp"
    log "OK: server.conf TCP management mode"
elif awk -F= '/(^|[[:space:]])mgmtMode[[:space:]]*=/ { if ($2 ~ /^[[:space:]]*auto[[:space:]]*$/) found = 1 } END { exit(found ? 0 : 1) }' <<<"${management_mode_output}"; then
    management_mode="auto"
    log "OK: server.conf preserves automatic/UDS management mode"
else
    log "ERROR: server.conf did not report a supported management mode (tcp or auto)."
    printf '%s\n' "${management_mode_output}" >&2
    exit 1
fi
if ! ipc_config_output="$(capture_splunk "$(splunk_cli_cmd btool server list ipc_broker --debug)" 2>&1)"; then
    log "ERROR: Could not read effective server.conf IPC broker port."
    printf '%s\n' "${ipc_config_output}" >&2
    exit 1
fi
if ! awk -F= -v expected_port="${IPC_PORT}" '
    /(^|[[:space:]])port[[:space:]]*=/ {
        value = $2
        if (value ~ ("^[[:space:]]*" expected_port "[[:space:]]*$")) found = 1
    }
    END { exit(found ? 0 : 1) }
' <<<"${ipc_config_output}"; then
    log "ERROR: server.conf IPC broker port did not contain the exact effective port ${IPC_PORT}."
    printf '%s\n' "${ipc_config_output}" >&2
    exit 1
fi
log "OK: server.conf IPC broker port ${IPC_PORT}"
if [[ "${management_mode}" == "tcp" ]]; then
    management_listener_check="if command -v ss >/dev/null 2>&1; then ss -H -ltn | awk -v p='${MGMT_PORT}' '\$4 ~ (\":\" p \"$\") { found = 1 } END { exit(found ? 0 : 1) }'; elif command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:'${MGMT_PORT}' -sTCP:LISTEN -t >/dev/null; else python3 -c 'import socket,sys; s=socket.create_connection((\"127.0.0.1\", int(sys.argv[1])), timeout=3); s.close()' '${MGMT_PORT}'; fi"
    assert_target_command "TCP management listener on localhost:${MGMT_PORT}" "${management_listener_check}"
fi

case "${ENROLL_MODE}" in
    deployment-server)
        assert_output_contains "deploymentclient.conf has deployment server" "$(splunk_cli_cmd btool deploymentclient list --debug)" "${DEPLOYMENT_SERVER:-targetUri =}"
        ;;
    enterprise-indexers)
        assert_output_contains "outputs.conf has configured tcpout servers" "$(splunk_cli_cmd btool outputs list --debug)" "${SERVER_LIST:-defaultGroup}"
        ;;
    splunk-cloud)
        assert_output_contains "outputs.conf has tcpout defaultGroup" "$(splunk_cli_cmd btool outputs list --debug)" "defaultGroup"
        ;;
esac

log "OK: Splunk Universal Forwarder validation completed."
