#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for script in setup.sh install_app.sh list_apps.sh uninstall_app.sh; do
    bash -n "${SCRIPT_DIR}/${script}"
done

bash "${SCRIPT_DIR}/setup.sh" --help >/dev/null
bash "${SCRIPT_DIR}/install_app.sh" --help >/dev/null
bash "${SCRIPT_DIR}/list_apps.sh" --help >/dev/null
bash "${SCRIPT_DIR}/uninstall_app.sh" --help >/dev/null

echo "splunk-app-install offline validation passed."
