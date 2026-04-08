#!/usr/bin/env bash
# Shared MCP KV store upload helpers.
# Sourced by per-skill load_mcp_tools.sh scripts.
#
# Requires: credential_helpers.sh (and transitively rest_helpers.sh)

[[ -n "${_MCP_HELPERS_LOADED:-}" ]] && return 0
_MCP_HELPERS_LOADED=true

# Load MCP tool definitions from a JSON file into Splunk KV collections.
#
# Usage: mcp_load_tools <tools_json_path> [app_context]
#
# Expects Splunk credentials already loaded and SPLUNK_URI set.
mcp_load_tools() {
    local tools_json="$1"
    local app_context="${2:-Splunk_MCP_Server}"
    local kv_collection="${3:-mcp_tools}"
    local kv_enabled_collection="${4:-mcp_tools_enabled}"
    local sk

    if [[ ! -f "${tools_json}" ]]; then
        log "ERROR: MCP tools file not found at ${tools_json}"
        return 1
    fi

    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; return 1; }
    sk=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not obtain Splunk session key. Check credentials."; return 1; }

    if ! rest_check_app "${sk}" "${SPLUNK_URI}" "${app_context}"; then
        log "ERROR: Splunk MCP Server app not installed"
        return 1
    fi

    log "Session key obtained. Loading MCP tools..."

    local tool_count
    tool_count=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
print(len(data.get('tools', [])))
" "${tools_json}")

    log "Found ${tool_count} tools to load."

    export __SPLUNK_SK="${sk}"
    splunk_export_python_tls_env || { log "ERROR: Could not configure TLS settings for MCP tool loading."; return 1; }
    python3 - "${tools_json}" "${SPLUNK_URI}" "${app_context}" \
              "${kv_collection}" "${kv_enabled_collection}" <<'PYEOF'
import json
import os
import ssl
import sys
import urllib.error
import urllib.request

tools_file, splunk_uri, app, kv_coll, kv_enabled = sys.argv[1:6]
session_key = os.environ.pop("__SPLUNK_SK", "")
tls_mode = os.environ.pop("__SPLUNK_TLS_MODE", "insecure")
tls_ca_cert = os.environ.pop("__SPLUNK_TLS_CA_CERT", "")

if tls_mode == "ca-cert":
    ctx = ssl.create_default_context(cafile=tls_ca_cert)
elif tls_mode == "verify":
    ctx = ssl.create_default_context()
else:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

headers = {
    "Authorization": f"Splunk {session_key}",
    "Content-Type": "application/json",
}

with open(tools_file) as f:
    data = json.load(f)

tools = data.get("tools", [])
loaded = 0
enabled = 0

for tool in tools:
    key = tool.get("_key", "")
    name = tool.get("name", "")
    if not key or not name:
        print("  SKIP: tool missing _key or name")
        continue

    payload = json.dumps(tool).encode("utf-8")

    url = f"{splunk_uri}/servicesNS/nobody/{app}/storage/collections/data/{kv_coll}/{key}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, context=ctx)
        print(f"  UPDATED: {name} ({key})")
        loaded += 1
    except urllib.error.HTTPError as e:
        if e.code == 404:
            url_insert = f"{splunk_uri}/servicesNS/nobody/{app}/storage/collections/data/{kv_coll}"
            req_insert = urllib.request.Request(url_insert, data=payload, headers=headers, method="POST")
            try:
                urllib.request.urlopen(req_insert, context=ctx)
                print(f"  INSERTED: {name} ({key})")
                loaded += 1
            except urllib.error.HTTPError as e2:
                if e2.code == 409:
                    print(f"  EXISTS: {name} ({key})")
                    loaded += 1
                else:
                    print(f"  ERROR inserting {name}: {e2.code} {e2.read().decode()}")
        else:
            print(f"  ERROR updating {name}: {e.code} {e.read().decode()}")

    enable_payload = json.dumps({"_key": name, "tool_id": key}).encode("utf-8")
    enable_url = f"{splunk_uri}/servicesNS/nobody/{app}/storage/collections/data/{kv_enabled}/{name}"
    enable_req = urllib.request.Request(enable_url, data=enable_payload, headers=headers, method="POST")
    try:
        urllib.request.urlopen(enable_req, context=ctx)
        print(f"  ENABLED: {name}")
        enabled += 1
    except urllib.error.HTTPError as e:
        if e.code == 404:
            enable_url_insert = f"{splunk_uri}/servicesNS/nobody/{app}/storage/collections/data/{kv_enabled}"
            enable_req_insert = urllib.request.Request(enable_url_insert, data=enable_payload, headers=headers, method="POST")
            try:
                urllib.request.urlopen(enable_req_insert, context=ctx)
                print(f"  ENABLED: {name}")
                enabled += 1
            except urllib.error.HTTPError as e2:
                if e2.code == 409:
                    print(f"  ALREADY ENABLED: {name}")
                    enabled += 1
                else:
                    print(f"  ERROR enabling {name}: {e2.code}")
        else:
            print(f"  ERROR enabling {name}: {e.code}")

print(f"\nSummary: {loaded}/{len(tools)} tools loaded, {enabled}/{len(tools)} tools enabled")
PYEOF

    log "MCP tool loading complete."
}
