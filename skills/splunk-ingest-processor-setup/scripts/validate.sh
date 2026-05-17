#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash -n "${SCRIPT_DIR}/setup.sh"
bash -n "${SCRIPT_DIR}/smoke_offline.sh"
python3 -m py_compile "${SCRIPT_DIR}/render_assets.py"
bash "${SCRIPT_DIR}/smoke_offline.sh"
