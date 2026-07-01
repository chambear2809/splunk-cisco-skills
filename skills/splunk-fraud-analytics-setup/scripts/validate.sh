#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
# shellcheck disable=SC1091
source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"
RENDERED_DIR=""
LIVE=false
COMPLETION=false
RISK_INDEX="risk"

usage() {
    cat <<EOF
Splunk Fraud Analytics Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --rendered-dir PATH  Rendered root or profile directory
  --live               Run read-only Splunk REST/search checks
  --completion         Run live checks and fail on readiness warnings
  --risk-index INDEX   Risk index for live checks
  --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) [[ $# -ge 2 ]] || { echo "ERROR: --rendered-dir requires a value." >&2; exit 1; }; RENDERED_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --completion|--strict) LIVE=true; COMPLETION=true; shift ;;
        --risk-index) [[ $# -ge 2 ]] || { echo "ERROR: --risk-index requires a value." >&2; exit 1; }; RISK_INDEX="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

cmd=(bash "${REPO_ROOT}/skills/shared/scripts/validate_render_first_skill.sh" --skill-name splunk-fraud-analytics-setup --profile-dir splunk-fraud-analytics --default-output splunk-fraud-analytics-rendered --app-name Splunk_Fraud_Analytics --index "${RISK_INDEX}" --require-dashboard)
[[ -n "${RENDERED_DIR}" ]] && cmd+=(--rendered-dir "${RENDERED_DIR}")
[[ "${LIVE}" == "true" ]] && cmd+=(--live)
[[ "${COMPLETION}" == "true" ]] && cmd+=(--completion)
"${cmd[@]}"
if [[ "${LIVE}" == "true" ]]; then
    load_splunk_credentials || { echo "ERROR: Could not load Splunk credentials." >&2; exit 1; }
    SK="$(get_session_key "${SPLUNK_URI}")" || { echo "ERROR: Could not authenticate to Splunk REST API." >&2; exit 1; }
    rest_check_app "${SK}" "${SPLUNK_URI}" Splunk_Fraud_Analytics || { echo "ERROR: Splunk_Fraud_Analytics is not installed." >&2; exit 1; }
    platform_check_index "${SK}" "${SPLUNK_URI}" "${RISK_INDEX}" || { echo "ERROR: Required risk index is missing: ${RISK_INDEX}" >&2; exit 1; }
fi
