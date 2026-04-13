#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

ENABLE_LIST=""
DISABLE_LIST=""
LIST_STREAMS=false
TARGET_INDEX=""

STREAM_API_BASE=""
STREAM_CONFIGURE_ROLE=""

usage() {
    cat <<EOF
Splunk Stream Protocol Configuration

Usage: $(basename "$0") [OPTIONS]

Options:
  --enable PROTOCOLS    Comma-separated list of protocols to enable
  --disable PROTOCOLS   Comma-separated list of protocols to disable
  --index INDEX         Target index for enabled streams (optional)
  --list                List all available streams and their status
  --help                Show this help

Examples:
  $(basename "$0") --list
  $(basename "$0") --enable dns,http,tcp,udp
  $(basename "$0") --enable netflow --index netflow
  $(basename "$0") --disable irc,xmpp

Environment:
  SPLUNK_SEARCH_API_URI Search-tier REST URI (legacy alias: SPLUNK_URI)
  SPLUNK_WEB_URL        Splunk Web URI for Stream API (default: derived from the search-tier REST URI)

Splunk credentials are read from the project-root credentials file automatically.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh

This script manages search-tier Stream protocol definitions only.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --enable) require_arg "$1" $# || exit 1; ENABLE_LIST="$2"; shift 2 ;;
        --disable) require_arg "$1" $# || exit 1; DISABLE_LIST="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; TARGET_INDEX="$2"; shift 2 ;;
        --list) LIST_STREAMS=true; shift ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

capitalize_word() {
    local word="${1:-}"
    if [[ -z "${word}" ]]; then
        printf ''
        return 0
    fi
    printf '%s%s' "$(printf '%s' "${word:0:1}" | tr '[:lower:]' '[:upper:]')" "${word:1}"
}

_get_session_key() {
    load_splunk_credentials || return 1
    set_stream_api_base || return 1
    SK=$(get_session_key "${SPLUNK_URI}") || return 1
}

stream_configure_role() {
    if [[ -n "${STREAM_CONFIGURE_ROLE:-}" ]]; then
        printf '%s' "${STREAM_CONFIGURE_ROLE}"
        return 0
    fi

    STREAM_CONFIGURE_ROLE="$(resolve_splunk_target_role 2>/dev/null || true)"
    printf '%s' "${STREAM_CONFIGURE_ROLE}"
}

stream_configure_preflight_role_checks() {
    local role

    role="$(stream_configure_role)"
    [[ -z "${role}" || "${role}" == "search-tier" ]] && return 0

    log "ERROR: Stream protocol configuration is search-tier only and cannot run against role '${role}'."
    log "Run this script against the search tier where splunk_app_stream is installed."
    exit 1
}

set_stream_api_base() {
    local splunk_web_url=""

    if [[ -z "${SPLUNK_URI:-}" ]]; then
        load_splunk_connection_settings || return 1
    fi

    splunk_web_url="${SPLUNK_WEB_URL:-}"
    if [[ -z "${splunk_web_url}" ]]; then
        if is_splunk_cloud; then
            splunk_web_url="${SPLUNK_URI/8089/443}"
        else
            splunk_web_url="${SPLUNK_URI/8089/8000}"
        fi
    fi

    STREAM_API_BASE="${splunk_web_url}/en-US/custom/splunk_app_stream"
}

# Try to fetch stream list via Stream REST API or KV Store.
# Returns success and prints JSON to streams_json when available.
check_stream_api() {
    local resp http_code

    # Try KV Store first (uses management port 8089, works with session key)
    resp=$(splunk_curl "${SK}" "${SPLUNK_URI}/servicesNS/nobody/splunk_app_stream/storage/collections/data/streams?output_mode=json" -w '\n%{http_code}' 2>/dev/null) || true
    http_code=$(echo "${resp}" | tail -1)
    if [[ "${http_code}" == "200" ]]; then
        streams_json=$(echo "${resp}" | sed '$d')
        if echo "${streams_json}" | python3 -c "import json,sys; d=json.load(sys.stdin); isinstance(d, list) or isinstance(d, dict)" 2>/dev/null; then
            return 0
        fi
    fi

    # Try Stream Web API (session key may work with some Splunk setups)
    resp=$(splunk_curl "${SK}" "${STREAM_API_BASE}/streams?output_mode=json" -w '\n%{http_code}' 2>/dev/null) || true
    http_code=$(echo "${resp}" | tail -1)
    if [[ "${http_code}" == "200" ]]; then
        streams_json=$(echo "${resp}" | sed '$d')
        if echo "${streams_json}" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
            return 0
        fi
    fi

    return 1
}

list_all_streams() {
    log "=== Available Streams ==="

    if ! check_stream_api; then
        log "Stream configuration requires local access or the Stream Web UI."
        log "The Stream REST API at ${STREAM_API_BASE}/streams could not be reached."
        log "Use Splunk Web: Stream app -> Protocol Streams to enable/disable streams."
        log "Or run this script from the Splunk host with local filesystem access."
        exit 1
    fi

    printf "  %-35s %-10s %-10s\n" "STREAM" "ENABLED" "INDEX"
    printf "  %-35s %-10s %-10s\n" "------" "-------" "-----"

    echo "${streams_json}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data if isinstance(data, list) else data.get('entry', data.get('streams', []))
    if isinstance(entries, dict):
        entries = list(entries.values())
    for e in (entries or []):
        if isinstance(e, dict):
            name = e.get('id') or e.get('name') or e.get('_key', '')
            if not name:
                continue
            enabled = e.get('enabled', False)
            idx = e.get('index') or ''
            print(f\"  {str(name):<35} {'YES' if enabled else 'no':<10} {str(idx):<10}\")
        elif isinstance(e, str):
            print(f\"  {e:<35} {'?':<10} {'':<10}\")
except Exception as ex:
    print(f'  Parse error: {ex}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null || {
        log "Could not parse stream list. Raw response (first 500 chars):"
        echo "${streams_json}" | head -c 500
        exit 1
    }
}

# Update stream via KV Store (works with session key on port 8089)
kvstore_update_stream() {
    local stream_id="$1"
    local enable="$2"
    local index="${3:-}"
    local kv_url="${SPLUNK_URI}/servicesNS/nobody/splunk_app_stream/storage/collections/data/streams"
    local encoded_key
    encoded_key=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "${stream_id}" 2>/dev/null) || echo "${stream_id}"

    local doc
    doc=$(splunk_curl "${SK}" "${kv_url}/${encoded_key}?output_mode=json" 2>/dev/null) || true
    if [[ -z "${doc}" ]]; then
        log "  WARNING: Stream '${stream_id}' not found in KV Store"
        return 1
    fi

    local body
    body=$(echo "${doc}" | python3 -c "
import json, sys
try:
    enable_val = sys.argv[1]
    index_val = sys.argv[2]
    d = json.load(sys.stdin)
    doc = d[0] if isinstance(d, list) and d else (d if isinstance(d, dict) else {})
    doc['enabled'] = (enable_val == 'true')
    if index_val:
        doc['index'] = index_val
    print(json.dumps(doc))
except Exception as e:
    sys.exit(1)
" "${enable}" "${index}" 2>/dev/null) || return 1

    local http_code
    http_code=$(splunk_curl_post "${SK}" "${body}" "${kv_url}/${encoded_key}" \
        -X POST \
        -H "Content-Type: application/json" \
        -o /dev/null -w '%{http_code}' 2>/dev/null) || echo "000"

    if [[ "${http_code}" == "200" ]]; then
        return 0
    fi
    return 1
}

stream_enable_disable() {
    local stream_id="$1"
    local enable="$2"
    local index="${3:-}"
    local action
    [[ "${enable}" == "true" ]] && action="enable" || action="disable"

    # Try Stream Web API first (may require cookies on some setups)
    local endpoint="${STREAM_API_BASE}/streams/${stream_id}/${action}"
    local http_code
    http_code=$(splunk_curl "${SK}" -X PUT "${endpoint}" \
        -H "Content-Type: application/json" \
        -H "X-Requested-With: XMLHttpRequest" \
        -o /dev/null -w '%{http_code}' 2>/dev/null) || echo "000"

    if [[ "${http_code}" == "200" ]]; then
        log "  $(capitalize_word "${action}")d: ${stream_id}"
        return 0
    fi

    # Fallback: update via KV Store
    if kvstore_update_stream "${stream_id}" "${enable}" "${index}"; then
        log "  $(capitalize_word "${action}")d: ${stream_id} (via KV Store)"
        return 0
    fi

    log "  WARNING: Could not ${action} ${stream_id}. Use Stream Web UI: Stream app -> Protocol Streams."
    return 1
}

enable_streams() {
    log "=== Enabling Streams ==="
    if ! check_stream_api; then
        log "Stream API unavailable. Use Stream Web UI to enable streams."
        exit 1
    fi

    IFS=',' read -ra protocols <<< "${ENABLE_LIST}"
    for proto in "${protocols[@]}"; do
        proto=$(echo "${proto}" | tr -d ' ')
        [[ -z "${proto}" ]] && continue
        stream_enable_disable "${proto}" "true" "${TARGET_INDEX}" || true
    done
    log "Stream enablement complete."
}

disable_streams() {
    log "=== Disabling Streams ==="
    if ! check_stream_api; then
        log "Stream API unavailable. Use Stream Web UI to disable streams."
        exit 1
    fi

    IFS=',' read -ra protocols <<< "${DISABLE_LIST}"
    for proto in "${protocols[@]}"; do
        proto=$(echo "${proto}" | tr -d ' ')
        [[ -z "${proto}" ]] && continue
        stream_enable_disable "${proto}" "false" "" || true
    done
    log "Stream disablement complete."
}

main() {
    warn_if_current_skill_role_unsupported
    stream_configure_preflight_role_checks
    _get_session_key || exit 1

    if $LIST_STREAMS; then
        list_all_streams
        exit 0
    fi

    if [[ -z "${ENABLE_LIST}" && -z "${DISABLE_LIST}" ]]; then
        log "ERROR: Specify --enable, --disable, or --list"
        usage
    fi

    if [[ -n "${ENABLE_LIST}" ]]; then
        enable_streams
    fi

    if [[ -n "${DISABLE_LIST}" ]]; then
        disable_streams
    fi

    log "$(log_platform_restart_guidance "stream definition changes")"
}

main
