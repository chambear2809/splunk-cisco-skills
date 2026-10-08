#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
SERVICE_USER="${SERVICE_USER:-splunk}"
MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"
KVSTORE_READY_TIMEOUT_SECONDS="${SPLUNK_KVSTORE_READY_TIMEOUT_SECONDS:-300}"
EXECUTION_MODE="local"
HOST_BOOTSTRAP_ROLE=""
FORWARDING_MODE=""
INDEXER_DISCOVERY_NAME="cluster_manager"
ADMIN_USER="admin"
ADMIN_PASSWORD_FILE=""
ADMIN_PASSWORD=""
REST_URI=""

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
  --mgmt-port PORT (default: 8089)
  --kvstore-ready-timeout-seconds SECONDS (default: 300)
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
    local rest_uri=""

    ensure_prompted_path ADMIN_PASSWORD_FILE "Admin password file path"
    SPLUNK_MGMT_PORT="${MGMT_PORT}"
    if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
        load_splunk_ssh_credentials || return 1
        rest_uri="$(_format_splunk_https_endpoint "127.0.0.1" "${MGMT_PORT}")" || return 1
        REST_URI="${rest_uri}"
        return 0
    fi

    if ! ADMIN_PASSWORD="$(read_secret_file "${ADMIN_PASSWORD_FILE}")"; then
        log "ERROR: Could not read the selected admin password file."
        return 1
    fi
    # shellcheck disable=SC2034  # Consumed by get_session_key via sourced helpers.
    SPLUNK_USER="${ADMIN_USER}"
    # shellcheck disable=SC2034  # Consumed by get_session_key via sourced helpers.
    SPLUNK_PASS="${ADMIN_PASSWORD}"
    load_splunk_connection_settings || return 1
    rest_uri="$(_format_splunk_https_endpoint "localhost" "${MGMT_PORT}")" || return 1
    if [[ -n "${rest_uri}" ]]; then
        _credential_transition_runtime_route "${rest_uri}" preserve || return 1
    fi
    REST_URI="${rest_uri}"
}

get_ssh_session_key_from_password_file() {
    local request_body raw_cmd response session_key
    if ! request_body="$(_secure_password_form_body "${ADMIN_PASSWORD_FILE}" "${ADMIN_USER}" 2>/dev/null)"; then
        printf '%s\n' "ERROR: Admin password file failed the secure-file checks." >&2
        return 1
    fi
    raw_cmd="$(hbs_shell_join curl -q -sS -k --connect-timeout 10 --max-time 30 -d @- "${REST_URI}/services/auth/login")"
    if ! response="$(hbs_capture_target_cmd_with_stdin ssh "${raw_cmd}" "${request_body}")"; then
        request_body=""
        printf '%s\n' "ERROR: Could not reach the target's loopback Splunk REST login endpoint over SSH." >&2
        return 1
    fi
    request_body=""
    session_key="$(sed -n 's/.*<sessionKey>\([^<]*\)<.*/\1/p' <<<"${response}" | head -n 1)"
    if ! _validate_splunk_session_key "${session_key}"; then
        printf '%s\n' "ERROR: REST authentication failed against the target's loopback management endpoint." >&2
        return 1
    fi
    printf '%s' "${session_key}"
}

host_rest_get() {
    local session_key="${1:-}"
    local uri="${2:-}"
    if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
        local curl_config raw_cmd
        curl_config="$(printf 'header = \"Authorization: Splunk %s\"\n' "${session_key}")"
        raw_cmd="$(hbs_shell_join curl -q -sS -k --connect-timeout 10 --max-time 120 -K - "${uri}")"
        hbs_capture_target_cmd_with_stdin ssh "${raw_cmd}" "${curl_config}"
    else
        splunk_curl "${session_key}" "${uri}"
    fi
}

extract_server_version() {
    local payload="${1:-}"
    python3 -c '
import json
import re
import sys

try:
    payload = json.load(sys.stdin)
    entry = (payload.get("entry") or [])[0]
    content = entry.get("content", {}) if isinstance(entry, dict) else {}
    version = str(content.get("version") or "").strip()
except (ValueError, TypeError, IndexError, AttributeError):
    version = ""
match = re.fullmatch(r"\d+(?:\.\d+){1,3}", version)
if match:
    print(version)
' <<<"${payload}"
}

version_at_least_10_6() {
    local version="${1:-}"
    python3 - "${version}" <<'PY'
import re
import sys

parts = sys.argv[1].split(".")
if not re.fullmatch(r"\d+(?:\.\d+){1,3}", sys.argv[1]):
    raise SystemExit(1)
numbers = tuple(int(part) for part in parts)
raise SystemExit(0 if numbers >= (10, 6) else 1)
PY
}

kvstore_config_value() {
    local config_text="${1:-}"
    local target_key="${2:-}"
    awk -F= -v target_key="${target_key}" '
        {
            key = $1
            gsub(/[[:space:]]/, "", key)
            if (key == target_key) {
                value = $2
                gsub(/[[:space:]]/, "", value)
                result = tolower(value)
            }
        }
        END { print result }
    ' <<<"${config_text}"
}

parse_kvstore_status() {
    local status_json="${1:-}"
    local require_cohosted="${2:-false}"
    python3 -c '
import json
import re
import sys

def safe(value):
    text = str(value if value is not None else "unknown").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", text)
    return cleaned[:80] or "unknown"

try:
    payload = json.load(sys.stdin)
    entries = payload.get("entry") or []
    content = entries[0].get("content", {}) if entries and isinstance(entries[0], dict) else {}
    current = content.get("current", {}) if isinstance(content, dict) else {}
    cohosted = content.get("cohosted", {}) if isinstance(content, dict) else {}
    if not cohosted and isinstance(current, dict):
        cohosted = current.get("cohosted", {}) or current.get("cohostedKVStore", {})
    if not cohosted and isinstance(content, dict):
        cohosted = content.get("cohostedKVStore", {}) or content.get("cohostedKVStoreInformation", {})
    if not isinstance(current, dict):
        current = {}
    if not isinstance(cohosted, dict):
        cohosted = {}
    member_status = safe(current.get("status", content.get("status", "unknown"))).lower()
    cohosted_status = safe(cohosted.get("status", "unknown")).lower()
    migration_status = safe(current.get("migrationStatus", content.get("migrationStatus", "unknown")))
    cohosted_type = safe(cohosted.get("type", "unknown"))
except (ValueError, TypeError, IndexError, AttributeError):
    member_status = "unknown"
    cohosted_status = "unknown"
    migration_status = "unknown"
    cohosted_type = "unknown"

ready = member_status == "ready"
if sys.argv[1].lower() == "true":
    ready = ready and cohosted_status == "ready"
print("\t".join(("ready" if ready else "not-ready", member_status, cohosted_status, migration_status, cohosted_type)))
' "${require_cohosted}" <<<"${status_json}"
}

wait_for_kvstore_ready() {
    local require_cohosted="${1:-false}"
    local timeout_seconds="${2:-300}"
    local started elapsed remaining sleep_seconds status_json summary
    local readiness member_status cohosted_status migration_status cohosted_type
    started="${SECONDS}"

    local requirement_label=""
    [[ "${require_cohosted}" != "true" ]] || requirement_label=" (cohosted store required)"
    log "Waiting up to ${timeout_seconds}s for KV Store readiness${requirement_label}."
    while true; do
        status_json="$(host_rest_get "${SK}" "${REST_URI}/services/kvstore/status?output_mode=json" 2>/dev/null || true)"
        summary="$(parse_kvstore_status "${status_json}" "${require_cohosted}")" || summary=$'not-ready\tunknown\tunknown\tunknown\tunknown'
        IFS=$'\t' read -r readiness member_status cohosted_status migration_status cohosted_type <<<"${summary}"
        if [[ "${readiness:-not-ready}" == "ready" ]]; then
            log "OK: KV Store is ready (member=${member_status}, cohosted=${cohosted_status}, type=${cohosted_type}, migration=${migration_status})."
            return 0
        fi

        elapsed=$((SECONDS - started))
        if (( elapsed >= timeout_seconds )); then
            log "ERROR: KV Store did not become ready within ${timeout_seconds}s (member=${member_status:-unknown}, cohosted=${cohosted_status:-unknown}, type=${cohosted_type:-unknown}, migration=${migration_status:-unknown})."
            log "Inspect ${SPLUNK_HOME}/var/log/splunk/splunkd.log and, on Enterprise 10.6 cohosted KV Store, sup-pkg-kvstore-pdl.log and sup-pkg-kvstore-pdl-stdout.log."
            return 1
        fi

        if (( elapsed == 0 || elapsed % 30 == 0 )); then
            log "Waiting for KV Store (member=${member_status:-unknown}, cohosted=${cohosted_status:-unknown}, migration=${migration_status:-unknown}; elapsed ${elapsed}s)."
        fi
        remaining=$((timeout_seconds - elapsed))
        sleep_seconds=5
        (( remaining < sleep_seconds )) && sleep_seconds="${remaining}"
        sleep "${sleep_seconds}"
    done
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --execution) require_arg "$1" $# || exit 1; EXECUTION_MODE="$2"; shift 2 ;;
        --host-bootstrap-role) require_arg "$1" $# || exit 1; HOST_BOOTSTRAP_ROLE="$2"; shift 2 ;;
        --forwarding-mode) require_arg "$1" $# || exit 1; FORWARDING_MODE="$2"; shift 2 ;;
        --indexer-discovery-name) require_arg "$1" $# || exit 1; INDEXER_DISCOVERY_NAME="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME="$2"; shift 2 ;;
        --service-user) require_arg "$1" $# || exit 1; SERVICE_USER="$2"; shift 2 ;;
        --mgmt-port) require_arg "$1" $# || exit 1; MGMT_PORT="$2"; shift 2 ;;
        --kvstore-ready-timeout-seconds) require_arg "$1" $# || exit 1; KVSTORE_READY_TIMEOUT_SECONDS="$2"; shift 2 ;;
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
if [[ ! "${MGMT_PORT}" =~ ^[0-9]+$ ]] || (( 10#${MGMT_PORT} < 1 || 10#${MGMT_PORT} > 65535 )); then
    log "ERROR: Management port must be a numeric value from 1 through 65535."
    exit 1
fi
if [[ ! "${KVSTORE_READY_TIMEOUT_SECONDS}" =~ ^[0-9]+$ ]] || (( 10#${KVSTORE_READY_TIMEOUT_SECONDS} < 1 || 10#${KVSTORE_READY_TIMEOUT_SECONDS} > 3600 )); then
    log "ERROR: KV Store readiness timeout must be a numeric value from 1 through 3600 seconds."
    exit 1
fi

assert_target_command "Splunk binary exists" "$(hbs_shell_join test -x "${SPLUNK_HOME}/bin/splunk")"
assert_target_command "Splunk status command succeeds" "$(splunk_cli_cmd status)"
assert_target_command "Splunk version command succeeds" "$(splunk_cli_cmd version)"

load_rest_auth || {
    log "ERROR: Could not prepare the selected REST authentication route."
    exit 1
}
if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
    if ! SK="$(get_ssh_session_key_from_password_file)" || [[ -z "${SK}" ]]; then
        log "ERROR: REST authentication failed."
        exit 1
    fi
elif ! SK="$(get_session_key "${SPLUNK_URI}")" || [[ -z "${SK}" ]]; then
    log "ERROR: REST authentication failed."
    exit 1
fi
log "OK: REST authentication succeeded"
server_info="$(host_rest_get "${SK}" "${REST_URI}/services/server/info?output_mode=json" 2>/dev/null || true)"
if [[ "${server_info}" != *'"entry"'* ]]; then
    log "ERROR: REST server info check failed."
    exit 1
fi
server_version="$(extract_server_version "${server_info}")"
if [[ -z "${server_version}" ]]; then
    log "ERROR: REST server info did not contain a valid Splunk version."
    exit 1
fi
log "OK: REST server info reachable (Splunk ${server_version})"

kvstore_config="$(capture_splunk_as_service_user "$(splunk_cli_cmd btool server list kvstore)" 2>/dev/null || true)"
kvstore_disabled="$(kvstore_config_value "${kvstore_config}" disabled)"
if [[ "${kvstore_disabled}" == "true" || "${kvstore_disabled}" == "1" ]]; then
    log "OK: KV Store is explicitly disabled in effective server.conf; readiness check is not applicable."
else
    kvstore_default_type="$(kvstore_config_value "${kvstore_config}" defaultKVStoreType)"
    require_cohosted=false
    if version_at_least_10_6 "${server_version}" && [[ "${kvstore_default_type}" != "local" ]]; then
        require_cohosted=true
    fi
    wait_for_kvstore_ready "${require_cohosted}" "${KVSTORE_READY_TIMEOUT_SECONDS}" || exit 1
fi

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
