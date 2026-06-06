#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
INSTALL_SCRIPT="${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh"

PHASE="render"
PRODUCTS="mssql,mysql,oracle"
INDEX="database"
SERVER_NAME="db01"
OUTPUT_DIR=""
JSON=false
DRY_RUN=false
INSTALL=false
NO_RESTART=false
CREATE_INDEX=false

usage() {
    cat >&2 <<'EOF'
Database Supported Add-ons Setup

Usage: setup.sh [OPTIONS]

Options:
  --phase render|list       Renderer phase (default: render)
  --render                  Alias for --phase render
  --install                 Install selected Splunkbase packages
  --create-index            Create the target event index
  --no-restart              Skip restart during package install
  --products LIST           Product selectors: mssql,mysql,oracle
  --index INDEX             Target event index (default: database)
  --server-name NAME        Host value for rendered SQL Server examples
  --output-dir DIR          Render output directory
  --json                    Emit JSON from renderer
  --dry-run                 Show render/install plan without writing or applying
  --help                    Show this help

This script does not accept database credential values. Use DB Connect
identities and protected secret-file handoffs.
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
        --server-name) require_arg "$1" $# || exit 1; SERVER_NAME="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

install_selected() {
    python3 - "${PRODUCTS}" <<'PY' | while IFS=$'\t' read -r app_id version app_name; do
import sys
profiles = {
    "mssql": ("2648", "3.1.0", "Splunk_TA_microsoft-sqlserver"),
    "mysql": ("2848", "3.2.0", "Splunk_TA_mysql"),
    "oracle": ("1910", "4.2.0", "Splunk_TA_oracle"),
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
    local cmd=(python3 "${RENDER_SCRIPT}" --phase "${PHASE}" --products "${PRODUCTS}" --index "${INDEX}" --server-name "${SERVER_NAME}")
    [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}")
    [[ "${JSON}" == "true" ]] && cmd+=(--json)
    [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run)
    "${cmd[@]}"
}

warn_if_current_skill_role_unsupported
[[ "${INSTALL}" == "true" ]] && install_selected
[[ "${CREATE_INDEX}" == "true" ]] && create_index
run_render
