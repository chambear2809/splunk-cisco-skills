#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/splunk-gcp-ta-setup/scripts/validate.sh [--index IDX]

Validates Splunk_TA_google-cloudplatform installation, index, configured
Pub/Sub inputs, and GCP data using configured Splunk credentials.
Pass --completion to treat every readiness warning as a failure.
EOF
    exit 0
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_google-cloudplatform"
INDEX="gcp"
COMPLETION=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --completion|--strict) COMPLETION=true; shift ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done
validate_splunk_index_name "${INDEX}" || exit 1

PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { if [[ "${COMPLETION}" == "true" ]]; then fail "$*"; else log "  WARN: $*"; WARN=$((WARN + 1)); fi; }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

log "=== Splunk Add-on for Google Cloud Platform Validation ==="
check_current_skill_role_for_validation "${COMPLETION}" || fail "Deployment role is unsupported for this skill"

if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials"
else
    SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }
fi

if [[ -n "${SK:-}" ]]; then
    app_present=false
    index_present=false
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        version=$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}" 2>/dev/null || echo "unknown")
        pass "Add-on installed: ${APP_NAME} (${version})"
        app_present=true
    else
        fail "Add-on missing: ${APP_NAME}"
    fi

    if [[ "${COMPLETION}" == "true" && "${app_present}" == "true" ]]; then
        enabled_inputs=$(rest_count_live_inputs "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "0" 2>/dev/null || echo 0)
        [[ "${enabled_inputs}" =~ ^[0-9]+$ && "${enabled_inputs}" -gt 0 ]] && pass "Enabled app inputs: ${enabled_inputs}" || fail "No enabled inputs owned by ${APP_NAME}"
    fi

    if platform_check_index "${SK}" "${SPLUNK_URI}" "${INDEX}"; then
        pass "Index ${INDEX} exists"
        index_present=true
    else
        warn "Index ${INDEX} not found"
    fi

    if ${app_present}; then
        inputs=$(rest_count_conf_stanzas "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "inputs" "google_cloud_pubsub://")
        if [[ "${inputs}" -gt 0 ]]; then
            pass "google_cloud_pubsub input stanzas: ${inputs}"
        else
            warn "No google_cloud_pubsub inputs configured yet"
        fi
    fi

    if ${index_present}; then
        evt=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" \
            "| tstats count where index=${INDEX} sourcetype=google:gcp:pubsub:message" "count")
        if [[ "${evt}" -gt 0 ]]; then
            pass "google:gcp:pubsub:message events in ${INDEX}: ${evt}"
        else
            warn "No google:gcp:pubsub:message events found in ${INDEX}"
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]
