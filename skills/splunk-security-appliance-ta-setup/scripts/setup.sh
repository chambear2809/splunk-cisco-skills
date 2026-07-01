#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
INSTALL_SCRIPT="${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh"

PHASE="render"
PRODUCTS="carbon_black,symantec_endpoint_protection"
INDEX="endpoint"
CARBON_BLACK_JSON_DIR="/var/lib/carbonblack/json"
SYMANTEC_DUMP_DIR="/var/lib/symantec_ep/dump"
SYSLOG_PORT="514"
OUTPUT_DIR=""
JSON=false
DRY_RUN=false
INSTALL=false
NO_RESTART=false
CREATE_INDEX=false

usage() {
    cat >&2 <<'EOF'
Security Appliance Supported Add-ons Setup

Options:
  --phase render|list       Renderer phase (default: render)
  --render                  Alias for --phase render
  --install                 Install selected packages
  --create-index            Create the target event index
  --no-restart              Skip restart during install
  --products LIST           Selectors: carbon_black,symantec_endpoint_protection
  --index INDEX             Target event index (default: endpoint)
  --carbon-black-json-dir DIR  Carbon Black JSON file monitor directory
  --symantec-dump-dir DIR   Symantec EP dump file directory
  --syslog-port PORT        Symantec EP syslog handoff port
  --output-dir DIR          Render output directory
  --json                    Emit JSON from renderer
  --dry-run                 Show render/install plan only
  --help                    Show this help

This script does not accept credential values.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --render) PHASE="render"; shift ;;
        --install) INSTALL=true; shift ;;
        --create-index) CREATE_INDEX=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --carbon-black-json-dir) require_arg "$1" $# || exit 1; CARBON_BLACK_JSON_DIR="$2"; shift 2 ;;
        --symantec-dump-dir) require_arg "$1" $# || exit 1; SYMANTEC_DUMP_DIR="$2"; shift 2 ;;
        --syslog-port) require_arg "$1" $# || exit 1; SYSLOG_PORT="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_request() {
    validate_splunk_index_name "${INDEX}" || return 1
    case "${PHASE}" in
        render|list) ;;
        *) echo "ERROR: --phase must be render or list (got: ${PHASE})" >&2; return 1 ;;
    esac
    python3 - "${PRODUCTS}" <<'PY'
import sys

allowed = {"carbon_black", "symantec_endpoint_protection"}
selected = [item.strip().lower() for item in sys.argv[1].split(",") if item.strip()]
if not selected:
    raise SystemExit("ERROR: --products must select at least one product")
unknown = sorted(set(selected) - allowed)
if unknown:
    raise SystemExit(f"ERROR: unknown product selector(s): {', '.join(unknown)}")
PY
    if [[ "${PHASE}" == "list" && ( "${INSTALL}" == "true" || "${CREATE_INDEX}" == "true" ) ]]; then
        echo "ERROR: --phase list cannot be combined with --install or --create-index" >&2
        return 1
    fi
    if [[ "${JSON}" == "true" && ( "${INSTALL}" == "true" || "${CREATE_INDEX}" == "true" ) ]]; then
        echo "ERROR: --json cannot be combined with --install or --create-index" >&2
        return 1
    fi
}

install_selected() {
    python3 - "${PRODUCTS}" <<'PY' | while IFS=$'\t' read -r app_id version app_name; do
import sys
profiles = {
    "carbon_black": ("2790", "3.0.0", "Splunk_TA_bit9-carbonblack"),
    "symantec_endpoint_protection": ("2772", "4.0.0", "Splunk_TA_symantec-ep"),
}
for item in [part.strip().lower() for part in sys.argv[1].split(",") if part.strip()]:
    if item not in profiles:
        raise SystemExit(f"ERROR: unknown product selector: {item}")
    print("\t".join(profiles[item]))
PY
        cmd=(bash "${INSTALL_SCRIPT}" --source splunkbase --app-id "${app_id}" --app-version "${version}" --no-update)
        [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
        if [[ "${DRY_RUN}" == "true" ]]; then
            printf 'DRY RUN: '
            printf '%q ' "${cmd[@]}"
            printf '# %s\n' "${app_name}"
        else
            "${cmd[@]}"
        fi
    done
}

create_index() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "DRY RUN: create index ${INDEX}"
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk=""
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    platform_create_index "${sk}" "${SPLUNK_URI}" "${INDEX}" "512000" || exit 1
}

run_render() {
    local cmd=(python3 "${RENDER_SCRIPT}" --phase "${PHASE}" --products "${PRODUCTS}" --index "${INDEX}" --carbon-black-json-dir "${CARBON_BLACK_JSON_DIR}" --symantec-dump-dir "${SYMANTEC_DUMP_DIR}" --syslog-port "${SYSLOG_PORT}")
    [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}")
    [[ "${JSON}" == "true" ]] && cmd+=(--json)
    [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run)
    "${cmd[@]}"
}

validate_request
warn_if_current_skill_role_unsupported
if [[ "${DRY_RUN}" != "true" && ( "${INSTALL}" == "true" || "${CREATE_INDEX}" == "true" ) ]]; then require_current_skill_role_supported; fi
if [[ "${DRY_RUN}" != "true" && "${INSTALL}" == "true" ]]; then require_splunk_management_target_role; fi
if [[ "${DRY_RUN}" != "true" && "${CREATE_INDEX}" == "true" ]]; then require_index_management_target_role; fi
[[ "${INSTALL}" == "true" ]] && install_selected
[[ "${CREATE_INDEX}" == "true" ]] && create_index
run_render
