#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-cisco-intersight-rendered"
LIVE=false

usage() {
    cat <<'EOF'
Cisco Intersight Integration validation

Usage:
  bash skills/splunk-observability-cisco-intersight-integration/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --live             Run oc/kubectl probes against the cluster
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

extract_endpoint_from_configmap() {
    local cli="$1"
    local ns="$2"
    "${cli}" -n "${ns}" get configmap intersight-otel-config \
        -o jsonpath='{.data.intersight-otel\.toml}' 2>/dev/null \
        | sed -n 's/^[[:space:]]*otel_collector_endpoint[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' \
        | head -1
}

assert_metrics_pipeline_accepts_otlp() {
    local relay="$1"
    printf '%s\n' "${relay}" | awk '
        /^service:/ { in_service = 1; next }
        in_service && /^  pipelines:/ { in_pipelines = 1; next }
        in_pipelines && /^    metrics:/ { in_metrics = 1; next }
        in_metrics && /^    [^[:space:]][^:]*:/ { exit }
        in_metrics && /^[[:space:]]*- otlp[[:space:]]*$/ { found = 1 }
        END { exit(found ? 0 : 1) }
    '
}

check_live_collector_endpoint() {
    local cli="$1"
    local endpoint="$2"

    if [[ "${endpoint}" =~ observability\.splunkcloud\.com|signalfx\.com|/services/collector|:8088 ]]; then
        log "ERROR: intersight-otel is pointed at a cloud/platform ingest endpoint (${endpoint}), not the in-cluster OTLP gRPC collector receiver."
        exit 1
    fi

    if [[ ! "${endpoint}" =~ ^http://([a-z0-9-]+)\.([a-z0-9-]+)\.svc\.cluster\.local:([0-9]+)$ ]]; then
        log "WARN: intersight-otel endpoint has a non-standard shape: ${endpoint}"
        return 0
    fi

    local svc="${BASH_REMATCH[1]}"
    local svc_ns="${BASH_REMATCH[2]}"
    local port="${BASH_REMATCH[3]}"
    if [[ "${port}" != "4317" ]]; then
        log "ERROR: intersight-otel must send OTLP gRPC metrics to port 4317; got ${endpoint}."
        exit 1
    fi

    if ! "${cli}" -n "${svc_ns}" get svc "${svc}" >/dev/null 2>&1; then
        log "ERROR: OTLP target service ${svc_ns}/${svc} does not exist."
        exit 1
    fi
    if ! "${cli}" -n "${svc_ns}" get svc "${svc}" -o jsonpath='{range .spec.ports[*]}{.port}{"\n"}{end}' 2>/dev/null | grep -qx "${port}"; then
        log "ERROR: OTLP target service ${svc_ns}/${svc} does not expose port ${port}."
        exit 1
    fi

    local release cfg relay
    release="$("${cli}" -n "${svc_ns}" get svc "${svc}" -o jsonpath='{.metadata.labels.release}' 2>/dev/null || true)"
    if [[ -z "${release}" ]]; then
        log "WARN: Could not infer Splunk OTel release label from ${svc_ns}/${svc}; skipping collector config pipeline check."
        return 0
    fi
    cfg="${release}-otel-agent"
    relay="$("${cli}" -n "${svc_ns}" get configmap "${cfg}" -o jsonpath='{.data.relay}' 2>/dev/null || true)"
    if [[ -z "${relay}" ]]; then
        log "WARN: Could not read ${svc_ns}/${cfg}; skipping collector config pipeline check."
        return 0
    fi
    if ! assert_metrics_pipeline_accepts_otlp "${relay}"; then
        log "ERROR: ${svc_ns}/${cfg} does not wire receiver 'otlp' into service.pipelines.metrics.receivers."
        exit 1
    fi
}

check_live_log_errors() {
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

current_intersight_logs() {
    local cli="$1"
    local ns="$2"
    local pod
    pod="$("${cli}" -n "${ns}" get pods -l app=intersight-otel --sort-by=.metadata.creationTimestamp --no-headers 2>/dev/null \
        | awk '$3 == "Running" {name=$1} END {print name}')"
    if [[ -n "${pod}" ]]; then
        "${cli}" -n "${ns}" logs "pod/${pod}" --since=3m --tail=200 2>&1 || true
    else
        "${cli}" -n "${ns}" logs deployment/intersight-otel --since=3m --tail=200 2>&1 || true
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
    check_file "${OUTPUT_DIR}/intersight-integration/intersight-otel-namespace.yaml"
    check_file "${OUTPUT_DIR}/intersight-integration/intersight-credentials-secret.yaml"
    check_file "${OUTPUT_DIR}/intersight-integration/intersight-otel-config.yaml"
    check_file "${OUTPUT_DIR}/intersight-integration/intersight-otel-deployment.yaml"

    # Token-scrub: no real Intersight key material in any rendered file.
    # The Secret stub is allowed PLACEHOLDER_* literals.
    if grep -rEq -- 'BEGIN [A-Z]+ PRIVATE KEY' "${OUTPUT_DIR}" 2>/dev/null; then
        if ! grep -rEq -- 'PLACEHOLDER_PRIVATE_KEY_PEM_CONTENT' "${OUTPUT_DIR}" 2>/dev/null; then
            log "ERROR: A rendered file appears to contain a non-placeholder private key block."
            exit 1
        fi
    fi

    # Confirm OTLP endpoint shape.
    if ! grep -q 'otel_collector_endpoint' "${OUTPUT_DIR}/intersight-integration/intersight-otel-config.yaml"; then
        log "ERROR: ConfigMap missing otel_collector_endpoint."
        exit 1
    fi
    if ! grep -Eq 'http://[a-z0-9-]+-splunk-otel-collector-agent\.[a-z0-9-]+\.svc\.cluster\.local:[0-9]+' "${OUTPUT_DIR}/intersight-integration/intersight-otel-config.yaml"; then
        log "ERROR: ConfigMap otel_collector_endpoint does not match the expected Splunk OTel agent service shape."
        exit 1
    fi

    log "Cisco Intersight Integration rendered assets passed static validation."
fi

if [[ "${LIVE}" == "true" ]]; then
    KUBE_CLI_BIN="$(choose_kube_cli || true)"
    if [[ -z "${KUBE_CLI_BIN}" ]]; then log "  ERROR: oc or kubectl not on PATH."; exit 1; fi
    if [[ "${HAVE_OUTPUT_DIR}" == "true" ]]; then
        NS="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('intersight_namespace', 'intersight-otel'))" "${OUTPUT_DIR}/metadata.json")"
    else
        NS="intersight-otel"
    fi
    log "  --live: probing namespace ${NS}..."
    "${KUBE_CLI_BIN}" -n "${NS}" get pods,deployment,configmap,secret 2>&1 | head -20 || true
    ENDPOINT="$(extract_endpoint_from_configmap "${KUBE_CLI_BIN}" "${NS}" || true)"
    if [[ -n "${ENDPOINT}" ]]; then
        log "  intersight-otel OTLP endpoint: ${ENDPOINT}"
        check_live_collector_endpoint "${KUBE_CLI_BIN}" "${ENDPOINT}"
    else
        log "WARN: Could not read intersight-otel ConfigMap endpoint from namespace ${NS}."
    fi
    log "  intersight-otel pod log tail:"
    LOG_TAIL="$(current_intersight_logs "${KUBE_CLI_BIN}" "${NS}")"
    printf '%s\n' "${LOG_TAIL}" | head -80 || true
    check_live_log_errors "${LOG_TAIL}"
fi
