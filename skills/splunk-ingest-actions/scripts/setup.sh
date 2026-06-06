#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-ingest-actions-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="splunk_ingest_actions"
PLATFORM="enterprise"
SOURCETYPE=""
RULESET_NAME=""
RULES=""
FILTER_REGEX=""
MASK_REGEX=""
MASK_REPLACEMENT=""
TARGET_INDEX=""
DESTINATION_TYPE="none"
DESTINATION_NAME=""
S3_PATH=""
FS_PATH=""
S3_ENDPOINT=""
S3_AUTH_REGION=""
S3_ENCRYPTION="unset"
S3_KMS_KEY_ID=""
S3_ACCESS_KEY_FILE=""
S3_SECRET_KEY_FILE=""
PARTITION_BY=""
FORMAT="json"
COMPRESSION="gzip"
BATCH_SIZE_KB=""
DROP_ON_UPLOAD_ERROR="false"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Ingest Actions

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|apply|status
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --platform cloud|enterprise
  --sourcetype NAME
  --ruleset-name NAME
  --rules CSV (filter,mask,setindex,route)
  --filter-regex REGEX
  --mask-regex REGEX
  --mask-replacement TEXT
  --target-index NAME
  --destination-type none|s3|filesystem
  --destination-name NAME
  --s3-path s3://...
  --fs-path PATH
  --s3-endpoint URL
  --s3-auth-region REGION
  --s3-encryption unset|none|sse-s3|sse-kms
  --s3-kms-key-id ID_OR_ARN
  --s3-access-key-file PATH
  --s3-secret-key-file PATH
  --partition-by FIELD_OR_TOKEN
  --format raw|json
  --compression none|gzip|zstd
  --batch-size-kb N
  --drop-events-on-upload-error true|false
  --help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --sourcetype) require_arg "$1" $# || exit 1; SOURCETYPE="$2"; shift 2 ;;
        --ruleset-name) require_arg "$1" $# || exit 1; RULESET_NAME="$2"; shift 2 ;;
        --rules) require_arg "$1" $# || exit 1; RULES="$2"; shift 2 ;;
        --filter-regex) require_arg "$1" $# || exit 1; FILTER_REGEX="$2"; shift 2 ;;
        --mask-regex) require_arg "$1" $# || exit 1; MASK_REGEX="$2"; shift 2 ;;
        --mask-replacement) require_arg "$1" $# || exit 1; MASK_REPLACEMENT="$2"; shift 2 ;;
        --target-index) require_arg "$1" $# || exit 1; TARGET_INDEX="$2"; shift 2 ;;
        --destination-type) require_arg "$1" $# || exit 1; DESTINATION_TYPE="$2"; shift 2 ;;
        --destination-name) require_arg "$1" $# || exit 1; DESTINATION_NAME="$2"; shift 2 ;;
        --s3-path) require_arg "$1" $# || exit 1; S3_PATH="$2"; shift 2 ;;
        --fs-path) require_arg "$1" $# || exit 1; FS_PATH="$2"; shift 2 ;;
        --s3-endpoint) require_arg "$1" $# || exit 1; S3_ENDPOINT="$2"; shift 2 ;;
        --s3-auth-region) require_arg "$1" $# || exit 1; S3_AUTH_REGION="$2"; shift 2 ;;
        --s3-encryption) require_arg "$1" $# || exit 1; S3_ENCRYPTION="$2"; shift 2 ;;
        --s3-kms-key-id) require_arg "$1" $# || exit 1; S3_KMS_KEY_ID="$2"; shift 2 ;;
        --s3-access-key-file) require_arg "$1" $# || exit 1; S3_ACCESS_KEY_FILE="$2"; shift 2 ;;
        --s3-secret-key-file) require_arg "$1" $# || exit 1; S3_SECRET_KEY_FILE="$2"; shift 2 ;;
        --partition-by) require_arg "$1" $# || exit 1; PARTITION_BY="$2"; shift 2 ;;
        --format) require_arg "$1" $# || exit 1; FORMAT="$2"; shift 2 ;;
        --compression) require_arg "$1" $# || exit 1; COMPRESSION="$2"; shift 2 ;;
        --batch-size-kb) require_arg "$1" $# || exit 1; BATCH_SIZE_KB="$2"; shift 2 ;;
        --drop-events-on-upload-error) require_arg "$1" $# || exit 1; DROP_ON_UPLOAD_ERROR="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_args() {
    validate_choice "${PHASE}" render apply status
    validate_choice "${PLATFORM}" cloud enterprise
    validate_choice "${DESTINATION_TYPE}" none s3 filesystem
    validate_choice "${FORMAT}" raw json
    validate_choice "${COMPRESSION}" none gzip zstd
    validate_choice "${S3_ENCRYPTION}" unset none sse-s3 sse-kms
    validate_choice "${DROP_ON_UPLOAD_ERROR}" true false
    if [[ "${JSON_OUTPUT}" == "true" && "${PHASE}" != "render" && "${DRY_RUN}" != "true" ]]; then
        log "ERROR: --json is supported only for render-only or --dry-run workflows."
        exit 1
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --platform "${PLATFORM}"
        --sourcetype "${SOURCETYPE}"
        --ruleset-name "${RULESET_NAME}"
        --rules "${RULES}"
        --filter-regex "${FILTER_REGEX}"
        --mask-regex "${MASK_REGEX}"
        --mask-replacement "${MASK_REPLACEMENT}"
        --target-index "${TARGET_INDEX}"
        --destination-type "${DESTINATION_TYPE}"
        --destination-name "${DESTINATION_NAME}"
        --s3-path "${S3_PATH}"
        --fs-path "${FS_PATH}"
        --s3-endpoint "${S3_ENDPOINT}"
        --s3-auth-region "${S3_AUTH_REGION}"
        --s3-encryption "${S3_ENCRYPTION}"
        --s3-kms-key-id "${S3_KMS_KEY_ID}"
        --s3-access-key-file "${S3_ACCESS_KEY_FILE}"
        --s3-secret-key-file "${S3_SECRET_KEY_FILE}"
        --partition-by "${PARTITION_BY}"
        --format "${FORMAT}"
        --compression "${COMPRESSION}"
        --batch-size-kb "${BATCH_SIZE_KB}"
        --drop-events-on-upload-error "${DROP_ON_UPLOAD_ERROR}"
    )
}

render_dir() {
    printf '%s/ingest-actions' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered_script() {
    local script_name="$1" dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_name})"
        return 0
    fi
    if [[ ! -x "${dir}/${script_name}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_name}"
        exit 1
    fi
    (cd "${dir}" && "./${script_name}")
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        fi
        python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
        exit 0
    fi
    case "${PHASE}" in
        render) render_assets ;;
        apply) render_assets; run_rendered_script apply.sh ;;
        status) render_assets; run_rendered_script status.sh ;;
    esac
}

main "$@"
