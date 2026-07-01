#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

RENDERED_DIR=""
LIVE=false
STRICT=false
INDEX="cisco_asa"
SOURCETYPE="cisco:asa"

usage() {
    cat <<EOF
Cisco ASA TA Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --rendered-dir PATH      Rendered root or cisco-asa-ta profile directory
  --live                   Run read-only Splunk REST/search checks
  --strict, --completion   Require live app, index, and event evidence
  --index INDEX            Index for live checks
  --sourcetype SOURCETYPE  Sourcetype for live checks
  --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) [[ $# -ge 2 ]] || { echo "ERROR: --rendered-dir requires a value." >&2; exit 1; }; RENDERED_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --strict|--completion) STRICT=true; shift ;;
        --index) [[ $# -ge 2 ]] || { echo "ERROR: --index requires a value." >&2; exit 1; }; INDEX="$2"; shift 2 ;;
        --sourcetype) [[ $# -ge 2 ]] || { echo "ERROR: --sourcetype requires a value." >&2; exit 1; }; SOURCETYPE="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

if [[ "${STRICT}" == "true" && "${LIVE}" != "true" ]]; then
    echo "ERROR: --strict/--completion requires --live." >&2
    exit 1
fi

cmd=(bash "${REPO_ROOT}/skills/shared/scripts/validate_render_first_skill.sh" --skill-name cisco-asa-ta-setup --profile-dir cisco-asa-ta --default-output cisco-asa-ta-rendered --app-name Splunk_TA_cisco-asa --index "${INDEX}" --sourcetypes "${SOURCETYPE}")
[[ -n "${RENDERED_DIR}" ]] && cmd+=(--rendered-dir "${RENDERED_DIR}")
[[ "${LIVE}" == "true" ]] && cmd+=(--live)
"${cmd[@]}"

if [[ "${STRICT}" == "true" ]]; then
    # The shared render validator intentionally treats live readiness gaps as
    # diagnostics. Recheck completion-critical ASA evidence locally.
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"
    completion_failures=0
    if ! load_splunk_credentials || ! SK=$(get_session_key "${SPLUNK_URI}"); then
        echo "FAIL: could not authenticate for ASA completion validation" >&2
        exit 1
    fi
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "Splunk_TA_cisco-asa" 2>/dev/null; then
        echo "FAIL: Splunk_TA_cisco-asa is not installed" >&2
        completion_failures=$((completion_failures + 1))
    fi
    if ! platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}" 2>/dev/null; then
        echo "FAIL: ASA index is missing: ${INDEX}" >&2
        completion_failures=$((completion_failures + 1))
    fi
    event_count=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
        "| tstats count where index=${INDEX} sourcetype=\"${SOURCETYPE}\"" "count" 2>/dev/null || echo "0")
    if [[ ! "${event_count}" =~ ^[0-9]+$ || "${event_count}" -eq 0 ]]; then
        echo "FAIL: no ${SOURCETYPE} events found in ${INDEX}" >&2
        completion_failures=$((completion_failures + 1))
    fi
    [[ "${completion_failures}" -eq 0 ]]
fi
