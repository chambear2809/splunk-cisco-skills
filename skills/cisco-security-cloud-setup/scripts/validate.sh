#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="CiscoSecurityCloud"
SETTINGS_CONF="ciscosecuritycloud_settings"
PRODUCTS_FILE="${SCRIPT_DIR}/../products.json"
PRODUCT=""
INPUT_TYPE=""
INPUT_NAME=""
SK=""
SKIP_DATA_FLOW=false
DATA_FLOW_EARLIEST="-1h@h"

PASS=0
FAIL=0
WARN=0

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }

usage() {
    cat >&2 <<EOF
Cisco Security Cloud Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --product NAME             Validate one specific product flow
  --input-type TYPE          Validate one specific input type
  --name NAME                Validate one specific input name (requires --input-type)
  --skip-data-flow           Skip the per-index 'tstats' event-flow probe
  --data-flow-earliest TIME  Earliest time for the event-flow probe (default: -1h@h)
  --help                     Show this help
EOF
    exit "${1:-0}"
}

handler_count() {
    local handler="$1"
    rest_list_ta_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "$handler" \
        | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(len(data.get('entry', [])))
except Exception:
    print(0)
" 2>/dev/null || echo "0"
}

handler_has_stanza() {
    local handler="$1" stanza="$2"
    rest_list_ta_stanzas "$SK" "$SPLUNK_URI" "$APP_NAME" "$handler" \
        | python3 -c "
import json, sys
target = sys.argv[1]
try:
    data = json.load(sys.stdin)
    for entry in data.get('entry', []):
        if entry.get('name') == target:
            print('yes', end='')
            raise SystemExit(0)
except Exception:
    pass
print('no', end='')
" "${stanza}" 2>/dev/null || echo "no"
}

validate_handler() {
    local input_type="$1"
    local handler="${APP_NAME}_${input_type}"
    local count
    count="$(handler_count "${handler}")"
    if [[ "${count}" -gt 0 ]]; then
        pass "${input_type}: ${count} configured stanza(s)"
    else
        warn "${input_type}: no configured stanzas"
    fi
}

product_input_type() {
    python3 - "$1" "${PRODUCTS_FILE}" <<'PY'
import json
import sys
from pathlib import Path

product = sys.argv[1]
products = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
entry = products.get(product)
if entry:
    print(entry.get("input_type", ""), end="")
PY
}

# Map a Cisco Security Cloud input_type to its default Splunk index, as
# declared in products.json. Returns an empty string if no default index is
# defined for the input type (e.g. operator overrides or non-event inputs).
input_type_default_index() {
    python3 - "$1" "${PRODUCTS_FILE}" <<'PY'
import json
import sys
from pathlib import Path

target = sys.argv[1]
products = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
for entry in products.values():
    if entry.get("input_type") == target:
        idx = entry.get("defaults", {}).get("index", "")
        if idx:
            print(idx, end="")
        break
PY
}

probe_index_event_flow() {
    local idx="$1"
    local label="$2"
    local count
    count=$(rest_oneshot_search "$SK" "$SPLUNK_URI" \
        "| tstats count where index=${idx} earliest=${DATA_FLOW_EARLIEST} latest=now" \
        "count" 2>/dev/null || echo "0")
    if [[ "${count}" =~ ^[0-9]+$ ]] && [[ "${count}" -gt 0 ]]; then
        pass "${label} index '${idx}' has ${count} events since ${DATA_FLOW_EARLIEST}"
    else
        warn "${label} index '${idx}' has no events since ${DATA_FLOW_EARLIEST} (may be normal if just configured)"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --product) require_arg "$1" $# || exit 1; PRODUCT="$2"; shift 2 ;;
        --input-type) require_arg "$1" $# || exit 1; INPUT_TYPE="$2"; shift 2 ;;
        --name) require_arg "$1" $# || exit 1; INPUT_NAME="$2"; shift 2 ;;
        --skip-data-flow) SKIP_DATA_FLOW=true; shift ;;
        --data-flow-earliest) require_arg "$1" $# || exit 1; DATA_FLOW_EARLIEST="$2"; shift 2 ;;
        --help) usage ;;
        *) log "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -n "${PRODUCT}" && -n "${INPUT_TYPE}" ]]; then
    log "ERROR: Use either --product or --input-type, not both."
    exit 1
fi

if [[ -n "${PRODUCT}" ]]; then
    INPUT_TYPE="$(product_input_type "${PRODUCT}")"
    if [[ -z "${INPUT_TYPE}" ]]; then
        log "ERROR: Unknown product '${PRODUCT}'."
        exit 1
    fi
fi

if [[ -n "${INPUT_NAME}" && -z "${INPUT_TYPE}" ]]; then
    log "ERROR: --name requires --input-type."
    exit 1
fi

log "=== Cisco Security Cloud Validation ==="
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
        fail "App not found — install Cisco Security Cloud first"
    fi
fi

if [[ -n "${SK:-}" ]]; then
log ""
log "--- App Settings ---"
loglevel=$(rest_get_conf_value "$SK" "$SPLUNK_URI" "$APP_NAME" "${SETTINGS_CONF}" "logging" "loglevel" 2>/dev/null || true)
if [[ -n "${loglevel}" ]]; then
    pass "Log level configured: ${loglevel}"
else
    warn "Log level not configured in ${SETTINGS_CONF}.conf"
fi

log ""
if [[ -n "${INPUT_TYPE}" && -n "${INPUT_NAME}" ]]; then
    log "--- Specific Input ---"
    handler="${APP_NAME}_${INPUT_TYPE}"
    if [[ "$(handler_has_stanza "${handler}" "${INPUT_NAME}")" == "yes" ]]; then
        pass "${INPUT_TYPE} '${INPUT_NAME}' is configured"
    else
        fail "${INPUT_TYPE} '${INPUT_NAME}' not found"
    fi
elif [[ -n "${INPUT_TYPE}" ]]; then
    log "--- Product/Input Type ---"
    validate_handler "${INPUT_TYPE}"
    if ! $SKIP_DATA_FLOW; then
        idx="$(input_type_default_index "${INPUT_TYPE}")"
        if [[ -n "${idx}" ]] && [[ "$(handler_count "${APP_NAME}_${INPUT_TYPE}")" -gt 0 ]]; then
            log ""
            log "--- Data Flow ---"
            probe_index_event_flow "${idx}" "${INPUT_TYPE}"
        fi
    fi
else
    log "--- Configured Inputs ---"
    declare -a CONFIGURED_TYPES=()
    total=0
    for type in \
        sbg_duo_input \
        cisco_sma_input \
        sbg_xdr_input \
        sbg_sfw_syslog_input \
        sbg_sfw_asa_syslog_input \
        sbg_fw_estreamer_input \
        sbg_multicloud_defense_input \
        sbg_sfw_api_input \
        sbg_etd_input \
        sbg_sna_input \
        sbg_se_input \
        sbg_cvi_input \
        sbg_cii_input \
        sbg_cii_aws_s3_input \
        sbg_ai_defense_input \
        sbg_isovalent_input \
        sbg_isovalent_edge_processor_input \
        sbg_nvm_input \
        sbg_sw_input; do
        validate_handler "${type}"
        count="$(handler_count "${APP_NAME}_${type}")"
        total=$((total + count))
        if [[ "${count}" -gt 0 ]]; then
            CONFIGURED_TYPES+=("${type}")
        fi
    done
    if [[ "${total}" -gt 0 ]]; then
        pass "At least one Cisco Security Cloud input is configured (${total} total)"
    else
        warn "No Cisco Security Cloud inputs are configured yet"
    fi

    if ! $SKIP_DATA_FLOW && [[ "${#CONFIGURED_TYPES[@]}" -gt 0 ]]; then
        log ""
        log "--- Data Flow (configured inputs only) ---"
        # Probe one default index per configured input type. Operators who
        # remap to non-default indexes will only see the warn path here; the
        # configuration check above is still authoritative for "configured?".
        declare -A SEEN_INDEXES=()
        for type in "${CONFIGURED_TYPES[@]}"; do
            idx="$(input_type_default_index "${type}")"
            if [[ -z "${idx}" ]]; then
                continue
            fi
            if [[ -n "${SEEN_INDEXES[${idx}]:-}" ]]; then
                continue
            fi
            SEEN_INDEXES["${idx}"]=1
            probe_index_event_flow "${idx}" "${type}"
        done
    fi
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
