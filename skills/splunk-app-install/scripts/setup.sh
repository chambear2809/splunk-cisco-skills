#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    cat <<'EOF'
Splunk App Install dispatcher

Usage:
  setup.sh --install [install_app.sh options]
  setup.sh --list [list_apps.sh options]
  setup.sh --uninstall [uninstall_app.sh options]
  setup.sh [install_app.sh options]

The default operation is --install so existing install_app.sh flags can be
passed directly.
EOF
}

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

case "$1" in
    --help|-h)
        usage
        exit 0
        ;;
    --install)
        shift
        exec bash "${SCRIPT_DIR}/install_app.sh" "$@"
        ;;
    --list)
        shift
        exec bash "${SCRIPT_DIR}/list_apps.sh" "$@"
        ;;
    --uninstall)
        shift
        exec bash "${SCRIPT_DIR}/uninstall_app.sh" "$@"
        ;;
    *)
        exec bash "${SCRIPT_DIR}/install_app.sh" "$@"
        ;;
esac
