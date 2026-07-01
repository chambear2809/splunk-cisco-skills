#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/shared/lib/credential_helpers.sh"

RENDERED_DIR="${PROJECT_ROOT}/../splunk-vmware-ta-rendered"
LIVE=false
COMPLETION=false
EVENT_INDEX="vmware"
ESXI_INDEX="vmware_esxi"
METRICS_INDEX="vmware_metrics"

usage() {
    cat <<'EOF'
Splunk VMware TA Setup validation

Usage:
  bash skills/splunk-vmware-ta-setup/scripts/validate.sh [options]

Options:
  --rendered-dir DIR      Offline rendered asset directory
  --live                  Also validate Splunk apps, indexes, and sample data
  --completion            Run live validation and fail on any readiness warning
  --event-index INDEX     vCenter event/inventory index
  --esxi-index INDEX      ESXi syslog index
  --metrics-index INDEX   VMware metrics index
  --help                  Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) require_arg "$1" "$#" || exit 1; RENDERED_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --completion|--strict) LIVE=true; COMPLETION=true; shift ;;
        --event-index|--index) require_arg "$1" "$#" || exit 1; EVENT_INDEX="$2"; shift 2 ;;
        --esxi-index) require_arg "$1" "$#" || exit 1; ESXI_INDEX="$2"; shift 2 ;;
        --metrics-index) require_arg "$1" "$#" || exit 1; METRICS_INDEX="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done
validate_splunk_index_name "${EVENT_INDEX}" || exit 1
validate_splunk_index_name "${ESXI_INDEX}" || exit 1
validate_splunk_index_name "${METRICS_INDEX}" || exit 1

PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { if [[ "${COMPLETION}" == "true" ]]; then fail "$*"; else log "  WARN: $*"; WARN=$((WARN + 1)); fi; }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

log "=== Splunk VMware TA Validation ==="
check_current_skill_role_for_validation "${COMPLETION}" || fail "Deployment role is unsupported for this skill"

for file in metadata.json vmware-plan.md indexes.conf.template validation-searches.spl vcenter-account-runbook.md esxi-syslog-runbook.md itsi-readiness.md vmware-readiness-evidence.template.json; do
    if [[ -f "${RENDERED_DIR}/${file}" ]]; then
        pass "Rendered asset exists: ${file}"
    else
        fail "Missing rendered asset: ${RENDERED_DIR}/${file}"
    fi
done

if [[ -f "${RENDERED_DIR}/indexes.conf.template" ]]; then
    grep -q "\[${EVENT_INDEX}\]" "${RENDERED_DIR}/indexes.conf.template" && pass "Event index template includes ${EVENT_INDEX}" || fail "Event index template missing ${EVENT_INDEX}"
    grep -q "\[${ESXI_INDEX}\]" "${RENDERED_DIR}/indexes.conf.template" && pass "ESXi index template includes ${ESXI_INDEX}" || fail "ESXi index template missing ${ESXI_INDEX}"
    grep -q "\[${METRICS_INDEX}\]" "${RENDERED_DIR}/indexes.conf.template" && pass "Metrics index template includes ${METRICS_INDEX}" || fail "Metrics index template missing ${METRICS_INDEX}"
    grep -q "datatype = metric" "${RENDERED_DIR}/indexes.conf.template" && pass "Metrics index marks datatype=metric" || fail "Metrics index missing datatype=metric"
fi

if [[ -f "${RENDERED_DIR}/vmware-readiness-evidence.template.json" ]]; then
    if python3 -m json.tool "${RENDERED_DIR}/vmware-readiness-evidence.template.json" >/dev/null; then
        pass "Readiness evidence template is valid JSON"
    else
        fail "Readiness evidence template is not valid JSON"
    fi
fi

if [[ "${LIVE}" == "true" ]]; then
    if ! load_splunk_credentials; then
        fail "Could not load Splunk credentials"
    else
        SK=$(get_session_key "${SPLUNK_URI}") || { fail "Could not authenticate to Splunk REST API"; SK=""; }
        if [[ -n "${SK:-}" ]]; then
            for index in "${EVENT_INDEX}" "${ESXI_INDEX}" "${METRICS_INDEX}"; do
                if platform_check_index "${SK}" "${SPLUNK_URI}" "${index}"; then
                    pass "Index exists: ${index}"
                else
                    warn "Index not found: ${index}"
                fi
            done
            for app in Splunk_TA_vmware Splunk_TA_esxilogs Splunk_TA_vmware_inframon; do
                if rest_check_app "${SK}" "${SPLUNK_URI}" "${app}"; then
                    pass "VMware package installed: ${app}"
                else
                    warn "VMware package not detected: ${app}"
                fi
            done
            vmw_events=$(rest_oneshot_search "${SK}" "${SPLUNK_URI}" "| search (index=${EVENT_INDEX} OR index=${ESXI_INDEX}) sourcetype=vmware* | stats count" "count" 2>/dev/null || echo 0)
            [[ "${vmw_events}" -gt 0 ]] && pass "VMware events found: ${vmw_events}" || warn "No VMware events found in ${EVENT_INDEX}/${ESXI_INDEX}"
        fi
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]
