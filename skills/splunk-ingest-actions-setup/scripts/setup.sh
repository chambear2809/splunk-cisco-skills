#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-ingest-actions-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
APP_NAME="ZZZ_cisco_skills_ingest_actions"
RULESET_SOURCETYPE=""
RULESET_NAME=""
RULE_TYPE=""
EVAL_EXPRESSION=""
MASK_REGEX=""
MASK_REPLACEMENT="########"
DROP_REGEX=""
S3_DESTINATION_NAME=""
S3_PATH=""
S3_AUTH_REGION=""
S3_ENCRYPTION="unset"
S3_KMS_KEY_ID=""
S3_ACCESS_KEY_FILE=""
S3_SECRET_KEY_FILE=""
ACCEPT_IRREVERSIBLE_INGEST=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Ingest Actions Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply | --dry-run | --json
  --output-dir PATH
  --app-name NAME
  --ruleset-sourcetype ST          (required)
  --ruleset-name NAME              (required)
  --rule-type eval|mask|drop|route-s3  (required)
  --eval-expression EXPR           (INGEST_EVAL for rule-type eval)
  --mask-regex REGEX               (rule-type mask)
  --mask-replacement TEXT
  --drop-regex REGEX               (rule-type drop)
  --s3-destination-name NAME       (rule-type route-s3)
  --s3-path s3://bucket/path
  --s3-auth-region REGION
  --s3-encryption unset|none|sse-s3|sse-kms
  --s3-kms-key-id ID
  --s3-access-key-file PATH
  --s3-secret-key-file PATH
  --accept-irreversible-ingest     (required to apply; transforms are pre-index)
  --help

Examples:
  $(basename "$0") --ruleset-sourcetype cisco:asa --ruleset-name drop_debug --rule-type drop --drop-regex 'level=DEBUG'
  $(basename "$0") --phase apply --ruleset-sourcetype cisco:asa --ruleset-name drop_debug \\
    --rule-type drop --drop-regex 'level=DEBUG' --accept-irreversible-ingest

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --ruleset-sourcetype) require_arg "$1" $# || exit 1; RULESET_SOURCETYPE="$2"; shift 2 ;;
        --ruleset-name) require_arg "$1" $# || exit 1; RULESET_NAME="$2"; shift 2 ;;
        --rule-type) require_arg "$1" $# || exit 1; RULE_TYPE="$2"; shift 2 ;;
        --eval-expression) require_arg "$1" $# || exit 1; EVAL_EXPRESSION="$2"; shift 2 ;;
        --mask-regex) require_arg "$1" $# || exit 1; MASK_REGEX="$2"; shift 2 ;;
        --mask-replacement) require_arg "$1" $# || exit 1; MASK_REPLACEMENT="$2"; shift 2 ;;
        --drop-regex) require_arg "$1" $# || exit 1; DROP_REGEX="$2"; shift 2 ;;
        --s3-destination-name) require_arg "$1" $# || exit 1; S3_DESTINATION_NAME="$2"; shift 2 ;;
        --s3-path) require_arg "$1" $# || exit 1; S3_PATH="$2"; shift 2 ;;
        --s3-auth-region) require_arg "$1" $# || exit 1; S3_AUTH_REGION="$2"; shift 2 ;;
        --s3-encryption) require_arg "$1" $# || exit 1; S3_ENCRYPTION="$2"; shift 2 ;;
        --s3-kms-key-id) require_arg "$1" $# || exit 1; S3_KMS_KEY_ID="$2"; shift 2 ;;
        --s3-access-key-file) require_arg "$1" $# || exit 1; S3_ACCESS_KEY_FILE="$2"; shift 2 ;;
        --s3-secret-key-file) require_arg "$1" $# || exit 1; S3_SECRET_KEY_FILE="$2"; shift 2 ;;
        --accept-irreversible-ingest) ACCEPT_IRREVERSIBLE_INGEST=true; shift ;;
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
    validate_choice "${PHASE}" render preflight apply status all
    [[ -n "${RULESET_SOURCETYPE}" ]] || { log "ERROR: --ruleset-sourcetype is required."; exit 1; }
    [[ -n "${RULESET_NAME}" ]] || { log "ERROR: --ruleset-name is required."; exit 1; }
    [[ -n "${RULE_TYPE}" ]] || { log "ERROR: --rule-type is required."; exit 1; }
    validate_choice "${RULE_TYPE}" eval mask drop route-s3
    validate_choice "${S3_ENCRYPTION}" unset none sse-s3 sse-kms
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
        --output-dir "${OUTPUT_DIR}"
        --app-name "${APP_NAME}"
        --ruleset-sourcetype "${RULESET_SOURCETYPE}"
        --ruleset-name "${RULESET_NAME}"
        --rule-type "${RULE_TYPE}"
        --eval-expression "${EVAL_EXPRESSION}"
        --mask-regex "${MASK_REGEX}"
        --mask-replacement "${MASK_REPLACEMENT}"
        --drop-regex "${DROP_REGEX}"
        --s3-destination-name "${S3_DESTINATION_NAME}"
        --s3-path "${S3_PATH}"
        --s3-auth-region "${S3_AUTH_REGION}"
        --s3-encryption "${S3_ENCRYPTION}"
        --s3-kms-key-id "${S3_KMS_KEY_ID}"
        --s3-access-key-file "${S3_ACCESS_KEY_FILE}"
        --s3-secret-key-file "${S3_SECRET_KEY_FILE}"
    )
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

transform_stanza() {
    printf '%s_%s' "${RULESET_NAME}" "${RULE_TYPE//-/_}"
}

# Escape a value for embedding inside a double-quoted SPL string literal.
spl_escape() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    printf '%s' "${value}"
}

apply_live() {
    if [[ "${ACCEPT_IRREVERSIBLE_INGEST}" != "true" ]]; then
        log "ERROR: Ingest Actions transform data before indexing and cannot be reverted."
        log "       Re-run with --accept-irreversible-ingest to apply."
        exit 1
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would write RULESET-${RULESET_NAME} (props), transform $(transform_stanza), and any [rfs:${S3_DESTINATION_NAME}] destination via REST to app ${APP_NAME}."
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

    if [[ -n "${S3_DESTINATION_NAME}" ]]; then
        local rfs_body
        rfs_body=$(form_urlencode_pairs path "${S3_PATH}")
        [[ -n "${S3_AUTH_REGION}" ]] && rfs_body="${rfs_body}&$(form_urlencode_pairs remote.s3.auth_region "${S3_AUTH_REGION}")"
        [[ "${S3_ENCRYPTION}" != "unset" ]] && rfs_body="${rfs_body}&$(form_urlencode_pairs remote.s3.encryption "${S3_ENCRYPTION}")"
        [[ -n "${S3_KMS_KEY_ID}" ]] && rfs_body="${rfs_body}&$(form_urlencode_pairs remote.s3.kms.key_id "${S3_KMS_KEY_ID}")"
        if [[ -n "${S3_ACCESS_KEY_FILE}" ]]; then
            local access_key secret_key
            access_key=$(read_secret_file "${S3_ACCESS_KEY_FILE}") || exit 1
            secret_key=$(read_secret_file "${S3_SECRET_KEY_FILE}") || exit 1
            rfs_body="${rfs_body}&$(form_urlencode_pairs remote.s3.access_key "${access_key}" remote.s3.secret_key "${secret_key}")"
        fi
        if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "outputs" "rfs:${S3_DESTINATION_NAME}" "${rfs_body}"; then
            log "ERROR: Failed to write RFS destination rfs:${S3_DESTINATION_NAME}."
            exit 1
        fi
        log "RFS S3 destination rfs:${S3_DESTINATION_NAME} written."
    fi

    if [[ "${RULE_TYPE}" == "route-s3" ]]; then
        log "RFS S3 destination is configured. Create the 'Route to Destination' rule for"
        log "source type ${RULESET_SOURCETYPE} in Splunk Web (Settings > Data > Ingest Actions)"
        log "or via /services/data/ingest/rulesets, selecting destination ${S3_DESTINATION_NAME}."
        log "$(log_platform_restart_guidance "Ingest Actions destination changes")"
        return 0
    fi

    local stanza tbody
    stanza="$(transform_stanza)"
    case "${RULE_TYPE}" in
        eval) tbody=$(form_urlencode_pairs INGEST_EVAL "${EVAL_EXPRESSION}") ;;
        mask) tbody=$(form_urlencode_pairs INGEST_EVAL "_raw=replace(_raw, \"$(spl_escape "${MASK_REGEX}")\", \"$(spl_escape "${MASK_REPLACEMENT}")\")") ;;
        drop) tbody=$(form_urlencode_pairs INGEST_EVAL "queue=if(match(_raw, \"$(spl_escape "${DROP_REGEX}")\"), \"nullQueue\", queue)") ;;
    esac
    if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "transforms" "${stanza}" "${tbody}"; then
        log "ERROR: Failed to write transform ${stanza}."
        exit 1
    fi
    local pbody
    pbody=$(form_urlencode_pairs "RULESET-${RULESET_NAME}" "${stanza}")
    if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "props" "${RULESET_SOURCETYPE}" "${pbody}"; then
        log "ERROR: Failed to bind RULESET-${RULESET_NAME} on ${RULESET_SOURCETYPE}."
        exit 1
    fi
    log "Ingest Actions ruleset ${RULESET_NAME} applied to source type ${RULESET_SOURCETYPE}."
    log "$(log_platform_restart_guidance "Ingest Actions ruleset changes")"
}

run_status() {
    local dir="${OUTPUT_DIR}/ingest-actions"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./status-rulesets.sh)"
        return 0
    fi
    (cd "${dir}" && ./status-rulesets.sh)
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        else
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
            [[ "${PHASE}" == "apply" || "${PHASE}" == "all" ]] && apply_live
        fi
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            [[ "${APPLY}" == "true" ]] && apply_live
            ;;
        preflight) render_assets ;;
        apply) render_assets; apply_live ;;
        status) render_assets; run_status ;;
        all) render_assets; apply_live; run_status ;;
    esac
}

main "$@"
