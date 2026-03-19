#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

MCP_TOOLS_JSON="${SCRIPT_DIR}/../mcp_tools.json"
KV_COLLECTION="mcp_tools"
KV_ENABLED_COLLECTION="mcp_tools_enabled"
APP_CONTEXT="Splunk_MCP_Server"

if [[ ! -f "${MCP_TOOLS_JSON}" ]]; then
    log "ERROR: MCP tools file not found at ${MCP_TOOLS_JSON}"
    exit 1
fi

load_splunk_credentials

SESSION_KEY=$(get_session_key "${SPLUNK_URI}")

if ! rest_check_app "${SESSION_KEY}" "${SPLUNK_URI}" "Splunk_MCP_Server"; then
    log "ERROR: Splunk MCP Server app not installed"
    exit 1
fi

log "Session key obtained. Loading MCP tools..."

TOOL_COUNT=$(python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
print(len(data.get('tools', [])))
" "${MCP_TOOLS_JSON}")

log "Found ${TOOL_COUNT} tools to load."

export __SPLUNK_SK="${SESSION_KEY}"
python3 - "${MCP_TOOLS_JSON}" "${SPLUNK_URI}" "${APP_CONTEXT}" \
          "${KV_COLLECTION}" "${KV_ENABLED_COLLECTION}" <<'PYEOF'
import json
import os
import sys
import urllib.request
import urllib.error
import ssl

tools_file, splunk_uri, app, kv_coll, kv_enabled = sys.argv[1:6]
session_key = os.environ.pop("__SPLUNK_SK", "")

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
        print(f"  SKIP: tool missing _key or name")
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
