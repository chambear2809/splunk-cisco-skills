#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash -n "${SCRIPT_DIR}/setup.sh"
bash -n "${SCRIPT_DIR}/size.sh"
bash "${SCRIPT_DIR}/setup.sh" \
    --daily-ingest-gb 100 \
    --retention-days 30 \
    --deployment-target standalone \
    --dry-run \
    --json >/dev/null

echo "splunk-platform-sizing offline validation passed."
