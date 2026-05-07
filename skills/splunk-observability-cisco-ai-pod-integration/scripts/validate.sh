#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-cisco-ai-pod-rendered"
LIVE=false

usage() {
    cat <<'EOF'
Cisco AI Pod Integration (umbrella) validation

Usage:
  bash skills/splunk-observability-cisco-ai-pod-integration/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --live             Run oc/kubectl probes against the cluster + recursively against children
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

choose_kube_cli() {
    if [[ -n "${KUBE_CLI:-}" ]]; then
        command -v "${KUBE_CLI}" >/dev/null 2>&1 || return 1
        printf '%s\n' "${KUBE_CLI}"
        return 0
    fi
    if command -v oc >/dev/null 2>&1; then
        printf '%s\n' "oc"
        return 0
    fi
    if command -v kubectl >/dev/null 2>&1; then
        printf '%s\n' "kubectl"
        return 0
    fi
    return 1
}

check_intersight_log_errors() {
    local log_text="$1"
    if grep -q 'unknown service opentelemetry.proto.collector.metrics.v1.MetricsService' <<<"${log_text}"; then
        log "ERROR: intersight-otel OTLP metrics export reached an endpoint that did not implement MetricsService."
        log "       Check otel_collector_endpoint, the Service target port, and whether the running collector actually serves OTLP metrics on 4317."
        exit 1
    fi
    if grep -q 'Error sending metrics:' <<<"${log_text}"; then
        log "ERROR: intersight-otel is polling Intersight but failing to export metrics. Inspect the log line above before accepting validation."
        exit 1
    fi
}

check_live_collector_config() {
    local cli="$1"
    local found=false
    local relay
    while read -r ns name; do
        [[ -n "${ns}" && -n "${name}" ]] || continue
        found=true
        relay="$("${cli}" -n "${ns}" get configmap "${name}" -o jsonpath='{.data.relay}' 2>/dev/null || true)"
        if grep -q 'receiver_creator/nvidia:' <<<"${relay}"; then
            log "ERROR: ${ns}/${name} contains receiver_creator/nvidia, which can collide with chart autodetect. Use receiver_creator/dcgm-cisco for GPU/DCGM and a non-nvidia name for custom AI Pod receivers."
            exit 1
        fi
    done < <("${cli}" get configmaps -A --no-headers -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name 2>/dev/null | awk '$2 == "splunk-otel-collector-otel-agent" { print $1, $2 }')

    if [[ "${found}" != "true" ]]; then
        log "WARN: No splunk-otel-collector-otel-agent ConfigMap found during live collector config check."
    fi
}

current_intersight_logs() {
    local cli="$1"
    local pod
    pod="$("${cli}" -n intersight-otel get pods -l app=intersight-otel --sort-by=.metadata.creationTimestamp --no-headers 2>/dev/null \
        | awk '$3 == "Running" {name=$1} END {print name}')"
    if [[ -n "${pod}" ]]; then
        "${cli}" -n intersight-otel logs "pod/${pod}" --since=3m --tail=200 2>&1 || true
    else
        "${cli}" -n intersight-otel logs deployment/intersight-otel --since=3m --tail=200 2>&1 || true
    fi
}

HAVE_OUTPUT_DIR=false
if [[ -d "${OUTPUT_DIR}" ]]; then
    HAVE_OUTPUT_DIR=true
elif [[ "${LIVE}" == "true" ]]; then
    log "WARN: ${OUTPUT_DIR} not found; skipping rendered asset checks and running live probes only."
else
    log "ERROR: ${OUTPUT_DIR} not found."
    exit 1
fi

if [[ "${HAVE_OUTPUT_DIR}" == "true" ]]; then
    check_file() { [[ -f "$1" ]] || { log "ERROR: Missing $1"; exit 1; }; }
    check_file "${OUTPUT_DIR}/metadata.json"
    check_file "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"

    # Run each child's validate.sh recursively. Skip a child cleanly if its
    # render directory is missing (the child may have been disabled in the spec).
    for child in splunk-observability-cisco-nexus-integration splunk-observability-cisco-intersight-integration splunk-observability-nvidia-gpu-integration; do
        child_dir="${OUTPUT_DIR}/child-renders/${child}"
        if [[ -d "${child_dir}" ]]; then
            log "  Recursive validate: ${child}"
            child_args=(--output-dir "${child_dir}")
            if [[ "${LIVE}" == "true" ]]; then
                child_args+=(--live)
            fi
            bash "${PROJECT_ROOT}/skills/${child}/scripts/validate.sh" "${child_args[@]}" || {
                log "ERROR: child ${child} validation failed."
                exit 1
            }
        fi
    done

    # AI-Pod-specific overlay sanity.
    OVERLAY="${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"

    # Critical: receiver_creator/nvidia must NOT appear (composed from GPU child
    # which uses receiver_creator/dcgm-cisco; if receiver_creator/nvidia shows up
    # it means the chart autodetect collision risk is back).
    if grep -q 'receiver_creator/nvidia:' "${OVERLAY}"; then
        log "ERROR: composed overlay contains receiver_creator/nvidia (collides with chart autodetect)."
        exit 1
    fi

    # When NIM scrape mode is endpoints, rbac.customRules must be present.
    NIM_MODE="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('nim_scrape_mode', ''))" "${OUTPUT_DIR}/metadata.json")"
    if [[ "${NIM_MODE}" == "endpoints" ]]; then
        if ! grep -q 'customRules' "${OVERLAY}"; then
            log "ERROR: nim_scrape_mode=endpoints requires rbac.customRules in the overlay."
            exit 1
        fi
        if ! grep -q 'endpointslices' "${OVERLAY}"; then
            log "ERROR: rbac.customRules must include discovery.k8s.io/endpointslices."
            exit 1
        fi
    fi

    # OpenShift defaults present when distribution=openshift.
    DISTRIBUTION="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('distribution', ''))" "${OUTPUT_DIR}/metadata.json")"
    if [[ "${DISTRIBUTION}" == "openshift" ]]; then
        grep -q 'insecure_skip_verify: true' "${OVERLAY}" || {
            log "ERROR: OpenShift distribution requires kubeletstats.insecure_skip_verify=true."
            exit 1
        }
    fi

    # Token-scrub.
    if grep -rEq -- '"(accessToken|access_token|X-SF-Token|apiToken|token)"[[:space:]]*:[[:space:]]*"[A-Za-z0-9._-]{20,}"' "${OUTPUT_DIR}" 2>/dev/null; then
        if ! grep -rEq -- '"(accessToken|access_token|X-SF-Token|apiToken|token)"[[:space:]]*:[[:space:]]*"\$\{[A-Z_]+\}"' "${OUTPUT_DIR}" 2>/dev/null; then
            log "ERROR: A rendered file appears to contain an inline token."
            exit 1
        fi
    fi

    log "Cisco AI Pod Integration (umbrella) rendered assets passed static validation."
fi

if [[ "${LIVE}" == "true" ]]; then
    KUBE_CLI_BIN="$(choose_kube_cli || true)"
    if [[ -z "${KUBE_CLI_BIN}" ]]; then log "  ERROR: oc or kubectl not on PATH."; exit 1; fi
    log "  --live: probing cluster..."
    log "  Splunk OTel collector pods:"
    "${KUBE_CLI_BIN}" get pods -A -l app=splunk-otel-collector 2>&1 | head -10 || true
    log "  Intersight namespace:"
    "${KUBE_CLI_BIN}" -n intersight-otel get all 2>&1 | head -10 || true
    log "  Intersight export log check:"
    INTERSIGHT_LOGS="$(current_intersight_logs "${KUBE_CLI_BIN}")"
    printf '%s\n' "${INTERSIGHT_LOGS}" | grep -E 'Error sending metrics|unknown service|MetricsService|Received resouce metrics' | head -20 || true
    check_intersight_log_errors "${INTERSIGHT_LOGS}"
    check_live_collector_config "${KUBE_CLI_BIN}"
    log "  AI Pod-specific scrape errors in collector logs:"
    "${KUBE_CLI_BIN}" logs -A -l app=splunk-otel-collector --tail=200 2>&1 | grep -E 'forbidden|nim|vllm|milvus|trident|portworx|redfish' | head -10 || true
fi
