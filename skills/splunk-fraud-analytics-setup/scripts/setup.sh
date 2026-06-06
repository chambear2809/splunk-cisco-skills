#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/render_first_action_helpers.sh"

RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
RENDER=false
JSON=false
DRY_RUN=false
INSTALL=false
VALIDATE=false
ALL=false
MODE_SET=false
LIVE=false
OUTPUT_DIR=""
SOURCE="local"
LOCAL_FILE=""
NO_RESTART=false
PLATFORM="auto"
ES_APP="SplunkEnterpriseSecuritySuite"
FRAUD_USE_CASE="account-takeover"
RISK_INDEX="risk"
TRANSACTION_INDEX="fraud"
LOOKUP_OWNER_APP="Splunk_Fraud_Analytics"
PRODUCT_NAME="Splunk Fraud Analytics Setup"
SKILL_NAME="splunk-fraud-analytics-setup"

usage() {
    cat <<EOF
Splunk Fraud Analytics Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                         Render reviewable Fraud Analytics assets
  --install                        Install local Fraud Analytics package through splunk-app-install
  --validate                       Run local or live validation
  --live                           With --validate/--all, run read-only Splunk REST/search checks
  --all                            Render, install, then validate
  --dry-run                        Show the executable action plan without changing Splunk
  --json                           Emit JSON from the renderer
  --output-dir PATH                Render output directory
  --source local                   App package source for --install
  --file PATH                      Local Fraud Analytics package
  --no-restart                     Skip installer restart handling
  --platform cloud|enterprise|auto Target platform
  --es-app APP                     Enterprise Security app name
  --fraud-use-case NAME            Fraud use case
  --risk-index INDEX               Risk index
  --transaction-index INDEX        Transaction/event index
  --lookup-owner-app APP           Lookup owner app
  --help                           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --install) INSTALL=true; MODE_SET=true; shift ;;
        --validate) VALIDATE=true; MODE_SET=true; shift ;;
        --all) ALL=true; MODE_SET=true; shift ;;
        --live) LIVE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --no-restart) NO_RESTART=true; shift ;;
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --es-app) require_arg "$1" $# || exit 1; ES_APP="$2"; shift 2 ;;
        --fraud-use-case) require_arg "$1" $# || exit 1; FRAUD_USE_CASE="$2"; shift 2 ;;
        --risk-index) require_arg "$1" $# || exit 1; RISK_INDEX="$2"; shift 2 ;;
        --transaction-index) require_arg "$1" $# || exit 1; TRANSACTION_INDEX="$2"; shift 2 ;;
        --lookup-owner-app) require_arg "$1" $# || exit 1; LOOKUP_OWNER_APP="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

case "${PLATFORM}" in cloud|enterprise|auto) ;; *) echo "ERROR: invalid --platform." >&2; exit 1 ;; esac
case "${SOURCE}" in local) ;; *) echo "ERROR: Fraud Analytics install currently requires --source local and --file PATH." >&2; exit 1 ;; esac

if [[ "${ALL}" == "true" ]]; then
    RENDER=true
    INSTALL=true
    VALIDATE=true
fi
if [[ "${MODE_SET}" == "false" && "${RENDER}" == "false" ]]; then
    RENDER=true
fi
if [[ "${JSON}" == "true" && "${DRY_RUN}" != "true" && ( "${INSTALL}" == "true" || "${VALIDATE}" == "true" ) ]]; then
    echo "ERROR: --json with action modes requires --dry-run." >&2
    exit 1
fi

RENDER_CMD=(python3 "${RENDER_SCRIPT}" --phase render --platform "${PLATFORM}" --es-app "${ES_APP}" --fraud-use-case "${FRAUD_USE_CASE}" --risk-index "${RISK_INDEX}" --transaction-index "${TRANSACTION_INDEX}" --lookup-owner-app "${LOOKUP_OWNER_APP}")
[[ -n "${OUTPUT_DIR}" ]] && RENDER_CMD+=(--output-dir "${OUTPUT_DIR}")
if [[ "${DRY_RUN}" == "true" && "${INSTALL}" != "true" && "${VALIDATE}" != "true" ]]; then
    RENDER_CMD+=(--dry-run)
fi
[[ "${JSON}" == "true" && "${DRY_RUN}" != "true" ]] && RENDER_CMD+=(--json)
VALIDATE_CMD=(bash "${SCRIPT_DIR}/validate.sh" --risk-index "${RISK_INDEX}")
[[ -n "${OUTPUT_DIR}" ]] && VALIDATE_CMD+=(--rendered-dir "${OUTPUT_DIR}")
[[ "${LIVE}" == "true" ]] && VALIDATE_CMD+=(--live)
RF_INSTALL_CMD=()
if [[ "${INSTALL}" == "true" ]]; then
    rf_build_app_install_command "N/A" "${SOURCE}" "${LOCAL_FILE}" "" "${NO_RESTART}"
fi

PHASES=()
[[ "${RENDER}" == "true" ]] && PHASES+=("render")
[[ "${INSTALL}" == "true" ]] && PHASES+=("install")
[[ "${VALIDATE}" == "true" ]] && PHASES+=("validate")
PHASES_JOIN="$(rf_join_unit "${PHASES[@]}")"

if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ "${JSON}" == "true" ]]; then
        rf_emit_action_plan_json "${SKILL_NAME}" "${PRODUCT_NAME}" "${PHASES_JOIN}" "$(rf_join_unit "${RENDER_CMD[@]}")" "$(rf_join_unit "${RF_INSTALL_CMD[@]}")" "$(rf_join_unit "${VALIDATE_CMD[@]}")" "$(rf_join_unit "Installs the local Fraud Analytics package only; ES/RBA activation remains delegated.")"
    else
        rf_emit_action_plan_text "${PRODUCT_NAME}" "${PHASES_JOIN}"
        [[ "${RENDER}" == "true" ]] && echo "Render command:" && rf_print_command "${RENDER_CMD[@]}"
        [[ "${INSTALL}" == "true" ]] && echo "Install command:" && rf_print_command "${RF_INSTALL_CMD[@]}"
        [[ "${VALIDATE}" == "true" ]] && echo "Validate command:" && rf_print_command "${VALIDATE_CMD[@]}"
    fi
    exit 0
fi

[[ "${RENDER}" == "true" ]] && "${RENDER_CMD[@]}"
[[ "${INSTALL}" == "true" ]] && rf_run_command "${RF_INSTALL_CMD[@]}"
[[ "${VALIDATE}" == "true" ]] && rf_run_command "${VALIDATE_CMD[@]}"
exit 0
