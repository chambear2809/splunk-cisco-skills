#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-nvidia-gpu-rendered"
LIVE=false

usage() {
    cat <<'EOF'
NVIDIA GPU Integration validation

Usage:
  bash skills/splunk-observability-nvidia-gpu-integration/scripts/validate.sh [options]

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
check_file "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"

# CRITICAL: receiver_creator name must NOT be 'nvidia' (collides with chart autodetect).
if grep -q 'receiver_creator/nvidia:' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Overlay uses receiver_creator/nvidia which collides with the chart's autodetect receiver_creator."
    log "       Re-render with --receiver-creator-name dcgm-cisco (or any name != 'nvidia')."
    exit 1
fi
if ! grep -q 'receiver_creator/dcgm-cisco:' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    if ! grep -Eq 'receiver_creator/[a-z0-9-]+:' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
        log "ERROR: Overlay missing receiver_creator/* receiver."
        exit 1
    fi
fi

# CRITICAL: discovery rule must match BOTH label conventions.
if ! grep -q 'app.kubernetes.io/name' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Discovery rule does not match app.kubernetes.io/name label (newer GPU Operator)."
    exit 1
fi
if ! grep -q 'labels\["app"\] == "nvidia-dcgm-exporter"' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Discovery rule does not match the bare app label (older standalone deployments)."
    exit 1
fi

# Confirm metrics/nvidia-metrics pipeline exists.
if ! grep -q 'metrics/nvidia-metrics' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Overlay missing metrics/nvidia-metrics pipeline."
    exit 1
fi

# DCGM pod-label patch validation (when present).
if [[ -d "${OUTPUT_DIR}/dcgm-pod-labels-patch" ]]; then
    check_file "${OUTPUT_DIR}/dcgm-pod-labels-patch/01-cluster-role.yaml"
    check_file "${OUTPUT_DIR}/dcgm-pod-labels-patch/02-cluster-role-binding.yaml"
    check_file "${OUTPUT_DIR}/dcgm-pod-labels-patch/03-service-account-automount.yaml"
    check_file "${OUTPUT_DIR}/dcgm-pod-labels-patch/04-daemonset-env-patch.yaml"
    grep -q 'DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS' "${OUTPUT_DIR}/dcgm-pod-labels-patch/04-daemonset-env-patch.yaml" || {
        log "ERROR: DCGM pod-label patch missing DCGM_EXPORTER_KUBERNETES_ENABLE_POD_LABELS env var."
        exit 1
    }
fi

log "NVIDIA GPU Integration rendered assets passed static validation."

if [[ "${LIVE}" == "true" ]]; then
    if ! command -v kubectl >/dev/null 2>&1; then log "  ERROR: kubectl not on PATH."; exit 1; fi
    log "  --live: probing cluster for DCGM Exporter pods..."
    log "  app=nvidia-dcgm-exporter (older convention):"
    kubectl get pods -A -l app=nvidia-dcgm-exporter -o wide 2>&1 | head -5 || true
    log "  app.kubernetes.io/name=nvidia-dcgm-exporter (newer GPU Operator):"
    kubectl get pods -A -l app.kubernetes.io/name=nvidia-dcgm-exporter -o wide 2>&1 | head -5 || true
fi
