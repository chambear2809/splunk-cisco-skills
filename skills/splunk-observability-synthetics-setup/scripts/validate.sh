#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/shared/lib/credential_helpers.sh"

RENDERED_DIR="${PROJECT_ROOT}/../splunk-observability-synthetics-rendered"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) require_arg "$1" "$#" || exit 1; RENDERED_DIR="$2"; shift 2 ;;
        --help|-h) echo "Usage: validate.sh [--rendered-dir DIR]"; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
    esac
done

test -f "${RENDERED_DIR}/native-ops-spec.json"
test -f "${RENDERED_DIR}/synthetics-plan.md"
test -f "${RENDERED_DIR}/delegate-native-ops.sh"
grep -q '"synthetics"' "${RENDERED_DIR}/native-ops-spec.json"
printf 'PASS: Synthetics rendered assets validated\n'
