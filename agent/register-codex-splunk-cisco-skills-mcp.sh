#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SERVER_NAME="${1:-splunk-cisco-skills}"
RUNNER="${REPO_ROOT}/agent/run-splunk-cisco-skills-mcp.py"

if [[ ! "${SERVER_NAME}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]]; then
    echo "ERROR: server name must match ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$." >&2
    exit 2
fi

if ! command -v codex >/dev/null 2>&1; then
    echo "ERROR: codex CLI not found on PATH." >&2
    exit 1
fi

PYTHON_BIN="$(command -v python3 || true)"
if [[ -z "${PYTHON_BIN}" || "${PYTHON_BIN}" != /* || ! -x "${PYTHON_BIN}" ]]; then
    echo "ERROR: python3 must resolve to an absolute executable path." >&2
    exit 1
fi

if [[ ! -f "${RUNNER}" ]]; then
    echo "ERROR: MCP runner not found: ${RUNNER}" >&2
    exit 1
fi

# `codex mcp add` updates an existing name atomically. Removing first would
# destroy a working registration if the replacement command fails.
exec codex mcp add \
    --env SPLUNK_SKILLS_MCP_ENABLE_EXECUTION=1 \
    --env SPLUNK_SKILLS_MCP_ALLOW_GENERIC_EXECUTION=0 \
    --env SPLUNK_SKILLS_MCP_ALLOW_MUTATION=0 \
    "${SERVER_NAME}" -- "${PYTHON_BIN}" -I "${RUNNER}"
