#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STRICT=false
CLASSINFO_INPUT=""
CLASSINFO_PRESET=""
EXPECT_CLASSES=""
CLASSINFO_INDEX="cisco_aci"
ADM_CLASSINFO_INPUT="classInfo_adm"
ADM_CLASSINFO_CLASSES="fabricLink lldpAdjEp vzBrCP vzSubj vzRsSubjFiltAtt vzEntry l3extInstP l3extSubnet"
ADM_POLICY_CLASSINFO_INPUT="classInfo_adm_policy"
ADM_POLICY_CLASSINFO_CLASSES="fvCtx fvAEPg fvEPg fvESg vzAny vzRsAnyToCons vzRsAnyToProv vzRsAnyToConsIf vzInTerm vzOutTerm vzTaboo fvRsProtBy vzRsSubjGraphAtt"
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    cat <<'EOF'
Usage: bash skills/cisco-dc-networking-setup/scripts/validate.sh [--strict|--completion]
           [--classinfo-input NAME [--expect-classes "C1 C2"] | --classinfo-preset NAME]
           [--index INDEX] [--help]

Validates the deployed Cisco DC Networking app using configured Splunk credentials.
Diagnostic mode reports incomplete onboarding as warnings. --strict and its
alias --completion make completion-critical findings exit nonzero.

Custom classInfo input checks (read-only):
  --classinfo-input NAME   Check cisco_nexus_aci://NAME is enabled as a classInfo
                           input and that cisco:dc:aci:class events from it
                           arrived in the last 24 hours, per APIC class.
  --expect-classes "C1 C2" Classes to expect (default: the input's apic_arguments)
  --classinfo-preset NAME  application-atlas (alias adm) = classInfo_adm;
                           adm-policy = classInfo_adm_policy; each with its class list
  --index INDEX            Index holding the custom input's events (default: cisco_aci)
EOF
    exit 0
fi
while [[ $# -gt 0 ]]; do
    case "$1" in
        --strict|--completion) STRICT=true; shift ;;
        --classinfo-input|--classinfo-preset|--expect-classes|--index)
            if [[ $# -lt 2 || -z "${2:-}" ]]; then
                echo "ERROR: $1 requires a value." >&2
                exit 1
            fi
            case "$1" in
                --classinfo-input) CLASSINFO_INPUT="$2" ;;
                --classinfo-preset) CLASSINFO_PRESET="$2" ;;
                --expect-classes) EXPECT_CLASSES="$2" ;;
                --index) CLASSINFO_INDEX="$2" ;;
            esac
            shift 2
            ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done
if [[ -n "${CLASSINFO_PRESET}" ]]; then
    if [[ -n "${CLASSINFO_INPUT}" ]]; then
        echo "ERROR: --classinfo-preset cannot be combined with --classinfo-input." >&2
        exit 1
    fi
    case "${CLASSINFO_PRESET}" in
        application-atlas|adm)
            CLASSINFO_INPUT="${ADM_CLASSINFO_INPUT}"
            EXPECT_CLASSES="${EXPECT_CLASSES:-${ADM_CLASSINFO_CLASSES}}"
            ;;
        adm-policy)
            CLASSINFO_INPUT="${ADM_POLICY_CLASSINFO_INPUT}"
            EXPECT_CLASSES="${EXPECT_CLASSES:-${ADM_POLICY_CLASSINFO_CLASSES}}"
            ;;
        *) echo "ERROR: Unknown --classinfo-preset '${CLASSINFO_PRESET}'. Use: application-atlas (alias adm), adm-policy" >&2; exit 1 ;;
    esac
fi
if [[ -n "${EXPECT_CLASSES}" && -z "${CLASSINFO_INPUT}" ]]; then
    echo "ERROR: --expect-classes requires --classinfo-input or --classinfo-preset." >&2
    exit 1
fi
# These values are interpolated into a search; accept only the TA's own name,
# index and class-name character sets.
if [[ -n "${CLASSINFO_INPUT}" && ! "${CLASSINFO_INPUT}" =~ ^[A-Za-z][A-Za-z0-9_]{0,99}$ ]]; then
    echo "ERROR: --classinfo-input must start with a letter and contain only letters, digits or underscores." >&2
    exit 1
fi
if [[ ! "${CLASSINFO_INDEX}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$ ]]; then
    echo "ERROR: --index contains unsupported characters." >&2
    exit 1
fi
if [[ -n "${EXPECT_CLASSES}" && ! "${EXPECT_CLASSES}" =~ ^[A-Za-z0-9_\ -]+$ ]]; then
    echo "ERROR: --expect-classes may contain only APIC class names separated by spaces." >&2
    exit 1
fi
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco_dc_networking_app_for_splunk"
SK=""

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
completion_issue() { if ${STRICT}; then fail "$@"; else warn "$@"; fi; }

log "=== Cisco DC Networking TA Validation ==="
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
        fail "App not found — install Cisco DC Networking app first"
    fi
fi

if [[ -n "${SK:-}" ]]; then
log ""
log "--- Indexes ---"
REQUIRED_INDEXES=("cisco_aci" "cisco_nd" "cisco_nexus_9k")
for idx in "${REQUIRED_INDEXES[@]}"; do
    if platform_check_index "$SK" "$SPLUNK_URI" "$idx" 2>/dev/null; then
        pass "Index '${idx}' exists"
    else
        completion_issue "Index '${idx}' not found"
    fi
done

log ""
log "--- Search Macros ---"
for macro_index in "cisco_dc_aci_index:cisco_aci" "cisco_dc_nd_index:cisco_nd" "cisco_dc_n9k_index:cisco_nexus_9k"; do
    macro="${macro_index%%:*}"
    expected_index="${macro_index#*:}"
    def=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "macros" "$macro" "definition" 2>/dev/null || true)
    if [[ -n "${def}" && "${def}" == *"${expected_index}"* ]]; then
        pass "Macro '${macro}' includes ${expected_index}"
    elif [[ -n "${def}" ]]; then
        completion_issue "Macro '${macro}' does not include ${expected_index}: ${def}"
    else
        completion_issue "Macro '${macro}' not found; shipped dashboards cannot be proven aligned"
    fi
done

view_count=$(splunk_curl "$SK" "${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/data/ui/views?output_mode=json&count=0" 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry", [])))' 2>/dev/null || echo "0")
if [[ "${view_count}" -gt 0 ]]; then
    pass "Shipped dashboard views are visible: ${view_count}"
else
    completion_issue "No dashboard views are visible for ${APP_NAME}"
fi

log ""
log "--- Account Configuration ---"
account_total=0
for label_handler in "ACI:cisco_dc_networking_app_for_splunk_aci_account" "ND:cisco_dc_networking_app_for_splunk_nd_account" "Nexus9K:cisco_dc_networking_app_for_splunk_nexus_9k_account"; do
    label="${label_handler%%:*}"
    handler="${label_handler#*:}"
    json=$(rest_list_ta_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "$handler" 2>/dev/null || true)
    if [[ -n "${json}" ]]; then
        count=$(echo "${json}" | python3 -c "import json,sys; d=json.load(sys.stdin); e=d.get('entry',[]); print(len(e))" 2>/dev/null || echo "0")
        if [[ "${count}" -gt 0 ]]; then
            account_total=$((account_total + count))
            pass "${label} account conf exists with ${count} account(s)"
        else
            warn "${label} account conf exists but has no stanzas"
        fi
    else
        warn "No ${label} account conf found"
    fi
done
[[ "${account_total}" -gt 0 ]] || completion_issue "No ACI, Nexus Dashboard, or Nexus 9K account is configured"

log ""
log "--- Data Inputs ---"
input_count=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null || echo "0")
enabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "0" 2>/dev/null || echo "0")
disabled_inputs=$(rest_count_live_inputs "$SK" "$SPLUNK_URI" "$APP_NAME" "1" 2>/dev/null || echo "0")
if [[ "${input_count}" -gt 0 ]]; then
    if [[ "${enabled_inputs}" -eq "${input_count}" ]]; then
        pass "${enabled_inputs} input(s) enabled"
    elif [[ "${enabled_inputs}" -gt 0 ]]; then
        warn "${enabled_inputs} input(s) enabled, ${disabled_inputs} disabled"
    else
        completion_issue "${input_count} input stanza(s) exist but all are disabled"
    fi
else
    completion_issue "No inputs configured"
fi

log ""
log "--- Data Flow Check ---"
event_total=0
for idx in "cisco_aci" "cisco_nd" "cisco_nexus_9k"; do
    event_count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" "| tstats count where index=${idx} earliest=-1h@h latest=now" "count" 2>/dev/null || echo "0")
    if [[ "${event_count}" -gt 0 ]]; then
        event_total=$((event_total + event_count))
        pass "Index '${idx}' has ${event_count} events in the last hour"
    else
        warn "Index '${idx}' has no events in the last hour (may be normal if just configured)"
    fi
done
[[ "${event_total}" -gt 0 ]] || completion_issue "No DC Networking events were found in the last hour"

if [[ -n "${CLASSINFO_INPUT}" ]]; then
    log ""
    log "--- Custom classInfo Input (${CLASSINFO_INPUT}) ---"
    ci_stanza="cisco_nexus_aci://${CLASSINFO_INPUT}"
    ci_type=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "inputs" "$ci_stanza" "apic_input_type" 2>/dev/null || true)
    ci_args=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "inputs" "$ci_stanza" "apic_arguments" 2>/dev/null || true)
    ci_disabled=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "inputs" "$ci_stanza" "disabled" 2>/dev/null || true)
    if [[ -z "${ci_type}" ]]; then
        completion_issue "Input ${ci_stanza} not found"
    else
        if [[ "${ci_type}" == "classInfo" ]]; then
            pass "${ci_stanza} is a classInfo input"
        else
            completion_issue "${ci_stanza} has apic_input_type '${ci_type}', expected classInfo"
        fi
        case "${ci_disabled}" in
            0|false|False|"") pass "${ci_stanza} is enabled" ;;
            *) completion_issue "${ci_stanza} is disabled" ;;
        esac
        ci_expected=()
        read -r -a ci_expected <<< "${EXPECT_CLASSES:-${ci_args}}"
        ci_seen=$(rest_oneshot_search "$SK" "$SPLUNK_URI" \
            "search index=${CLASSINFO_INDEX} sourcetype=\"cisco:dc:aci:class\" source=\"${ci_stanza}\" earliest=-24h | stats values(component) AS components | eval components=mvjoin(components, \" \")" \
            "components" 2>/dev/null || echo "0")
        [[ "${ci_seen}" == "0" ]] && ci_seen=""
        ci_missing=""
        for ci_class in "${ci_expected[@]+"${ci_expected[@]}"}"; do
            if [[ " ${ci_args} " != *" ${ci_class} "* ]]; then
                completion_issue "Class '${ci_class}' is not configured in ${ci_stanza} apic_arguments"
            fi
            if [[ " ${ci_seen} " == *" ${ci_class} "* ]]; then
                pass "Class '${ci_class}' has cisco:dc:aci:class events in index '${CLASSINFO_INDEX}' (last 24h)"
            else
                ci_missing="${ci_missing:+${ci_missing} }${ci_class}"
            fi
        done
        if [[ -z "${ci_seen}" ]]; then
            completion_issue "No cisco:dc:aci:class events from ${ci_stanza} in index '${CLASSINFO_INDEX}' in the last 24 hours"
        elif [[ -n "${ci_missing}" ]]; then
            warn "No events in the last 24 hours for: ${ci_missing} (a class with no objects in the fabric produces no events)"
        fi
    fi
fi

log ""
log "--- Settings ---"
ssl_verify=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_dc_networking_app_for_splunk_settings" "additional_parameters" "verify_ssl" 2>/dev/null || true)
if [[ "${ssl_verify}" == "True" || "${ssl_verify}" == "1" ]]; then
    pass "SSL verification is enabled"
else
    warn "SSL verification is disabled (verify_ssl = ${ssl_verify})"
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
