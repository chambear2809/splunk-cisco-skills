#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

WORKFLOW=""
SPEC_PATH=""
MODE_OVERRIDE=""
OUTPUT_PATH=""
OUTPUT_FORMAT="json"
BACKUP_OUTPUT=""
BACKUP_FORMAT="yaml"
APPLY=false

usage() {
  cat <<'EOF'
Usage: setup.sh --workflow native|content-packs|topology --spec PATH [--apply]
       setup.sh --workflow native --spec PATH --mode export|inventory|prune-plan [--output PATH] [--output-format json|yaml]
       setup.sh --workflow native --spec PATH --mode cleanup-apply --backup-output PATH

Examples:
  bash scripts/setup.sh --workflow content-packs --spec templates/beginner.content-pack.yaml
  bash scripts/setup.sh --workflow topology --spec templates/beginner.topology.yaml
  bash scripts/setup.sh --workflow native --spec templates/native.example.yaml
  bash scripts/setup.sh --workflow native --spec my-native.yaml --apply
  bash scripts/setup.sh --workflow native --spec my-native.yaml --mode export --output exported.native.yaml --output-format yaml
  bash scripts/setup.sh --workflow native --spec my-native.yaml --mode inventory --output inventory.json
  bash scripts/setup.sh --workflow native --spec my-native.yaml --mode prune-plan --output prune-plan.json
  bash scripts/setup.sh --workflow native --spec my-native.yaml --mode cleanup-apply --backup-output cleanup-backup.native.yaml
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
    --mode)
      MODE_OVERRIDE="${2:-}"
      shift 2
      ;;
    --output)
      OUTPUT_PATH="${2:-}"
      shift 2
      ;;
    --output-format)
      OUTPUT_FORMAT="${2:-}"
      shift 2
      ;;
    --backup-output)
      BACKUP_OUTPUT="${2:-}"
      shift 2
      ;;
    --backup-format)
      BACKUP_FORMAT="${2:-}"
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

if [[ -n "${MODE_OVERRIDE}" && "${APPLY}" == true ]]; then
  echo "--mode and --apply are mutually exclusive" >&2
  exit 1
fi

if [[ "${OUTPUT_FORMAT}" != "json" && "${OUTPUT_FORMAT}" != "yaml" ]]; then
  echo "Unsupported --output-format: ${OUTPUT_FORMAT}" >&2
  exit 1
fi
if [[ "${BACKUP_FORMAT}" != "json" && "${BACKUP_FORMAT}" != "yaml" ]]; then
  echo "Unsupported --backup-format: ${BACKUP_FORMAT}" >&2
  exit 1
fi

load_splunk_connection_settings >/dev/null 2>&1 || true
if [[ -n "${SPLUNK_USER:-}" ]]; then
  SPLUNK_USERNAME="${SPLUNK_USER}"
fi
if [[ -n "${SPLUNK_PASS:-}" ]]; then
  SPLUNK_PASSWORD="${SPLUNK_PASS}"
fi
export SPLUNK_PLATFORM SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_SESSION_KEY SPLUNK_USERNAME SPLUNK_PASSWORD SPLUNK_VERIFY_SSL

SPEC_JSON="$(mktemp)"
trap 'rm -f "${SPEC_JSON}"' EXIT

ruby "${SCRIPT_DIR}/spec_to_json.rb" --spec "${SPEC_PATH}" --output "${SPEC_JSON}"

case "${WORKFLOW}" in
  native)
    MODE="${MODE_OVERRIDE:-preview}"
    if [[ "${APPLY}" == true ]]; then
      MODE="apply"
    fi
    EXTRA_ARGS=()
    if [[ -n "${OUTPUT_PATH}" ]]; then
      EXTRA_ARGS+=(--output "${OUTPUT_PATH}" --output-format "${OUTPUT_FORMAT}")
    fi
    if [[ -n "${BACKUP_OUTPUT}" ]]; then
      EXTRA_ARGS+=(--backup-output "${BACKUP_OUTPUT}" --backup-format "${BACKUP_FORMAT}")
    fi
    if [[ "${#EXTRA_ARGS[@]}" -gt 0 ]]; then
      python3 "${SCRIPT_DIR}/run_native.py" --spec-json "${SPEC_JSON}" --mode "${MODE}" "${EXTRA_ARGS[@]}"
    else
      python3 "${SCRIPT_DIR}/run_native.py" --spec-json "${SPEC_JSON}" --mode "${MODE}"
    fi
    ;;
  content-packs)
    if [[ -n "${MODE_OVERRIDE}" ]]; then
      echo "--mode is only supported for the native workflow" >&2
      exit 1
    fi
    MODE="preview"
    if [[ "${APPLY}" == true ]]; then
      MODE="apply"
    fi
    python3 "${SCRIPT_DIR}/run_content_packs.py" --spec-json "${SPEC_JSON}" --mode "${MODE}"
    ;;
  topology)
    if [[ -n "${MODE_OVERRIDE}" ]]; then
      echo "--mode is only supported for the native workflow" >&2
      exit 1
    fi
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
