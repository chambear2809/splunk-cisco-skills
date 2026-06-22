#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/galileo-mcp-rendered"
RUN_PROBE=false

usage() {
    cat <<'EOF'
Galileo MCP Server rendered asset validation

Usage:
  bash skills/galileo-mcp-server-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --probe            Also run live no-secret MCP probe
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --probe|--live) RUN_PROBE=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

check_file() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        log "ERROR: Missing ${path}"
        exit 1
    fi
}

check_file "${OUTPUT_DIR}/metadata.json"
check_file "${OUTPUT_DIR}/mcp/README.md"
check_file "${OUTPUT_DIR}/coverage/product-gap-matrix.json"
check_file "${OUTPUT_DIR}/coverage/tool-catalog.json"
check_file "${OUTPUT_DIR}/observability/mcp-tool-span-logging.md"

python3 - "${OUTPUT_DIR}/metadata.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
required = {"skill", "mcp_url", "clients", "expected_tools", "expected_tool_count"}
missing = required - set(data)
if missing:
    raise SystemExit(f"metadata.json missing keys: {sorted(missing)}")
if data["skill"] != "galileo-mcp-server-setup":
    raise SystemExit("metadata.json skill mismatch")
if not str(data["mcp_url"]).endswith("/mcp/http/mcp"):
    raise SystemExit("metadata.json mcp_url does not end with /mcp/http/mcp")
if data.get("expected_prompts_count") != 0 or data.get("expected_resources_count") != 0:
    raise SystemExit("metadata.json expected prompt/resource counts should be zero")
tools = data.get("expected_tools")
if not isinstance(tools, list) or len(tools) != data["expected_tool_count"]:
    raise SystemExit("metadata.json expected_tools does not match expected_tool_count")
for tool in tools:
    for key in ("name", "risk_group", "required", "properties", "schema_sha256"):
        if key not in tool:
            raise SystemExit(f"metadata.json expected tool missing {key}: {tool}")
PY

python3 - "${OUTPUT_DIR}/coverage/product-gap-matrix.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
matrix = data.get("product_gap_matrix")
if not isinstance(matrix, list) or len(matrix) < 8:
    raise SystemExit("product-gap-matrix.json does not contain expected coverage rows")
PY

python3 - "${OUTPUT_DIR}/coverage/tool-catalog.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as fh:
    data = json.load(fh)
tools = data.get("tools")
if not isinstance(tools, list) or data.get("tool_count") != len(tools):
    raise SystemExit("tool-catalog.json tool_count mismatch")
for tool in tools:
    for key in ("name", "risk_group", "required", "properties", "schema_sha256", "coverage", "auto_allow"):
        if key not in tool:
            raise SystemExit(f"tool-catalog.json tool missing {key}: {tool}")
if data.get("prompts_expected") != [] or data.get("resources_expected") != []:
    raise SystemExit("tool-catalog.json prompt/resource expectations should be empty lists")
PY

ANY_CLIENT=false
for cfg in cursor.mcp.json vscode.mcp.json claude.mcp.json kiro.mcp.json; do
    if [[ -f "${OUTPUT_DIR}/mcp/${cfg}" ]]; then
        ANY_CLIENT=true
        python3 - "${OUTPUT_DIR}/mcp/${cfg}" <<'PY'
import json, sys
text = open(sys.argv[1], encoding="utf-8").read()
clean = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
json.loads(clean)
PY
        case "${cfg}" in
            cursor.mcp.json|vscode.mcp.json)
                grep -q 'mcp/http/mcp' "${OUTPUT_DIR}/mcp/${cfg}" || {
                    log "ERROR: ${cfg} does not reference a Galileo MCP endpoint."
                    exit 1
                }
                ;;
            claude.mcp.json|kiro.mcp.json)
                grep -q 'run-galileo-mcp.js' "${OUTPUT_DIR}/mcp/${cfg}" || {
                    log "ERROR: ${cfg} does not reference the local Galileo MCP bridge."
                    exit 1
                }
                ;;
        esac
    fi
done

if [[ -f "${OUTPUT_DIR}/mcp/codex-register-galileo-mcp.sh" ]]; then
    ANY_CLIENT=true
    [[ -x "${OUTPUT_DIR}/mcp/codex-register-galileo-mcp.sh" ]] || {
        log "ERROR: codex-register-galileo-mcp.sh is not executable."
        exit 1
    }
    grep -q 'codex mcp add' "${OUTPUT_DIR}/mcp/codex-register-galileo-mcp.sh" || {
        log "ERROR: codex-register-galileo-mcp.sh does not register with Codex."
        exit 1
    }
fi

if [[ -f "${OUTPUT_DIR}/mcp/run-galileo-mcp.js" ]]; then
    [[ -x "${OUTPUT_DIR}/mcp/run-galileo-mcp.js" ]] || {
        log "ERROR: run-galileo-mcp.js is not executable."
        exit 1
    }
    if command -v node >/dev/null 2>&1; then
        node --check "${OUTPUT_DIR}/mcp/run-galileo-mcp.js" >/dev/null
    else
        log "  WARN: node not on PATH; skipping JS syntax check."
    fi
fi

if [[ -f "${OUTPUT_DIR}/mcp/run-galileo-mcp.sh" && ! -x "${OUTPUT_DIR}/mcp/run-galileo-mcp.sh" ]]; then
    log "ERROR: run-galileo-mcp.sh is not executable."
    exit 1
fi

if [[ "${ANY_CLIENT}" != "true" ]]; then
    log "ERROR: No rendered client configs found in ${OUTPUT_DIR}/mcp."
    exit 1
fi

python3 - "${OUTPUT_DIR}" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
bad = []
for path in root.rglob("*"):
    if not path.is_file():
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "YOUR-API-KEY" in text:
        bad.append((path, "placeholder YOUR-API-KEY"))
    if re.search(r"Bearer [A-Za-z0-9._-]{12,}", text):
        bad.append((path, "inline bearer token-like value"))
    if re.search(r"GALILEO_API_KEY=(?!''|\"\"|\$\{)[^'\n#][^\n#]{7,}", text):
        bad.append((path, "populated GALILEO_API_KEY assignment"))
    if re.search(r'"Galileo-API-Key"\s*:\s*"(?!\$\{)[^"]{8,}"', text):
        bad.append((path, "inline Galileo-API-Key header value"))
if bad:
    for path, reason in bad:
        print(f"ERROR: {path}: {reason}", file=sys.stderr)
    raise SystemExit(1)
PY

log "Galileo MCP Server rendered assets passed static validation."

if [[ "${RUN_PROBE}" == "true" ]]; then
    MCP_URL="$(python3 - "${OUTPUT_DIR}/metadata.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["mcp_url"])
PY
)"
    python3 "${SCRIPT_DIR}/probe_mcp.py" --mcp-url "${MCP_URL}"
fi
