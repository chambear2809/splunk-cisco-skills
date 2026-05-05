#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-cisco-nexus-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

usage() {
    cat <<'EOF'
Splunk Observability Cisco Nexus Integration setup

Usage:
  bash skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh [mode] [options]

Modes:
  --render            Render overlay + handoff scripts (default)
  --validate          Run static validation against an already-rendered output
  --dry-run           Show the plan without writing
  --json              Emit JSON dry-run output
  --explain           Print plan in plain English

Options:
  --spec PATH         YAML or JSON spec (default: template.example)
  --output-dir DIR    Rendered output directory
  --realm REALM       Override spec.realm
  --cluster-name NAME Override spec.cluster_name
  --distribution NAME openshift | kubernetes | eks | gke
  --nexus-device STR  name:host[:port]; may be repeated to override spec.devices
  --o11y-token-file PATH
                      Splunk Observability Org access token file (passed through to base collector)
  --allow-loose-token-perms  Skip the chmod-600 token permission preflight (warns)
  --help              Show this help

Direct token flags rejected: --o11y-token, --access-token, --token, --bearer-token,
--api-token, --sf-token.
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
MODE_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
REALM=""
CLUSTER_NAME=""
DISTRIBUTION=""
DEVICE_OVERRIDES=()
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
        --nexus-device) require_arg "$1" "$#" || exit 1; DEVICE_OVERRIDES+=("$2"); shift 2 ;;
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
Splunk Observability Cisco Nexus Integration -- execution plan
==============================================================
  Spec:                ${SPEC}
  Output directory:    ${OUTPUT_DIR}
  Realm:               ${REALM:-<from spec>}
  Cluster:             ${CLUSTER_NAME:-<from spec>}
  Distribution:        ${DISTRIBUTION:-<from spec>}
  Device overrides:    ${DEVICE_OVERRIDES[*]:-<from spec>}
  O11y token file:     ${O11Y_TOKEN_FILE:-<not set>}
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
)
for d in "${DEVICE_OVERRIDES[@]}"; do
    RENDER_ARGS+=(--nexus-device "${d}")
done
if [[ "${DRY_RUN}" == "true" ]]; then RENDER_ARGS+=(--dry-run); fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then RENDER_ARGS+=(--json); fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then exit 0; fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
fi
