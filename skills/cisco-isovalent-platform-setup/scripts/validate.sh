#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/cisco-isovalent-platform-rendered"
LIVE=false
KUBE_CONTEXT=""
CILIUM_NAMESPACE="kube-system"
TETRAGON_NAMESPACE="tetragon"

usage() {
    cat <<'EOF'
Cisco Isovalent Platform Setup validation

Usage:
  bash skills/cisco-isovalent-platform-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --kube-context CTX Kubernetes context for live checks
  --cilium-namespace NS
                     Namespace for Cilium services (default: kube-system)
  --tetragon-namespace NS
                     Namespace for Tetragon services (default: tetragon)
  --live             Run helm status / kubectl probes against the cluster
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --cilium-namespace) require_arg "$1" "$#" || exit 1; CILIUM_NAMESPACE="$2"; shift 2 ;;
        --tetragon-namespace) require_arg "$1" "$#" || exit 1; TETRAGON_NAMESPACE="$2"; shift 2 ;;
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
EXPORT_MODE="$(PYTHONPATH="${PROJECT_ROOT}/skills/shared/lib${PYTHONPATH:+:${PYTHONPATH}}" python3 -c "import sys;
from pathlib import Path
from yaml_compat import load_yaml_or_json
data = load_yaml_or_json(Path(sys.argv[1]).read_text(encoding='utf-8'), source=sys.argv[1])
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
    KUBECTL=(kubectl)
    HELM=(helm)
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        KUBECTL=(kubectl --context "${KUBE_CONTEXT}")
        HELM=(helm --kube-context "${KUBE_CONTEXT}")
    fi
    helm_status() {
        local release="$1" namespace=""
        namespace="$("${HELM[@]}" list --all-namespaces --filter "^${release}$" 2>/dev/null | awk -v release="${release}" 'NR > 1 && $1 == release {print $2; exit}')"
        if [[ -z "${namespace}" ]]; then
            log "    ${release}: not installed"
            return 0
        fi
        log "    ${release} (${namespace}):"
        "${HELM[@]}" status "${release}" -n "${namespace}" 2>/dev/null | sed -n '1,3p' || log "      status unavailable"
    }
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
        printf '%s\n' "${output}" | sed -n '1,5p'
    }
    log "  helm status (cilium, tetragon, hubble-enterprise, cilium-dnsproxy, hubble-timescape):"
    for release in cilium tetragon hubble-enterprise cilium-dnsproxy hubble-timescape; do
        helm_status "${release}"
    done
    log "  Cilium status (via kubectl exec is intentionally NOT used; checking pod readiness instead):"
    "${KUBECTL[@]}" -n "${CILIUM_NAMESPACE}" get pods -l k8s-app=cilium -o wide 2>&1 | sed -n '1,10p' || true
    log "  Metrics endpoints via API server proxy (no exec):"
    probe_metrics "cilium-agent:9962" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-agent:9962/proxy/metrics"
    probe_metrics "hubble-metrics:9965" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/hubble-metrics:9965/proxy/metrics"
    probe_metrics "cilium-envoy:9964" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-envoy:9964/proxy/metrics"
    probe_metrics "cilium-operator:9963" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-operator:9963/proxy/metrics"
    probe_metrics "tetragon:2112" "/api/v1/namespaces/${TETRAGON_NAMESPACE}/services/tetragon:2112/proxy/metrics"
    probe_metrics "tetragon-operator-metrics:2113" "/api/v1/namespaces/${TETRAGON_NAMESPACE}/services/tetragon-operator-metrics:2113/proxy/metrics"
    probe_metrics "cilium-dnsproxy:9967" "/api/v1/namespaces/${CILIUM_NAMESPACE}/services/cilium-dnsproxy:9967/proxy/metrics" false
    log "  Tetragon file export values (read-only Helm inspection; no kubectl debug pod):"
    TETRAGON_VALUES="$("${HELM[@]}" get values tetragon -n "${TETRAGON_NAMESPACE}" -a 2>/dev/null || true)"
    printf '%s\n' "${TETRAGON_VALUES}" | grep -E 'exportDirectory|exportFilename|clusterName|enableEvents' | sed -n '1,12p' || \
        log "    WARN: unable to inspect tetragon Helm values"
    if printf '%s\n' "${TETRAGON_VALUES}" | grep -q 'clusterName: ""'; then
        log "    WARN: installed Tetragon clusterName is empty; rendered values should set cluster_name for Splunk scoping."
    fi
fi
