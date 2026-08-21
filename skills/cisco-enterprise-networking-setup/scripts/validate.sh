#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRICT=false
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-enterprise-networking-setup/scripts/validate.sh [--strict|--completion] [--help]

Validates the deployed Cisco Enterprise Networking app using configured Splunk credentials.
Diagnostic mode reports incomplete onboarding as warnings. --strict and its
alias --completion make completion-critical findings exit nonzero.
EOF
    exit 0
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict|--completion) STRICT=true; shift ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-catalyst-app"
CATALYST_TA_APP="TA_cisco_catalyst"
ENHANCED_NETFLOW_TA_APP="splunk_app_stream_ipfix_cisco_hsl"
readonly SAVED_SEARCHES=(
    "cisco_catalyst_location"
    "cisco_catalyst_sdwan_netflow"
    "cisco_catalyst_sdwan_policy"
    "cisco_catalyst_meraki_organization_mapping"
    "cisco_catalyst_meraki_devices_serial_mapping"
)
readonly REQUIRED_SOURCETYPE_FAMILIES=(
    "cisco:ise*"
    "cisco:sdwan*"
    "cisco:dnac*"
    "stream:netflow"
    "cisco:cybervision:*"
    "meraki:*"
    "cisco:ios"
    "cisco:thousandeyes:metric"
    "cisco:sgacl:logs"
    "cisco:catalyst:center:*"
    "cisco:ise:analytics*"
    "tenable:sc*"
)
SK=""
dashboard_index_csv=""
sdwan_index_csv=""
ta_sdwan_index_csv=""
dashboard_indexes=()

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
completion_issue() { if ${STRICT}; then fail "$@"; else warn "$@"; fi; }

# Accept only the explicit index-list form written by setup.sh and documented
# by the package. Canonical output is a sorted, de-duplicated comma list that is
# safe to split and interpolate into the bounded tstats checks below.
parse_index_macro_definition() {
    local definition="${1:-}"
    python3 - "${definition}" <<'PY'
import re
import sys

definition = sys.argv[1].strip()
match = re.fullmatch(r"index\s+IN\s*\(\s*(.*?)\s*\)", definition, re.IGNORECASE)
if not match:
    raise SystemExit(1)

indexes = []
for raw_token in match.group(1).split(","):
    token = raw_token.strip()
    if len(token) >= 2 and token[0] in {'"', "'"} and token[-1] == token[0]:
        token = token[1:-1]
    elif '"' in token or "'" in token:
        raise SystemExit(1)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", token):
        raise SystemExit(1)
    indexes.append(token)

if not indexes:
    raise SystemExit(1)
print(",".join(sorted(set(indexes))), end="")
PY
}

index_csv_contains() {
    local csv="${1:-}" candidate="${2:-}"
    [[ ",${csv}," == *",${candidate},"* ]]
}

log "=== Cisco Enterprise Networking App Validation ==="
log ""

warn_if_current_skill_role_unsupported

log "--- App Installation ---"
if ! load_splunk_credentials; then
    fail "Could not load Splunk credentials — check credentials file"
elif ! SK=$(get_session_key "${SPLUNK_URI}"); then
    fail "Could not authenticate to Splunk REST API — check credentials"
else
    if rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        version=$(rest_get_app_version "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "unknown")
        pass "App installed (version: ${version})"
    else
        fail "App not found — install Cisco Enterprise Networking app first"
    fi
fi

if [[ -n "${SK:-}" ]]; then
log ""
log "--- Companion Technical Add-ons ---"
if rest_check_app "$SK" "$SPLUNK_URI" "${CATALYST_TA_APP}" 2>/dev/null; then
    pass "Cisco Catalyst Add-on (${CATALYST_TA_APP}) is installed"
else
    fail "Cisco Catalyst Add-on (${CATALYST_TA_APP}) not found — dashboards will have no Catalyst, ISE, SD-WAN, or Cyber Vision data"
fi

if rest_check_app "$SK" "$SPLUNK_URI" "${ENHANCED_NETFLOW_TA_APP}" 2>/dev/null; then
    pass "Cisco Catalyst Enhanced Netflow Add-on (${ENHANCED_NETFLOW_TA_APP}) is installed"
else
    warn "Optional Cisco Catalyst Enhanced Netflow Add-on (${ENHANCED_NETFLOW_TA_APP}) not found — additional NetFlow-focused dashboards will remain unavailable"
fi

log ""
log "--- Macros ---"
def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_catalyst_app_index" "definition" 2>/dev/null || true)
if [[ -z "${def}" ]]; then
    completion_issue "cisco_catalyst_app_index macro not found; dashboard searches are not aligned"
elif dashboard_index_csv=$(parse_index_macro_definition "${def}" 2>/dev/null); then
    pass "cisco_catalyst_app_index has an explicit, safe index scope: ${def}"
    IFS=',' read -r -a dashboard_indexes <<<"${dashboard_index_csv}"
    for idx in "${dashboard_indexes[@]}"; do
        pass "  Configured dashboard index '${idx}' accepted"
    done
else
    completion_issue "cisco_catalyst_app_index must use an explicit safe list such as index IN (\"catalyst\", \"ise\"); wildcard, empty, and arbitrary SPL definitions are refused"
fi

sourcetype_def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_catalyst_app_sourcetypes" "definition" 2>/dev/null || true)
if [[ -n "${sourcetype_def}" ]]; then
    pass "cisco_catalyst_app_sourcetypes macro is defined"
    for source_family in "${REQUIRED_SOURCETYPE_FAMILIES[@]}"; do
        if [[ "${sourcetype_def}" == *"\"${source_family}\""* ]]; then
            pass "  Sourcetype family '${source_family}' included in macro"
        else
            completion_issue "Sourcetype family '${source_family}' is missing from cisco_catalyst_app_sourcetypes"
        fi
    done
    if [[ "${sourcetype_def}" == *"cisco:thousandeyes:test"* ]]; then
        warn "Sourcetype macro still contains retired alias 'cisco:thousandeyes:test'; run setup.sh --macros-only"
    fi
else
    completion_issue "cisco_catalyst_app_sourcetypes macro not found; dashboard source coverage is not aligned"
fi

sdwan_def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "cisco_catalyst_sdwan_index" "definition" 2>/dev/null || true)
if [[ -z "${sdwan_def}" ]]; then
    completion_issue "cisco_catalyst_sdwan_index macro not found; SD-WAN raw dashboards are not scoped"
elif sdwan_index_csv=$(parse_index_macro_definition "${sdwan_def}" 2>/dev/null); then
    pass "cisco_catalyst_sdwan_index has an explicit, safe index scope: ${sdwan_def}"
    if [[ -n "${dashboard_index_csv}" ]]; then
        IFS=',' read -r -a sdwan_indexes <<<"${sdwan_index_csv}"
        for idx in "${sdwan_indexes[@]}"; do
            if index_csv_contains "${dashboard_index_csv}" "${idx}"; then
                pass "  SD-WAN index '${idx}' is included in cisco_catalyst_app_index"
            else
                completion_issue "SD-WAN index '${idx}' is missing from cisco_catalyst_app_index"
            fi
        done
    fi
else
    completion_issue "cisco_catalyst_sdwan_index must use an explicit safe index IN (...) list; the wildcard and empty definitions are not completion-ready"
fi

ta_sdwan_def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$CATALYST_TA_APP" "eventtypes" "cisco_sdwan_index" "search" 2>/dev/null || true)
if [[ -z "${ta_sdwan_def}" ]]; then
    completion_issue "TA eventtype cisco_sdwan_index was not found"
elif ta_sdwan_index_csv=$(parse_index_macro_definition "${ta_sdwan_def}" 2>/dev/null); then
    pass "TA eventtype cisco_sdwan_index has an explicit, safe index scope: ${ta_sdwan_def}"
    if [[ -n "${sdwan_index_csv}" ]]; then
        if [[ "${ta_sdwan_index_csv}" == "${sdwan_index_csv}" ]]; then
            pass "TA cisco_sdwan_index eventtype matches the app cisco_catalyst_sdwan_index macro"
        else
            completion_issue "TA cisco_sdwan_index eventtype does not match the app cisco_catalyst_sdwan_index macro"
        fi
    fi
else
    completion_issue "TA eventtype cisco_sdwan_index must replace the package's empty () placeholder with the same explicit index IN (...) list used by cisco_catalyst_sdwan_index"
fi

view_count=$(splunk_curl "$SK" "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views?output_mode=json&count=0" 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
if [[ "${view_count}" -gt 0 ]]; then
    pass "Shipped dashboard views are visible: ${view_count}"
else
    completion_issue "No dashboard views are visible for ${APP_NAME}"
fi

log ""
log "--- Data Model ---"
accel=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "datamodels" "Cisco_Catalyst_App" "acceleration" 2>/dev/null || true)
if [[ "${accel}" == "true" ]]; then
    pass "Data model acceleration is enabled"
else
    warn "Data model acceleration is not enabled (optional for production)"
fi

log ""
log "--- Saved Searches ---"
for search_name in "${SAVED_SEARCHES[@]}"; do
    if ! rest_check_saved_search "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}" 2>/dev/null; then
        fail "Saved search '${search_name}' not found"
        continue
    fi

    disabled=$(rest_get_saved_search_value "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}" "disabled" 2>/dev/null || true)
    cron_schedule=$(rest_get_saved_search_value "$SK" "$SPLUNK_URI" "$APP_NAME" "${search_name}" "cron_schedule" 2>/dev/null || true)
    case "${disabled}" in
        0|false|False|"")
            pass "Saved search '${search_name}' enabled${cron_schedule:+ (schedule: ${cron_schedule})}"
            ;;
        *)
            completion_issue "Saved search '${search_name}' is disabled${cron_schedule:+ (schedule: ${cron_schedule})}"
            ;;
    esac
done

log ""
log "--- Data Flow Check ---"
event_total=0
if [[ ${#dashboard_indexes[@]} -eq 0 ]]; then
    warn "Data flow check skipped because cisco_catalyst_app_index has no valid explicit index list"
else
    for idx in "${dashboard_indexes[@]}"; do
        event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" "| tstats count where index=\"${idx}\"" "count" 2>/dev/null || echo "0")
        if [[ "${event_count}" =~ ^[0-9]+$ && "${event_count}" -gt 0 ]]; then
            event_total=$((event_total + event_count))
            pass "Index '${idx}' has ${event_count} events"
        else
            warn "Index '${idx}' has no events (configure TA first)"
        fi
    done
    [[ "${event_total}" -gt 0 ]] || completion_issue "No Enterprise Networking dashboard data was found"
fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if [[ ${FAIL} -gt 0 ]]; then
    log "  Status: ISSUES FOUND — review failures above"
    exit 1
elif [[ ${WARN} -gt 0 ]]; then
    log "  Status: OK with warnings"
    exit 0
else
    log "  Status: ALL CHECKS PASSED"
    exit 0
fi
