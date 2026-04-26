#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

WORKFLOW=""
SPEC_PATH=""

usage() {
  cat <<'EOF'
Usage: validate.sh --workflow native|content-packs|topology --spec PATH

Examples:
  bash scripts/validate.sh --workflow content-packs --spec templates/beginner.content-pack.yaml
  bash scripts/validate.sh --workflow topology --spec templates/beginner.topology.yaml
  bash scripts/validate.sh --workflow native --spec templates/native.example.yaml
  bash scripts/validate.sh --workflow content-packs --spec templates/content_packs.example.yaml
  bash scripts/validate.sh --workflow topology --spec templates/topology.example.yaml
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow)
      WORKFLOW="${2:-}"
      shift 2
      ;;
    --spec)
      SPEC_PATH="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${WORKFLOW}" || -z "${SPEC_PATH}" ]]; then
  usage >&2
  exit 1
fi

load_splunk_connection_settings >/dev/null 2>&1 || true
if [[ -n "${SPLUNK_USER:-}" ]]; then
  SPLUNK_USERNAME="${SPLUNK_USER}"
fi
if [[ -n "${SPLUNK_PASS:-}" ]]; then
  SPLUNK_PASSWORD="${SPLUNK_PASS}"
fi
export SPLUNK_PLATFORM SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_SESSION_KEY SPLUNK_USERNAME SPLUNK_PASSWORD

SPEC_JSON="$(mktemp)"
trap 'rm -f "${SPEC_JSON}"' EXIT

ruby "${SCRIPT_DIR}/spec_to_json.rb" --spec "${SPEC_PATH}" --output "${SPEC_JSON}"

case "${WORKFLOW}" in
  native)
    python3 "${SCRIPT_DIR}/run_native.py" --spec-json "${SPEC_JSON}" --mode validate
    ;;
  content-packs)
    python3 "${SCRIPT_DIR}/run_content_packs.py" --spec-json "${SPEC_JSON}" --mode validate
    ;;
  topology)
    python3 "${SCRIPT_DIR}/run_topology.py" --spec-json "${SPEC_JSON}" --mode validate
    ;;
  *)
    echo "Unsupported workflow: ${WORKFLOW}" >&2
    exit 1
    ;;
esac
