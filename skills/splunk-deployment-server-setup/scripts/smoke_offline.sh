#!/usr/bin/env bash
set -euo pipefail

# Offline smoke: render with example config into a temp dir, then validate.
# No live API calls, no Splunk credentials required. Useful in CI.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TMP_DIR="$(mktemp -d -t ds-smoke.XXXXXX)"
trap 'rm -rf "${TMP_DIR}"' EXIT

python3 "${SCRIPT_DIR}/render_assets.py" \
    --ds-host ds01.example.com \
    --fleet-size 500 \
    --output-dir "${TMP_DIR}"

bash "${SCRIPT_DIR}/validate.sh" --output-dir "${TMP_DIR}" --summary

echo "smoke_offline: OK (output: ${TMP_DIR})"
