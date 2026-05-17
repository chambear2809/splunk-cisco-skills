#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"

MCP_TOOLS_JSON=""
PASSTHRU_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tools-json)
            require_arg "$1" $# || exit 1
            MCP_TOOLS_JSON="$2"
            shift 2
            ;;
        --allow-legacy-kv|--override-collisions)
            PASSTHRU_ARGS+=("$1")
            shift
            ;;
        *)
            log "ERROR: Unknown option: $1"
            exit 1
            ;;
    esac
done

if [[ -z "${MCP_TOOLS_JSON}" ]]; then
    log "ERROR: --tools-json is required."
    exit 1
fi
if [[ ! -f "${MCP_TOOLS_JSON}" ]]; then
    log "ERROR: MCP tools file not found at ${MCP_TOOLS_JSON}"
    exit 1
fi

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SESSION_KEY="$(get_session_key "${SPLUNK_URI}")" || {
    log "ERROR: Could not authenticate to Splunk."
    exit 1
}

if ! rest_check_app "${SESSION_KEY}" "${SPLUNK_URI}" "Splunk_MCP_Server"; then
    log "ERROR: Splunk MCP Server app not installed"
    exit 1
fi

TOOL_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1], encoding="utf-8")).get("tools", [])))' "${MCP_TOOLS_JSON}")"
log "Session key obtained. Loading ${TOOL_COUNT} MCP tools..."

export __SPLUNK_SK="${SESSION_KEY}"
splunk_export_python_tls_env || {
    log "ERROR: Could not configure TLS settings for MCP tool loading."
    exit 1
}

python3 "${SCRIPT_DIR}/load_mcp_tools.py" \
    --tools-json "${MCP_TOOLS_JSON}" \
    --splunk-uri "${SPLUNK_URI}" \
    --app-context "Splunk_MCP_Server" \
    "${PASSTHRU_ARGS[@]}"

log "MCP tool loading complete."
