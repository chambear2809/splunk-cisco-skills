#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-kvstore-admin-rendered"

PHASE="render"
OPERATION="none"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
SPLUNK_HOME_VALUE="/opt/splunk"
TOPOLOGY="standalone"
APP_NAME="ZZZ_cisco_skills_kvstore"
POINT_IN_TIME="true"
BACKUP_ARCHIVE_NAME=""
STORAGE_ENGINE="wiredTiger"
MIGRATE_DRY_RUN="true"
TARGET_KVSTORE_VERSION=""
DISABLE_STARTUP_UPGRADE="false"
COLLECTION_NAME=""
COLLECTION_FIELDS=""
COLLECTION_REPLICATE="false"
LOOKUP_DEFINITION_NAME=""
ACCEPT_KVSTORE_RESTORE=false
ACCEPT_KVSTORE_CLEAN=false
ACCEPT_KVSTORE_MIGRATE=false
ACCEPT_KVSTORE_UPGRADE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk KV Store Admin Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --operation none|backup|restore|clean|migrate|upgrade|collections
  --apply
  --dry-run
  --json
  --output-dir PATH
  --splunk-home PATH
  --topology standalone|shc
  --app-name NAME
  --point-in-time true|false
  --backup-archive-name NAME        (required for restore; include .tar.gz)
  --storage-engine wiredTiger|mmapv1
  --migrate-dry-run true|false
  --target-kvstore-version VERSION  (required for SHC upgrade, e.g. 7.0)
  --disable-startup-upgrade true|false
  --collection-name NAME
  --collection-fields name:type,... (type: number|string|bool|time|cidr)
  --collection-replicate true|false
  --lookup-definition-name NAME
  --accept-kvstore-restore          (required to run restore)
  --accept-kvstore-clean            (required to run clean)
  --accept-kvstore-migrate          (required when --migrate-dry-run false)
  --accept-kvstore-upgrade          (required to run upgrade)
  --help

Examples:
  $(basename "$0") --operation backup --point-in-time true
  $(basename "$0") --phase apply --operation backup
  $(basename "$0") --phase apply --operation restore --backup-archive-name kvdump_2026.tar.gz --accept-kvstore-restore
  $(basename "$0") --phase apply --operation collections --collection-name asset_inventory --collection-fields ip:string,risk:number

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --operation) require_arg "$1" $# || exit 1; OPERATION="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --topology) require_arg "$1" $# || exit 1; TOPOLOGY="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; APP_NAME="$2"; shift 2 ;;
        --point-in-time) require_arg "$1" $# || exit 1; POINT_IN_TIME="$2"; shift 2 ;;
        --backup-archive-name) require_arg "$1" $# || exit 1; BACKUP_ARCHIVE_NAME="$2"; shift 2 ;;
        --storage-engine) require_arg "$1" $# || exit 1; STORAGE_ENGINE="$2"; shift 2 ;;
        --migrate-dry-run) require_arg "$1" $# || exit 1; MIGRATE_DRY_RUN="$2"; shift 2 ;;
        --target-kvstore-version) require_arg "$1" $# || exit 1; TARGET_KVSTORE_VERSION="$2"; shift 2 ;;
        --disable-startup-upgrade) require_arg "$1" $# || exit 1; DISABLE_STARTUP_UPGRADE="$2"; shift 2 ;;
        --collection-name) require_arg "$1" $# || exit 1; COLLECTION_NAME="$2"; shift 2 ;;
        --collection-fields) require_arg "$1" $# || exit 1; COLLECTION_FIELDS="$2"; shift 2 ;;
        --collection-replicate) require_arg "$1" $# || exit 1; COLLECTION_REPLICATE="$2"; shift 2 ;;
        --lookup-definition-name) require_arg "$1" $# || exit 1; LOOKUP_DEFINITION_NAME="$2"; shift 2 ;;
        --accept-kvstore-restore) ACCEPT_KVSTORE_RESTORE=true; shift ;;
        --accept-kvstore-clean) ACCEPT_KVSTORE_CLEAN=true; shift ;;
        --accept-kvstore-migrate) ACCEPT_KVSTORE_MIGRATE=true; shift ;;
        --accept-kvstore-upgrade) ACCEPT_KVSTORE_UPGRADE=true; shift ;;
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
    validate_choice "${OPERATION}" none backup restore clean migrate upgrade collections
    validate_choice "${TOPOLOGY}" standalone shc
    validate_choice "${POINT_IN_TIME}" true false
    validate_choice "${STORAGE_ENGINE}" wiredTiger mmapv1
    validate_choice "${MIGRATE_DRY_RUN}" true false
    validate_choice "${DISABLE_STARTUP_UPGRADE}" true false
    validate_choice "${COLLECTION_REPLICATE}" true false
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
}

build_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --topology "${TOPOLOGY}"
        --app-name "${APP_NAME}"
        --point-in-time "${POINT_IN_TIME}"
        --backup-archive-name "${BACKUP_ARCHIVE_NAME}"
        --storage-engine "${STORAGE_ENGINE}"
        --migrate-dry-run "${MIGRATE_DRY_RUN}"
        --target-kvstore-version "${TARGET_KVSTORE_VERSION}"
        --disable-startup-upgrade "${DISABLE_STARTUP_UPGRADE}"
        --collection-name "${COLLECTION_NAME}"
        --collection-fields "${COLLECTION_FIELDS}"
        --collection-replicate "${COLLECTION_REPLICATE}"
        --lookup-definition-name "${LOOKUP_DEFINITION_NAME}"
    )
}

render_dir() {
    printf '%s/kvstore' "${OUTPUT_DIR}"
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
    (cd "${dir}" && \
        KVSTORE_ACCEPT_RESTORE="${ACCEPT_KVSTORE_RESTORE}" \
        KVSTORE_ACCEPT_CLEAN="${ACCEPT_KVSTORE_CLEAN}" \
        KVSTORE_ACCEPT_MIGRATION="${ACCEPT_KVSTORE_MIGRATE}" \
        KVSTORE_ACCEPT_UPGRADE="${ACCEPT_KVSTORE_UPGRADE}" \
        "./${script_name}")
}

apply_collections_via_rest() {
    if [[ -z "${COLLECTION_NAME}" ]]; then
        log "ERROR: --operation collections requires --collection-name."
        exit 1
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would write collections.conf/[${COLLECTION_NAME}] and transforms.conf via REST to app ${APP_NAME}."
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    local sk
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    local body entry name field_type pair
    local -a _collection_field_parts
    body=$(form_urlencode_pairs replicate "${COLLECTION_REPLICATE}")
    if [[ -n "${COLLECTION_FIELDS}" ]]; then
        IFS=',' read -ra _collection_field_parts <<<"${COLLECTION_FIELDS}"
        for entry in "${_collection_field_parts[@]}"; do
            name="${entry%%:*}"
            field_type="${entry#*:}"
            name="$(printf '%s' "${name}" | tr -d '[:space:]')"
            field_type="$(printf '%s' "${field_type}" | tr -d '[:space:]')"
            pair="$(form_urlencode_pairs "field.${name}" "${field_type}")" || exit 1
            body="${body}&${pair}"
        done
    fi
    if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "collections" "${COLLECTION_NAME}" "${body}"; then
        log "ERROR: Failed to write KV Store collection '${COLLECTION_NAME}'."
        exit 1
    fi
    log "KV Store collection '${COLLECTION_NAME}' written to app ${APP_NAME}."
    if [[ -n "${LOOKUP_DEFINITION_NAME}" ]]; then
        local fields_list lookup_body
        fields_list="_key"
        if [[ -n "${COLLECTION_FIELDS}" ]]; then
            local entry name
            IFS=',' read -ra _field_parts <<<"${COLLECTION_FIELDS}"
            for entry in "${_field_parts[@]}"; do
                name="${entry%%:*}"
                name="$(echo "${name}" | tr -d '[:space:]')"
                [[ -n "${name}" ]] && fields_list="${fields_list}, ${name}"
            done
        fi
        lookup_body=$(form_urlencode_pairs external_type "kvstore" collection "${COLLECTION_NAME}" fields_list "${fields_list}")
        if ! rest_set_conf "${sk}" "${SPLUNK_URI}" "${APP_NAME}" "transforms" "${LOOKUP_DEFINITION_NAME}" "${lookup_body}"; then
            log "ERROR: Failed to write KV Store lookup definition '${LOOKUP_DEFINITION_NAME}'."
            exit 1
        fi
        log "KV Store lookup definition '${LOOKUP_DEFINITION_NAME}' written to app ${APP_NAME}."
    fi
    log "$(log_platform_restart_guidance "KV Store collection changes")"
}

operation_script() {
    case "${OPERATION}" in
        backup) printf '%s' "backup.sh" ;;
        restore) printf '%s' "restore.sh" ;;
        clean) printf '%s' "clean.sh" ;;
        migrate) printf '%s' "migrate.sh" ;;
        upgrade) printf '%s' "upgrade.sh" ;;
        *) printf '%s' "" ;;
    esac
}

apply_operation() {
    case "${OPERATION}" in
        none)
            log "ERROR: Apply requested without an operation."
            log "HANDOFF: Choose --operation backup|restore|clean|migrate|upgrade|collections, or use --phase render without --apply."
            return 1
            ;;
        collections)
            apply_collections_via_rest
            ;;
        restore)
            if [[ "${DRY_RUN}" != "true" && "${ACCEPT_KVSTORE_RESTORE}" != "true" ]]; then
                log "ERROR: restore is destructive. Re-run with --accept-kvstore-restore to proceed."
                exit 1
            fi
            run_rendered_script restore.sh
            ;;
        clean)
            if [[ "${DRY_RUN}" != "true" && "${ACCEPT_KVSTORE_CLEAN}" != "true" ]]; then
                log "ERROR: clean is destructive. Re-run with --accept-kvstore-clean to proceed."
                exit 1
            fi
            run_rendered_script clean.sh
            ;;
        migrate)
            if [[ "${TOPOLOGY}" == "standalone" ]]; then
                log "ERROR: Standalone KV Store ${OPERATION} is performed by the supported Splunk Enterprise binary-upgrade workflow, not by this apply path."
                log "HANDOFF: Take a point-in-time backup, complete the supported Splunk upgrade, then run --phase status to verify KV Store state."
                return 1
            fi
            if [[ "${DRY_RUN}" != "true" && "${MIGRATE_DRY_RUN}" == "false" && "${ACCEPT_KVSTORE_MIGRATE}" != "true" ]]; then
                log "ERROR: Live KV Store migration requires --accept-kvstore-migrate after a successful dry run and backup."
                return 1
            fi
            run_rendered_script migrate.sh
            if [[ "${MIGRATE_DRY_RUN}" == "true" ]]; then
                log "INFO: KV Store migration dry run completed; no storage-engine migration was applied."
            fi
            ;;
        upgrade)
            if [[ "${TOPOLOGY}" == "standalone" ]]; then
                log "ERROR: Standalone KV Store ${OPERATION} is performed by the supported Splunk Enterprise binary-upgrade workflow, not by this apply path."
                log "HANDOFF: Take a point-in-time backup, complete the supported Splunk upgrade, then run --phase status to verify KV Store state."
                return 1
            fi
            if [[ "${DRY_RUN}" != "true" && "${ACCEPT_KVSTORE_UPGRADE}" != "true" ]]; then
                log "ERROR: KV Store server-version upgrade requires --accept-kvstore-upgrade after a backup and topology review."
                return 1
            fi
            run_rendered_script upgrade.sh
            ;;
        *)
            run_rendered_script "$(operation_script)"
            ;;
    esac
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        else
            python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
            [[ "${PHASE}" == "apply" || "${PHASE}" == "all" || "${APPLY}" == "true" ]] && apply_operation
        fi
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            [[ "${APPLY}" == "true" ]] && apply_operation
            ;;
        preflight) render_assets; run_rendered_script preflight.sh ;;
        apply) render_assets; apply_operation ;;
        status) render_assets; run_rendered_script status.sh ;;
        all) render_assets; run_rendered_script preflight.sh; apply_operation; run_rendered_script status.sh ;;
    esac
}

main "$@"
