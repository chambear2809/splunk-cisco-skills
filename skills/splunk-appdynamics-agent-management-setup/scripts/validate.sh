#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
SKILL_NAME="$(basename "$(cd "${SCRIPT_DIR}/.." && pwd)")"
source "${PROJECT_ROOT}/skills/shared/lib/appdynamics_helpers.sh"
appd_reject_direct_secret_args "$@" || exit $?
PYTHON_BIN="python3"; [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]] && PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
exec "${PYTHON_BIN}" "${PROJECT_ROOT}/skills/splunk-appdynamics-setup/scripts/appdynamics_suite.py" --skill "${SKILL_NAME}" --validate "$@"
