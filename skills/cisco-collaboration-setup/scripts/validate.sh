#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"
OUTPUT_DIR="${PROJECT_ROOT}/cisco-collaboration-rendered"
JSON_OUTPUT=false
TRUSTED_SPEC=""
EXPECTED_SPEC_SHA256=""

usage() {
    cat <<'EOF'
Cisco Collaboration Setup offline validation

Usage:
  bash skills/cisco-collaboration-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered bundle directory
  --spec PATH        Trusted original spec; re-parse it and revalidate bound evidence
  --expected-spec-sha256 HEX
                     Optional external SHA-256 trust anchor for --spec
  --json             Emit machine-readable result
  --help             Show this help

Validation reads local artifacts and, when --spec is supplied, its locally bound
evidence files. It never contacts Splunk, SC4S, Cisco, Splunkbase, or a device,
and it never reads credentials.
EOF
}

if [[ $# -eq 0 ]]; then
    :
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
                printf 'ERROR: --output-dir requires a value.\n' >&2
                exit 2
            fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --spec)
            if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
                printf 'ERROR: --spec requires a value.\n' >&2
                exit 2
            fi
            TRUSTED_SPEC="$2"
            shift 2
            ;;
        --expected-spec-sha256)
            if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
                printf 'ERROR: --expected-spec-sha256 requires a value.\n' >&2
                exit 2
            fi
            EXPECTED_SPEC_SHA256="$2"
            shift 2
            ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help|-h) usage; exit 0 ;;
        --live|--token|--password|--secret|--authorization|--api-key|--client-secret|\
        --live=*|--token=*|--password=*|--secret=*|--authorization=*|--api-key=*|--client-secret=*)
            printf 'ERROR: live and secret-bearing options are not supported.\n' >&2
            exit 2
            ;;
        *) printf 'ERROR: unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

args=(--output-dir "${OUTPUT_DIR}" --validate-only)
[[ -z "${TRUSTED_SPEC}" ]] || args+=(--spec "${TRUSTED_SPEC}")
[[ -z "${EXPECTED_SPEC_SHA256}" ]] || args+=(--expected-spec-sha256 "${EXPECTED_SPEC_SHA256}")
[[ "${JSON_OUTPUT}" != true ]] || args+=(--json)
python3 "${SCRIPT_DIR}/render_assets.py" "${args[@]}"
