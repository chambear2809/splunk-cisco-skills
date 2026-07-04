#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
STATE_HELPER="${SCRIPT_DIR}/transaction_state.py"
DEFAULT_RENDER_DIR_NAME="splunk-dashboard-studio-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
APP_NAME="search"
DASHBOARD_NAME=""
TITLE=""
DESCRIPTION=""
THEME="light"
SEARCH=""
VIZ_TYPE="splunk.table"
DATASOURCE_NAME="Search_1"
LAYOUT="grid"
DEFINITION_FILE=""
OWNER="nobody"
SHARING="app"
READ_ROLES="*"
WRITE_ROLES=""
ACCEPT_OVERWRITE=false
STATE_DIR=""
TXN_DIR=""
EVENTS_FILE=""
PRE_VIEW_CODE="unknown"
PRE_ACL_CODE="unknown"
ROLLBACK_STATUS="not-required"
TRANSACTION_ACTIVE=false
TRANSACTION_SK=""
TRAP_RUNNING=false
MANUAL_CLEANUP_REQUIRED=false
MANUAL_CLEANUP_PATH=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Dashboard Studio Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --phase render|preflight|apply|status|all
  --apply | --dry-run | --json
  --output-dir PATH
  --app-name NAME
  --dashboard-name ID              (required; the view id)
  --title TEXT
  --description TEXT
  --theme light|dark
  --search SPL                     (primary ds.search query)
  --viz-type splunk.table|splunk.singlevalue|splunk.line|...
  --datasource-name NAME
  --layout grid|absolute|freeform
  --definition-file PATH           (full Dashboard Studio JSON instead of building)
  --owner USER
  --sharing user|app|global
  --read-roles CSV                 (default: *; exact expected role set)
  --write-roles CSV                (default: empty; exact expected role set)
  --accept-overwrite               (required to overwrite an existing dashboard)
  --help

Examples:
  $(basename "$0") --dashboard-name net_overview --title "Network Overview" \\
    --search 'index=netfw | stats count by action' --viz-type splunk.column
  $(basename "$0") --phase apply --dashboard-name net_overview --app-name search \\
    --search 'index=netfw | stats count' --accept-overwrite

Live phases:
  preflight  Authenticates, verifies app/view endpoint access, and privately
             snapshots the exact existing view and ACL without mutation.
  status     Queries the exact live view and ACL and exits nonzero on content,
             owner, sharing, or role-set drift.
  apply/all  Preflight, write content+ACL, and read back. Failed mutations are
             retained for reviewed recovery; no automatic restore/delete runs.

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
        --dashboard-name) require_arg "$1" $# || exit 1; DASHBOARD_NAME="$2"; shift 2 ;;
        --title) require_arg "$1" $# || exit 1; TITLE="$2"; shift 2 ;;
        --description) require_arg "$1" $# || exit 1; DESCRIPTION="$2"; shift 2 ;;
        --theme) require_arg "$1" $# || exit 1; THEME="$2"; shift 2 ;;
        --search) require_arg "$1" $# || exit 1; SEARCH="$2"; shift 2 ;;
        --viz-type) require_arg "$1" $# || exit 1; VIZ_TYPE="$2"; shift 2 ;;
        --datasource-name) require_arg "$1" $# || exit 1; DATASOURCE_NAME="$2"; shift 2 ;;
        --layout) require_arg "$1" $# || exit 1; LAYOUT="$2"; shift 2 ;;
        --definition-file) require_arg "$1" $# || exit 1; DEFINITION_FILE="$2"; shift 2 ;;
        --owner) require_arg "$1" $# || exit 1; OWNER="$2"; shift 2 ;;
        --sharing) require_arg "$1" $# || exit 1; SHARING="$2"; shift 2 ;;
        --read-roles) require_arg "$1" $# || exit 1; READ_ROLES="$2"; shift 2 ;;
        --write-roles) require_arg "$1" $# || exit 1; WRITE_ROLES="$2"; shift 2 ;;
        --accept-overwrite) ACCEPT_OVERWRITE=true; shift ;;
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
    validate_choice "${THEME}" light dark
    validate_choice "${LAYOUT}" grid absolute freeform
    validate_choice "${SHARING}" user app global
    [[ -n "${DASHBOARD_NAME}" ]] || { log "ERROR: --dashboard-name is required."; exit 1; }
    [[ "${APP_NAME}" =~ ^[A-Za-z0-9_.:-]+$ && "${APP_NAME}" != "." && "${APP_NAME}" != ".." && "${APP_NAME}" != "-" ]] || {
        log "ERROR: --app-name must be a safe namespace segment (letters, numbers, underscore, dot, colon, or hyphen)."
        exit 1
    }
    [[ "${OWNER}" =~ ^[A-Za-z0-9_.@-]+$ && "${OWNER}" != "." && "${OWNER}" != ".." && "${OWNER}" != "-" ]] || {
        log "ERROR: --owner must be a safe non-empty Splunk username namespace segment."
        exit 1
    }
    local roles role
    for roles in "${READ_ROLES}" "${WRITE_ROLES}"; do
        IFS=',' read -ra _roles <<<"${roles}"
        for role in "${_roles[@]}"; do
            role="$(printf '%s' "${role}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
            [[ -z "${role}" || "${role}" =~ ^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$ || "${role}" == "*" ]] || {
                log "ERROR: ACL roles must be comma-separated Splunk role names (or *)."
                exit 1
            }
        done
    done
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
        --dashboard-name "${DASHBOARD_NAME}"
        --title "${TITLE}"
        --description "${DESCRIPTION}"
        --theme "${THEME}"
        --search "${SEARCH}"
        --viz-type "${VIZ_TYPE}"
        --datasource-name "${DATASOURCE_NAME}"
        --layout "${LAYOUT}"
        --definition-file "${DEFINITION_FILE}"
        --owner "${OWNER}"
        --sharing "${SHARING}"
        --read-roles "${READ_ROLES}"
        --write-roles "${WRITE_ROLES}"
    )
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

prepare_state_dir() {
    STATE_DIR="${OUTPUT_DIR}/dashboard-studio/state"
    if [[ -L "${STATE_DIR}" ]]; then
        log "ERROR: Refusing symlink transaction-state directory: ${STATE_DIR}"
        return 1
    fi
    mkdir -p "${STATE_DIR}"
    [[ -d "${STATE_DIR}" ]] || {
        log "ERROR: Transaction-state path is not a directory: ${STATE_DIR}"
        return 1
    }
    chmod 700 "${STATE_DIR}"
}

begin_transaction() {
    prepare_state_dir || return 1
    TXN_DIR="$(mktemp -d "${STATE_DIR}/.transaction.XXXXXX")"
    chmod 700 "${TXN_DIR}"
    EVENTS_FILE="${TXN_DIR}/events.jsonl"
    : > "${EVENTS_FILE}"
    chmod 600 "${EVENTS_FILE}"
    MANUAL_CLEANUP_REQUIRED=false
    MANUAL_CLEANUP_PATH=""
    trap 'transaction_exit_trap $?' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    trap 'exit 129' HUP
}

cleanup_transaction() {
    if [[ -n "${TXN_DIR:-}" && -d "${TXN_DIR}" ]]; then
        rm -rf -- "${TXN_DIR}"
    fi
    TXN_DIR=""
}

deactivate_transaction() {
    TRANSACTION_ACTIVE=false
    TRANSACTION_SK=""
}

transaction_exit_trap() {
    local status="${1:-1}"
    if [[ "${TRAP_RUNNING}" == "true" ]]; then
        exit "${status}"
    fi
    TRAP_RUNNING=true
    trap - EXIT INT TERM HUP
    set +e
    if [[ "${TRANSACTION_ACTIVE}" == "true" && -n "${TRANSACTION_SK}" ]]; then
        [[ "${status}" -ne 0 ]] || status=1
        record_event "unexpected-exit" "failed" \
            "The process exited or received a signal after a mutation request; read-only failure reconciliation was attempted."
        rollback_transaction "${TRANSACTION_SK}" || true
        write_evidence "failed" "unexpected-exit" "${ROLLBACK_STATUS}" \
            "${STATE_DIR}/apply-evidence.json" || true
    fi
    cleanup_transaction
    exit "${status}"
}

record_event() {
    python3 "${STATE_HELPER}" event \
        --events "${EVENTS_FILE}" --step "$1" --status "$2" --detail "$3"
}

write_evidence() {
    local result="$1" failure_step="$2" rollback="$3" destination="$4" existed=false
    [[ "${PRE_VIEW_CODE}" == "200" ]] && existed=true
    python3 "${STATE_HELPER}" evidence \
        --events "${EVENTS_FILE}" --output "${destination}" \
        --result "${result}" --failure-step "${failure_step}" --rollback "${rollback}" \
        --app "${APP_NAME}" --name "${DASHBOARD_NAME}" --object-existed "${existed}" \
        --manual-cleanup-required "${MANUAL_CLEANUP_REQUIRED}" \
        --manual-cleanup-path "${MANUAL_CLEANUP_PATH}"
}

ensure_manual_cleanup_dir() {
    local candidate
    if [[ -n "${MANUAL_CLEANUP_PATH}" ]]; then
        [[ -d "${MANUAL_CLEANUP_PATH}" && ! -L "${MANUAL_CLEANUP_PATH}" ]]
        return
    fi
    candidate="${STATE_DIR}/manual-cleanup-$(date -u '+%Y%m%dT%H%M%SZ')-$$"
    if [[ -e "${candidate}" || -L "${candidate}" ]]; then
        log "ERROR: Refusing existing manual-cleanup evidence path: ${candidate}"
        return 1
    fi
    mkdir -m 700 -- "${candidate}" || return 1
    [[ -d "${candidate}" && ! -L "${candidate}" ]] || return 1
    MANUAL_CLEANUP_PATH="${candidate}"
}

preserve_private_snapshot() {
    local label="$1" source="$2"
    [[ -f "${source}" ]] || return 0
    ensure_manual_cleanup_dir || return 1
    python3 "${STATE_HELPER}" publish-raw \
        --source "${source}" --output "${MANUAL_CLEANUP_PATH}/${label}"
}

require_reviewed_recovery() {
    MANUAL_CLEANUP_REQUIRED=true
    ensure_manual_cleanup_dir || return 1
    log "MANUAL RECOVERY REQUIRED: failed dashboard state was retained; automatic restore and delete are disabled because Splunk exposes no verified conditional write/delete contract."
    log "Review the private before/current snapshots under ${MANUAL_CLEANUP_PATH}, fetch the exact live view and ACL again, confirm no concurrent owner changed them, then reconcile through the supported Splunk UI/REST workflow."
}

view_collection_endpoint() {
    printf '%s/servicesNS/%s/%s/data/ui/views' \
        "${SPLUNK_URI}" "$(_urlencode "${OWNER}")" "$(_urlencode "${APP_NAME}")"
}

view_endpoint() {
    printf '%s/%s' "$(view_collection_endpoint)" "$(_urlencode "${DASHBOARD_NAME}")"
}

capture_endpoint() {
    local sk="$1" url="$2" destination="$3"
    local response code
    response="$(mktemp "${TXN_DIR}/.response.XXXXXX")"
    chmod 600 "${response}"
    if ! splunk_curl "${sk}" "${url}?output_mode=json" -w '\n%{http_code}' > "${response}" 2>/dev/null; then
        : > "${destination}"
        chmod 600 "${destination}"
        rm -f -- "${response}"
        printf '%s' "000"
        return 0
    fi
    code="$(tail -n 1 "${response}")"
    [[ "${code}" =~ ^[0-9]{3}$ ]] || code="000"
    sed '$d' "${response}" > "${destination}"
    chmod 600 "${destination}"
    rm -f -- "${response}"
    printf '%s' "${code}"
}

post_form_code() {
    local sk="$1" url="$2" body="$3"
    local response code
    response="$(mktemp "${TXN_DIR}/.post-response.XXXXXX")"
    chmod 600 "${response}"
    if ! splunk_curl_post "${sk}" "${body}" "${url}" -w '\n%{http_code}' > "${response}" 2>/dev/null; then
        rm -f -- "${response}"
        printf '%s' "000"
        return 0
    fi
    code="$(tail -n 1 "${response}")"
    [[ "${code}" =~ ^[0-9]{3}$ ]] || code="000"
    rm -f -- "${response}"
    printf '%s' "${code}"
}

capture_preflight_state() {
    local sk="$1" code app_endpoint
    app_endpoint="${SPLUNK_URI}/services/apps/local/$(_urlencode "${APP_NAME}")"
    code="$(capture_endpoint "${sk}" "${app_endpoint}" "${TXN_DIR}/app.json")"
    if [[ "${code}" != "200" ]] || ! python3 "${STATE_HELPER}" json-valid --path "${TXN_DIR}/app.json" --one-entry; then
        record_event "app-access" "failed" "Target app was not readable as one exact JSON entry (HTTP ${code})."
        log "ERROR: Target app ${APP_NAME} is not readable as an exact entry (HTTP ${code}); refusing mutation."
        return 1
    fi
    record_event "app-access" "passed" "Target app is readable as one exact entry."

    code="$(capture_endpoint "${sk}" "${SPLUNK_URI}/services/authentication/current-context" "${TXN_DIR}/context.json")"
    if [[ "${code}" != "200" ]] || ! python3 "${STATE_HELPER}" json-valid --path "${TXN_DIR}/context.json" --one-entry; then
        record_event "authenticated-context" "failed" "Authenticated context was not readable as one exact JSON entry (HTTP ${code})."
        log "ERROR: Could not read authenticated Splunk context (HTTP ${code}); refusing mutation."
        return 1
    fi
    record_event "authenticated-context" "passed" "Authenticated context is readable."

    code="$(capture_endpoint "${sk}" "$(view_collection_endpoint)" "${TXN_DIR}/collection.json")"
    if [[ "${code}" != "200" ]] || ! python3 "${STATE_HELPER}" json-valid --path "${TXN_DIR}/collection.json"; then
        record_event "view-collection-access" "failed" "Dashboard view collection was not readable as JSON (HTTP ${code})."
        log "ERROR: data/ui/views is not readable in app ${APP_NAME} (HTTP ${code}); refusing mutation."
        return 1
    fi
    record_event "view-collection-access" "passed" "Dashboard view collection is readable."

    PRE_VIEW_CODE="$(capture_endpoint "${sk}" "$(view_endpoint)" "${TXN_DIR}/before-view.json")"
    PRE_ACL_CODE="404"
    : > "${TXN_DIR}/before-acl.json"
    chmod 600 "${TXN_DIR}/before-acl.json"
    case "${PRE_VIEW_CODE}" in
        200)
            PRE_ACL_CODE="$(capture_endpoint "${sk}" "$(view_endpoint)/acl" "${TXN_DIR}/before-acl.json")"
            if [[ "${PRE_ACL_CODE}" != "200" ]] || ! python3 "${STATE_HELPER}" snapshot-valid \
                --view "${TXN_DIR}/before-view.json" --acl "${TXN_DIR}/before-acl.json"; then
                record_event "view-snapshot" "failed" "Existing view content or ACL could not be snapshotted exactly (ACL HTTP ${PRE_ACL_CODE})."
                log "ERROR: Existing dashboard content/ACL snapshot failed; refusing mutation."
                return 1
            fi
            record_event "view-snapshot" "passed" "Existing view content and ACL were privately snapshotted."
            ;;
        404)
            record_event "view-snapshot" "passed" \
                "Exact target view does not exist; a failed create will be retained for reviewed manual cleanup because REST delete has no conditional concurrency guard."
            ;;
        *)
            record_event "view-snapshot" "failed" "Exact target view lookup failed (HTTP ${PRE_VIEW_CODE})."
            log "ERROR: Exact dashboard lookup failed (HTTP ${PRE_VIEW_CODE}); refusing mutation."
            return 1
            ;;
    esac
}

evaluate_live_state() {
    local sk="$1" prefix="$2" destination="$3"
    local view_code acl_code="404"
    view_code="$(capture_endpoint "${sk}" "$(view_endpoint)" "${TXN_DIR}/${prefix}-view.json")"
    : > "${TXN_DIR}/${prefix}-acl.json"
    chmod 600 "${TXN_DIR}/${prefix}-acl.json"
    if [[ "${view_code}" == "200" ]]; then
        acl_code="$(capture_endpoint "${sk}" "$(view_endpoint)/acl" "${TXN_DIR}/${prefix}-acl.json")"
    fi
    python3 "${STATE_HELPER}" status \
        --view "${TXN_DIR}/${prefix}-view.json" --view-code "${view_code}" \
        --acl "${TXN_DIR}/${prefix}-acl.json" --acl-code "${acl_code}" \
        --desired-view "${OUTPUT_DIR}/dashboard-studio/view.xml" \
        --owner "${OWNER}" --sharing "${SHARING}" \
        --read-roles "${READ_ROLES}" --write-roles "${WRITE_ROLES}" \
        --app "${APP_NAME}" --name "${DASHBOARD_NAME}" --output "${destination}"
}

capture_owned_content_state() {
    local sk="$1" view_code acl_code="404"
    view_code="$(capture_endpoint "${sk}" "$(view_endpoint)" "${TXN_DIR}/owned-view.json")"
    : > "${TXN_DIR}/owned-baseline-acl.json"
    chmod 600 "${TXN_DIR}/owned-baseline-acl.json"
    if [[ "${view_code}" == "200" ]]; then
        acl_code="$(capture_endpoint "${sk}" "$(view_endpoint)/acl" "${TXN_DIR}/owned-baseline-acl.json")"
    fi
    if [[ "${view_code}" != "200" || "${acl_code}" != "200" ]] || \
        ! python3 "${STATE_HELPER}" snapshot-valid \
            --view "${TXN_DIR}/owned-view.json" --acl "${TXN_DIR}/owned-baseline-acl.json" || \
        ! python3 "${STATE_HELPER}" view-matches \
            --view "${TXN_DIR}/owned-view.json" \
            --desired-view "${OUTPUT_DIR}/dashboard-studio/view.xml"; then
        record_event "content-readback" "failed" \
            "Could not establish an exact transaction-owned content/ACL baseline (view HTTP ${view_code}, ACL HTTP ${acl_code})."
        return 1
    fi
    record_event "content-readback" "passed" \
        "Exact desired content and its baseline ACL were captured after the write."
}

reconcile_ambiguous_content_write() {
    local sk="$1" write_code="$2" view_code acl_code="404"
    view_code="$(capture_endpoint "${sk}" "$(view_endpoint)" "${TXN_DIR}/ambiguous-current-view.json")"
    : > "${TXN_DIR}/ambiguous-current-acl.json"
    chmod 600 "${TXN_DIR}/ambiguous-current-acl.json"
    if [[ "${view_code}" == "200" ]]; then
        acl_code="$(capture_endpoint "${sk}" "$(view_endpoint)/acl" "${TXN_DIR}/ambiguous-current-acl.json")"
    fi

    if [[ "${PRE_VIEW_CODE}" == "404" && "${view_code}" == "404" ]]; then
        record_event "content-write-reconcile" "unchanged" \
            "The ambiguous content response left the exact target absent (HTTP ${write_code})."
        deactivate_transaction
        write_evidence "failed" "content-write" "not-required" "${STATE_DIR}/apply-evidence.json"
        log "ERROR: Content write was not confirmed (HTTP ${write_code}); reconciliation confirmed no target view exists."
        return 1
    fi
    if [[ "${PRE_VIEW_CODE}" == "200" && "${view_code}" == "200" && "${acl_code}" == "200" ]] && \
        python3 "${STATE_HELPER}" compare-snapshots \
            --expected-view "${TXN_DIR}/before-view.json" --expected-acl "${TXN_DIR}/before-acl.json" \
            --actual-view "${TXN_DIR}/ambiguous-current-view.json" --actual-acl "${TXN_DIR}/ambiguous-current-acl.json"; then
        record_event "content-write-reconcile" "unchanged" \
            "The ambiguous content response left the exact prior view and ACL unchanged (HTTP ${write_code})."
        deactivate_transaction
        write_evidence "failed" "content-write" "not-required" "${STATE_DIR}/apply-evidence.json"
        log "ERROR: Content write was not confirmed (HTTP ${write_code}); reconciliation confirmed no state change."
        return 1
    fi

    record_event "content-write-reconcile" "ambiguous" \
        "The content response was HTTP ${write_code} and live state changed or could not be verified; read-only failure reconciliation follows."
    transaction_failed "${sk}" "content-write" \
        "Content write returned HTTP ${write_code} after a mutation request; live state was reconciled."
    return 1
}

run_live_preflight() {
    local sk
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; return 1; }
    sk="$(get_session_key "${SPLUNK_URI}")" || { log "ERROR: Could not authenticate to Splunk."; return 1; }
    begin_transaction
    if ! capture_preflight_state "${sk}"; then
        write_evidence "failed" "preflight" "not-required" "${STATE_DIR}/preflight-evidence.json" || true
        log "ERROR: Live Dashboard Studio preflight failed before mutation. Evidence: ${STATE_DIR}/preflight-evidence.json"
        return 1
    fi
    record_event "preflight" "passed" "All live read-only preflight checks passed."
    write_evidence "succeeded" "" "not-required" "${STATE_DIR}/preflight-evidence.json"
    log "Live Dashboard Studio preflight passed. Evidence: ${STATE_DIR}/preflight-evidence.json"
}

run_live_status() {
    local sk status_file
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; return 1; }
    sk="$(get_session_key "${SPLUNK_URI}")" || { log "ERROR: Could not authenticate to Splunk."; return 1; }
    begin_transaction
    if ! capture_preflight_state "${sk}"; then
        log "ERROR: Live status could not query the exact dashboard endpoints."
        return 1
    fi
    status_file="${STATE_DIR}/live-status.json"
    if evaluate_live_state "${sk}" "status" "${status_file}"; then
        log "Live dashboard content and exact ACL governance match rendered intent. Evidence: ${status_file}"
        return 0
    fi
    log "ERROR: Live dashboard content or exact ACL governance does not match rendered intent. Evidence: ${status_file}"
    return 1
}

rollback_transaction() {
    local sk="$1" current_view_code current_acl_code="404"
    current_view_code="$(capture_endpoint "${sk}" "$(view_endpoint)" "${TXN_DIR}/rollback-current-view.json")"
    : > "${TXN_DIR}/rollback-current-acl.json"
    chmod 600 "${TXN_DIR}/rollback-current-acl.json"
    if [[ "${current_view_code}" == "200" ]]; then
        current_acl_code="$(capture_endpoint "${sk}" "$(view_endpoint)/acl" "${TXN_DIR}/rollback-current-acl.json")"
    fi

    if [[ "${PRE_VIEW_CODE}" == "404" && "${current_view_code}" == "404" ]]; then
        record_event "rollback-state" "unchanged" \
            "Read-only reconciliation confirmed that the target remains absent."
        ROLLBACK_STATUS="complete"
        log "Failure reconciliation confirmed no retained dashboard state."
        return 0
    fi

    if [[ "${PRE_VIEW_CODE}" == "200" && "${current_view_code}" == "200" && "${current_acl_code}" == "200" ]] && \
        python3 "${STATE_HELPER}" compare-snapshots \
            --expected-view "${TXN_DIR}/before-view.json" --expected-acl "${TXN_DIR}/before-acl.json" \
            --actual-view "${TXN_DIR}/rollback-current-view.json" --actual-acl "${TXN_DIR}/rollback-current-acl.json"; then
        record_event "rollback-state" "unchanged" \
            "Read-only reconciliation confirmed that the exact pre-transaction view and ACL remain in place."
        ROLLBACK_STATUS="complete"
        log "Failure reconciliation confirmed the exact pre-transaction dashboard state remains in place."
        return 0
    fi

    require_reviewed_recovery || true
    preserve_private_snapshot "view-before.raw" "${TXN_DIR}/before-view.json" || true
    preserve_private_snapshot "acl-before.raw" "${TXN_DIR}/before-acl.json" || true
    preserve_private_snapshot "view-current.raw" "${TXN_DIR}/rollback-current-view.json" || true
    preserve_private_snapshot "acl-current.raw" "${TXN_DIR}/rollback-current-acl.json" || true
    preserve_private_snapshot "view-post-content-write.raw" "${TXN_DIR}/owned-view.json" || true
    preserve_private_snapshot "acl-post-content-write.raw" "${TXN_DIR}/owned-baseline-acl.json" || true
    record_event "rollback-view" "manual-cleanup-required" \
        "Failed state was retained (view HTTP ${current_view_code}, ACL HTTP ${current_acl_code}). Automatic restore POST and DELETE are disabled; use the private before/current snapshots for reviewed recovery after a fresh live read."
    ROLLBACK_STATUS="partial"
    log "ERROR: Automatic rollback is disabled; private recovery evidence and redacted partial-failure evidence were retained."
    return 1
}

transaction_failed() {
    local sk="$1" failure_step="$2" detail="$3"
    record_event "${failure_step}" "failed" "${detail}"
    rollback_transaction "${sk}" || true
    write_evidence "failed" "${failure_step}" "${ROLLBACK_STATUS}" "${STATE_DIR}/apply-evidence.json" || \
        log "ERROR: Could not write redacted transaction evidence."
    deactivate_transaction
    log "ERROR: Dashboard apply failed at ${failure_step}. Evidence: ${STATE_DIR}/apply-evidence.json"
    return 1
}

apply_live() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would preflight, write the exact view, set exact ACL owner/sharing/role sets, and read back; failures retain state for reviewed recovery."
        return 0
    fi
    local xml_file="${OUTPUT_DIR}/dashboard-studio/view.xml" sk xml_content body write_code acl_code write_endpoint
    if [[ ! -f "${xml_file}" ]]; then
        log "ERROR: Rendered view.xml not found; run render first."
        return 1
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; return 1; }
    sk="$(get_session_key "${SPLUNK_URI}")" || { log "ERROR: Could not authenticate to Splunk."; return 1; }
    begin_transaction
    if ! capture_preflight_state "${sk}"; then
        write_evidence "failed" "preflight" "not-required" "${STATE_DIR}/apply-evidence.json" || true
        log "ERROR: Live preflight failed before mutation. Evidence: ${STATE_DIR}/apply-evidence.json"
        return 1
    fi
    record_event "preflight" "passed" "All live read-only preflight checks passed."
    if [[ "${PRE_VIEW_CODE}" == "200" && "${ACCEPT_OVERWRITE}" != "true" ]]; then
        record_event "overwrite-ack" "failed" "Existing dashboard overwrite was not explicitly accepted."
        write_evidence "failed" "overwrite-ack" "not-required" "${STATE_DIR}/apply-evidence.json"
        log "ERROR: Dashboard '${DASHBOARD_NAME}' already exists. Re-run with --accept-overwrite to update it."
        return 1
    fi

    # Command substitution strips trailing newlines. Add/remove a sentinel so
    # the eai:data write is byte-for-byte identical to the rendered view.xml
    # that status/readback validates.
    xml_content="$(cat "${xml_file}"; printf '.sentinel')"
    xml_content="${xml_content%.sentinel}"
    if [[ "${PRE_VIEW_CODE}" == "200" ]]; then
        body="$(form_urlencode_pairs "eai:data" "${xml_content}")"
        write_endpoint="$(view_endpoint)"
    else
        body="$(form_urlencode_pairs name "${DASHBOARD_NAME}" "eai:data" "${xml_content}")"
        write_endpoint="$(view_collection_endpoint)"
    fi
    TRANSACTION_SK="${sk}"
    TRANSACTION_ACTIVE=true
    write_code="$(post_form_code "${sk}" "${write_endpoint}" "${body}")"
    case "${write_code}" in
        200|201) record_event "content-write" "passed" "Dashboard content write succeeded (HTTP ${write_code})." ;;
        *)
            reconcile_ambiguous_content_write "${sk}" "${write_code}" || return 1
            ;;
    esac
    if ! capture_owned_content_state "${sk}"; then
        transaction_failed "${sk}" "content-readback" \
            "Content write returned HTTP ${write_code}, but exact content/ACL ownership could not be established."
        return 1
    fi

    body="$(form_urlencode_pairs sharing "${SHARING}" owner "${OWNER}")"
    local role
    if [[ -n "${READ_ROLES}" ]]; then
        IFS=',' read -ra _read_roles <<<"${READ_ROLES}"
        for role in "${_read_roles[@]}"; do
            role="$(printf '%s' "${role}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
            [[ -n "${role}" ]] && body="${body}&$(form_urlencode_pairs perms.read "${role}")"
        done
    else
        body="${body}&$(form_urlencode_pairs perms.read "")"
    fi
    if [[ -n "${WRITE_ROLES}" ]]; then
        IFS=',' read -ra _write_roles <<<"${WRITE_ROLES}"
        for role in "${_write_roles[@]}"; do
            role="$(printf '%s' "${role}" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
            [[ -n "${role}" ]] && body="${body}&$(form_urlencode_pairs perms.write "${role}")"
        done
    else
        body="${body}&$(form_urlencode_pairs perms.write "")"
    fi
    acl_code="$(post_form_code "${sk}" "$(view_endpoint)/acl" "${body}")"
    case "${acl_code}" in
        200|201) record_event "acl-write" "passed" "Requested owner, sharing, read-role, and write-role sets succeeded (HTTP ${acl_code})." ;;
        *) transaction_failed "${sk}" "acl-write" "ACL update failed (HTTP ${acl_code})."; return 1 ;;
    esac

    if ! evaluate_live_state "${sk}" "apply-readback" "${STATE_DIR}/apply-readback.json"; then
        transaction_failed "${sk}" "readback" "Exact content or exact ACL owner/sharing/role-set readback did not match rendered intent."
        return 1
    fi
    deactivate_transaction
    record_event "readback" "passed" "Exact content and normalized ACL owner/sharing/read/write role sets matched rendered intent."
    write_evidence "succeeded" "" "not-required" "${STATE_DIR}/apply-evidence.json"
    log "Dashboard Studio view '${DASHBOARD_NAME}' applied and verified in app ${APP_NAME}. Evidence: ${STATE_DIR}/apply-evidence.json"
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
        preflight) render_assets; run_live_preflight ;;
        apply) render_assets; apply_live ;;
        status) render_assets; run_live_status ;;
        all) render_assets; apply_live ;;
    esac
}

main "$@"
