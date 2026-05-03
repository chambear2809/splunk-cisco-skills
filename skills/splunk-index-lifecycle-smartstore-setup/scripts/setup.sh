#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-smartstore-rendered"

DEPLOYMENT="cluster"
SCOPE="per-index"
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="ZZZ_cisco_skills_smartstore"
REMOTE_PROVIDER="s3"
VOLUME_NAME="remote_store"
REMOTE_PATH=""
INDEXES="main"
MAX_GLOBAL_DATA_SIZE_MB=""
MAX_GLOBAL_RAW_DATA_SIZE_MB=""
FROZEN_TIME_PERIOD_IN_SECS=""
CACHE_SIZE_MB=""
EVICTION_POLICY=""
EVICTION_PADDING_MB=""
HOTLIST_RECENCY_SECS=""
HOTLIST_BLOOM_FILTER_RECENCY_HOURS=""
INDEX_HOTLIST_RECENCY_SECS=""
INDEX_HOTLIST_BLOOM_FILTER_RECENCY_HOURS=""
S3_ENDPOINT=""
S3_AUTH_REGION=""
S3_SIGNATURE_VERSION=""
S3_SUPPORTS_VERSIONING="unset"
S3_TSIDX_COMPRESSION="unset"
S3_ENCRYPTION="unset"
S3_KMS_KEY_ID=""
S3_KMS_AUTH_REGION=""
S3_SSL_VERIFY_SERVER_CERT="unset"
S3_SSL_VERSIONS=""
S3_ACCESS_KEY_FILE=""
S3_SECRET_KEY_FILE=""
GCS_CREDENTIAL_FILE=""
AZURE_ENDPOINT=""
AZURE_CONTAINER_NAME=""
BUCKET_LOCALIZE_ACQUIRE_LOCK_TIMEOUT_SEC=""
BUCKET_LOCALIZE_CONNECT_TIMEOUT_MAX_RETRIES=""
BUCKET_LOCALIZE_MAX_TIMEOUT_SEC=""
CLEAN_REMOTE_STORAGE_BY_DEFAULT="false"
APPLY_CLUSTER_BUNDLE="false"
RESTART_SPLUNK="true"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Index Lifecycle / SmartStore Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --deployment cluster|standalone
  --scope per-index|global
  --phase render|preflight|apply|status|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --remote-provider s3|gcs|azure
  --volume-name NAME
  --remote-path URI
  --indexes CSV
  --max-global-data-size-mb N
  --max-global-raw-data-size-mb N
  --frozen-time-period-in-secs N
  --cache-size-mb N
  --eviction-policy NAME
  --eviction-padding-mb N
  --hotlist-recency-secs N
  --hotlist-bloom-filter-recency-hours N
  --index-hotlist-recency-secs N
  --index-hotlist-bloom-filter-recency-hours N
  --s3-endpoint URL
  --s3-auth-region REGION
  --s3-signature-version VERSION
  --s3-supports-versioning true|false|unset
  --s3-tsidx-compression true|false|unset
  --s3-encryption unset|none|sse-s3|sse-kms|sse-c
  --s3-kms-key-id ID_OR_ARN
  --s3-kms-auth-region REGION
  --s3-ssl-verify-server-cert true|false|unset
  --s3-ssl-versions CSV
  --s3-access-key-file PATH
  --s3-secret-key-file PATH
  --gcs-credential-file PATH
  --azure-endpoint URL
  --azure-container-name NAME
  --bucket-localize-acquire-lock-timeout-sec N
  --bucket-localize-connect-timeout-max-retries N
  --bucket-localize-max-timeout-sec N
  --clean-remote-storage-by-default true|false
  --apply-cluster-bundle true|false
  --restart-splunk true|false
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --deployment) require_arg "$1" $# || exit 1; DEPLOYMENT="$2"; shift 2 ;;
        --scope) require_arg "$1" $# || exit 1; SCOPE="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --remote-provider) require_arg "$1" $# || exit 1; REMOTE_PROVIDER="$2"; shift 2 ;;
        --volume-name) require_arg "$1" $# || exit 1; VOLUME_NAME="$2"; shift 2 ;;
        --remote-path) require_arg "$1" $# || exit 1; REMOTE_PATH="$2"; shift 2 ;;
        --indexes) require_arg "$1" $# || exit 1; INDEXES="$2"; shift 2 ;;
        --max-global-data-size-mb) require_arg "$1" $# || exit 1; MAX_GLOBAL_DATA_SIZE_MB="$2"; shift 2 ;;
        --max-global-raw-data-size-mb) require_arg "$1" $# || exit 1; MAX_GLOBAL_RAW_DATA_SIZE_MB="$2"; shift 2 ;;
        --frozen-time-period-in-secs) require_arg "$1" $# || exit 1; FROZEN_TIME_PERIOD_IN_SECS="$2"; shift 2 ;;
        --cache-size-mb) require_arg "$1" $# || exit 1; CACHE_SIZE_MB="$2"; shift 2 ;;
        --eviction-policy) require_arg "$1" $# || exit 1; EVICTION_POLICY="$2"; shift 2 ;;
        --eviction-padding-mb) require_arg "$1" $# || exit 1; EVICTION_PADDING_MB="$2"; shift 2 ;;
        --hotlist-recency-secs) require_arg "$1" $# || exit 1; HOTLIST_RECENCY_SECS="$2"; shift 2 ;;
        --hotlist-bloom-filter-recency-hours) require_arg "$1" $# || exit 1; HOTLIST_BLOOM_FILTER_RECENCY_HOURS="$2"; shift 2 ;;
        --index-hotlist-recency-secs) require_arg "$1" $# || exit 1; INDEX_HOTLIST_RECENCY_SECS="$2"; shift 2 ;;
        --index-hotlist-bloom-filter-recency-hours) require_arg "$1" $# || exit 1; INDEX_HOTLIST_BLOOM_FILTER_RECENCY_HOURS="$2"; shift 2 ;;
        --s3-endpoint) require_arg "$1" $# || exit 1; S3_ENDPOINT="$2"; shift 2 ;;
        --s3-auth-region) require_arg "$1" $# || exit 1; S3_AUTH_REGION="$2"; shift 2 ;;
        --s3-signature-version) require_arg "$1" $# || exit 1; S3_SIGNATURE_VERSION="$2"; shift 2 ;;
        --s3-supports-versioning) require_arg "$1" $# || exit 1; S3_SUPPORTS_VERSIONING="$2"; shift 2 ;;
        --s3-tsidx-compression) require_arg "$1" $# || exit 1; S3_TSIDX_COMPRESSION="$2"; shift 2 ;;
        --s3-encryption) require_arg "$1" $# || exit 1; S3_ENCRYPTION="$2"; shift 2 ;;
        --s3-kms-key-id) require_arg "$1" $# || exit 1; S3_KMS_KEY_ID="$2"; shift 2 ;;
        --s3-kms-auth-region) require_arg "$1" $# || exit 1; S3_KMS_AUTH_REGION="$2"; shift 2 ;;
        --s3-ssl-verify-server-cert) require_arg "$1" $# || exit 1; S3_SSL_VERIFY_SERVER_CERT="$2"; shift 2 ;;
        --s3-ssl-versions) require_arg "$1" $# || exit 1; S3_SSL_VERSIONS="$2"; shift 2 ;;
        --s3-access-key-file) require_arg "$1" $# || exit 1; S3_ACCESS_KEY_FILE="$2"; shift 2 ;;
        --s3-secret-key-file) require_arg "$1" $# || exit 1; S3_SECRET_KEY_FILE="$2"; shift 2 ;;
        --gcs-credential-file) require_arg "$1" $# || exit 1; GCS_CREDENTIAL_FILE="$2"; shift 2 ;;
        --azure-endpoint) require_arg "$1" $# || exit 1; AZURE_ENDPOINT="$2"; shift 2 ;;
        --azure-container-name) require_arg "$1" $# || exit 1; AZURE_CONTAINER_NAME="$2"; shift 2 ;;
        --bucket-localize-acquire-lock-timeout-sec) require_arg "$1" $# || exit 1; BUCKET_LOCALIZE_ACQUIRE_LOCK_TIMEOUT_SEC="$2"; shift 2 ;;
        --bucket-localize-connect-timeout-max-retries) require_arg "$1" $# || exit 1; BUCKET_LOCALIZE_CONNECT_TIMEOUT_MAX_RETRIES="$2"; shift 2 ;;
        --bucket-localize-max-timeout-sec) require_arg "$1" $# || exit 1; BUCKET_LOCALIZE_MAX_TIMEOUT_SEC="$2"; shift 2 ;;
        --clean-remote-storage-by-default) require_arg "$1" $# || exit 1; CLEAN_REMOTE_STORAGE_BY_DEFAULT="$2"; shift 2 ;;
        --apply-cluster-bundle) require_arg "$1" $# || exit 1; APPLY_CLUSTER_BUNDLE="$2"; shift 2 ;;
        --restart-splunk) require_arg "$1" $# || exit 1; RESTART_SPLUNK="$2"; shift 2 ;;
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
    validate_choice "${DEPLOYMENT}" cluster standalone
    validate_choice "${SCOPE}" per-index global
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${REMOTE_PROVIDER}" s3 gcs azure
    validate_choice "${S3_SUPPORTS_VERSIONING}" true false unset
    validate_choice "${S3_TSIDX_COMPRESSION}" true false unset
    validate_choice "${S3_ENCRYPTION}" unset none sse-s3 sse-kms sse-c
    validate_choice "${S3_SSL_VERIFY_SERVER_CERT}" true false unset
    validate_choice "${CLEAN_REMOTE_STORAGE_BY_DEFAULT}" true false
    validate_choice "${APPLY_CLUSTER_BUNDLE}" true false
    validate_choice "${RESTART_SPLUNK}" true false
    if [[ -z "${REMOTE_PATH}" ]]; then
        log "ERROR: --remote-path is required."
        exit 1
    fi
    if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" && ( "${PHASE}" != "render" || "${APPLY}" == "true" ) ]]; then
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
        --deployment "${DEPLOYMENT}"
        --scope "${SCOPE}"
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --remote-provider "${REMOTE_PROVIDER}"
        --volume-name "${VOLUME_NAME}"
        --remote-path "${REMOTE_PATH}"
        --indexes "${INDEXES}"
        --max-global-data-size-mb "${MAX_GLOBAL_DATA_SIZE_MB}"
        --max-global-raw-data-size-mb "${MAX_GLOBAL_RAW_DATA_SIZE_MB}"
        --frozen-time-period-in-secs "${FROZEN_TIME_PERIOD_IN_SECS}"
        --cache-size-mb "${CACHE_SIZE_MB}"
        --eviction-policy "${EVICTION_POLICY}"
        --eviction-padding-mb "${EVICTION_PADDING_MB}"
        --hotlist-recency-secs "${HOTLIST_RECENCY_SECS}"
        --hotlist-bloom-filter-recency-hours "${HOTLIST_BLOOM_FILTER_RECENCY_HOURS}"
        --index-hotlist-recency-secs "${INDEX_HOTLIST_RECENCY_SECS}"
        --index-hotlist-bloom-filter-recency-hours "${INDEX_HOTLIST_BLOOM_FILTER_RECENCY_HOURS}"
        --s3-endpoint "${S3_ENDPOINT}"
        --s3-auth-region "${S3_AUTH_REGION}"
        --s3-signature-version "${S3_SIGNATURE_VERSION}"
        --s3-supports-versioning "${S3_SUPPORTS_VERSIONING}"
        --s3-tsidx-compression "${S3_TSIDX_COMPRESSION}"
        --s3-encryption "${S3_ENCRYPTION}"
        --s3-kms-key-id "${S3_KMS_KEY_ID}"
        --s3-kms-auth-region "${S3_KMS_AUTH_REGION}"
        --s3-ssl-verify-server-cert "${S3_SSL_VERIFY_SERVER_CERT}"
        --s3-ssl-versions "${S3_SSL_VERSIONS}"
        --s3-access-key-file "${S3_ACCESS_KEY_FILE}"
        --s3-secret-key-file "${S3_SECRET_KEY_FILE}"
        --gcs-credential-file "${GCS_CREDENTIAL_FILE}"
        --azure-endpoint "${AZURE_ENDPOINT}"
        --azure-container-name "${AZURE_CONTAINER_NAME}"
        --bucket-localize-acquire-lock-timeout-sec "${BUCKET_LOCALIZE_ACQUIRE_LOCK_TIMEOUT_SEC}"
        --bucket-localize-connect-timeout-max-retries "${BUCKET_LOCALIZE_CONNECT_TIMEOUT_MAX_RETRIES}"
        --bucket-localize-max-timeout-sec "${BUCKET_LOCALIZE_MAX_TIMEOUT_SEC}"
        --clean-remote-storage-by-default "${CLEAN_REMOTE_STORAGE_BY_DEFAULT}"
        --apply-cluster-bundle "${APPLY_CLUSTER_BUNDLE}"
        --restart-splunk "${RESTART_SPLUNK}"
    )
}

render_dir() {
    printf '%s/smartstore' "${OUTPUT_DIR}"
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

apply_script() {
    if [[ "${DEPLOYMENT}" == "cluster" ]]; then
        printf '%s' "apply-cluster-manager.sh"
    else
        printf '%s' "apply-standalone-indexer.sh"
    fi
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
        render)
            render_assets
            if [[ "${APPLY}" == "true" ]]; then
                run_rendered_script "$(apply_script)"
            fi
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; run_rendered_script "$(apply_script)" ;;
        status) run_rendered_script status.sh ;;
        all) render_assets; run_rendered_script preflight.sh; run_rendered_script "$(apply_script)"; run_rendered_script status.sh ;;
    esac
}

main "$@"
