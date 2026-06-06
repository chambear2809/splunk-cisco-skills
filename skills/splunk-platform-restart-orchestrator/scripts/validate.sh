#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash -n "${SCRIPT_DIR}/setup.sh"
python3 -m py_compile "${SCRIPT_DIR}/repo_audit.py"
bash "${SCRIPT_DIR}/setup.sh" --audit-repo --output-dir /tmp/splunk-platform-restart-validate >/dev/null

echo "splunk-platform-restart-orchestrator offline validation passed."
