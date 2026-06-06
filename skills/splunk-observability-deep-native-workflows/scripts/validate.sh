#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<EOF
Splunk Observability Deep Native Workflows Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --help    Show this help
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if [[ $# -gt 0 ]]; then
    echo "Unknown option: $1" >&2
    usage >&2
    exit 1
fi

bash -n "${SCRIPT_DIR}/setup.sh"
bash "${SCRIPT_DIR}/setup.sh" \
    --validate \
    --spec "${SKILL_DIR}/template.example" >/dev/null

echo "splunk-observability-deep-native-workflows offline validation passed."
