#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVER_NAME="${1:-splunk-cisco-skills}"
RUNNER="${REPO_ROOT}/agent/run-splunk-cisco-skills-mcp.py"

if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: codex CLI not found on PATH." >&2
    exit 1
fi

if [[ ! -f "${RUNNER}" ]]; then
    echo "ERROR: MCP runner not found: ${RUNNER}" >&2
    exit 1
fi

if codex mcp get "${SERVER_NAME}" --json >/dev/null 2>&1; then
    codex mcp remove "${SERVER_NAME}" >/dev/null
fi

exec codex mcp add "${SERVER_NAME}" -- python3 "${RUNNER}"
