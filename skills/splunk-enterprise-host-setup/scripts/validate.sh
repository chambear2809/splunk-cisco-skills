#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
SERVICE_USER="${SERVICE_USER:-splunk}"
MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"
EXECUTION_MODE="local"
HOST_BOOTSTRAP_ROLE=""
FORWARDING_MODE=""
INDEXER_DISCOVERY_NAME="cluster_manager"
ADMIN_USER="admin"
ADMIN_PASSWORD_FILE=""
ADMIN_PASSWORD=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Host Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --execution local|ssh
  --host-bootstrap-role standalone-search-tier|standalone-indexer|heavy-forwarder|cluster-manager|indexer-peer|shc-deployer|shc-member
  --forwarding-mode indexer-discovery|server-list
  --indexer-discovery-name NAME
  --splunk-home PATH
  --service-user USER
  --admin-user USER
  --admin-password-file PATH
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

ensure_prompted_value() {
    local var_name="$1"
    local prompt="$2"
    local current_value="${!var_name:-}"
    if [[ -z "${current_value}" ]] && hbs_is_interactive; then
        current_value="$(hbs_prompt_value "${prompt}")"
        printf -v "${var_name}" '%s' "${current_value}"
    fi
    if [[ -z "${!var_name:-}" ]]; then
        log "ERROR: ${prompt} is required."
        exit 1
    fi
}

ensure_prompted_path() {
    local var_name="$1"
    local prompt="$2"
    local current_value="${!var_name:-}"
    if [[ -z "${current_value}" ]] && hbs_is_interactive; then
        current_value="$(hbs_prompt_secret_path "${prompt}")"
        printf -v "${var_name}" '%s' "${current_value}"
    fi
    if [[ -z "${!var_name:-}" ]]; then
        log "ERROR: ${prompt} is required."
        exit 1
    fi
}

splunk_cli_cmd() {
    hbs_shell_join "${SPLUNK_HOME}/bin/splunk" "$@"
}

capture_splunk_as_service_user() {
    local raw_cmd="${1:-}"
    hbs_capture_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}"
}

assert_target_command() {
    local description="$1"
    local command_text="$2"
    local output
    if ! output="$(capture_splunk_as_service_user "${command_text}" 2>&1)"; then
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
    output="$(capture_splunk_as_service_user "${command_text}" 2>&1 || true)"
    if [[ "${output}" != *"${pattern}"* ]]; then
        log "ERROR: ${description} did not include expected pattern '${pattern}'."
        printf '%s\n' "${output}" >&2
        exit 1
    fi
    log "OK: ${description}"
}

load_rest_auth() {
    ensure_prompted_path ADMIN_PASSWORD_FILE "Admin password file path"
    ADMIN_PASSWORD="$(read_secret_file "${ADMIN_PASSWORD_FILE}")"
    # shellcheck disable=SC2034  # Consumed by get_session_key via sourced helpers.
    SPLUNK_USER="${ADMIN_USER}"
    # shellcheck disable=SC2034  # Consumed by get_session_key via sourced helpers.
    SPLUNK_PASS="${ADMIN_PASSWORD}"
    if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
        load_splunk_ssh_credentials
        SPLUNK_HOST="${SPLUNK_SSH_HOST}"
    fi
    load_splunk_connection_settings
    SPLUNK_MGMT_PORT="${MGMT_PORT}"
    if [[ "${EXECUTION_MODE}" == "local" ]]; then
        SPLUNK_HOST="localhost"
        SPLUNK_SEARCH_API_URI="https://localhost:${MGMT_PORT}"
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    elif [[ -n "${SPLUNK_HOST:-}" ]]; then
        SPLUNK_SEARCH_API_URI="https://${SPLUNK_HOST}:${MGMT_PORT}"
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --execution) require_arg "$1" $# || exit 1; EXECUTION_MODE="$2"; shift 2 ;;
        --host-bootstrap-role) require_arg "$1" $# || exit 1; HOST_BOOTSTRAP_ROLE="$2"; shift 2 ;;
        --forwarding-mode) require_arg "$1" $# || exit 1; FORWARDING_MODE="$2"; shift 2 ;;
        --indexer-discovery-name) require_arg "$1" $# || exit 1; INDEXER_DISCOVERY_NAME="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME="$2"; shift 2 ;;
        --service-user) require_arg "$1" $# || exit 1; SERVICE_USER="$2"; shift 2 ;;
        --admin-user) require_arg "$1" $# || exit 1; ADMIN_USER="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_prompted_value HOST_BOOTSTRAP_ROLE "Host bootstrap role"
validate_choice "${EXECUTION_MODE}" local ssh
validate_choice "${HOST_BOOTSTRAP_ROLE}" standalone-search-tier standalone-indexer heavy-forwarder cluster-manager indexer-peer shc-deployer shc-member
if [[ -n "${FORWARDING_MODE}" ]]; then
    validate_choice "${FORWARDING_MODE}" indexer-discovery server-list
fi

assert_target_command "Splunk binary exists" "$(hbs_shell_join test -x "${SPLUNK_HOME}/bin/splunk")"
assert_target_command "Splunk status command succeeds" "$(splunk_cli_cmd status)"
assert_target_command "Splunk version command succeeds" "$(splunk_cli_cmd version)"

load_rest_auth
SK="$(get_session_key "${SPLUNK_URI}")"
log "OK: REST authentication succeeded"
server_info="$(splunk_curl "${SK}" "${SPLUNK_URI}/services/server/info?output_mode=json" 2>/dev/null || true)"
if [[ "${server_info}" != *'"entry"'* ]]; then
    log "ERROR: REST server info check failed."
    exit 1
fi
log "OK: REST server info reachable"

case "${HOST_BOOTSTRAP_ROLE}" in
    standalone-indexer|indexer-peer)
        assert_output_contains "inputs.conf exposes splunktcp receiver" \
            "$(splunk_cli_cmd btool inputs list splunktcp --debug)" \
            "splunktcp://"
        ;;
    heavy-forwarder)
        outputs_btool="$(capture_splunk_as_service_user "$(splunk_cli_cmd btool outputs list --debug)" 2>&1 || true)"
        assert_output_contains "outputs.conf contains defaultGroup" \
            "$(splunk_cli_cmd btool outputs list --debug)" \
            "defaultGroup"
        assert_output_contains "outputs.conf disables local indexing" \
            "$(splunk_cli_cmd btool outputs list --debug)" \
            "indexAndForward = false"
        if [[ "${FORWARDING_MODE}" == "indexer-discovery" ]]; then
            assert_output_contains "outputs.conf contains indexer discovery stanza" \
                "$(splunk_cli_cmd btool outputs list --debug)" \
                "indexer_discovery:${INDEXER_DISCOVERY_NAME}"
        elif [[ "${FORWARDING_MODE}" == "server-list" ]]; then
            assert_output_contains "outputs.conf contains static server list" \
                "$(splunk_cli_cmd btool outputs list --debug)" \
                "server ="
        elif [[ "${outputs_btool}" == *"indexer_discovery:${INDEXER_DISCOVERY_NAME}"* ]]; then
            log "OK: outputs.conf uses indexer discovery"
        elif [[ "${outputs_btool}" == *"server ="* ]]; then
            log "OK: outputs.conf uses a static server list"
        else
            log "ERROR: outputs.conf did not include either indexer discovery or a static server list."
            printf '%s\n' "${outputs_btool}" >&2
            exit 1
        fi
        ;;
    cluster-manager)
        assert_output_contains "server.conf contains clustering stanza" \
            "$(splunk_cli_cmd btool server list clustering --debug)" \
            "mode ="
        assert_target_command "cluster-status command succeeds" "$(splunk_cli_cmd show cluster-status)"
        ;;
    shc-deployer|shc-member)
        assert_output_contains "server.conf contains shclustering stanza" \
            "$(splunk_cli_cmd btool server list shclustering --debug)" \
            "shcluster"
        ;;
esac

if [[ "${HOST_BOOTSTRAP_ROLE}" == "indexer-peer" ]]; then
    assert_output_contains "server.conf contains clustering stanza" \
        "$(splunk_cli_cmd btool server list clustering --debug)" \
        "mode ="
    assert_target_command "cluster-status command succeeds" "$(splunk_cli_cmd show cluster-status)"
fi

if [[ "${HOST_BOOTSTRAP_ROLE}" == "shc-member" ]]; then
    assert_target_command "search head cluster status succeeds" "$(splunk_cli_cmd show shcluster-status)"
fi

log "Validation completed for role ${HOST_BOOTSTRAP_ROLE}"
