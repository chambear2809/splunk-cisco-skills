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
  --live             Run kubectl probes against the cluster
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

if [[ ! -d "${OUTPUT_DIR}" ]]; then log "ERROR: ${OUTPUT_DIR} not found."; exit 1; fi

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

if [[ "${LIVE}" == "true" ]]; then
    if ! command -v kubectl >/dev/null 2>&1; then log "  ERROR: kubectl not on PATH."; exit 1; fi
    NS="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('intersight_namespace', 'intersight-otel'))" "${OUTPUT_DIR}/metadata.json")"
    log "  --live: probing namespace ${NS}..."
    kubectl -n "${NS}" get pods,deployment,configmap,secret 2>&1 | head -20 || true
    log "  intersight-otel pod log tail:"
    kubectl -n "${NS}" logs deployment/intersight-otel --tail=20 2>&1 | head -25 || true
fi
