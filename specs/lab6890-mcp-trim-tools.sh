#!/usr/bin/env bash
# Disable all MCP tools except splunk_get_info for lab completion allowlist.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export SPLUNK_PROFILE="${SPLUNK_PROFILE:-lab_6890}"

bash -lc "
  set -euo pipefail
  source '${REPO_ROOT}/skills/shared/lib/credential_helpers.sh'
  load_splunk_credentials
  SK=\$(get_session_key \"\${SPLUNK_URI}\")
  TOOLS_JSON=\$(splunk_curl \"\${SK}\" \"\${SPLUNK_URI}/servicesNS/nobody/Splunk_MCP_Server/mcp_tools?output_mode=json\")
  python3 - \"\${SK}\" \"\${SPLUNK_URI}\" \"\${TOOLS_JSON}\" <<'PY'
import json, subprocess, sys

sk, uri, tools_json = sys.argv[1], sys.argv[2], sys.argv[3]
keep = 'splunk_get_info'
payload = json.loads(tools_json)
for tool in payload.get('tools', []):
    name = tool.get('name', '')
    tool_id = tool.get('tool_id', '')
    if not tool_id or name == keep:
        continue
    body = json.dumps({'tool_id': tool_id, 'enabled': False})
    proc = subprocess.run(
        ['curl', '-sk', '-u', f'splunk:{sk}', '-X', 'POST',
         f'{uri}/servicesNS/nobody/Splunk_MCP_Server/mcp_tools?output_mode=json',
         '-H', 'Content-Type: application/json', '-d', body],
        capture_output=True, text=True, check=False,
    )
    msg = json.loads(proc.stdout).get('message', proc.stdout[:80]) if proc.stdout else proc.stderr[:80]
    print(f'disabled {name}: {msg}')
proc = subprocess.run(
    ['curl', '-sk', '-u', f'splunk:{sk}',
     f'{uri}/servicesNS/nobody/Splunk_MCP_Server/mcp_tools?output_mode=json'],
    capture_output=True, text=True, check=False,
)
remaining = [t['name'] for t in json.loads(proc.stdout).get('tools', [])]
print('tools still listed:', remaining)
PY
"
