#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-nvidia-gpu-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability NVIDIA GPU Integration setup

Usage:
  bash skills/splunk-observability-nvidia-gpu-integration/scripts/setup.sh [mode] [options]

Modes:
  --render                       Render overlay + (optional) DCGM patch + handoffs (default)
  --validate                     Run static validation
  --dry-run                      Show plan without writing
  --json                         Emit JSON dry-run output
  --explain                      Print plan in plain English

Options:
  --spec PATH                    YAML or JSON spec (default: template.example)
  --output-dir DIR               Rendered output directory
  --realm REALM                  Override spec.realm
  --cluster-name NAME            Override spec.cluster_name
  --distribution NAME            openshift | kubernetes | eks | gke
  --receiver-creator-name NAME   Override spec.receiver_creator_name (default: dcgm-cisco;
                                 NEVER use 'nvidia' -- collides with chart autodetect)
  --filter strict|none           Override spec.filter.mode (default: none = unfiltered)
  --enable-dcgm-pod-labels       Render the DCGM pod-label gap patch
  --o11y-token-file PATH         Splunk O11y Org access token (passed through to base collector)
  --allow-loose-token-perms      Skip the chmod-600 token permission preflight (warns)
  --help                         Show this help

Direct token flags rejected: --o11y-token, --access-token, --token, --bearer-token,
--api-token, --sf-token.
EOF
}

bool_text() { if [[ "$1" == "true" ]]; then printf 'true'; else printf 'false'; fi; }

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

MODE_RENDER=true
MODE_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
REALM=""
CLUSTER_NAME=""
DISTRIBUTION=""
RECEIVER_CREATOR_NAME=""
FILTER_MODE=""
ENABLE_DCGM_POD_LABELS="false"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
ALLOW_LOOSE_TOKEN_PERMS=false

if [[ $# -eq 0 ]]; then usage; exit 0; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; CLUSTER_NAME="$2"; shift 2 ;;
        --distribution) require_arg "$1" "$#" || exit 1; DISTRIBUTION="$2"; shift 2 ;;
        --receiver-creator-name) require_arg "$1" "$#" || exit 1; RECEIVER_CREATOR_NAME="$2"; shift 2 ;;
        --filter) require_arg "$1" "$#" || exit 1; FILTER_MODE="$2"; shift 2 ;;
        --enable-dcgm-pod-labels) ENABLE_DCGM_POD_LABELS="true"; shift ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --o11y-token|--access-token|--token|--bearer-token|--api-token|--sf-token)
            reject_secret_arg "$1" "--o11y-token-file"
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
        log "ERROR: ${label} (${path}) is mode ${mode}; tokens must be mode 600."
        return 1
    fi
}

[[ -n "${O11Y_TOKEN_FILE}" ]] && { _check_token_perms "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1; }

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability NVIDIA GPU Integration -- execution plan
=============================================================
  Spec:                       ${SPEC}
  Output directory:           ${OUTPUT_DIR}
  Realm:                      ${REALM:-<from spec>}
  Cluster:                    ${CLUSTER_NAME:-<from spec>}
  Distribution:               ${DISTRIBUTION:-<from spec>}
  Receiver creator name:      ${RECEIVER_CREATOR_NAME:-<from spec, default dcgm-cisco>}
  Filter mode:                ${FILTER_MODE:-<from spec, default none>}
  Enable DCGM pod labels:     ${ENABLE_DCGM_POD_LABELS}
  Mode: render=$(bool_text "${MODE_RENDER}") validate=$(bool_text "${MODE_VALIDATE}")
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --realm "${REALM}"
    --cluster-name "${CLUSTER_NAME}"
    --distribution "${DISTRIBUTION}"
    --receiver-creator-name "${RECEIVER_CREATOR_NAME}"
    --filter-mode "${FILTER_MODE}"
    --enable-dcgm-pod-labels "${ENABLE_DCGM_POD_LABELS}"
)
if [[ "${DRY_RUN}" == "true" ]]; then RENDER_ARGS+=(--dry-run); fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then RENDER_ARGS+=(--json); fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then exit 0; fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
fi
