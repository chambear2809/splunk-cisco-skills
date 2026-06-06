#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-secure-gateway-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
APP_NAME="splunk_secure_gateway"
ACTION="configure"
DEPLOYMENT_NAME=""
VISIBLE_APPS=""
PRIVATE_SPACEBRIDGE="false"
CUSTOM_ENDPOINT_ID=""
CUSTOM_ENDPOINT_HOSTNAME=""
CUSTOM_ENDPOINT_GRPC_HOSTNAME=""
CLIENT_CERT_REQUIRED="true"
ACCEPT_SPACEBRIDGE_EGRESS=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Secure Gateway Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply | --dry-run | --json
  --output-dir PATH
  --app-name NAME                  (default splunk_secure_gateway)
  --action configure|enable|disable
  --deployment-name NAME
  --visible-apps CSV
  --private-spacebridge true|false
  --custom-endpoint-id ID
  --custom-endpoint-hostname HOST
  --custom-endpoint-grpc-hostname HOST
  --client-cert-required true|false
  --accept-spacebridge-egress      (required to enable outbound Spacebridge)
  --help

Examples:
  $(basename "$0") --deployment-name prod-sh --visible-apps search,cisco-catalyst-app
  $(basename "$0") --phase apply --action enable --accept-spacebridge-egress
  $(basename "$0") --phase apply --action disable

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
        --action) require_arg "$1" $# || exit 1; ACTION="$2"; shift 2 ;;
        --deployment-name) require_arg "$1" $# || exit 1; DEPLOYMENT_NAME="$2"; shift 2 ;;
        --visible-apps) require_arg "$1" $# || exit 1; VISIBLE_APPS="$2"; shift 2 ;;
        --private-spacebridge) require_arg "$1" $# || exit 1; PRIVATE_SPACEBRIDGE="$2"; shift 2 ;;
        --custom-endpoint-id) require_arg "$1" $# || exit 1; CUSTOM_ENDPOINT_ID="$2"; shift 2 ;;
        --custom-endpoint-hostname) require_arg "$1" $# || exit 1; CUSTOM_ENDPOINT_HOSTNAME="$2"; shift 2 ;;
        --custom-endpoint-grpc-hostname) require_arg "$1" $# || exit 1; CUSTOM_ENDPOINT_GRPC_HOSTNAME="$2"; shift 2 ;;
        --client-cert-required) require_arg "$1" $# || exit 1; CLIENT_CERT_REQUIRED="$2"; shift 2 ;;
        --accept-spacebridge-egress) ACCEPT_SPACEBRIDGE_EGRESS=true; shift ;;
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
    validate_choice "${ACTION}" configure enable disable
    validate_choice "${PRIVATE_SPACEBRIDGE}" true false
    validate_choice "${CLIENT_CERT_REQUIRED}" true false
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
        --action "${ACTION}"
        --deployment-name "${DEPLOYMENT_NAME}"
        --visible-apps "${VISIBLE_APPS}"
        --private-spacebridge "${PRIVATE_SPACEBRIDGE}"
        --custom-endpoint-id "${CUSTOM_ENDPOINT_ID}"
        --custom-endpoint-hostname "${CUSTOM_ENDPOINT_HOSTNAME}"
        --custom-endpoint-grpc-hostname "${CUSTOM_ENDPOINT_GRPC_HOSTNAME}"
        --client-cert-required "${CLIENT_CERT_REQUIRED}"
    )
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_preflight() {
    local dir="${OUTPUT_DIR}/secure-gateway"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./egress-preflight.sh)"
        return 0
    fi
    (cd "${dir}" && ./egress-preflight.sh)
}

set_app_state() {
    local disabled="$1"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would POST disabled=${disabled} to apps/local/${APP_NAME}."
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    local body http_code resp
    body=$(form_urlencode_pairs disabled "${disabled}")
    resp=$(splunk_curl_post "${sk}" "${body}" \
        "${SPLUNK_URI}/servicesNS/nobody/system/apps/local/${APP_NAME}" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201)
            if [[ "${disabled}" == "0" ]]; then
                log "Enabled ${APP_NAME}."
            else
                log "Disabled ${APP_NAME}."
            fi
            ;;
        *)
            log "ERROR: Setting ${APP_NAME} state returned HTTP ${http_code}."
            exit 1
            ;;
    esac
    log "$(log_platform_restart_guidance "Secure Gateway app state change")"
}

apply_live() {
    case "${ACTION}" in
        enable)
            if [[ "${ACCEPT_SPACEBRIDGE_EGRESS}" != "true" ]]; then
                log "ERROR: Enabling Secure Gateway opens outbound 443 to the Spacebridge host."
                log "       Re-run with --accept-spacebridge-egress to proceed."
                exit 1
            fi
            run_preflight
            set_app_state 0
            ;;
        disable)
            set_app_state 1
            ;;
        configure)
            log "Rendered Secure Gateway assets. Use --action enable/disable to change app state;"
            log "deployment settings and device registration are Splunk Web / MDM operations (see runbooks)."
            ;;
    esac
}

get_status() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would GET apps/local/${APP_NAME} disabled state."
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    splunk_curl "${sk}" "${SPLUNK_URI}/servicesNS/nobody/system/apps/local/${APP_NAME}?output_mode=json" \
        2>/dev/null | rest_json_field "disabled" || log "Could not read ${APP_NAME} state."
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
        preflight) render_assets; run_preflight ;;
        apply) render_assets; apply_live ;;
        status) render_assets; get_status ;;
        all) render_assets; run_preflight; apply_live; get_status ;;
    esac
}

main "$@"
