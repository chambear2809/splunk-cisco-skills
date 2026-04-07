#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_INDEXES=(
    sc4s
    print
    osnix
    oswinsec
    oswin
    netipam
    netproxy
    netwaf
    netops
    netlb
    netids
    netfw
    netdns
    netdlp
    netauth
    infraops
    gitops
    fireeye
    epintel
    epav
    email
)
OPTIONAL_METRICS_INDEX="_metrics"
EXPECTED_DEFAULT_INDEX="sc4s"

CHECK_HOST=false
CHECK_K8S=false
HEC_TOKEN_NAME="sc4s"
RUNTIME=""
NAMESPACE="sc4s"
RELEASE_NAME="sc4s"

PASS=0
WARN=0
FAIL=0
SK=""
INGEST_SK=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
SC4S Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --check-host                 Validate the local SC4S container runtime
  --check-k8s                  Validate the SC4S Helm release and pods
  --hec-token-name NAME        HEC token name to inspect (default: sc4s)
  --runtime docker|podman      Host runtime override for --check-host
  --namespace NAME             Kubernetes namespace (default: sc4s)
  --release-name NAME          Helm release name (default: sc4s)
  --help                       Show this help

With no flags, validates the Splunk-side SC4S prerequisites and startup events.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check-host) CHECK_HOST=true; shift ;;
        --check-k8s) CHECK_K8S=true; shift ;;
        --hec-token-name) require_arg "$1" $# || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --runtime) require_arg "$1" $# || exit 1; RUNTIME="$2"; shift 2 ;;
        --namespace) require_arg "$1" $# || exit 1; NAMESPACE="$2"; shift 2 ;;
        --release-name) require_arg "$1" $# || exit 1; RELEASE_NAME="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

ensure_search_session() {
    if ! load_splunk_credentials; then
        fail "Could not load Splunk credentials — check credentials file"
        return 1
    fi
    if ! SK=$(get_session_key "${SPLUNK_URI}"); then
        fail "Could not authenticate to Splunk REST API — check credentials"
        return 1
    fi
    return 0
}

ensure_ingest_session() {
    local saved_user saved_pass

    if ! load_splunk_credentials; then
        fail "Could not load Splunk credentials — check credentials file"
        return 1
    fi
    load_ingest_connection_settings

    saved_user="${SPLUNK_USER:-}"
    saved_pass="${SPLUNK_PASS:-}"
    SPLUNK_USER="${INGEST_SPLUNK_USER:-${SPLUNK_USER:-}}"
    SPLUNK_PASS="${INGEST_SPLUNK_PASS:-${SPLUNK_PASS:-}}"
    if ! INGEST_SK=$(get_session_key "${INGEST_SPLUNK_URI}"); then
        SPLUNK_USER="${saved_user}"
        SPLUNK_PASS="${saved_pass}"
        fail "Could not authenticate to the ingest-tier Splunk REST API — check ingest credentials"
        return 1
    fi
    SPLUNK_USER="${saved_user}"
    SPLUNK_PASS="${saved_pass}"
    return 0
}

inspect_hec_token_state() {
    local token_name="$1"

    if is_splunk_cloud; then
        rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown"
        return 0
    fi
    if type deployment_should_manage_ingest_hec_via_bundle >/dev/null 2>&1 \
        && deployment_should_manage_ingest_hec_via_bundle; then
        deployment_get_bundle_hec_token_state "${token_name}" 2>/dev/null || echo "unknown"
        return 0
    fi
    ensure_ingest_session || return 1
    rest_get_hec_token_state "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown"
}

inspect_hec_token_record() {
    local token_name="$1"

    if is_splunk_cloud; then
        rest_get_hec_token_record "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}"
        return 0
    fi
    if type deployment_should_manage_ingest_hec_via_bundle >/dev/null 2>&1 \
        && deployment_should_manage_ingest_hec_via_bundle; then
        deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null || echo "{}"
        return 0
    fi
    ensure_ingest_session || return 1
    rest_get_hec_token_record "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}"
}

validate_indexes() {
    local idx metrics_datatype
    log "--- Indexes ---"
    for idx in "${DEFAULT_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            pass "Index '${idx}' exists"
        else
            warn "Index '${idx}' not found"
        fi
    done

    if platform_check_index "${SK}" "${SPLUNK_URI}" "${OPTIONAL_METRICS_INDEX}" 2>/dev/null; then
        metrics_datatype="$(platform_get_index_datatype "${SK}" "${SPLUNK_URI}" "${OPTIONAL_METRICS_INDEX}" 2>/dev/null || echo "")"
        case "${metrics_datatype}" in
            metric)
                pass "Optional metrics index '${OPTIONAL_METRICS_INDEX}' exists and is a metrics index"
                ;;
            event)
                fail "Optional metrics index '${OPTIONAL_METRICS_INDEX}' exists but is an event index"
                ;;
            "")
                warn "Optional metrics index '${OPTIONAL_METRICS_INDEX}' exists but its datatype could not be determined"
                ;;
            *)
                fail "Optional metrics index '${OPTIONAL_METRICS_INDEX}' exists with unexpected datatype '${metrics_datatype}'"
                ;;
        esac
    else
        warn "Optional metrics index '${OPTIONAL_METRICS_INDEX}' not found"
    fi
    log ""
}

validate_hec_token() {
    local token_state token_record ack_state restricted_indexes default_index
    log "--- HEC Token ---"
    token_state="$(inspect_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
    case "${token_state}" in
        enabled) pass "HEC token '${HEC_TOKEN_NAME}' exists" ;;
        disabled) fail "HEC token '${HEC_TOKEN_NAME}' exists but is disabled" ;;
        missing) warn "HEC token '${HEC_TOKEN_NAME}' not found" ;;
        *) warn "Could not determine HEC token '${HEC_TOKEN_NAME}' status" ;;
    esac

    token_record="$(inspect_hec_token_record "${HEC_TOKEN_NAME}" 2>/dev/null || echo "{}")"
    ack_state="$(rest_json_field "${token_record}" "useACK")"
    restricted_indexes="$(rest_json_field "${token_record}" "indexes")"
    default_index="$(rest_json_field "${token_record}" "default_index")"
    if [[ -z "${default_index}" ]]; then
        default_index="$(rest_json_field "${token_record}" "index")"
    fi

    case "${ack_state}" in
        1|true|True)
            fail "HEC token '${HEC_TOKEN_NAME}' has acknowledgement enabled"
            ;;
        0|false|False)
            pass "HEC token '${HEC_TOKEN_NAME}' does not use HEC ACK"
            ;;
        *)
            warn "Could not determine HEC ACK state for '${HEC_TOKEN_NAME}' (got '${ack_state}')"
            ;;
    esac

    if [[ -n "${restricted_indexes}" ]]; then
        warn "HEC token '${HEC_TOKEN_NAME}' restricts Selected Indexes to: ${restricted_indexes}"
    fi
    if [[ -n "${default_index}" ]]; then
        if [[ "${default_index}" == "${EXPECTED_DEFAULT_INDEX}" ]]; then
            pass "HEC token '${HEC_TOKEN_NAME}' default index: ${default_index}"
        else
            fail "HEC token '${HEC_TOKEN_NAME}' default index is '${default_index}', expected '${EXPECTED_DEFAULT_INDEX}'"
        fi
    fi
    log ""
}

validate_startup_events() {
    local startup_count
    log "--- SC4S Startup Events ---"
    startup_count="$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" 'search index=sc4s sourcetype=sc4s:events "starting up" | stats count as count' "count" 2>/dev/null || echo "0")"
    if [[ "${startup_count}" =~ ^[0-9]+$ ]] && (( startup_count > 0 )); then
        pass "Splunk contains ${startup_count} SC4S startup event(s)"
    else
        warn "No SC4S startup events were found in Splunk yet"
    fi
    log ""
}

resolve_runtime() {
    if [[ -n "${RUNTIME}" ]]; then
        printf '%s' "${RUNTIME}"
        return 0
    fi
    if command_exists docker; then
        printf '%s' "docker"
        return 0
    fi
    if command_exists podman; then
        printf '%s' "podman"
        return 0
    fi
    printf '%s' ""
}

validate_host_runtime() {
    local runtime_name container_json running health log_output
    runtime_name="$(resolve_runtime)"
    log "--- Host Runtime ---"

    if [[ -z "${runtime_name}" ]]; then
        fail "No supported container runtime found for --check-host"
        log ""
        return 0
    fi

    container_json="$(${runtime_name} inspect SC4S 2>/dev/null || true)"
    if [[ -z "${container_json}" ]]; then
        fail "SC4S container 'SC4S' not found in ${runtime_name}"
        log ""
        return 0
    fi

    running="$(printf '%s' "${container_json}" | python3 -c "
import json
import sys
try:
    data = json.load(sys.stdin)
    item = data[0] if isinstance(data, list) and data else {}
    state = item.get('State', {}) or {}
    print('true' if state.get('Running') else 'false', end='')
except Exception:
    print('unknown', end='')
" 2>/dev/null)"
    health="$(printf '%s' "${container_json}" | python3 -c "
import json
import sys
try:
    data = json.load(sys.stdin)
    item = data[0] if isinstance(data, list) and data else {}
    state = item.get('State', {}) or {}
    health = state.get('Health', {}) or {}
    print(health.get('Status', 'none'), end='')
except Exception:
    print('unknown', end='')
" 2>/dev/null)"

    if [[ "${running}" == "true" ]]; then
        pass "Container 'SC4S' is running in ${runtime_name}"
    else
        fail "Container 'SC4S' is not running in ${runtime_name}"
    fi

    case "${health}" in
        healthy) pass "Container health check reports healthy" ;;
        unhealthy) fail "Container health check reports unhealthy" ;;
        none|unknown) warn "Container health status is ${health}" ;;
        *) warn "Container health status is ${health}" ;;
    esac

    log_output="$(${runtime_name} logs --tail 200 SC4S 2>&1 || true)"
    case "${log_output}" in
        *"starting syslog-ng"*|*"SC4S_ENV_CHECK_HEC"*)
            pass "Container logs show SC4S startup markers"
            ;;
        *)
            warn "Container logs do not show the expected SC4S startup markers"
            ;;
    esac
    log ""
}

validate_k8s_runtime() {
    local helm_output pods_json pod_summary
    log "--- Kubernetes Runtime ---"

    if ! command_exists helm; then
        fail "helm is required for --check-k8s"
        log ""
        return 0
    fi
    if ! command_exists kubectl; then
        fail "kubectl is required for --check-k8s"
        log ""
        return 0
    fi

    helm_output="$(helm status "${RELEASE_NAME}" -n "${NAMESPACE}" 2>/dev/null || true)"
    if [[ -n "${helm_output}" ]]; then
        pass "Helm release '${RELEASE_NAME}' exists in namespace '${NAMESPACE}'"
    else
        fail "Helm release '${RELEASE_NAME}' was not found in namespace '${NAMESPACE}'"
        log ""
        return 0
    fi

    pods_json="$(kubectl get pods -n "${NAMESPACE}" -l "app.kubernetes.io/instance=${RELEASE_NAME}" -o json 2>/dev/null || true)"
    pod_summary="$(printf '%s' "${pods_json}" | python3 -c "
import json
import sys
try:
    data = json.load(sys.stdin)
    items = data.get('items', [])
    total = len(items)
    ready = 0
    for item in items:
        statuses = item.get('status', {}).get('containerStatuses', []) or []
        if statuses and all(status.get('ready') for status in statuses):
            ready += 1
    print(f'{total} {ready}', end='')
except Exception:
    print('0 0', end='')
" 2>/dev/null)"
    if [[ -z "${pod_summary}" ]]; then
        pod_summary="0 0"
    fi

    if [[ "${pod_summary%% *}" =~ ^[0-9]+$ ]] && (( ${pod_summary%% *} > 0 )); then
        pass "Found ${pod_summary%% *} SC4S pod(s) in namespace '${NAMESPACE}'"
    else
        fail "No SC4S pods found in namespace '${NAMESPACE}'"
    fi

    if [[ "${pod_summary##* }" =~ ^[0-9]+$ ]] && (( ${pod_summary##* } > 0 )); then
        pass "${pod_summary##* } SC4S pod(s) report Ready"
    else
        warn "No SC4S pods report Ready yet"
    fi
    log ""
}

log "=== SC4S Validation ==="
log ""
warn_if_current_skill_role_unsupported
log "--- Splunk Authentication ---"
if ! ensure_search_session; then
    log ""
    log "=== Validation Summary ==="
    log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
    exit 1
fi
pass "Authenticated to Splunk REST API"
log ""

validate_indexes
validate_hec_token
validate_startup_events

if [[ "${CHECK_HOST}" == "true" ]]; then
    validate_host_runtime
fi

if [[ "${CHECK_K8S}" == "true" ]]; then
    validate_k8s_runtime
fi

log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ "${FAIL}" -gt 0 ]]; then
    exit 1
fi
