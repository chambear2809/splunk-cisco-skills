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
  --live             Run kubectl probes against the cluster + recursively against children
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
check_file "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"

# Run each child's validate.sh recursively. Skip a child cleanly if its
# render directory is missing (the child may have been disabled in the spec).
for child in splunk-observability-cisco-nexus-integration splunk-observability-cisco-intersight-integration splunk-observability-nvidia-gpu-integration; do
    child_dir="${OUTPUT_DIR}/child-renders/${child}"
    if [[ -d "${child_dir}" ]]; then
        log "  Recursive validate: ${child}"
        bash "${PROJECT_ROOT}/skills/${child}/scripts/validate.sh" --output-dir "${child_dir}" || {
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

if [[ "${LIVE}" == "true" ]]; then
    if ! command -v kubectl >/dev/null 2>&1; then log "  ERROR: kubectl not on PATH."; exit 1; fi
    log "  --live: probing cluster..."
    log "  Splunk OTel collector pods:"
    kubectl get pods -A -l app=splunk-otel-collector 2>&1 | head -10 || true
    log "  Intersight namespace:"
    kubectl -n intersight-otel get all 2>&1 | head -10 || true
    log "  AI Pod-specific scrape errors in collector logs:"
    kubectl logs -A -l app=splunk-otel-collector --tail=200 2>&1 | grep -E 'forbidden|nim|vllm|milvus|trident|portworx|redfish' | head -10 || true
fi
