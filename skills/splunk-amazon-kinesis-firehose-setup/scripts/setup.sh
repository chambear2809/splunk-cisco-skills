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
PLATFORM="enterprise"
INDEX="aws"
HEC_TOKEN_NAME="aws_firehose_hec"
SOURCE_PROFILE="cloudtrail"
S3_BACKUP_BUCKET="s3://example-firehose-backup"
BUFFER_SIZE_MB="5"
BUFFER_INTERVAL_SEC="60"
USE_ACK="true"
TOKEN_FILE=""
WRITE_TOKEN_FILE=""
RESTART_SPLUNK="true"
PRODUCT_NAME="Amazon Kinesis Firehose Setup"
SKILL_NAME="splunk-amazon-kinesis-firehose-setup"

usage() {
    cat <<EOF
Amazon Kinesis Firehose Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                                  Render reviewable Firehose setup assets
  --install                                 Apply Splunk-side HEC setup through splunk-hec-service-setup
  --validate                                Run local or live validation
  --live                                    With --validate/--all, run read-only Splunk REST/search checks
  --all                                     Render, apply HEC setup, then validate
  --dry-run                                 Show the executable action plan without changing Splunk
  --json                                    Emit JSON from the renderer
  --output-dir PATH                         Render output directory
  --platform enterprise|cloud                Splunk platform for HEC setup
  --index INDEX                             Target index (default: aws)
  --hec-token-name NAME                     HEC token name (default: aws_firehose_hec)
  --source-profile cloudtrail|vpcflow|cloudwatch-events|raw-json
  --s3-backup-bucket URI                    S3 backup bucket URI
  --buffer-size-mb MB                       Firehose buffer size
  --buffer-interval-sec SECONDS             Firehose buffer interval
  --use-ack true|false                      HEC ACK guidance
  --token-file PATH                         Enterprise HEC token secret file for delegated apply
  --write-token-file PATH                   Cloud HEC token output file for delegated apply
  --restart-splunk true|false               Delegate restart handling to HEC setup
  --help                                    Show this help
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
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --hec-token-name) require_arg "$1" $# || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --source-profile) require_arg "$1" $# || exit 1; SOURCE_PROFILE="$2"; shift 2 ;;
        --s3-backup-bucket) require_arg "$1" $# || exit 1; S3_BACKUP_BUCKET="$2"; shift 2 ;;
        --buffer-size-mb) require_arg "$1" $# || exit 1; BUFFER_SIZE_MB="$2"; shift 2 ;;
        --buffer-interval-sec) require_arg "$1" $# || exit 1; BUFFER_INTERVAL_SEC="$2"; shift 2 ;;
        --use-ack) require_arg "$1" $# || exit 1; USE_ACK="$2"; shift 2 ;;
        --token-file) require_arg "$1" $# || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --write-token-file) require_arg "$1" $# || exit 1; WRITE_TOKEN_FILE="$2"; shift 2 ;;
        --restart-splunk) require_arg "$1" $# || exit 1; RESTART_SPLUNK="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        --token|--password|--api-key|--session-key) echo "ERROR: secrets must not be passed on argv." >&2; exit 1 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

case "${SOURCE_PROFILE}" in
    cloudtrail|vpcflow|cloudwatch-events|raw-json) ;;
    *) echo "ERROR: invalid --source-profile." >&2; exit 1 ;;
esac
case "${PLATFORM}" in
    enterprise|cloud) ;;
    *) echo "ERROR: --platform must be enterprise or cloud." >&2; exit 1 ;;
esac
case "${USE_ACK}" in
    true|false) ;;
    *) echo "ERROR: --use-ack must be true or false." >&2; exit 1 ;;
esac
case "${RESTART_SPLUNK}" in
    true|false) ;;
    *) echo "ERROR: --restart-splunk must be true or false." >&2; exit 1 ;;
esac

case "${SOURCE_PROFILE}" in
    cloudtrail) SELECTED_SOURCE="aws:firehose:cloudtrail"; SELECTED_SOURCETYPE="aws:cloudtrail" ;;
    vpcflow) SELECTED_SOURCE="aws:firehose:vpcflow"; SELECTED_SOURCETYPE="aws:cloudwatchlogs:vpcflow" ;;
    cloudwatch-events) SELECTED_SOURCE="aws:firehose:cloudwatch-events"; SELECTED_SOURCETYPE="aws:cloudwatch:events" ;;
    raw-json) SELECTED_SOURCE="aws:firehose:raw-json"; SELECTED_SOURCETYPE="_json" ;;
esac

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

RENDER_CMD=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --hec-token-name "${HEC_TOKEN_NAME}" --source-profile "${SOURCE_PROFILE}" --s3-backup-bucket "${S3_BACKUP_BUCKET}" --buffer-size-mb "${BUFFER_SIZE_MB}" --buffer-interval-sec "${BUFFER_INTERVAL_SEC}" --use-ack "${USE_ACK}")
[[ -n "${OUTPUT_DIR}" ]] && RENDER_CMD+=(--output-dir "${OUTPUT_DIR}")
if [[ "${DRY_RUN}" == "true" && "${INSTALL}" != "true" && "${VALIDATE}" != "true" ]]; then
    RENDER_CMD+=(--dry-run)
fi
[[ "${JSON}" == "true" && "${DRY_RUN}" != "true" ]] && RENDER_CMD+=(--json)
RF_INSTALL_CMD=()
if [[ "${INSTALL}" == "true" ]]; then
    RF_INSTALL_CMD=(bash "${SCRIPT_DIR}/../../splunk-hec-service-setup/scripts/setup.sh" --phase apply --platform "${PLATFORM}" --token-name "${HEC_TOKEN_NAME}" --default-index "${INDEX}" --allowed-indexes "${INDEX}" --source "${SELECTED_SOURCE}" --sourcetype "${SELECTED_SOURCETYPE}" --use-ack "${USE_ACK}" --restart-splunk "${RESTART_SPLUNK}")
    [[ -n "${TOKEN_FILE}" ]] && RF_INSTALL_CMD+=(--token-file "${TOKEN_FILE}")
    [[ -n "${WRITE_TOKEN_FILE}" ]] && RF_INSTALL_CMD+=(--write-token-file "${WRITE_TOKEN_FILE}")
fi
VALIDATE_CMD=(bash "${SCRIPT_DIR}/validate.sh" --index "${INDEX}")
[[ -n "${OUTPUT_DIR}" ]] && VALIDATE_CMD+=(--rendered-dir "${OUTPUT_DIR}")
[[ "${LIVE}" == "true" ]] && VALIDATE_CMD+=(--live)

PHASES=()
[[ "${RENDER}" == "true" ]] && PHASES+=("render")
[[ "${INSTALL}" == "true" ]] && PHASES+=("hec-apply")
[[ "${VALIDATE}" == "true" ]] && PHASES+=("validate")
PHASES_JOIN="$(rf_join_unit "${PHASES[@]}")"

if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ "${JSON}" == "true" ]]; then
        rf_emit_action_plan_json "${SKILL_NAME}" "${PRODUCT_NAME}" "${PHASES_JOIN}" "$(rf_join_unit "${RENDER_CMD[@]}")" "$(rf_join_unit "${RF_INSTALL_CMD[@]}")" "$(rf_join_unit "${VALIDATE_CMD[@]}")" "$(rf_join_unit "Applies Splunk-side HEC setup only; AWS Firehose stream creation remains an AWS-owner handoff.")"
    else
        rf_emit_action_plan_text "${PRODUCT_NAME}" "${PHASES_JOIN}"
        [[ "${RENDER}" == "true" ]] && echo "Render command:" && rf_print_command "${RENDER_CMD[@]}"
        [[ "${INSTALL}" == "true" ]] && echo "HEC apply command:" && rf_print_command "${RF_INSTALL_CMD[@]}"
        [[ "${VALIDATE}" == "true" ]] && echo "Validate command:" && rf_print_command "${VALIDATE_CMD[@]}"
    fi
    exit 0
fi

[[ "${RENDER}" == "true" ]] && "${RENDER_CMD[@]}"
[[ "${INSTALL}" == "true" ]] && rf_run_command "${RF_INSTALL_CMD[@]}"
[[ "${VALIDATE}" == "true" ]] && rf_run_command "${VALIDATE_CMD[@]}"
exit 0
