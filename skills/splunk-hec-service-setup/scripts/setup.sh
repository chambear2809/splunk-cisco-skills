#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-hec-service-rendered"

PLATFORM="enterprise"
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
APP_NAME="splunk_httpinput"
TOKEN_NAME="cisco_skills_hec"
DESCRIPTION="Managed by splunk-hec-service-setup"
DEFAULT_INDEX="main"
ALLOWED_INDEXES="main"
SOURCE=""
SOURCETYPE=""
PORT="8088"
ENABLE_SSL="true"
GLOBAL_DISABLED="false"
TOKEN_DISABLED="false"
USE_ACK="false"
S2S_INDEXES_VALIDATION="disabled_for_internal"
TOKEN_FILE=""
WRITE_TOKEN_FILE=""
RESTART_SPLUNK="true"
HEC_BUNDLE_KIND=""
CLOUD_STACK=""
CLOUD_SEARCH_HEAD=""
CLOUD_ACS_SERVER=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk HEC Service Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --platform enterprise|cloud
  --phase render|preflight|apply|status|all
  --apply
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --app-name NAME
  --token-name NAME
  --description TEXT
  --default-index NAME
  --allowed-indexes CSV
  --source VALUE
  --sourcetype VALUE
  --port PORT
  --enable-ssl true|false
  --global-disabled true|false
  --token-disabled true|false
  --use-ack true|false
  --s2s-indexes-validation disabled|disabled_for_internal|enabled_for_all
  --token-file PATH
  --write-token-file PATH
  --restart-splunk true|false
  --stack STACK
  --search-head SEARCH_HEAD
  --acs-server https://admin.splunk.com|https://staging.admin.splunk.com
  --help

Examples:
  $(basename "$0") --platform enterprise --token-name app_hec --default-index app --allowed-indexes app
  $(basename "$0") --platform enterprise --phase apply --token-file /tmp/app_hec_token
  $(basename "$0") --platform cloud --stack my-stack --phase apply --write-token-file /tmp/app_hec_token

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --platform) require_arg "$1" $# || exit 1; PLATFORM="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --token-name) require_arg "$1" $# || exit 1; TOKEN_NAME="$2"; shift 2 ;;
        --description) require_arg "$1" $# || exit 1; DESCRIPTION="$2"; shift 2 ;;
        --default-index) require_arg "$1" $# || exit 1; DEFAULT_INDEX="$2"; shift 2 ;;
        --allowed-indexes) require_arg "$1" $# || exit 1; ALLOWED_INDEXES="$2"; shift 2 ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --sourcetype) require_arg "$1" $# || exit 1; SOURCETYPE="$2"; shift 2 ;;
        --port) require_arg "$1" $# || exit 1; PORT="$2"; shift 2 ;;
        --enable-ssl) require_arg "$1" $# || exit 1; ENABLE_SSL="$2"; shift 2 ;;
        --global-disabled) require_arg "$1" $# || exit 1; GLOBAL_DISABLED="$2"; shift 2 ;;
        --token-disabled) require_arg "$1" $# || exit 1; TOKEN_DISABLED="$2"; shift 2 ;;
        --use-ack) require_arg "$1" $# || exit 1; USE_ACK="$2"; shift 2 ;;
        --s2s-indexes-validation) require_arg "$1" $# || exit 1; S2S_INDEXES_VALIDATION="$2"; shift 2 ;;
        --token-file) require_arg "$1" $# || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --write-token-file) require_arg "$1" $# || exit 1; WRITE_TOKEN_FILE="$2"; shift 2 ;;
        --restart-splunk) require_arg "$1" $# || exit 1; RESTART_SPLUNK="$2"; shift 2 ;;
        --stack) require_arg "$1" $# || exit 1; CLOUD_STACK="$2"; shift 2 ;;
        --search-head) require_arg "$1" $# || exit 1; CLOUD_SEARCH_HEAD="$2"; shift 2 ;;
        --acs-server) require_arg "$1" $# || exit 1; CLOUD_ACS_SERVER="$2"; shift 2 ;;
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
    validate_choice "${PLATFORM}" enterprise cloud
    validate_choice "${PHASE}" render preflight apply status all
    validate_choice "${ENABLE_SSL}" true false
    validate_choice "${GLOBAL_DISABLED}" true false
    validate_choice "${TOKEN_DISABLED}" true false
    validate_choice "${USE_ACK}" true false
    validate_choice "${S2S_INDEXES_VALIDATION}" disabled disabled_for_internal enabled_for_all
    validate_choice "${RESTART_SPLUNK}" true false
    if [[ "${APPLY}" == "true" && "${PHASE}" != "render" && "${PHASE}" != "apply" && "${PHASE}" != "all" ]]; then
        log "ERROR: --apply is valid only with --phase render, apply, or all."
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
    if [[ -n "${CLOUD_ACS_SERVER}" ]]; then
        validate_choice "${CLOUD_ACS_SERVER}" https://admin.splunk.com https://staging.admin.splunk.com
    fi
    if [[ "${PLATFORM}" != "cloud" \
        && ( -n "${CLOUD_STACK}" || -n "${CLOUD_SEARCH_HEAD}" || -n "${CLOUD_ACS_SERVER}" ) ]]; then
        log "ERROR: --stack, --search-head, and --acs-server are valid only with --platform cloud."
        exit 1
    fi
}

resolve_cloud_target() {
    [[ "${PLATFORM}" == "cloud" ]] || return 0

    if [[ -n "${CLOUD_STACK}" ]]; then
        SPLUNK_CLOUD_STACK="${CLOUD_STACK}"
        export SPLUNK_CLOUD_STACK
    fi
    if [[ -n "${CLOUD_SEARCH_HEAD}" ]]; then
        SPLUNK_CLOUD_SEARCH_HEAD="${CLOUD_SEARCH_HEAD}"
        export SPLUNK_CLOUD_SEARCH_HEAD
    fi
    if [[ -n "${CLOUD_ACS_SERVER}" ]]; then
        ACS_SERVER="${CLOUD_ACS_SERVER}"
        export ACS_SERVER
    fi
    SPLUNK_PLATFORM="cloud"
    export SPLUNK_PLATFORM
    if ! load_splunk_platform_settings; then
        log "ERROR: Could not resolve the selected Splunk Cloud target."
        exit 1
    fi
    CLOUD_STACK="${SPLUNK_CLOUD_STACK:-}"
    CLOUD_SEARCH_HEAD="${SPLUNK_CLOUD_SEARCH_HEAD:-}"
    CLOUD_ACS_SERVER="${ACS_SERVER:-}"
    if [[ ! "${CLOUD_STACK}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        log "ERROR: A valid --stack or configured SPLUNK_CLOUD_STACK is required for Splunk Cloud rendering."
        exit 1
    fi
    if [[ -n "${CLOUD_SEARCH_HEAD}" \
        && ! "${CLOUD_SEARCH_HEAD}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
        log "ERROR: The resolved Splunk Cloud search-head identity is invalid."
        exit 1
    fi
    case "${CLOUD_ACS_SERVER}" in
        https://admin.splunk.com|https://staging.admin.splunk.com) ;;
        *)
            log "ERROR: The resolved ACS control-plane origin is not allowlisted."
            exit 1
            ;;
    esac
    ACS_SERVER="${CLOUD_ACS_SERVER}"
    export ACS_SERVER
}

build_renderer_args() {
    RENDER_ARGS=(
        --platform "${PLATFORM}"
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --app-name "${APP_NAME}"
        --token-name "${TOKEN_NAME}"
        --description "${DESCRIPTION}"
        --default-index "${DEFAULT_INDEX}"
        --allowed-indexes "${ALLOWED_INDEXES}"
        --source "${SOURCE}"
        --sourcetype "${SOURCETYPE}"
        --port "${PORT}"
        --enable-ssl "${ENABLE_SSL}"
        --global-disabled "${GLOBAL_DISABLED}"
        --token-disabled "${TOKEN_DISABLED}"
        --use-ack "${USE_ACK}"
        --s2s-indexes-validation "${S2S_INDEXES_VALIDATION}"
        --token-file "${TOKEN_FILE}"
        --write-token-file "${WRITE_TOKEN_FILE}"
        --restart-splunk "${RESTART_SPLUNK}"
        --stack "${CLOUD_STACK}"
        --search-head "${CLOUD_SEARCH_HEAD}"
        --acs-server "${CLOUD_ACS_SERVER}"
    )
}

render_dir() {
    printf '%s/hec-service' "${OUTPUT_DIR}"
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
    if [[ "${PLATFORM}" == "enterprise" ]]; then
        printf '%s' "apply-enterprise-files.sh"
    else
        printf '%s' "apply-cloud-acs.sh"
    fi
}

status_script() {
    if [[ "${PLATFORM}" == "enterprise" ]]; then
        printf '%s' "status-enterprise.sh"
    else
        printf '%s' "status-cloud-acs.sh"
    fi
}

verify_rendered_cloud_status_binding() {
    local metadata_file
    [[ "${PLATFORM}" == "cloud" ]] || return 0
    metadata_file="$(render_dir)/metadata.json"
    if ! python3 - "${metadata_file}" "${CLOUD_STACK}" "${CLOUD_SEARCH_HEAD}" "${CLOUD_ACS_SERVER}" "${TOKEN_NAME}" <<'PY'
import json
import os
import stat
import sys

metadata_path = sys.argv[1]
expected = {
    "platform": "cloud",
    "cloud_stack": sys.argv[2],
    "cloud_search_head": sys.argv[3],
    "acs_server": sys.argv[4],
    "token_name": sys.argv[5],
}
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
descriptor = -1
try:
    descriptor = os.open(metadata_path, flags)
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size < 1
        or before.st_size > 65536
    ):
        raise ValueError("metadata is not a bounded regular file")
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        descriptor = -1
        metadata = json.load(handle)
        after = os.fstat(handle.fileno())
except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
    raise SystemExit(1)
finally:
    if descriptor >= 0:
        os.close(descriptor)
before_fingerprint = (
    before.st_dev,
    before.st_ino,
    before.st_mode,
    before.st_uid,
    before.st_size,
    before.st_mtime_ns,
    before.st_ctime_ns,
    before.st_nlink,
)
after_fingerprint = (
    after.st_dev,
    after.st_ino,
    after.st_mode,
    after.st_uid,
    after.st_size,
    after.st_mtime_ns,
    after.st_ctime_ns,
    after.st_nlink,
)
if before_fingerprint != after_fingerprint:
    raise SystemExit(1)
if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in expected.items()):
    raise SystemExit(1)
PY
    then
        log "ERROR: Existing rendered Cloud HEC status assets do not match the requested ACS origin, stack, search head, or token."
        log "HANDOFF: Re-render the reviewed assets for this exact Cloud target before running status."
        exit 1
    fi
}

guard_enterprise_direct_apply() {
    case "${HEC_BUNDLE_KIND}" in
        idxc|shc)
            log "ERROR: Direct Enterprise HEC apply is not supported for ${HEC_BUNDLE_KIND} bundle targets."
            log "HANDOFF: Materialize $(render_dir)/inputs.conf.template with the secure token file in the cluster-manager/deployer bundle workflow, activate it topology-safely, then run status validation."
            return 1
            ;;
    esac
}

main() {
    local resolved_role="" bundle_kind="" bundle_status=0
    validate_args
    resolve_cloud_target
    if [[ "${PLATFORM}" == "enterprise" && "${DRY_RUN}" != "true" \
        && ( "${PHASE}" == "apply" || "${PHASE}" == "all" || "${APPLY}" == "true" ) ]]; then
        if ! load_splunk_connection_settings; then
            log "ERROR: Could not resolve the selected Splunk credential target."
            exit 1
        fi
        if ! resolved_role="$(resolve_splunk_target_role)"; then
            log "ERROR: Could not resolve the selected Splunk target role."
            exit 1
        fi
        SPLUNK_TARGET_ROLE="${resolved_role:-${SPLUNK_TARGET_ROLE:-standalone}}"
        export SPLUNK_TARGET_ROLE
        if deployment_should_use_bundle_for_current_target; then
            if ! bundle_kind="$(deployment_bundle_kind_for_current_target)" \
                || [[ -z "${bundle_kind}" ]]; then
                log "ERROR: Could not determine the bundle deployment path for the selected Splunk target."
                exit 1
            fi
            HEC_BUNDLE_KIND="${bundle_kind}"
        else
            bundle_status=$?
            if (( bundle_status == 2 )) \
                || [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
                log "ERROR: Could not resolve the configured Enterprise HEC deployment path; refusing direct apply."
                exit 1
            fi
        fi
    fi
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
                guard_enterprise_direct_apply
                run_rendered_script "$(apply_script)"
            fi
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; guard_enterprise_direct_apply; run_rendered_script "$(apply_script)" ;;
        status) verify_rendered_cloud_status_binding; run_rendered_script "$(status_script)" ;;
        all) render_assets; guard_enterprise_direct_apply; run_rendered_script preflight.sh; run_rendered_script "$(apply_script)"; run_rendered_script "$(status_script)" ;;
    esac
}

main "$@"
