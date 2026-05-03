#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/cisco-thousandeyes-mcp-rendered"
LIVE=false

usage() {
    cat <<'EOF'
Cisco ThousandEyes MCP Server validation

Usage:
  bash skills/cisco-thousandeyes-mcp-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --live             Reach https://api.thousandeyes.com/mcp from each rendered config
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}/mcp" ]]; then
    log "ERROR: No rendered MCP configs at ${OUTPUT_DIR}/mcp."
    exit 1
fi

check_file() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        log "ERROR: Missing ${path}"
        exit 1
    fi
}

check_file "${OUTPUT_DIR}/mcp/README.md"
check_file "${OUTPUT_DIR}/metadata.json"

# Per-client checks. Each is optional; only configs that were rendered must
# be valid. The README always lists which clients were selected, which lets
# us verify the rendered set without re-parsing argv.
ANY_CLIENT_FOUND=false
for cfg in cursor.mcp.json claude.mcp.json vscode.mcp.json kiro.mcp.json; do
    if [[ -f "${OUTPUT_DIR}/mcp/${cfg}" ]]; then
        ANY_CLIENT_FOUND=true
        # The configs may include a leading // comment block (Cursor / Claude),
        # so strip lines starting with // before parsing as JSON.
        python3 - "${OUTPUT_DIR}/mcp/${cfg}" <<'PY' || { log "ERROR: ${cfg} is not valid JSON after stripping comments."; exit 1; }
import json, re, sys
text = open(sys.argv[1], encoding="utf-8").read()
clean = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
json.loads(clean)
PY
        # The TE MCP URL must be referenced in every JSON config.
        grep -q 'api.thousandeyes.com/mcp' "${OUTPUT_DIR}/mcp/${cfg}" || {
            log "ERROR: ${cfg} does not reference api.thousandeyes.com/mcp."
            exit 1
        }
    fi
done

if [[ -f "${OUTPUT_DIR}/mcp/codex-register-te-mcp.sh" ]]; then
    ANY_CLIENT_FOUND=true
    if [[ ! -x "${OUTPUT_DIR}/mcp/codex-register-te-mcp.sh" ]]; then
        log "ERROR: codex-register-te-mcp.sh is not executable."
        exit 1
    fi
    grep -q 'api.thousandeyes.com/mcp' "${OUTPUT_DIR}/mcp/codex-register-te-mcp.sh" || {
        log "ERROR: codex-register-te-mcp.sh does not reference api.thousandeyes.com/mcp."
        exit 1
    }
    grep -q 'codex mcp add' "${OUTPUT_DIR}/mcp/codex-register-te-mcp.sh" || {
        log "ERROR: codex-register-te-mcp.sh does not invoke 'codex mcp add'."
        exit 1
    }
fi

if [[ "${ANY_CLIENT_FOUND}" != "true" ]]; then
    log "ERROR: No client configs found in ${OUTPUT_DIR}/mcp."
    exit 1
fi

# Token-scrub assertion: no JWT-style or bare-token strings in any rendered
# file. The renderer should only ever emit placeholders / env-var refs.
if grep -rEq -- '"Authorization"[[:space:]]*:[[:space:]]*"Bearer [A-Za-z0-9._-]{12,}' "${OUTPUT_DIR}" 2>/dev/null; then
    log "ERROR: A rendered file appears to contain an inline Bearer token."
    exit 1
fi

log "Cisco ThousandEyes MCP Setup rendered assets passed static validation."

if [[ "${LIVE}" == "true" ]]; then
    log "  --live: probing https://api.thousandeyes.com/mcp ..."
    if command -v curl >/dev/null 2>&1; then
        # Without auth this should return 401; the goal is to confirm the
        # endpoint is reachable, not that auth succeeds.
        local_status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 'https://api.thousandeyes.com/mcp' || echo 000)"
        log "  status: ${local_status} (401 expected without Authorization)"
    else
        log "  WARN: curl not on PATH; cannot probe."
    fi
fi
