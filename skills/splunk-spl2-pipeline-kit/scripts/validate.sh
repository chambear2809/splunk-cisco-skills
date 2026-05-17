#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash -n "${SCRIPT_DIR}/setup.sh"
bash -n "${SCRIPT_DIR}/smoke_offline.sh"
python3 -m py_compile "${SCRIPT_DIR}/spl2_pipeline_kit.py"
python3 "${SCRIPT_DIR}/spl2_pipeline_kit.py" --phase smoke
