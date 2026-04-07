#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

EVENT_INDEXES=(
    em_logs
    netops
)
METRIC_INDEXES=(
    em_metrics
    netmetrics
)

CHECK_COMPOSE=false
CHECK_K8S=false
HEC_TOKEN_NAME="sc4snmp"
COMPOSE_RUNTIME=""
NAMESPACE="sc4snmp"
RELEASE_NAME="sc4snmp"
EXPECTED_DEFAULT_INDEX="netops"

PASS=0
WARN=0
FAIL=0
SK=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
SC4SNMP Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --check-compose              Validate the local Docker Compose runtime
  --check-k8s                  Validate the SC4SNMP Helm release and pods
  --hec-token-name NAME        HEC token name to inspect (default: sc4snmp)
  --compose-runtime NAME       Runtime override for --check-compose: docker|podman
  --namespace NAME             Kubernetes namespace (default: sc4snmp)
  --release-name NAME          Helm release name (default: sc4snmp)
  --help                       Show this help

With no flags, validates the Splunk-side SC4SNMP prerequisites and data flow.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --check-compose) CHECK_COMPOSE=true; shift ;;
        --check-k8s) CHECK_K8S=true; shift ;;
        --hec-token-name) require_arg "$1" $# || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --compose-runtime) require_arg "$1" $# || exit 1; COMPOSE_RUNTIME="$2"; shift 2 ;;
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

validate_indexes() {
    local idx datatype
    log "--- Indexes ---"
    for idx in "${EVENT_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            datatype="$(platform_get_index_datatype "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null || echo "")"
            case "${datatype}" in
                ""|event) pass "Index '${idx}' exists as an event index" ;;
                *) fail "Index '${idx}' exists but has datatype '${datatype}', expected 'event'" ;;
            esac
        else
            warn "Index '${idx}' not found"
        fi
    done

    for idx in "${METRIC_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            datatype="$(platform_get_index_datatype "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null || echo "")"
            case "${datatype}" in
                metric) pass "Index '${idx}' exists as a metrics index" ;;
                event) fail "Index '${idx}' exists but is an event index" ;;
                *) fail "Index '${idx}' exists but has datatype '${datatype}', expected 'metric'" ;;
            esac
        else
            warn "Index '${idx}' not found"
        fi
    done
    log ""
}

validate_hec_token() {
    # On Splunk Cloud, HEC tokens created via ACS may not be visible through
    # the management REST API used here; results may report "unknown" even
    # when the token exists and is functional.
    local token_state token_record ack_state restricted_indexes default_index
    log "--- HEC Token ---"
    token_state="$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
    case "${token_state}" in
        enabled) pass "HEC token '${HEC_TOKEN_NAME}' exists" ;;
        disabled) fail "HEC token '${HEC_TOKEN_NAME}' exists but is disabled" ;;
        missing) warn "HEC token '${HEC_TOKEN_NAME}' not found" ;;
        *) warn "Could not determine HEC token '${HEC_TOKEN_NAME}' status" ;;
    esac

    token_record="$(rest_get_hec_token_record "${SK}" "${SPLUNK_URI}" "${HEC_TOKEN_NAME}" 2>/dev/null || echo "{}")"
    ack_state="$(rest_json_field "${token_record}" "useACK")"
    restricted_indexes="$(rest_json_field "${token_record}" "indexes")"
    default_index="$(rest_json_field "${token_record}" "default_index")"
    if [[ -z "${default_index}" ]]; then
        default_index="$(rest_json_field "${token_record}" "index")"
    fi

    case "${ack_state}" in
        1|true|True)
            warn "HEC token '${HEC_TOKEN_NAME}' has acknowledgement enabled"
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

validate_sc4snmp_data() {
    local data_count metric_count
    log "--- SC4SNMP Data ---"
    data_count="$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" 'search index=em_logs OR index=netops | stats count as count' "count" 2>/dev/null || echo "0")"
    if [[ "${data_count}" =~ ^[0-9]+$ ]] && (( data_count > 0 )); then
        pass "Splunk contains ${data_count} SC4SNMP event(s)"
    else
        warn "No SC4SNMP event data found in Splunk yet (indexes: em_logs, netops)"
    fi

    metric_count="$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" '| mcatalog values(_dims) WHERE index=em_metrics OR index=netmetrics | stats count as count' "count" 2>/dev/null || echo "0")"
    if [[ "${metric_count}" =~ ^[0-9]+$ ]] && (( metric_count > 0 )); then
        pass "Splunk contains metric dimensions across em_metrics/netmetrics"
    else
        warn "No SC4SNMP metric data found in Splunk yet (indexes: em_metrics, netmetrics)"
    fi
    log ""
}

resolve_runtime() {
    if [[ -n "${COMPOSE_RUNTIME}" ]]; then
        printf '%s' "${COMPOSE_RUNTIME}"
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

validate_compose_runtime() {
    local runtime_name container_json running
    log "--- Compose Runtime ---"

    runtime_name="$(resolve_runtime)"
    if [[ -z "${runtime_name}" ]]; then
        fail "No supported container runtime found for --check-compose"
        log ""
        return 0
    fi

    container_json="$(${runtime_name} inspect SC4SNMP-worker-poller 2>/dev/null || true)"
    if [[ -z "${container_json}" ]]; then
        fail "SC4SNMP compose container 'SC4SNMP-worker-poller' not found in ${runtime_name}"
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

    if [[ "${running}" == "true" ]]; then
        pass "Container 'SC4SNMP-worker-poller' is running in ${runtime_name}"
    else
        fail "Container 'SC4SNMP-worker-poller' is not running in ${runtime_name}"
    fi
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
        pass "Found ${pod_summary%% *} SC4SNMP pod(s) in namespace '${NAMESPACE}'"
    else
        fail "No SC4SNMP pods found in namespace '${NAMESPACE}'"
    fi

    if [[ "${pod_summary##* }" =~ ^[0-9]+$ ]] && (( ${pod_summary##* } > 0 )); then
        pass "${pod_summary##* } SC4SNMP pod(s) report Ready"
    else
        warn "No SC4SNMP pods report Ready yet"
    fi
    log ""
}

log "=== SC4SNMP Validation ==="
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
validate_sc4snmp_data

if [[ "${CHECK_COMPOSE}" == "true" ]]; then
    validate_compose_runtime
fi

if [[ "${CHECK_K8S}" == "true" ]]; then
    validate_k8s_runtime
fi

log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ "${FAIL}" -gt 0 ]]; then
    exit 1
fi
