#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"

TARGET="all"
SEARCH_VERIFY=false
SEARCH_WAIT_SECONDS=10
SC4S_PORT="601"
SC4SNMP_PORT="162"
SC4S_TOKEN_NAME="sc4s"
SC4SNMP_TOKEN_NAME="sc4snmp"

PASS=0
WARN=0
FAIL=0
SK=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
SC4S / SC4SNMP Live Smoke Test

Usage: $(basename "$0") [OPTIONS]

Options:
  --target sc4s|sc4snmp|all     Which live smoke flow to run (default: all)
  --search-verify               Also require the marker to appear in Splunk search
  --search-wait-seconds N       Wait time before marker search (default: 10)
  --sc4s-port PORT              SC4S TCP syslog port (default: 601)
  --sc4snmp-port PORT           SC4SNMP trap port (default: 162)
  --sc4s-token-name NAME        SC4S HEC token name (default: sc4s)
  --sc4snmp-token-name NAME     SC4SNMP HEC token name (default: sc4snmp)
  --help                        Show this help

Behavior:
  Validates Splunk-side prerequisites, checks the live collector runtime over SSH,
  sends one marked test event per target, and verifies collector-side handling.
  Remote runtime checks require the SSH user to be root or to have passwordless
  sudo. Search verification is optional because some hosts accept HEC writes but
  do not surface those events to local search reliably.
EOF
    exit "${exit_code}"
}

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) require_arg "$1" $# || exit 1; TARGET="$2"; shift 2 ;;
        --search-verify) SEARCH_VERIFY=true; shift ;;
        --search-wait-seconds) require_arg "$1" $# || exit 1; SEARCH_WAIT_SECONDS="$2"; shift 2 ;;
        --sc4s-port) require_arg "$1" $# || exit 1; SC4S_PORT="$2"; shift 2 ;;
        --sc4snmp-port) require_arg "$1" $# || exit 1; SC4SNMP_PORT="$2"; shift 2 ;;
        --sc4s-token-name) require_arg "$1" $# || exit 1; SC4S_TOKEN_NAME="$2"; shift 2 ;;
        --sc4snmp-token-name) require_arg "$1" $# || exit 1; SC4SNMP_TOKEN_NAME="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice "${TARGET}" sc4s sc4snmp all

if [[ ! "${SEARCH_WAIT_SECONDS}" =~ ^[0-9]+$ ]] || (( SEARCH_WAIT_SECONDS < 0 )); then
    log "ERROR: --search-wait-seconds must be a non-negative integer."
    exit 1
fi

if [[ ! "${SC4S_PORT}" =~ ^[0-9]+$ ]] || (( SC4S_PORT < 1 || SC4S_PORT > 65535 )); then
    log "ERROR: --sc4s-port must be between 1 and 65535."
    exit 1
fi

if [[ ! "${SC4SNMP_PORT}" =~ ^[0-9]+$ ]] || (( SC4SNMP_PORT < 1 || SC4SNMP_PORT > 65535 )); then
    log "ERROR: --sc4snmp-port must be between 1 and 65535."
    exit 1
fi

load_splunk_credentials >/dev/null
load_splunk_ssh_credentials >/dev/null
SK="$(get_session_key "${SPLUNK_URI}")" || {
    log "ERROR: Could not authenticate to Splunk REST API."
    exit 1
}

REMOTE_HOST="${SPLUNK_SSH_HOST}"
REMOTE_PORT="${SPLUNK_SSH_PORT}"
REMOTE_USER="${SPLUNK_SSH_USER}"

run_remote_root() {
    local remote_cmd="$1"
    local remote_payload remote_shell pass_file rc
    remote_payload="$(printf '%q' "${remote_cmd}")"

    if [[ "${REMOTE_USER}" == "root" ]]; then
        remote_shell="sh -lc ${remote_payload}"
    else
        remote_shell="sudo -n sh -lc ${remote_payload}"
    fi

    if ! command_exists sshpass; then
        log "ERROR: sshpass is required for SSH-based live smoke checks."
        return 1
    fi

    pass_file="$(hbs_make_sshpass_file)"
    # Use accept-new + a per-smoke-run known_hosts file so the host key is
    # pinned for the duration of the run. SMOKE_KNOWN_HOSTS_FILE may be
    # pre-populated by the operator to lock the run to a specific key.
    local known_hosts_file="${SMOKE_KNOWN_HOSTS_FILE:-${HOME}/.ssh/sc4x-smoke-known-hosts}"
    mkdir -p "$(dirname "${known_hosts_file}")"
    sshpass -f "${pass_file}" ssh \
        -p "${REMOTE_PORT}" \
        -o StrictHostKeyChecking=accept-new \
        -o UserKnownHostsFile="${known_hosts_file}" \
        "${REMOTE_USER}@${REMOTE_HOST}" \
        "${remote_shell}"
    rc=$?
    rm -f "${pass_file}"
    return "${rc}"
}

search_marker_count() {
    local index_name="$1" marker="$2"
    rest_oneshot_search "${SK}" "${SPLUNK_URI}" "search index=${index_name} \"${marker}\" | stats count as count" "count" 2>/dev/null || echo "0"
}

sc4s_hec_processed_total() {
    run_remote_root "docker exec SC4S sh -lc 'syslog-ng-ctl stats'" | python3 -c '
import sys
total = 0
for raw in sys.stdin:
    parts = [part.strip() for part in raw.strip().split(";")]
    if len(parts) < 6:
        continue
    if parts[0] != "destination":
        continue
    if not parts[1].startswith("d_hec_fmt"):
        continue
    if parts[4] != "processed":
        continue
    try:
        total += int(parts[5])
    except Exception:
        pass
print(total, end="")
'
}

run_sc4s_smoke() {
    local marker before_count after_count search_count

    log "=== SC4S Live Smoke ==="
    if ! bash "${PROJECT_ROOT}/skills/splunk-connect-for-syslog-setup/scripts/validate.sh" --hec-token-name "${SC4S_TOKEN_NAME}"; then
        fail "SC4S validation failed before smoke send"
        log ""
        return 0
    fi
    pass "SC4S validation succeeded"

    if ! command_exists nc; then
        fail "nc is required for the SC4S smoke send"
        log ""
        return 0
    fi

    if ! run_remote_root "docker inspect SC4S >/dev/null 2>&1"; then
        fail "Remote SC4S container 'SC4S' was not found"
        log ""
        return 0
    fi
    pass "Remote SC4S container is present"

    before_count="$(sc4s_hec_processed_total)"
    marker="CODEX_SC4S_SMOKE_$(date +%Y%m%d_%H%M%S)"
    printf '<134>1 %s codex-smoke sc4s-live-smoke 1000 ID47 - %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${marker}" \
        | nc -w 2 "${REMOTE_HOST}" "${SC4S_PORT}"
    sleep 3
    after_count="$(sc4s_hec_processed_total)"

    if [[ "${before_count}" =~ ^[0-9]+$ && "${after_count}" =~ ^[0-9]+$ ]] && (( after_count > before_count )); then
        pass "SC4S HEC processed count increased from ${before_count} to ${after_count}"
    else
        fail "SC4S HEC processed count did not increase after sending marker ${marker}"
    fi

    if [[ "${SEARCH_VERIFY}" == "true" ]]; then
        sleep "${SEARCH_WAIT_SECONDS}"
        search_count="$(search_marker_count "sc4s" "${marker}")"
        if [[ "${search_count}" =~ ^[0-9]+$ ]] && (( search_count > 0 )); then
            pass "Splunk search found SC4S marker ${marker} in index sc4s"
        else
            fail "Splunk search did not find SC4S marker ${marker} in index sc4s"
        fi
    else
        warn "SC4S search verification skipped; use --search-verify to require marker visibility in index sc4s"
    fi
    log ""
}

run_sc4snmp_smoke() {
    local marker search_count sender_logs

    log "=== SC4SNMP Live Smoke ==="
    if ! bash "${PROJECT_ROOT}/skills/splunk-connect-for-snmp-setup/scripts/validate.sh" --hec-token-name "${SC4SNMP_TOKEN_NAME}"; then
        fail "SC4SNMP validation failed before trap send"
        log ""
        return 0
    fi
    pass "SC4SNMP validation succeeded"

    if ! command_exists snmptrap; then
        fail "snmptrap is required for the SC4SNMP smoke send"
        log ""
        return 0
    fi

    if ! run_remote_root "docker inspect SC4SNMP-worker-sender >/dev/null 2>&1"; then
        fail "Remote SC4SNMP worker sender container was not found"
        log ""
        return 0
    fi
    pass "Remote SC4SNMP worker sender is present"

    marker="CODEX_SC4SNMP_SMOKE_$(date +%Y%m%d_%H%M%S)"
    snmptrap -v 2c -c public "${REMOTE_HOST}:${SC4SNMP_PORT}" '' 1.3.6.1.6.3.1.1.5.1 1.3.6.1.2.1.1.5.0 s "${marker}" >/dev/null
    sleep 5
    sender_logs="$(run_remote_root "docker logs --since 60s SC4SNMP-worker-sender 2>&1" || true)"

    if printf '%s' "${sender_logs}" | grep -Fq "${marker}"; then
        pass "SC4SNMP sender logs contain marker ${marker}"
    else
        fail "SC4SNMP sender logs did not contain marker ${marker}"
    fi

    if [[ "${SEARCH_VERIFY}" == "true" ]]; then
        sleep "${SEARCH_WAIT_SECONDS}"
        search_count="$(search_marker_count "netops" "${marker}")"
        if [[ "${search_count}" =~ ^[0-9]+$ ]] && (( search_count > 0 )); then
            pass "Splunk search found SC4SNMP marker ${marker} in index netops"
        else
            fail "Splunk search did not find SC4SNMP marker ${marker} in index netops"
        fi
    else
        warn "SC4SNMP search verification skipped; use --search-verify to require marker visibility in index netops"
    fi
    log ""
}

if [[ "${TARGET}" == "sc4s" || "${TARGET}" == "all" ]]; then
    run_sc4s_smoke
fi

if [[ "${TARGET}" == "sc4snmp" || "${TARGET}" == "all" ]]; then
    run_sc4snmp_smoke
fi

log "=== Smoke Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"

if (( FAIL > 0 )); then
    exit 1
fi
