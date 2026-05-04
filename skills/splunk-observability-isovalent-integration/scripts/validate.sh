#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-isovalent-rendered"
LIVE=false
KUBE_CONTEXT=""
CILIUM_NAMESPACE="kube-system"
TETRAGON_NAMESPACE="tetragon"
COLLECTOR_RELEASE="splunk-otel-collector"
COLLECTOR_NAMESPACE=""

usage() {
    cat <<'EOF'
Splunk Observability Isovalent Integration validation

Usage:
  bash skills/splunk-observability-isovalent-integration/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --kube-context CTX Kubernetes context for live checks
  --cilium-namespace NS
                     Namespace for Cilium services (default: kube-system)
  --tetragon-namespace NS
                     Namespace for Tetragon services (default: tetragon)
  --collector-release NAME
                     Helm release for Splunk OTel Collector (default: splunk-otel-collector)
  --collector-namespace NS
                     Namespace for Splunk OTel Collector; auto-detected when omitted
  --live             Run helm + kubectl probes against the cluster
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --cilium-namespace) require_arg "$1" "$#" || exit 1; CILIUM_NAMESPACE="$2"; shift 2 ;;
        --tetragon-namespace) require_arg "$1" "$#" || exit 1; TETRAGON_NAMESPACE="$2"; shift 2 ;;
        --collector-release) require_arg "$1" "$#" || exit 1; COLLECTOR_RELEASE="$2"; shift 2 ;;
        --collector-namespace) require_arg "$1" "$#" || exit 1; COLLECTOR_NAMESPACE="$2"; shift 2 ;;
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
    HOST_PATH="$(PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib${PYTHONPATH:+:${PYTHONPATH}}" python3 -c "
import sys
from pathlib import Path
from yaml_compat import load_yaml_or_json
data = load_yaml_or_json(Path(sys.argv[1]).read_text(encoding='utf-8'), source=sys.argv[1])
hp = ''
for vol in (data.get('agent', {}).get('extraVolumes') or []):
    if 'hostPath' in vol:
        hp = vol['hostPath']['path']
        break
print(hp)
" "${OUTPUT_DIR}/splunk-otel-overlay/values.overlay.yaml")"
    LOG_INCLUDE="$(PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib${PYTHONPATH:+:${PYTHONPATH}}" python3 -c "
import sys
from pathlib import Path
from yaml_compat import load_yaml_or_json
data = load_yaml_or_json(Path(sys.argv[1]).read_text(encoding='utf-8'), source=sys.argv[1])
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
    if ! command -v helm >/dev/null 2>&1; then
        log "  ERROR: helm not on PATH."
        exit 1
    fi
    KUBECTL=(kubectl)
    HELM=(helm)
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        KUBECTL=(kubectl --context "${KUBE_CONTEXT}")
        HELM=(helm --kube-context "${KUBE_CONTEXT}")
    fi
    discover_release_namespace() {
        local release="$1"
        "${HELM[@]}" list --all-namespaces --filter "^${release}$" 2>/dev/null | awk -v release="${release}" 'NR > 1 && $1 == release {print $2; exit}'
    }
    if [[ -z "${COLLECTOR_NAMESPACE}" ]]; then
        COLLECTOR_NAMESPACE="$(discover_release_namespace "${COLLECTOR_RELEASE}")"
        if [[ -z "${COLLECTOR_NAMESPACE}" ]]; then
            COLLECTOR_NAMESPACE="splunk-otel"
        fi
    fi
    probe_metrics() {
        local label="$1" path="$2" required="${3:-true}" output status
        output="$("${KUBECTL[@]}" get --raw "${path}" 2>&1)" && status=0 || status=$?
        if [[ "${status}" -ne 0 ]]; then
            if [[ "${required}" == "false" && "${output}" == *"NotFound"* ]]; then
                log "    ${label}: optional service not installed"
                return 0
            fi
            log "    WARN: ${label} metrics not reachable: $(printf '%s\n' "${output}" | head -1)"
            return 0
        fi
        log "    ${label}: reachable"
        printf '%s\n' "${output}" | sed -n '1,3p'
    }
    log "  Helm status (${COLLECTOR_RELEASE} in ${COLLECTOR_NAMESPACE}):"
    "${HELM[@]}" status "${COLLECTOR_RELEASE}" -n "${COLLECTOR_NAMESPACE}" 2>/dev/null | sed -n '1,3p' || \
        log "    WARN: ${COLLECTOR_RELEASE} status unavailable in ${COLLECTOR_NAMESPACE}"
    log "  Cilium pods (Hubble metrics on 9965 served from cilium agent pods):"
    "${KUBECTL[@]}" -n "${CILIUM_NAMESPACE}" get pods -l k8s-app=cilium 2>&1 | sed -n '1,5p' || true
    log "  Metrics endpoints via API server proxy (no kubectl exec):"
    probe_metrics "cilium-agent:9962" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-agent:9962/proxy/metrics"
    probe_metrics "hubble-metrics:9965" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/hubble-metrics:9965/proxy/metrics"
    probe_metrics "cilium-envoy:9964" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-envoy:9964/proxy/metrics"
    probe_metrics "cilium-operator:9963" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-operator:9963/proxy/metrics"
    probe_metrics "tetragon:2112" "/api/v1/namespaces/${TETRAGON_NAMESPACE}/services/tetragon:2112/proxy/metrics"
    probe_metrics "tetragon-operator-metrics:2113" "/api/v1/namespaces/${TETRAGON_NAMESPACE}/services/tetragon-operator-metrics:2113/proxy/metrics"
    probe_metrics "cilium-dnsproxy:9967" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-dnsproxy:9967/proxy/metrics" false
    log "  Splunk OTel collector logs (search for Isovalent scrape errors):"
    "${KUBECTL[@]}" -n "${COLLECTOR_NAMESPACE}" logs -l app=splunk-otel-collector --tail=50 2>&1 | grep -E 'cilium|tetragon|hubble|dnsproxy|forbidden' | sed -n '1,10p' || true
fi
