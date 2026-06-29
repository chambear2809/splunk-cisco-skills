#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

exec python3 "${PROJECT_ROOT}/skills/shared/coding_agent_o11y/parent.py" "$@"

