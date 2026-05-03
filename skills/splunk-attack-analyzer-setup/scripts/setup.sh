#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

ADDON_APP_ID="6999"
VIS_APP_NAME="Splunk_App_SAA"
VIS_APP_ID="7000"
INSTALL_APP_SCRIPT="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"

SOURCE="splunkbase"
APP_VERSION=""
ADDON_FILE=""
APP_FILE=""
NO_RESTART=false
INSTALL=false
VALIDATE=false
MODE_SET=false
DRY_RUN=false
JSON_OUTPUT=false
CREATE_INDEX=true
CONFIGURE_MACRO=true
INDEX_NAME="saa"
TENANT_URL=""
CONNECTION_NAME="attack_analyzer"
INPUT_NAME="completed_jobs"
INTERVAL="300"
API_KEY_FILE=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Attack Analyzer Setup

Usage: $(basename "$0") [OPTIONS]

Modes:
  --install             Install/configure only
  --validate            Validate only
  --dry-run             Show the plan without changing Splunk
  --json                Emit JSON with --dry-run

Options:
  --source splunkbase|local
  --app-version VER     Pin Splunkbase app/add-on version
  --file PATH           Local Splunk App for Attack Analyzer package
  --app-file PATH       Local Splunk App for Attack Analyzer package
  --addon-file PATH     Local Splunk Add-on for Attack Analyzer package
  --index NAME          Events index for Attack Analyzer data (default: saa)
  --skip-index          Do not create or validate the events index during setup
  --skip-macro          Do not configure the saa_indexes macro during setup
  --tenant-url URL      Non-secret tenant/API URL used in handoff output
  --connection-name N   Connection name for operator handoff
  --input-name N        Completed-jobs input name for operator handoff
  --interval SECONDS    Completed-jobs input interval, minimum 300 (default: 300)
  --api-key-file PATH   File containing the Attack Analyzer API key for handoff readiness
  --no-restart          Skip installer restart handling
  --help                Show this help

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
        --file|--app-file) require_arg "$1" $# || exit 1; APP_FILE="$2"; shift 2 ;;
        --addon-file) require_arg "$1" $# || exit 1; ADDON_FILE="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX_NAME="$2"; shift 2 ;;
        --skip-index) CREATE_INDEX=false; shift ;;
        --skip-macro) CONFIGURE_MACRO=false; shift ;;
        --tenant-url) require_arg "$1" $# || exit 1; TENANT_URL="$2"; shift 2 ;;
        --connection-name) require_arg "$1" $# || exit 1; CONNECTION_NAME="$2"; shift 2 ;;
        --input-name) require_arg "$1" $# || exit 1; INPUT_NAME="$2"; shift 2 ;;
        --interval) require_arg "$1" $# || exit 1; INTERVAL="$2"; shift 2 ;;
        --api-key-file) require_arg "$1" $# || exit 1; API_KEY_FILE="$2"; shift 2 ;;
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

if ! [[ "${INTERVAL}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: --interval must be a positive integer." >&2
    exit 1
fi
if (( INTERVAL < 300 )); then
    echo "ERROR: --interval must be at least 300 seconds." >&2
    exit 1
fi

if [[ -n "${API_KEY_FILE}" && ! -r "${API_KEY_FILE}" ]]; then
    echo "ERROR: --api-key-file is not readable: ${API_KEY_FILE}" >&2
    exit 1
fi

ADDON_INSTALL_CMD=()
APP_INSTALL_CMD=()
VALIDATE_CMD=(bash "${VALIDATE_SCRIPT}" --index "${INDEX_NAME}")

build_install_command() {
    local app_id="$1" file_path="$2"
    local -n out_ref="$3"
    out_ref=(bash "${INSTALL_APP_SCRIPT}")
    if [[ "${SOURCE}" == "splunkbase" ]]; then
        out_ref+=(--source splunkbase --app-id "${app_id}" --no-update)
        [[ -n "${APP_VERSION}" ]] && out_ref+=(--app-version "${APP_VERSION}")
    else
        [[ -n "${file_path}" ]] || { echo "ERROR: local source requires --app-file and --addon-file." >&2; exit 1; }
        out_ref+=(--source local --file "${file_path}" --no-update)
    fi
    [[ "${NO_RESTART}" == "true" ]] && out_ref+=(--no-restart)
    return 0
}

build_commands() {
    build_install_command "${ADDON_APP_ID}" "${ADDON_FILE}" ADDON_INSTALL_CMD
    build_install_command "${VIS_APP_ID}" "${APP_FILE}" APP_INSTALL_CMD
    return 0
}

join_unit() {
    local IFS=$'\037'
    printf '%s' "$*"
}

emit_plan() {
    local phases=()
    [[ "${INSTALL}" == "true" ]] && phases+=("install")
    [[ "${CREATE_INDEX}" == "true" && "${INSTALL}" == "true" ]] && phases+=("create-index")
    [[ "${CONFIGURE_MACRO}" == "true" && "${INSTALL}" == "true" ]] && phases+=("configure-macro")
    [[ "${VALIDATE}" == "true" ]] && phases+=("validate")
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        JSON_PHASES="$(join_unit "${phases[@]}")" \
        JSON_ADDON_INSTALL_COMMAND="$(join_unit "${ADDON_INSTALL_CMD[@]}")" \
        JSON_APP_INSTALL_COMMAND="$(join_unit "${APP_INSTALL_CMD[@]}")" \
        JSON_VALIDATE_COMMAND="$(join_unit "${VALIDATE_CMD[@]}")" \
        INDEX_NAME="${INDEX_NAME}" TENANT_URL="${TENANT_URL}" CONNECTION_NAME="${CONNECTION_NAME}" \
        INPUT_NAME="${INPUT_NAME}" INTERVAL="${INTERVAL}" API_KEY_READY="$([[ -n "${API_KEY_FILE}" ]] && echo true || echo false)" \
        python3 - <<'PY'
import json
import os
import sys

sep = "\x1f"
payload = {
    "ok": True,
    "dry_run": True,
    "product": "Splunk Attack Analyzer",
    "phases": os.environ.get("JSON_PHASES", "").split(sep) if os.environ.get("JSON_PHASES") else [],
    "apps": [
        {"app_id": "6999", "app_name": "Splunk_TA_SAA"},
        {"app_id": "7000", "app_name": "Splunk_App_SAA"},
    ],
    "addon_install_command": os.environ.get("JSON_ADDON_INSTALL_COMMAND", "").split(sep) if os.environ.get("JSON_ADDON_INSTALL_COMMAND") else [],
    "app_install_command": os.environ.get("JSON_APP_INSTALL_COMMAND", "").split(sep) if os.environ.get("JSON_APP_INSTALL_COMMAND") else [],
    "validate_command": os.environ.get("JSON_VALIDATE_COMMAND", "").split(sep) if os.environ.get("JSON_VALIDATE_COMMAND") else [],
    "index": os.environ["INDEX_NAME"],
    "macro": {"app": "Splunk_App_SAA", "name": "saa_indexes", "definition": f"index={os.environ['INDEX_NAME']}"},
    "handoff": {
        "tenant_url": os.environ.get("TENANT_URL", ""),
        "connection_name": os.environ.get("CONNECTION_NAME", ""),
        "input_name": os.environ.get("INPUT_NAME", ""),
        "interval": int(os.environ.get("INTERVAL", "300")),
        "api_key_file_ready": os.environ.get("API_KEY_READY") == "true",
        "note": "Create the tenant connection and completed-jobs input in the add-on UI unless a supported app REST contract is verified.",
    },
}
json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
    else
        echo "Planned phases:"
        printf '  - %s\n' "${phases[@]}"
        printf 'Add-on install command:\n  %q ' "${ADDON_INSTALL_CMD[@]}"; echo
        printf 'App install command:\n  %q ' "${APP_INSTALL_CMD[@]}"; echo
        printf 'Validate command:\n  %q ' "${VALIDATE_CMD[@]}"; echo
        echo "Handoff: create connection '${CONNECTION_NAME}' and input '${INPUT_NAME}' for tenant '${TENANT_URL:-<tenant-url>}' using an API key file."
    fi
}

ensure_session() {
    if [[ -n "${SK:-}" ]]; then
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK="$(get_session_key "${SPLUNK_URI}")" || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

create_index_if_needed() {
    [[ "${CREATE_INDEX}" == "true" ]] || return 0
    ensure_session
    if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX_NAME}" 2>/dev/null; then
        log "Index '${INDEX_NAME}' already exists."
    else
        log "Creating Attack Analyzer index '${INDEX_NAME}'."
        platform_create_index "${SK}" "${SPLUNK_URI}" "${INDEX_NAME}" "512000" "event"
    fi
}

configure_macro_if_needed() {
    local body
    [[ "${CONFIGURE_MACRO}" == "true" ]] || return 0
    ensure_session
    body="$(form_urlencode_pairs definition "index=${INDEX_NAME}" iseval "0")"
    log "Configuring ${VIS_APP_NAME} macro saa_indexes -> index=${INDEX_NAME}."
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${VIS_APP_NAME}" "macros" "saa_indexes" "${body}"
}

build_commands

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
    "${ADDON_INSTALL_CMD[@]}"
    "${APP_INSTALL_CMD[@]}"
    create_index_if_needed
    configure_macro_if_needed
fi

if [[ "${VALIDATE}" == "true" ]]; then
    "${VALIDATE_CMD[@]}"
fi
