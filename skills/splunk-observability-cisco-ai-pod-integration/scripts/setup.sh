#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-cisco-ai-pod-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

usage() {
    cat <<'EOF'
Splunk Observability Cisco AI Pod Integration (umbrella) setup

Usage:
  bash skills/splunk-observability-cisco-ai-pod-integration/scripts/setup.sh [mode] [options]

Modes:
  --render                       Render composed overlay + AI-Pod additions + handoffs (default)
  --apply-existing-collector     Apply the rendered overlay to an existing Splunk OTel Helm release
  --validate                     Run static validation (recursively + AI-Pod-specific)
  --live                         With --validate, run oc/kubectl live validation
  --dry-run                      Show plan without writing
  --json                         Emit JSON dry-run output
  --explain                      Print plan in plain English

Options:
  --spec PATH                    YAML or JSON spec (default: template.example)
  --output-dir DIR               Rendered output directory
  --realm REALM                  Override spec.realm
  --cluster-name NAME            Override spec.cluster_name
  --distribution NAME            openshift (default for AI Pod) | kubernetes | eks | gke
  --nim-scrape-mode MODE         receiver_creator (default) | endpoints (requires rbac.customRules)
  --enable-dcgm-pod-labels       Render the GPU child skill's pod-label gap patch
  --workshop-mode                Render the workshop multi-tenant deploy script
  --collector-release NAME       Override Intersight child's collector.release
  --collector-namespace NS       Override Intersight child's collector.namespace
  --collector-chart-ref REF      Helm chart ref for --apply-existing-collector
  --o11y-token-file PATH         Splunk O11y Org access token (passed through)
  --intersight-key-id-file PATH  Intersight key ID (passed through to Intersight child)
  --intersight-key-file PATH     Intersight private key (passed through to Intersight child)
  --platform-hec-token-file PATH Splunk Platform HEC token (when splunk_platform_logs.enabled)
  --allow-loose-token-perms      Skip the chmod-600 token permission preflight (warns)
  --help                         Show this help

Direct token / key flags rejected: --intersight-key-id, --intersight-key,
--api-key, --client-secret, --o11y-token, --access-token, --token,
--bearer-token, --api-token, --sf-token, --platform-hec-token, --hec-token.
EOF
}

bool_text() { if [[ "$1" == "true" ]]; then printf 'true'; else printf 'false'; fi; }

resolve_abs_path() {
    "${PYTHON_BIN}" - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

MODE_RENDER=true
MODE_APPLY_EXISTING_COLLECTOR=false
MODE_VALIDATE=false
VALIDATE_LIVE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
REALM=""
CLUSTER_NAME=""
DISTRIBUTION=""
NIM_SCRAPE_MODE=""
ENABLE_DCGM_POD_LABELS="false"
WORKSHOP_MODE="false"
COLLECTOR_RELEASE=""
COLLECTOR_NAMESPACE=""
COLLECTOR_CHART_REF="splunk-otel-collector-chart/splunk-otel-collector"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
INTERSIGHT_KEY_ID_FILE=""
INTERSIGHT_KEY_FILE=""
PLATFORM_HEC_TOKEN_FILE=""
ALLOW_LOOSE_TOKEN_PERMS=false

if [[ $# -eq 0 ]]; then usage; exit 0; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --apply-existing-collector) MODE_APPLY_EXISTING_COLLECTOR=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --live) VALIDATE_LIVE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; CLUSTER_NAME="$2"; shift 2 ;;
        --distribution) require_arg "$1" "$#" || exit 1; DISTRIBUTION="$2"; shift 2 ;;
        --nim-scrape-mode) require_arg "$1" "$#" || exit 1; NIM_SCRAPE_MODE="$2"; shift 2 ;;
        --enable-dcgm-pod-labels) ENABLE_DCGM_POD_LABELS="true"; shift ;;
        --workshop-mode) WORKSHOP_MODE="true"; shift ;;
        --collector-release) require_arg "$1" "$#" || exit 1; COLLECTOR_RELEASE="$2"; shift 2 ;;
        --collector-namespace) require_arg "$1" "$#" || exit 1; COLLECTOR_NAMESPACE="$2"; shift 2 ;;
        --collector-chart-ref) require_arg "$1" "$#" || exit 1; COLLECTOR_CHART_REF="$2"; shift 2 ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --intersight-key-id-file) require_arg "$1" "$#" || exit 1; INTERSIGHT_KEY_ID_FILE="$2"; shift 2 ;;
        --intersight-key-file) require_arg "$1" "$#" || exit 1; INTERSIGHT_KEY_FILE="$2"; shift 2 ;;
        --platform-hec-token-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --intersight-key-id|--intersight-key|--api-key|--client-secret)
            reject_secret_arg "$1" "--intersight-key-id-file or --intersight-key-file"
            exit 1
            ;;
        --o11y-token|--access-token|--token|--bearer-token|--api-token|--sf-token)
            reject_secret_arg "$1" "--o11y-token-file"
            exit 1
            ;;
        --platform-hec-token|--hec-token)
            reject_secret_arg "$1" "--platform-hec-token-file"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

_token_perm_octal() {
    local target="$1" mode=""
    mode="$(stat -f '%A' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    mode="$(stat -c '%a' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    printf ''
}

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" && -r "${path}" ]] || return 0
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then return 0; fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS:-false}" == "true" ]]; then
            log "  WARN: ${label} permissions are ${mode}; --allow-loose-token-perms is set, proceeding."
            return 0
        fi
        log "ERROR: ${label} (${path}) is mode ${mode}; secrets must be mode 600."
        return 1
    fi
}

[[ -n "${O11Y_TOKEN_FILE}" ]] && { _check_token_perms "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1; }
[[ -n "${INTERSIGHT_KEY_ID_FILE}" ]] && { _check_token_perms "--intersight-key-id-file" "${INTERSIGHT_KEY_ID_FILE}" || exit 1; }
[[ -n "${INTERSIGHT_KEY_FILE}" ]] && { _check_token_perms "--intersight-key-file" "${INTERSIGHT_KEY_FILE}" || exit 1; }
[[ -n "${PLATFORM_HEC_TOKEN_FILE}" ]] && { _check_token_perms "--platform-hec-token-file" "${PLATFORM_HEC_TOKEN_FILE}" || exit 1; }

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability Cisco AI Pod Integration (umbrella) -- execution plan
==========================================================================
  Spec:                   ${SPEC}
  Output directory:       ${OUTPUT_DIR}
  Realm:                  ${REALM:-<from spec>}
  Cluster:                ${CLUSTER_NAME:-<from spec>}
  Distribution:           ${DISTRIBUTION:-<from spec, default openshift>}
  NIM scrape mode:        ${NIM_SCRAPE_MODE:-<from spec, default receiver_creator>}
  DCGM pod labels:        ${ENABLE_DCGM_POD_LABELS}
  Workshop mode:          ${WORKSHOP_MODE}
  Composes child skills:  Nexus + Intersight + GPU
  Adds:                   NIM, vLLM, Milvus, Trident, Portworx, Redfish,
                          dual-pipeline filtering, k8s_attributes/nim,
                          OpenShift defaults (when distribution=openshift),
                          rbac.customRules (when nim_scrape_mode=endpoints),
                          --workshop-mode multi-tenant.sh, OpenShift SCC helper.
  Mode: render=$(bool_text "${MODE_RENDER}") apply_existing_collector=$(bool_text "${MODE_APPLY_EXISTING_COLLECTOR}") validate=$(bool_text "${MODE_VALIDATE}") live=$(bool_text "${VALIDATE_LIVE}")
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --realm "${REALM}"
    --cluster-name "${CLUSTER_NAME}"
    --distribution "${DISTRIBUTION}"
    --nim-scrape-mode "${NIM_SCRAPE_MODE}"
    --enable-dcgm-pod-labels "${ENABLE_DCGM_POD_LABELS}"
    --workshop-mode "${WORKSHOP_MODE}"
    --collector-release "${COLLECTOR_RELEASE}"
    --collector-namespace "${COLLECTOR_NAMESPACE}"
)
if [[ "${DRY_RUN}" == "true" ]]; then RENDER_ARGS+=(--dry-run); fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then RENDER_ARGS+=(--json); fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then exit 0; fi

if [[ "${MODE_APPLY_EXISTING_COLLECTOR}" == "true" ]]; then
    if [[ -z "${O11Y_TOKEN_FILE}" ]]; then
        log "ERROR: --apply-existing-collector requires --o11y-token-file (or SPLUNK_O11Y_TOKEN_FILE)."
        exit 1
    fi
    if [[ ! -r "${O11Y_TOKEN_FILE}" ]]; then
        log "ERROR: --o11y-token-file is not readable: ${O11Y_TOKEN_FILE}"
        exit 1
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/apply_existing_collector.py" \
        --output-dir "${OUTPUT_DIR}" \
        --release "${COLLECTOR_RELEASE:-splunk-otel-collector}" \
        --namespace "${COLLECTOR_NAMESPACE:-splunk-otel}" \
        --chart-ref "${COLLECTOR_CHART_REF}" \
        --o11y-token-file "${O11Y_TOKEN_FILE}"
    MODE_VALIDATE=true
    VALIDATE_LIVE=true
fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    VALIDATE_ARGS=(--output-dir "${OUTPUT_DIR}")
    if [[ "${VALIDATE_LIVE}" == "true" ]]; then
        VALIDATE_ARGS+=(--live)
    fi
    bash "${SCRIPT_DIR}/validate.sh" "${VALIDATE_ARGS[@]}"
fi
