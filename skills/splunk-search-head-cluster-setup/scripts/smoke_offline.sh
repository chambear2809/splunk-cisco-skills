#!/usr/bin/env bash
set -euo pipefail

# Offline smoke: render with example config into a temp dir, then validate.
# No live API calls, no Splunk credentials required. Useful in CI.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TMP_DIR="$(mktemp -d -t shc-smoke.XXXXXX)"
trap 'rm -rf "${TMP_DIR}"' EXIT

python3 "${SCRIPT_DIR}/render_assets.py" \
    --shc-label smoke_shc \
    --deployer-host deployer01.example.com \
    --member-hosts sh01.example.com,sh02.example.com,sh03.example.com \
    --output-dir "${TMP_DIR}"

bash "${SCRIPT_DIR}/validate.sh" --output-dir "${TMP_DIR}" --summary

echo "smoke_offline: OK (output: ${TMP_DIR})"
