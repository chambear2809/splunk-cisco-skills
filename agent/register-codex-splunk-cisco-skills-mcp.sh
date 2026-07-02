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

# `codex mcp add` updates an existing name atomically. Removing first would
# destroy a working registration if the replacement command fails.
exec codex mcp add "${SERVER_NAME}" -- python3 "${RUNNER}"
