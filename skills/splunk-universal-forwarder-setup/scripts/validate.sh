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
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

detect_defaults
validate_choice "${TARGET_OS}" linux macos windows freebsd solaris aix
validate_choice "${EXECUTION_MODE}" local ssh render
validate_choice "${ENROLL_MODE}" none deployment-server enterprise-indexers splunk-cloud

if [[ "${TARGET_OS}" == "windows" || "${TARGET_OS}" =~ ^(freebsd|solaris|aix)$ || "${EXECUTION_MODE}" == "render" ]]; then
    log "INFO: ${TARGET_OS}/render validation is a handoff check in v1. Verify Universal Forwarder service state on the target host."
    exit 0
fi

if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
    load_splunk_ssh_credentials
fi

assert_target_command "Universal Forwarder binary exists" "$(hbs_shell_join test -x "${SPLUNK_HOME}/bin/splunk")"
assert_output_contains "Splunk version identifies Universal Forwarder" "$(splunk_cli_cmd version)" "Universal Forwarder"
assert_output_contains "Universal Forwarder status command succeeds" "$(splunk_cli_cmd status)" "splunkd"

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
