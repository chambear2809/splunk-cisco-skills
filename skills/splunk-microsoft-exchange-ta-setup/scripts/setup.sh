#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
INSTALL_SCRIPT="${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh"

PHASE="render"
PRODUCTS="exchange"
INDEX="msexchange"
PERFMON_INDEX="perfmon"
WINDOWS_INDEX="windows"
WINEVENTLOG_INDEX="wineventlog"
MSAD_INDEX="msad"
SERVER_NAME="exchange01"
OUTPUT_DIR=""
JSON=false
DRY_RUN=false
INSTALL=false
NO_RESTART=false

usage() {
    cat >&2 <<'EOF'
Microsoft Exchange Supported Add-on Setup

Options:
  --phase render|list       Renderer phase (default: render)
  --render                  Alias for --phase render
  --install                 Install Exchange bundle and Exchange Indexes package
  --no-restart              Skip restart during install
  --products exchange       Product selector (default: exchange)
  --index INDEX             Exchange event index (default: msexchange)
  --perfmon-index INDEX     Perfmon index (default: perfmon)
  --windows-index INDEX     Windows index (default: windows)
  --wineventlog-index INDEX WinEventLog index (default: wineventlog)
  --msad-index INDEX        Microsoft AD index (default: msad)
  --server-name NAME        Host value for rendered examples
  --output-dir DIR          Render output directory
  --json                    Emit JSON from renderer
  --dry-run                 Show render/install plan only
  --help                    Show this help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --render) PHASE="render"; shift ;;
        --install) INSTALL=true; shift ;;
        --no-restart) NO_RESTART=true; shift ;;
        --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --perfmon-index) require_arg "$1" $# || exit 1; PERFMON_INDEX="$2"; shift 2 ;;
        --windows-index) require_arg "$1" $# || exit 1; WINDOWS_INDEX="$2"; shift 2 ;;
        --wineventlog-index) require_arg "$1" $# || exit 1; WINEVENTLOG_INDEX="$2"; shift 2 ;;
        --msad-index) require_arg "$1" $# || exit 1; MSAD_INDEX="$2"; shift 2 ;;
        --server-name) require_arg "$1" $# || exit 1; SERVER_NAME="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --json) JSON=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help|-h) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

install_apps() {
    local commands=(
        "3225 4.1.0 Exchange_bundle"
        "5663 4.0.4 SA-ExchangeIndex"
    )
    local spec app_id version label
    for spec in "${commands[@]}"; do
        read -r app_id version label <<<"${spec}"
        cmd=(bash "${INSTALL_SCRIPT}" --source splunkbase --app-id "${app_id}" --app-version "${version}" --no-update)
        [[ "${NO_RESTART}" == "true" ]] && cmd+=(--no-restart)
        if [[ "${DRY_RUN}" == "true" ]]; then
            printf 'DRY RUN: '
            printf '%q ' "${cmd[@]}"
            printf '# %s\n' "${label}"
        else
            "${cmd[@]}"
        fi
    done
}

run_render() {
    local cmd=(python3 "${RENDER_SCRIPT}" --phase "${PHASE}" --products "${PRODUCTS}" --index "${INDEX}" --perfmon-index "${PERFMON_INDEX}" --windows-index "${WINDOWS_INDEX}" --wineventlog-index "${WINEVENTLOG_INDEX}" --msad-index "${MSAD_INDEX}" --server-name "${SERVER_NAME}")
    [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}")
    [[ "${JSON}" == "true" ]] && cmd+=(--json)
    [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run)
    "${cmd[@]}"
}

warn_if_current_skill_role_unsupported
[[ "${INSTALL}" == "true" ]] && install_apps
run_render
