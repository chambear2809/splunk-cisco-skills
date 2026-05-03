#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-isovalent-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability Isovalent Integration setup

Usage:
  bash skills/splunk-observability-isovalent-integration/scripts/setup.sh [mode] [options]

Modes:
  --render               Render overlay + handoff scripts (default)
  --validate             Run static validation against an already-rendered output
  --dry-run              Show the plan without writing
  --json                 Emit JSON dry-run output
  --explain              Print plan in plain English

Options:
  --spec PATH            YAML or JSON spec (default: template.example)
  --output-dir DIR       Rendered output directory
  --realm REALM          Override spec.realm
  --cluster-name NAME    Override spec.cluster_name
  --distribution NAME    openshift | kubernetes | eks | gke
  --export-mode MODE     file (default) | stdout | fluentd
  --legacy-fluentd-hec   Render the DEPRECATED fluentd splunk_hec block
  --platform-hec-url URL Splunk Platform HEC URL (auto when --render-platform-hec-helper)
  --platform-hec-token-file PATH  HEC token file (chmod 600 enforced)
  --render-platform-hec-helper    Hand off HEC token provisioning to splunk-hec-service-setup
  --o11y-token-file PATH O11y Org access token file (passed through to base collector)
  --dashboards-source DIR  Directory of upstream dashboard JSONs to copy + scrub
  --allow-loose-token-perms  Skip the chmod-600 token permission preflight (warns)
  --help                 Show this help

Direct token flags such as --access-token, --token, --bearer-token, --api-token,
--o11y-token, --sf-token, --platform-hec-token, --hec-token are rejected.
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
EXPORT_MODE=""
LEGACY_FLUENTD="false"
PLATFORM_HEC_URL=""
PLATFORM_HEC_TOKEN_FILE=""
RENDER_PLATFORM_HEC_HELPER="false"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
DASHBOARDS_SOURCE=""
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
        --export-mode) require_arg "$1" "$#" || exit 1; EXPORT_MODE="$2"; shift 2 ;;
        --legacy-fluentd-hec) LEGACY_FLUENTD="true"; shift ;;
        --platform-hec-url) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_URL="$2"; shift 2 ;;
        --platform-hec-token-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --render-platform-hec-helper) RENDER_PLATFORM_HEC_HELPER="true"; shift ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --dashboards-source) require_arg "$1" "$#" || exit 1; DASHBOARDS_SOURCE="$2"; shift 2 ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --access-token|--token|--bearer-token|--api-token|--o11y-token|--sf-token)
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
    if [[ -z "${mode}" ]]; then
        log "  WARN: Could not stat ${label} (${path}); skipping."
        return 0
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS:-false}" == "true" ]]; then
            log "  WARN: ${label} permissions are ${mode}; --allow-loose-token-perms is set, proceeding."
            return 0
        fi
        log "ERROR: ${label} (${path}) is mode ${mode}; tokens must be mode 600."
        log "       Run 'chmod 600 ${path}' to fix."
        return 1
    fi
}

[[ -n "${O11Y_TOKEN_FILE}" ]] && { _check_token_perms "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1; }
[[ -n "${PLATFORM_HEC_TOKEN_FILE}" ]] && { _check_token_perms "--platform-hec-token-file" "${PLATFORM_HEC_TOKEN_FILE}" || exit 1; }

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability Isovalent Integration -- execution plan
============================================================
  Spec:                     ${SPEC}
  Output directory:         ${OUTPUT_DIR}
  Realm:                    ${REALM:-<from spec>}
  Cluster:                  ${CLUSTER_NAME:-<from spec>}
  Distribution:             ${DISTRIBUTION:-<from spec>}
  Export mode:              ${EXPORT_MODE:-<from spec, default file>}
  Legacy fluentd HEC:       ${LEGACY_FLUENTD}
  Platform HEC URL:         ${PLATFORM_HEC_URL:-<not set>}
  Platform HEC token file:  ${PLATFORM_HEC_TOKEN_FILE:-<not set>}
  O11y token file:          ${O11Y_TOKEN_FILE:-<not set>}
  Dashboards source:        ${DASHBOARDS_SOURCE:-<placeholder README>}
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
    --export-mode "${EXPORT_MODE}"
    --legacy-fluentd-hec "${LEGACY_FLUENTD}"
    --platform-hec-url "${PLATFORM_HEC_URL}"
    --platform-hec-token-file "${PLATFORM_HEC_TOKEN_FILE}"
    --render-platform-hec-helper "${RENDER_PLATFORM_HEC_HELPER}"
    --o11y-token-file "${O11Y_TOKEN_FILE}"
    --dashboards-source "${DASHBOARDS_SOURCE}"
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
