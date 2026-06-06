#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

bash -n "${SCRIPT_DIR}/setup.sh"
bash "${SCRIPT_DIR}/setup.sh" \
    --validate \
    --spec "${SKILL_DIR}/template.example" >/dev/null

echo "splunk-observability-deep-native-workflows offline validation passed."
