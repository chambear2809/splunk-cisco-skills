#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

RENDERED_DIR=""
LIVE=false
INDEX="aws"
SOURCETYPES="aws:cloudtrail,aws:cloudwatchlogs:vpcflow,aws:cloudwatch:events,_json,httpevent"

usage() {
    cat <<EOF
Amazon Kinesis Firehose Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --rendered-dir PATH  Rendered root or profile directory
  --live               Run read-only Splunk REST/search checks
  --index INDEX        Index for live checks
  --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) [[ $# -ge 2 ]] || { echo "ERROR: --rendered-dir requires a value." >&2; exit 1; }; RENDERED_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --index) [[ $# -ge 2 ]] || { echo "ERROR: --index requires a value." >&2; exit 1; }; INDEX="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

cmd=(bash "${REPO_ROOT}/skills/shared/scripts/validate_render_first_skill.sh" --skill-name splunk-amazon-kinesis-firehose-setup --profile-dir splunk-amazon-kinesis-firehose --default-output splunk-amazon-kinesis-firehose-rendered --app-name N/A --index "${INDEX}" --sourcetypes "${SOURCETYPES}")
[[ -n "${RENDERED_DIR}" ]] && cmd+=(--rendered-dir "${RENDERED_DIR}")
[[ "${LIVE}" == "true" ]] && cmd+=(--live)
"${cmd[@]}"
