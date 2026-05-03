#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-cisco-nexus-rendered"
LIVE=false

usage() {
    cat <<'EOF'
Cisco Nexus Integration validation

Usage:
  bash skills/splunk-observability-cisco-nexus-integration/scripts/validate.sh [options]

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
check_file "${OUTPUT_DIR}/secrets/cisco-nexus-ssh-secret.yaml"

# Token-scrub: no SSH passwords / private keys in any rendered file.
# The Secret manifest stub is allowed to contain PLACEHOLDER_* literals.
if grep -rEq -- '"(password|privateKey|key)"[[:space:]]*:[[:space:]]*"[A-Za-z0-9+/=._-]{20,}"' "${OUTPUT_DIR}" 2>/dev/null; then
    log "ERROR: A rendered file appears to contain inline SSH credential material."
    exit 1
fi

# Overlay sanity: must include cisco_os receiver and metrics/cisco-os-metrics pipeline.
if ! grep -q 'cisco_os:' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Overlay missing cisco_os receiver."
    exit 1
fi
if ! grep -q 'metrics/cisco-os-metrics' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Overlay missing metrics/cisco-os-metrics pipeline."
    exit 1
fi

# Confirm secret refs use ${env:CISCO_NEXUS_SSH_*} placeholders, not literals.
if grep -Eq '"(username|password)":[[:space:]]*"[^$]' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml" 2>/dev/null; then
    if ! grep -q '\${env:CISCO_NEXUS_SSH_' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
        log "ERROR: cisco_os auth must use \${env:CISCO_NEXUS_SSH_*} placeholders."
        exit 1
    fi
fi

log "Cisco Nexus Integration rendered assets passed static validation."

if [[ "${LIVE}" == "true" ]]; then
    log "  --live: probing cluster..."
    if ! command -v kubectl >/dev/null 2>&1; then
        log "  ERROR: kubectl not on PATH."
        exit 1
    fi
    log "  Splunk OTel cluster receiver pods:"
    kubectl get pods -A -l app=splunk-otel-collector,component=k8s-cluster-receiver 2>&1 | head -5 || true
    log "  cisco_os scrape errors (look for ssh failures):"
    kubectl logs -A -l app=splunk-otel-collector,component=k8s-cluster-receiver --tail=200 2>&1 | grep -E 'cisco_os|ssh' | head -10 || true
fi
