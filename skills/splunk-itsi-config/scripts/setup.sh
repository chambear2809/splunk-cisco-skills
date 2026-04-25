#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW=""
SPEC_PATH=""
APPLY=false

usage() {
  cat <<'EOF'
Usage: setup.sh --workflow native|content-packs|topology --spec PATH [--apply]

Examples:
  bash scripts/setup.sh --workflow native --spec templates/native.example.yaml
  bash scripts/setup.sh --workflow native --spec my-native.yaml --apply
  bash scripts/setup.sh --workflow content-packs --spec templates/content_packs.example.yaml
  bash scripts/setup.sh --workflow content-packs --spec my-packs.yaml --apply
  bash scripts/setup.sh --workflow topology --spec templates/topology.example.yaml
  bash scripts/setup.sh --workflow topology --spec my-topology.yaml --apply
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
    --apply)
      APPLY=true
      shift
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

SPEC_JSON="$(mktemp)"
trap 'rm -f "${SPEC_JSON}"' EXIT

ruby "${SCRIPT_DIR}/spec_to_json.rb" --spec "${SPEC_PATH}" --output "${SPEC_JSON}"

case "${WORKFLOW}" in
  native)
    MODE="preview"
    if [[ "${APPLY}" == true ]]; then
      MODE="apply"
    fi
    python3 "${SCRIPT_DIR}/run_native.py" --spec-json "${SPEC_JSON}" --mode "${MODE}"
    ;;
  content-packs)
    MODE="preview"
    if [[ "${APPLY}" == true ]]; then
      MODE="apply"
    fi
    python3 "${SCRIPT_DIR}/run_content_packs.py" --spec-json "${SPEC_JSON}" --mode "${MODE}"
    ;;
  topology)
    MODE="preview"
    if [[ "${APPLY}" == true ]]; then
      MODE="apply"
    fi
    python3 "${SCRIPT_DIR}/run_topology.py" --spec-json "${SPEC_JSON}" --mode "${MODE}"
    ;;
  *)
    echo "Unsupported workflow: ${WORKFLOW}" >&2
    exit 1
    ;;
esac
