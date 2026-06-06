#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

RENDERED_DIR=""
LIVE=false
INDEX="cisco_asa"
SOURCETYPE="cisco:asa"

usage() {
    cat <<EOF
Cisco ASA TA Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --rendered-dir PATH      Rendered root or cisco-asa-ta profile directory
  --live                   Run read-only Splunk REST/search checks
  --index INDEX            Index for live checks
  --sourcetype SOURCETYPE  Sourcetype for live checks
  --help                   Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) [[ $# -ge 2 ]] || { echo "ERROR: --rendered-dir requires a value." >&2; exit 1; }; RENDERED_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --index) [[ $# -ge 2 ]] || { echo "ERROR: --index requires a value." >&2; exit 1; }; INDEX="$2"; shift 2 ;;
        --sourcetype) [[ $# -ge 2 ]] || { echo "ERROR: --sourcetype requires a value." >&2; exit 1; }; SOURCETYPE="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

cmd=(bash "${REPO_ROOT}/skills/shared/scripts/validate_render_first_skill.sh" --skill-name cisco-asa-ta-setup --profile-dir cisco-asa-ta --default-output cisco-asa-ta-rendered --app-name Splunk_TA_cisco-asa --index "${INDEX}" --sourcetypes "${SOURCETYPE}")
[[ -n "${RENDERED_DIR}" ]] && cmd+=(--rendered-dir "${RENDERED_DIR}")
[[ "${LIVE}" == "true" ]] && cmd+=(--live)
"${cmd[@]}"
