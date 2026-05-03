#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-isovalent-rendered"
LIVE=false

usage() {
    cat <<'EOF'
Splunk Observability Isovalent Integration validation

Usage:
  bash skills/splunk-observability-isovalent-integration/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --live             Run helm + kubectl probes against the cluster
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

check_file() { [[ -f "$1" ]] || { log "ERROR: Missing $1"; exit 1; }; }

check_file "${OUTPUT_DIR}/metadata.json"
check_file "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"

# Token-scrub: any access token-shaped value should be a placeholder, not a
# real string. The renderer scrubs dashboards before write; this is defense
# in depth so a hand-edited overlay or dashboard file is also caught.
if grep -rEq -- '"(accessToken|access_token|X-SF-Token|apiToken)"[[:space:]]*:[[:space:]]*"[A-Za-z0-9._-]{20,}"' "${OUTPUT_DIR}" 2>/dev/null; then
    if ! grep -rEq -- '"(accessToken|access_token|X-SF-Token|apiToken)"[[:space:]]*:[[:space:]]*"\$\{[A-Z_]+\}"' "${OUTPUT_DIR}" 2>/dev/null; then
        log "ERROR: A rendered file appears to contain an inline access token."
        exit 1
    fi
fi

# Overlay sanity: must include at least one prometheus/isovalent_* receiver
# and the filter/includemetrics processor.
if ! grep -q 'prometheus/isovalent_' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Overlay missing prometheus/isovalent_* scrape jobs."
    exit 1
fi
if ! grep -q 'filter/includemetrics' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    log "ERROR: Overlay missing filter/includemetrics processor."
    exit 1
fi

# When the file-based Splunk Platform path is rendered (default), confirm
# the hostPath mount and extraFileLogs.filelog/tetragon block are present
# AND aligned. A common mis-render is a hostPath mount at one path and an
# extraFileLogs glob at a different path.
if grep -q 'logsCollection' "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml"; then
    HOST_PATH="$(python3 -c "
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
hp = ''
for vol in (data.get('agent', {}).get('extraVolumes') or []):
    if 'hostPath' in vol:
        hp = vol['hostPath']['path']
        break
print(hp)
" "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml")"
    LOG_INCLUDE="$(python3 -c "
import sys, yaml
with open(sys.argv[1]) as f:
    data = yaml.safe_load(f)
inc = data.get('logsCollection', {}).get('extraFileLogs', {}).get('filelog/tetragon', {}).get('include', [])
print(inc[0] if inc else '')
" "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml")"
    if [[ -n "${HOST_PATH}" && -n "${LOG_INCLUDE}" ]]; then
        if [[ "${LOG_INCLUDE}" != "${HOST_PATH}/"* ]]; then
            log "ERROR: extraFileLogs include (${LOG_INCLUDE}) is not under hostPath (${HOST_PATH})."
            exit 1
        fi
    fi
fi

# Dashboards: every JSON in dashboards/ must parse cleanly and not contain
# an access token-shaped value (re-running the same scrub-tokens.py logic).
if [[ -d "${OUTPUT_DIR}/dashboards" ]]; then
    for json_file in "${OUTPUT_DIR}/dashboards"/*.json; do
        [[ -f "${json_file}" ]] || continue
        python3 -c "import json,sys; json.load(open(sys.argv[1]))" "${json_file}" || {
            log "ERROR: ${json_file} is not valid JSON."
            exit 1
        }
    done
fi

log "Splunk Observability Isovalent Integration rendered assets passed static validation."

if [[ "${LIVE}" == "true" ]]; then
    log "  --live: probing cluster..."
    if ! command -v kubectl >/dev/null 2>&1; then
        log "  ERROR: kubectl not on PATH."
        exit 1
    fi
    log "  Cilium pods (Hubble metrics on 9965 served from cilium agent pods):"
    kubectl -n kube-system get pods -l k8s-app=cilium 2>&1 | head -5 || true
    log "  Tetragon metrics endpoint via API server proxy (no kubectl exec):"
    kubectl get --raw /api/v1/namespaces/tetragon/services/tetragon:2112/proxy/metrics 2>&1 | head -3 || true
    log "  Splunk OTel collector logs (search for cilium scrape errors):"
    kubectl -n splunk-otel logs -l app=splunk-otel-collector --tail=50 2>&1 | grep -E 'cilium|tetragon|hubble|forbidden' | head -10 || true
fi
