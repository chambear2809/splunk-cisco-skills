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
       setup.sh --workflow native|content-packs|topology --spec PATH --mode lint
       setup.sh --workflow native --spec PATH --mode validate|export|inventory|prune-plan [--output PATH] [--output-format json|yaml]
       setup.sh --workflow native --spec PATH --mode cleanup-apply --backup-output PATH
       setup.sh --workflow topology --spec PATH --mode prune-plan [--output PATH] [--output-format json|yaml]
       setup.sh --workflow topology --spec PATH --mode cleanup-apply --backup-output PATH

Examples:
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow content-packs --spec skills/splunk-itsi-config/templates/beginner.content-pack.yaml --mode lint
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec skills/splunk-itsi-config/templates/beginner.topology.yaml
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow native --spec my-native.yaml --apply
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow native --spec my-native.yaml --mode export --output exported.native.yaml --output-format yaml
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow native --spec my-native.yaml --mode inventory --output inventory.json
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow native --spec my-native.yaml --mode prune-plan --output prune-plan.json
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow native --spec my-native.yaml --mode cleanup-apply --backup-output cleanup-backup.native.yaml
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow content-packs --spec my-packs.yaml --apply
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec my-topology.yaml --apply
  bash skills/splunk-itsi-config/scripts/setup.sh --workflow topology --spec my-topology.yaml --mode prune-plan --output topology-prune-plan.json
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

if [[ ! -f "${SPEC_PATH}" ]]; then
  echo "ERROR: Spec file not found: ${SPEC_PATH}" >&2
  exit 1
fi

if [[ -n "${MODE_OVERRIDE}" && "${APPLY}" == true ]]; then
  echo "--mode and --apply are mutually exclusive" >&2
  exit 1
fi

case "${WORKFLOW}" in
  native)
    case "${MODE_OVERRIDE:-preview}" in
      lint|preview|validate|export|inventory|prune-plan|cleanup-apply) ;;
      apply)
        echo "ERROR: --mode apply is not permitted; use the explicit --apply flag." >&2
        exit 1
        ;;
      *)
        echo "Unsupported native mode: ${MODE_OVERRIDE}" >&2
        exit 1
        ;;
    esac
    ;;
  content-packs)
    if [[ -n "${MODE_OVERRIDE}" && "${MODE_OVERRIDE}" != "lint" ]]; then
      echo "--mode for content-packs only supports lint; use --apply for writes." >&2
      exit 1
    fi
    ;;
  topology)
    case "${MODE_OVERRIDE:-preview}" in
      lint|preview|validate|prune-plan|cleanup-apply) ;;
      apply)
        echo "ERROR: --mode apply is not permitted; use the explicit --apply flag." >&2
        exit 1
        ;;
      *)
        echo "Unsupported topology mode: ${MODE_OVERRIDE}" >&2
        exit 1
        ;;
    esac
    ;;
  *)
    echo "Unsupported workflow: ${WORKFLOW}" >&2
    exit 1
    ;;
esac

if [[ "${OUTPUT_FORMAT}" != "json" && "${OUTPUT_FORMAT}" != "yaml" ]]; then
  echo "Unsupported --output-format: ${OUTPUT_FORMAT}" >&2
  exit 1
fi
if [[ "${BACKUP_FORMAT}" != "json" && "${BACKUP_FORMAT}" != "yaml" ]]; then
  echo "Unsupported --backup-format: ${BACKUP_FORMAT}" >&2
  exit 1
fi
if [[ "${APPLY}" == true || "${MODE_OVERRIDE}" == "cleanup-apply" ]]; then
  require_current_skill_role_supported
  export ITSI_CONFIG_APPLY_AUTHORIZED=1
fi

SPEC_JSON="$(mktemp)"
trap 'rm -f "${SPEC_JSON}"' EXIT

ruby "${SCRIPT_DIR}/spec_to_json.rb" --spec "${SPEC_PATH}" --output "${SPEC_JSON}"

if [[ "${MODE_OVERRIDE}" == "lint" ]]; then
  python3 "${SCRIPT_DIR}/lint_spec.py" --workflow "${WORKFLOW}" --spec-json "${SPEC_JSON}" --source-path "${SPEC_PATH}"
  exit $?
fi

LINT_ARGS=(--workflow "${WORKFLOW}" --spec-json "${SPEC_JSON}" --source-path "${SPEC_PATH}" --quiet)
if [[ "${APPLY}" == true || "${MODE_OVERRIDE}" == "cleanup-apply" ]]; then
  LINT_ARGS+=(--for-apply)
fi
python3 "${SCRIPT_DIR}/lint_spec.py" "${LINT_ARGS[@]}"

load_splunk_connection_settings
if [[ -n "${SPLUNK_USER:-}" ]]; then
  SPLUNK_USERNAME="${SPLUNK_USER}"
fi
if [[ -n "${SPLUNK_PASS:-}" ]]; then
  SPLUNK_PASSWORD="${SPLUNK_PASS}"
fi
export SPLUNK_PLATFORM SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_SESSION_KEY SPLUNK_USERNAME SPLUNK_PASSWORD SPLUNK_VERIFY_SSL SPLUNK_ALLOW_INSECURE_TLS SPLUNK_CA_CERT
export SPLUNK_SSH_HOST SPLUNK_SSH_PORT SPLUNK_SSH_USER SPLUNK_SSH_PASS SPLUNK_SSH_KNOWN_HOSTS_FILE

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
    MODE="preview"
    if [[ "${APPLY}" == true ]]; then
      MODE="apply"
    fi
    python3 "${SCRIPT_DIR}/run_content_packs.py" --spec-json "${SPEC_JSON}" --mode "${MODE}"
    ;;
  topology)
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
      python3 "${SCRIPT_DIR}/run_topology.py" --spec-json "${SPEC_JSON}" --mode "${MODE}" "${EXTRA_ARGS[@]}"
    else
      python3 "${SCRIPT_DIR}/run_topology.py" --spec-json "${SPEC_JSON}" --mode "${MODE}"
    fi
    ;;
  *)
    echo "Unsupported workflow: ${WORKFLOW}" >&2
    exit 1
    ;;
esac
