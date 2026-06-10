#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-dashboard-studio-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
APP_NAME="search"
DASHBOARD_NAME=""
TITLE=""
DESCRIPTION=""
THEME="light"
SEARCH=""
VIZ_TYPE="splunk.table"
DATASOURCE_NAME="Search_1"
LAYOUT="grid"
DEFINITION_FILE=""
REQUIRES_AUTO_REFRESH="false"
OWNER="nobody"
SHARING="app"
ACCEPT_OVERWRITE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Dashboard Studio Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply | --dry-run | --json
  --output-dir PATH
  --app-name NAME
  --dashboard-name ID              (required; the view id)
  --title TEXT
  --description TEXT
  --theme light|dark
  --search SPL                     (primary ds.search query)
  --viz-type splunk.table|splunk.singlevalue|splunk.line|...
  --datasource-name NAME
  --layout grid|absolute|freeform
  --definition-file PATH           (full Dashboard Studio JSON instead of building)
  --requires-auto-refresh true|false
  --owner USER
  --sharing user|app|global
  --accept-overwrite               (required to overwrite an existing dashboard)
  --help

Examples:
  $(basename "$0") --dashboard-name net_overview --title "Network Overview" \\
    --search 'index=netfw | stats count by action' --viz-type splunk.column
  $(basename "$0") --phase apply --dashboard-name net_overview --app-name search \\
    --search 'index=netfw | stats count' --accept-overwrite

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --dashboard-name) require_arg "$1" $# || exit 1; DASHBOARD_NAME="$2"; shift 2 ;;
        --title) require_arg "$1" $# || exit 1; TITLE="$2"; shift 2 ;;
        --description) require_arg "$1" $# || exit 1; DESCRIPTION="$2"; shift 2 ;;
        --theme) require_arg "$1" $# || exit 1; THEME="$2"; shift 2 ;;
        --search) require_arg "$1" $# || exit 1; SEARCH="$2"; shift 2 ;;
        --viz-type) require_arg "$1" $# || exit 1; VIZ_TYPE="$2"; shift 2 ;;
        --datasource-name) require_arg "$1" $# || exit 1; DATASOURCE_NAME="$2"; shift 2 ;;
        --layout) require_arg "$1" $# || exit 1; LAYOUT="$2"; shift 2 ;;
        --definition-file) require_arg "$1" $# || exit 1; DEFINITION_FILE="$2"; shift 2 ;;
        --requires-auto-refresh) require_arg "$1" $# || exit 1; REQUIRES_AUTO_REFRESH="$2"; shift 2 ;;
        --owner) require_arg "$1" $# || exit 1; OWNER="$2"; shift 2 ;;
        --sharing) require_arg "$1" $# || exit 1; SHARING="$2"; shift 2 ;;
        --accept-overwrite) ACCEPT_OVERWRITE=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_args() {
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${THEME}" light dark
    validate_choice "${LAYOUT}" grid absolute freeform
    validate_choice "${REQUIRES_AUTO_REFRESH}" true false
    validate_choice "${SHARING}" user app global
    [[ -n "${DASHBOARD_NAME}" ]] || { log "ERROR: --dashboard-name is required."; exit 1; }
    if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" && ( "${PHASE}" != "render" || "${APPLY}" == "true" ) ]]; then
        log "ERROR: --json is supported only for render-only or --dry-run workflows."
        exit 1
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --app-name "${APP_NAME}"
        --dashboard-name "${DASHBOARD_NAME}"
        --title "${TITLE}"
        --description "${DESCRIPTION}"
        --theme "${THEME}"
        --search "${SEARCH}"
        --viz-type "${VIZ_TYPE}"
        --datasource-name "${DATASOURCE_NAME}"
        --layout "${LAYOUT}"
        --definition-file "${DEFINITION_FILE}"
        --requires-auto-refresh "${REQUIRES_AUTO_REFRESH}"
        --owner "${OWNER}"
        --sharing "${SHARING}"
    )
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

view_exists() {
    local sk="$1" encoded
    encoded=$(_urlencode "${DASHBOARD_NAME}")
    local http_code
    http_code=$(splunk_curl "${sk}" \
        "${SPLUNK_URI}/servicesNS/${OWNER}/${APP_NAME}/data/ui/views/${encoded}?output_mode=json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
    [[ "${http_code}" == "200" ]]
}

apply_live() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would POST name=${DASHBOARD_NAME} + eai:data(view.xml) to data/ui/views in app ${APP_NAME}."
        return 0
    fi
    local xml_file="${OUTPUT_DIR}/dashboard-studio/view.xml"
    if [[ ! -f "${xml_file}" ]]; then
        log "ERROR: Rendered view.xml not found; run render first."
        exit 1
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    local xml_content
    xml_content="$(cat "${xml_file}")"
    local http_code resp encoded
    if view_exists "${sk}"; then
        if [[ "${ACCEPT_OVERWRITE}" != "true" ]]; then
            log "ERROR: Dashboard '${DASHBOARD_NAME}' already exists. Re-run with --accept-overwrite to update it."
            exit 1
        fi
        encoded=$(_urlencode "${DASHBOARD_NAME}")
        resp=$(splunk_curl_post "${sk}" "$(form_urlencode_pairs "eai:data" "${xml_content}")" \
            "${SPLUNK_URI}/servicesNS/${OWNER}/${APP_NAME}/data/ui/views/${encoded}" \
            -w '\n%{http_code}' 2>/dev/null)
    else
        resp=$(splunk_curl_post "${sk}" "$(form_urlencode_pairs name "${DASHBOARD_NAME}" "eai:data" "${xml_content}")" \
            "${SPLUNK_URI}/servicesNS/${OWNER}/${APP_NAME}/data/ui/views" \
            -w '\n%{http_code}' 2>/dev/null)
    fi
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201) log "Dashboard Studio view '${DASHBOARD_NAME}' applied to app ${APP_NAME}." ;;
        *) log "ERROR: data/ui/views write returned HTTP ${http_code}."; exit 1 ;;
    esac
    apply_acl "${sk}"
}

apply_acl() {
    local sk="$1" encoded http_code resp
    encoded=$(_urlencode "${DASHBOARD_NAME}")
    resp=$(splunk_curl_post "${sk}" "$(form_urlencode_pairs sharing "${SHARING}" owner "${OWNER}" "perms.read" "*")" \
        "${SPLUNK_URI}/servicesNS/${OWNER}/${APP_NAME}/data/ui/views/${encoded}/acl" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201) log "ACL set: sharing=${SHARING}, owner=${OWNER}." ;;
        *) log "WARNING: ACL update returned HTTP ${http_code}; review dashboard permissions." ;;
    esac
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        else
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
            [[ "${PHASE}" == "apply" || "${PHASE}" == "all" ]] && apply_live
        fi
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            [[ "${APPLY}" == "true" ]] && apply_live
            ;;
        preflight) render_assets ;;
        apply) render_assets; apply_live ;;
        status) render_assets ;;
        all) render_assets; apply_live ;;
    esac
}

main "$@"
