#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
# shellcheck disable=SC1091
source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"
RENDERED_DIR=""
LIVE=false
COMPLETION=false

usage() {
    cat <<EOF
Splunk Security Content Update Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --rendered-dir PATH  Rendered root or profile directory
  --live               Run read-only Splunk REST/search checks
  --completion         Run live checks and fail on readiness warnings
  --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) [[ $# -ge 2 ]] || { echo "ERROR: --rendered-dir requires a value." >&2; exit 1; }; RENDERED_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --completion|--strict) LIVE=true; COMPLETION=true; shift ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

cmd=(bash "${REPO_ROOT}/skills/shared/scripts/validate_render_first_skill.sh" --skill-name splunk-security-content-update-setup --profile-dir splunk-security-content-update --default-output splunk-security-content-update-rendered --app-name DA-ESS-ContentUpdate)
[[ -n "${RENDERED_DIR}" ]] && cmd+=(--rendered-dir "${RENDERED_DIR}")
[[ "${LIVE}" == "true" ]] && cmd+=(--live)
[[ "${COMPLETION}" == "true" ]] && cmd+=(--completion)
"${cmd[@]}"
if [[ "${LIVE}" == "true" ]]; then
    load_splunk_credentials || { echo "ERROR: Could not load Splunk credentials." >&2; exit 1; }
    SK="$(get_session_key "${SPLUNK_URI}")" || { echo "ERROR: Could not authenticate to Splunk REST API." >&2; exit 1; }
    rest_check_app "${SK}" "${SPLUNK_URI}" DA-ESS-ContentUpdate || { echo "ERROR: DA-ESS-ContentUpdate is not installed." >&2; exit 1; }
fi
