#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: bash skills/cisco-meraki-aam-thousandeyes-setup/scripts/setup.sh --render [options]

Options:
  --render                    Render reviewable runbooks (default action)
  --spec PATH                 Intake YAML/JSON file (default: skill template.local if present)
  --output-dir DIR            Output directory (default: meraki-aam-thousandeyes-rendered)
  --har PATH                  Optional Meraki Dashboard HAR export to summarize
  --help                      Show this help

This script does not mutate Meraki or ThousandEyes. Meraki AAM agent deployment
is UI-driven; captured private Dashboard POSTs are summarized for evidence only.
EOF
}

ACTION="render"
SPEC="${SKILL_DIR}/template.local"
OUTPUT_DIR="meraki-aam-thousandeyes-rendered"
HAR_PATH=""

if [[ ! -f "${SPEC}" ]]; then
    SPEC="${SKILL_DIR}/template.example"
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render)
            ACTION="render"
            shift
            ;;
        --spec)
            SPEC="${2:-}"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="${2:-}"
            shift 2
            ;;
        --har)
            HAR_PATH="${2:-}"
            shift 2
            ;;
        --apply|--apply-private-meraki-posts|--replay)
            echo "ERROR: Meraki AAM private POST replay is intentionally not implemented by this setup script." >&2
            echo "Use the Meraki Dashboard UI, or follow SKILL.md replay confirmation rules manually." >&2
            exit 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ "${ACTION}" != "render" ]]; then
    echo "ERROR: unsupported action: ${ACTION}" >&2
    exit 2
fi

python3 "${SCRIPT_DIR}/render_assets.py" \
    --spec "${SPEC}" \
    --output-dir "${OUTPUT_DIR}"

if [[ -n "${HAR_PATH}" ]]; then
    python3 "${SCRIPT_DIR}/summarize_har.py" \
        --har "${HAR_PATH}" \
        --output-md "${OUTPUT_DIR}/har-summary.md" \
        --output-json "${OUTPUT_DIR}/har-summary.json" \
        --url-filter meraki
fi

echo "Rendered Meraki AAM ThousandEyes assets in ${OUTPUT_DIR}"
