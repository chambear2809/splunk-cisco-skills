#!/usr/bin/env bash
set -euo pipefail

# Offline smoke: render the example spec into a temp directory and run validate.
# No live API calls. Useful in CI to catch render regressions early.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

TMP_DIR="$(mktemp -d -t soics-smoke.XXXXXX)"
trap 'rm -rf "${TMP_DIR}"' EXIT

bash "${SCRIPT_DIR}/setup.sh" \
    --render \
    --spec "${SCRIPT_DIR}/../template.example" \
    --output-dir "${TMP_DIR}"

bash "${SCRIPT_DIR}/validate.sh" --output-dir "${TMP_DIR}" --summary

echo "smoke_offline: OK (output: ${TMP_DIR})"
