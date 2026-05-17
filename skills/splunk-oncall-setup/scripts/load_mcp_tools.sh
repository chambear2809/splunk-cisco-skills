#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/../../shared/scripts/load_mcp_tools.sh" \
    --tools-json "${SCRIPT_DIR}/../mcp_tools.json" \
    "$@"
