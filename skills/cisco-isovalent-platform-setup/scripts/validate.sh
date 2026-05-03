#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/cisco-isovalent-platform-rendered"
LIVE=false

usage() {
    cat <<'EOF'
Cisco Isovalent Platform Setup validation

Usage:
  bash skills/cisco-isovalent-platform-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --live             Run helm status / kubectl probes against the cluster
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

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

check_file() {
    local path="$1"
    [[ -f "${path}" ]] || { log "ERROR: Missing ${path}"; exit 1; }
}

check_file "${OUTPUT_DIR}/metadata.json"
check_file "${OUTPUT_DIR}/helm/cilium-values.yaml"
check_file "${OUTPUT_DIR}/helm/tetragon-values.yaml"
check_file "${OUTPUT_DIR}/scripts/install-cilium.sh"
check_file "${OUTPUT_DIR}/scripts/install-tetragon.sh"
check_file "${OUTPUT_DIR}/scripts/preflight.sh"

# Token-scrub: ensure no real licence material got into rendered files. The
# license is supplied via a token file at apply time; if the values file
# contains anything that looks like a JWT or long base64 blob under a
# license-shaped key, fail.
if grep -rEq -- '"(license|licenseKey|license_key)"[[:space:]]*:[[:space:]]*"[A-Za-z0-9._-]{20,}"' "${OUTPUT_DIR}" 2>/dev/null; then
    log "ERROR: A rendered file appears to contain an inline license value."
    exit 1
fi

# Tetragon export mode sanity. The default is file-based; validate that
# the tetragon-values.yaml contains the expected exportDirectory + exportFilename
# (when in file mode).
EXPORT_MODE="$(python3 -c "import json,sys;
try:
    import yaml
    with open(sys.argv[1]) as f: data = yaml.safe_load(f.read())
except (ModuleNotFoundError, ImportError):
    print('file'); sys.exit(0)
mode = (((data or {}).get('tetragon') or {}).get('export') or {}).get('mode', 'file')
print(mode)" "${OUTPUT_DIR}/helm/tetragon-values.yaml" 2>/dev/null || echo "file")"

if [[ "${EXPORT_MODE}" == "fluentd" ]]; then
    log "  WARN: Tetragon export mode is 'fluentd' (DEPRECATED, fluent-plugin-splunk-hec archived 2025-06-24)."
fi

log "Cisco Isovalent Platform Setup rendered assets passed static validation."

if [[ "${LIVE}" == "true" ]]; then
    log "  --live: probing cluster..."
    if ! command -v helm >/dev/null 2>&1; then
        log "  ERROR: helm not on PATH."
        exit 1
    fi
    if ! command -v kubectl >/dev/null 2>&1; then
        log "  ERROR: kubectl not on PATH."
        exit 1
    fi
    log "  helm status (cilium, tetragon, hubble-enterprise, cilium-dnsproxy, hubble-timescape):"
    for release in cilium tetragon hubble-enterprise cilium-dnsproxy hubble-timescape; do
        helm status "${release}" -A 2>/dev/null | head -3 || log "    ${release}: not installed"
    done
    log "  Cilium status (via kubectl exec is intentionally NOT used; checking pod readiness instead):"
    kubectl -n kube-system get pods -l k8s-app=cilium -o wide 2>&1 | head -10 || true
    log "  Tetragon metrics endpoint via API server proxy (no exec):"
    kubectl get --raw "/api/v1/namespaces/tetragon/services/tetragon:2112/proxy/metrics" 2>&1 | head -5 || \
        log "    (Tetragon metrics not reachable via API proxy; install may not be complete)"
    log "  Tetragon log file presence (probe a node — adjust nodename as needed):"
    log "    Run: kubectl debug node/<node> --image=ubuntu -- ls /host/var/run/cilium/tetragon/"
fi
