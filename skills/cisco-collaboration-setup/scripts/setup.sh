#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

SPEC="${SKILL_DIR}/template.example"
OUTPUT_DIR="${PROJECT_ROOT}/cisco-collaboration-rendered"
DRY_RUN=false
JSON_OUTPUT=false
RUN_VALIDATE=false
REPLACE_EXISTING=false
EXPECTED_SPEC_SHA256=""

usage() {
    cat <<'EOF'
Cisco Collaboration Setup (offline render-only)

Usage:
  bash skills/cisco-collaboration-setup/scripts/setup.sh [options]

Options:
  --spec PATH          Strict v1 YAML/JSON intake (default: template.example)
  --output-dir DIR     Dedicated rendered bundle directory
  --dry-run            Validate and preview without writing
  --json               Emit machine-readable summary
  --validate           Validate the rendered bundle after writing
  --expected-spec-sha256 HEX
                       External digest required to match --spec (with --validate)
  --replace-existing   Preserve existing output as a path-bound recoverable backup, then publish
  --help               Show this help

There is no apply, execute, install, live-service, credential, or device mode.
Unknown and secret-bearing flags fail closed.
EOF
}

require_value() {
    if [[ $# -lt 2 || -z "${2:-}" || "${2:-}" == --* ]]; then
        printf 'ERROR: %s requires a value.\n' "$1" >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --spec) require_value "$1" "${2:-}"; SPEC="$2"; shift 2 ;;
        --output-dir) require_value "$1" "${2:-}"; OUTPUT_DIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --validate) RUN_VALIDATE=true; shift ;;
        --expected-spec-sha256) require_value "$1" "${2:-}"; EXPECTED_SPEC_SHA256="$2"; shift 2 ;;
        --replace-existing) REPLACE_EXISTING=true; shift ;;
        --help|-h) usage; exit 0 ;;
        --apply|--execute|--install|--live|--device-*|--mutate|--configure-device|\
        --token|--password|--secret|--authorization|--api-key|--client-secret|\
        --*-token|--*-password|--*-secret|--*-key|--*_token|--*_password|--*_secret|--*_key|\
        --apply=*|--execute=*|--install=*|--live=*|--mutate=*|--configure-device=*|\
        --token=*|--password=*|--secret=*|--authorization=*|--api-key=*|--client-secret=*|\
        --*-token=*|--*-password=*|--*-secret=*|--*-key=*|--*_token=*|--*_password=*|--*_secret=*|--*_key=*)
            printf 'ERROR: live, mutation, executable, and secret-bearing options are not supported.\n' >&2
            exit 2
            ;;
        *)
            printf 'ERROR: unknown option: %s\n' "$1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "${RUN_VALIDATE}" == true && "${DRY_RUN}" == true ]]; then
    printf 'ERROR: --validate cannot be combined with --dry-run.\n' >&2
    exit 2
fi
if [[ -n "${EXPECTED_SPEC_SHA256}" && "${RUN_VALIDATE}" != true ]]; then
    printf 'ERROR: --expected-spec-sha256 requires --validate.\n' >&2
    exit 2
fi

args=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
[[ "${DRY_RUN}" != true ]] || args+=(--dry-run)
[[ "${JSON_OUTPUT}" != true ]] || args+=(--json)
[[ "${REPLACE_EXISTING}" != true ]] || args+=(--replace-existing)
[[ -z "${EXPECTED_SPEC_SHA256}" ]] || args+=(--expected-spec-sha256 "${EXPECTED_SPEC_SHA256}")

python3 "${SCRIPT_DIR}/render_assets.py" "${args[@]}"

# The renderer validates the complete private stage before publication and the
# published bundle afterward. --validate is retained as an explicit operator
# assertion without emitting a second result document (especially in --json).
