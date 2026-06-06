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
SOURCE="splunkbase"
APP_VERSION=""
LOCAL_FILE=""
NO_RESTART=false
PLATFORM="auto"
ES_APP="SplunkEnterpriseSecuritySuite"
STORY_FILTER="all"
ACTIVATION_POLICY="review-only"
APP_ID="3449"
PRODUCT_NAME="Splunk Security Content Update Setup"
SKILL_NAME="splunk-security-content-update-setup"

usage() {
    cat <<EOF
Splunk Security Content Update Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                         Render reviewable ESCU setup assets
  --install                        Install DA-ESS-ContentUpdate through splunk-app-install
  --validate                       Run local or live validation
  --live                           With --validate/--all, run read-only Splunk REST checks
  --all                            Render, install, then validate
  --dry-run                        Show the executable action plan without changing Splunk
  --json                           Emit JSON from the renderer
  --output-dir PATH                Render output directory
  --source splunkbase|local        App package source for --install
  --app-version VERSION            Optional Splunkbase version pin
  --file PATH                      Local app package for --source local
  --no-restart                     Skip installer restart handling
  --platform cloud|enterprise|auto Target platform
  --es-app APP                     Enterprise Security app name
  --story-filter VALUE             Analytic story filter for review
  --activation-policy VALUE        Correlation-search activation policy note
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
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --no-restart) NO_RESTART=true; shift ;;
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --es-app) require_arg "$1" $# || exit 1; ES_APP="$2"; shift 2 ;;
        --story-filter) require_arg "$1" $# || exit 1; STORY_FILTER="$2"; shift 2 ;;
        --activation-policy) require_arg "$1" $# || exit 1; ACTIVATION_POLICY="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

case "${PLATFORM}" in cloud|enterprise|auto) ;; *) echo "ERROR: invalid --platform." >&2; exit 1 ;; esac
case "${SOURCE}" in splunkbase|local) ;; *) echo "ERROR: --source must be splunkbase or local." >&2; exit 1 ;; esac

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

RENDER_CMD=(python3 "${RENDER_SCRIPT}" --phase render --platform "${PLATFORM}" --es-app "${ES_APP}" --story-filter "${STORY_FILTER}" --activation-policy "${ACTIVATION_POLICY}")
[[ -n "${OUTPUT_DIR}" ]] && RENDER_CMD+=(--output-dir "${OUTPUT_DIR}")
if [[ "${DRY_RUN}" == "true" && "${INSTALL}" != "true" && "${VALIDATE}" != "true" ]]; then
    RENDER_CMD+=(--dry-run)
fi
[[ "${JSON}" == "true" && "${DRY_RUN}" != "true" ]] && RENDER_CMD+=(--json)
VALIDATE_CMD=(bash "${SCRIPT_DIR}/validate.sh")
[[ -n "${OUTPUT_DIR}" ]] && VALIDATE_CMD+=(--rendered-dir "${OUTPUT_DIR}")
[[ "${LIVE}" == "true" ]] && VALIDATE_CMD+=(--live)
RF_INSTALL_CMD=()
if [[ "${INSTALL}" == "true" ]]; then
    rf_build_app_install_command "${APP_ID}" "${SOURCE}" "${LOCAL_FILE}" "${APP_VERSION}" "${NO_RESTART}"
fi

PHASES=()
[[ "${RENDER}" == "true" ]] && PHASES+=("render")
[[ "${INSTALL}" == "true" ]] && PHASES+=("install")
[[ "${VALIDATE}" == "true" ]] && PHASES+=("validate")
PHASES_JOIN="$(rf_join_unit "${PHASES[@]}")"

if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ "${JSON}" == "true" ]]; then
        rf_emit_action_plan_json "${SKILL_NAME}" "${PRODUCT_NAME}" "${PHASES_JOIN}" "$(rf_join_unit "${RENDER_CMD[@]}")" "$(rf_join_unit "${RF_INSTALL_CMD[@]}")" "$(rf_join_unit "${VALIDATE_CMD[@]}")" "$(rf_join_unit "Installs ESCU package only; correlation-search activation remains delegated to Enterprise Security configuration.")"
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
