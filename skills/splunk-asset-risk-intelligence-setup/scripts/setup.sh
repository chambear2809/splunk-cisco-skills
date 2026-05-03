#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

APP_ID="7180"
INSTALL_APP_SCRIPT="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
ARI_INDEXES=("ari_staging" "ari_asset" "ari_internal" "ari_ta")

SOURCE="splunkbase"
APP_VERSION=""
LOCAL_FILE=""
NO_RESTART=false
INSTALL=false
VALIDATE=false
MODE_SET=false
DRY_RUN=false
JSON_OUTPUT=false
CREATE_INDEXES=true
EXPOSURE_HANDOFF=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Asset and Risk Intelligence Setup

Usage: $(basename "$0") [OPTIONS]

Modes:
  --install                     Install/configure only
  --validate                    Validate only
  --dry-run                     Show the plan without changing Splunk
  --json                        Emit JSON with --dry-run

Options:
  --source splunkbase|local
  --app-version VER             Pin a Splunkbase app version
  --file PATH                   Local ARI package path or Splunkbase fallback package path
  --skip-indexes                Do not create ARI indexes during setup
  --exposure-analytics-handoff  Include ES Exposure Analytics handoff in output
  --no-restart                  Skip installer restart handling
  --help                        Show this help

Default with no mode is install/configure followed by validate.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; MODE_SET=true; shift ;;
        --validate) VALIDATE=true; MODE_SET=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --skip-indexes) CREATE_INDEXES=false; shift ;;
        --exposure-analytics-handoff) EXPOSURE_HANDOFF=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${MODE_SET}" != "true" ]]; then
    INSTALL=true
    VALIDATE=true
fi

case "${SOURCE}" in
    splunkbase|local) ;;
    *) echo "ERROR: --source must be splunkbase or local." >&2; exit 1 ;;
esac

INSTALL_CMD=()
FALLBACK_CMD=()
VALIDATE_CMD=(bash "${VALIDATE_SCRIPT}")

build_install_command() {
    INSTALL_CMD=(bash "${INSTALL_APP_SCRIPT}" --source "${SOURCE}")
    if [[ "${SOURCE}" == "splunkbase" ]]; then
        INSTALL_CMD+=(--app-id "${APP_ID}" --no-update)
        [[ -n "${APP_VERSION}" ]] && INSTALL_CMD+=(--app-version "${APP_VERSION}")
    else
        [[ -n "${LOCAL_FILE}" ]] || { echo "ERROR: --file is required with --source local." >&2; exit 1; }
        INSTALL_CMD+=(--file "${LOCAL_FILE}" --no-update)
    fi
    [[ "${NO_RESTART}" == "true" ]] && INSTALL_CMD+=(--no-restart)
    return 0
}

build_fallback_command() {
    FALLBACK_CMD=()
    if [[ "${SOURCE}" == "splunkbase" && -n "${LOCAL_FILE}" ]]; then
        FALLBACK_CMD=(bash "${INSTALL_APP_SCRIPT}" --source local --file "${LOCAL_FILE}" --no-update)
        [[ "${NO_RESTART}" == "true" ]] && FALLBACK_CMD+=(--no-restart)
    fi
    return 0
}

join_unit() {
    local IFS=$'\037'
    printf '%s' "$*"
}

emit_plan() {
    local phases=()
    [[ "${INSTALL}" == "true" ]] && phases+=("install")
    [[ "${CREATE_INDEXES}" == "true" && "${INSTALL}" == "true" ]] && phases+=("create-indexes")
    [[ "${EXPOSURE_HANDOFF}" == "true" ]] && phases+=("exposure-analytics-handoff")
    [[ "${VALIDATE}" == "true" ]] && phases+=("validate")
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        JSON_PHASES="$(join_unit "${phases[@]}")" \
        JSON_INSTALL_COMMAND="$(join_unit "${INSTALL_CMD[@]}")" \
        JSON_FALLBACK_COMMAND="$(join_unit "${FALLBACK_CMD[@]}")" \
        JSON_VALIDATE_COMMAND="$(join_unit "${VALIDATE_CMD[@]}")" \
        JSON_ARI_INDEXES="$(join_unit "${ARI_INDEXES[@]}")" \
        EXPOSURE_HANDOFF="${EXPOSURE_HANDOFF}" \
        python3 - <<'PY'
import json
import os
import sys

sep = "\x1f"
payload = {
    "ok": True,
    "dry_run": True,
    "product": "Splunk Asset and Risk Intelligence",
    "app_id": "7180",
    "app_name": "SplunkAssetRiskIntelligence",
    "restricted_download": True,
    "phases": os.environ.get("JSON_PHASES", "").split(sep) if os.environ.get("JSON_PHASES") else [],
    "install_command": os.environ.get("JSON_INSTALL_COMMAND", "").split(sep) if os.environ.get("JSON_INSTALL_COMMAND") else [],
    "fallback_install_command": os.environ.get("JSON_FALLBACK_COMMAND", "").split(sep) if os.environ.get("JSON_FALLBACK_COMMAND") else [],
    "validate_command": os.environ.get("JSON_VALIDATE_COMMAND", "").split(sep) if os.environ.get("JSON_VALIDATE_COMMAND") else [],
    "indexes": os.environ.get("JSON_ARI_INDEXES", "").split(sep) if os.environ.get("JSON_ARI_INDEXES") else [],
    "exposure_analytics_handoff": os.environ.get("EXPOSURE_HANDOFF") == "true",
    "handoff": "Initialize ARI data and configure ES Exposure Analytics sources in the product UI/ES config workflow.",
}
json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
    else
        echo "Planned phases:"
        printf '  - %s\n' "${phases[@]}"
        printf 'Install command:\n  %q ' "${INSTALL_CMD[@]}"; echo
        printf 'Validate command:\n  %q ' "${VALIDATE_CMD[@]}"; echo
        echo "ARI indexes: ${ARI_INDEXES[*]}"
        echo "Restricted download note: provide --file if Splunkbase access is unavailable."
    fi
}

ensure_session() {
    if [[ -n "${SK:-}" ]]; then
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK="$(get_session_key "${SPLUNK_URI}")" || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

create_indexes_if_needed() {
    local idx
    [[ "${CREATE_INDEXES}" == "true" ]] || return 0
    ensure_session
    for idx in "${ARI_INDEXES[@]}"; do
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            log "Index '${idx}' already exists."
        else
            log "Creating ARI index '${idx}'."
            platform_create_index "${SK}" "${SPLUNK_URI}" "${idx}" "512000" "event"
        fi
    done
}

build_install_command
build_fallback_command

if [[ "${DRY_RUN}" == "true" ]]; then
    emit_plan
    exit 0
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    echo "ERROR: --json is only supported with --dry-run." >&2
    exit 1
fi

warn_if_current_skill_role_unsupported

if [[ "${INSTALL}" == "true" ]]; then
    if ! "${INSTALL_CMD[@]}"; then
        if [[ -n "${FALLBACK_CMD[0]+set}" ]]; then
            echo "WARN: Splunkbase install failed; trying local fallback package." >&2
            "${FALLBACK_CMD[@]}"
        else
            exit 1
        fi
    fi
    create_indexes_if_needed
fi

if [[ "${EXPOSURE_HANDOFF}" == "true" ]]; then
    log "Exposure Analytics handoff: use splunk-enterprise-security-config to configure ARI Asset, IP, Mac, and User entity discovery sources."
fi

if [[ "${VALIDATE}" == "true" ]]; then
    "${VALIDATE_CMD[@]}"
fi
