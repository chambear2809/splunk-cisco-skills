#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -eq 0 ]]; then
    exec bash "${SCRIPT_DIR}/size.sh" --help
fi

exec bash "${SCRIPT_DIR}/size.sh" "$@"
