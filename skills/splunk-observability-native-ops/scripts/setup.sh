#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-native-rendered"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON:-python3}"
fi

usage() {
    cat <<'EOF'
Splunk Observability native operations

Usage:
  bash skills/splunk-observability-native-ops/scripts/setup.sh [mode] --spec SPEC [options]

Modes:
  --render              Validate and render native operations assets
  --validate            Validate a spec and/or rendered output
  --apply               Render, validate, then execute API-supported actions
  --dry-run             With --apply, show the API sequence without network writes
  --json                Emit JSON output where supported

Options:
  --spec PATH         YAML or JSON native operations spec
  --output-dir DIR    Rendered output directory
  --realm REALM       Observability realm, such as us0
  --token-file PATH   File containing an Observability API token for live apply
  --help              Show this help

Direct secret flags such as --token, --access-token, --api-token, and
--sf-token are rejected. Use --token-file instead.

Splunk On-Call API actions live in the splunk-oncall-setup skill, not here.
EOF
}

RENDER=false
VALIDATE=false
APPLY=false
DRY_RUN=false
JSON_OUTPUT=false

SPEC=""
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
REALM="${SPLUNK_O11Y_REALM:-}"
TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --validate) VALIDATE=true; shift ;;
        --apply) APPLY=true; RENDER=true; VALIDATE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --token-file) require_arg "$1" "$#" || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token)
            reject_secret_arg "$1" "--token-file"
            exit 1
            ;;
        --token=*|--access-token=*|--api-token=*|--o11y-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "--token-file"
            exit 1
            ;;
        --oncall-api-id|--oncall-api-key|--on-call-api-key|--x-vo-api-key)
            log "ERROR: Splunk On-Call API actions live in the splunk-oncall-setup skill."
            log "Use: bash skills/splunk-oncall-setup/scripts/setup.sh --apply ..."
            exit 1
            ;;
        --oncall-api-id=*|--oncall-api-key=*|--on-call-api-key=*|--x-vo-api-key=*)
            log "ERROR: Splunk On-Call API actions live in the splunk-oncall-setup skill."
            log "Use: bash skills/splunk-oncall-setup/scripts/setup.sh --apply ..."
            exit 1
            ;;
        --oncall-api-key-file)
            log "ERROR: Splunk On-Call API actions live in the splunk-oncall-setup skill."
            log "Use: bash skills/splunk-oncall-setup/scripts/setup.sh --apply --api-key-file ..."
            exit 1
            ;;
        --oncall-api-key-file=*)
            log "ERROR: Splunk On-Call API actions live in the splunk-oncall-setup skill."
            log "Use: bash skills/splunk-oncall-setup/scripts/setup.sh --apply --api-key-file ..."
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ "${RENDER}" != "true" && "${VALIDATE}" != "true" && "${APPLY}" != "true" ]]; then
    RENDER=true
fi

json_flag=()
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    json_flag=(--json)
fi

if [[ -z "${SPEC}" && ("${RENDER}" == "true" || "${APPLY}" == "true") ]]; then
    log "ERROR: --spec is required for render and apply."
    exit 1
fi

if [[ -n "${SPEC}" ]]; then
    case "${SPEC}" in
        *.json|*.JSON) ;;
        *)
            if ! "${PYTHON_BIN}" -c 'import yaml' >/dev/null 2>&1; then
                log "ERROR: YAML native operations specs require PyYAML for ${PYTHON_BIN}."
                log "Install repo Python dependencies with: ${PYTHON_BIN} -m pip install -r requirements-agent.txt"
                log "Or use the JSON example at skills/splunk-observability-native-ops/templates/native-ops.example.json."
                exit 1
            fi
            ;;
    esac
fi

if [[ "${VALIDATE}" == "true" && "${RENDER}" != "true" ]]; then
    validate_args=()
    if [[ -n "${SPEC}" ]]; then
        validate_args+=(--spec "${SPEC}")
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        validate_args+=(--output-dir "${OUTPUT_DIR}")
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_native_ops.py" "${validate_args[@]}" "${json_flag[@]}"
    exit $?
fi

if [[ "${RENDER}" == "true" ]]; then
    render_args=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
    if [[ -n "${REALM}" ]]; then
        render_args+=(--realm "${REALM}")
    fi
    if [[ "${JSON_OUTPUT}" == "true" && "${APPLY}" != "true" ]]; then
        render_args+=(--json)
    fi
    if [[ "${JSON_OUTPUT}" == "true" && "${APPLY}" == "true" ]]; then
        "${PYTHON_BIN}" "${SCRIPT_DIR}/render_native_ops.py" "${render_args[@]}" >&2
        "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_native_ops.py" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" >&2
    else
        "${PYTHON_BIN}" "${SCRIPT_DIR}/render_native_ops.py" "${render_args[@]}"
        "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_native_ops.py" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}"
    fi
fi

if [[ "${APPLY}" == "true" ]]; then
    if [[ "${DRY_RUN}" != "true" && (-z "${TOKEN_FILE}" || ! -r "${TOKEN_FILE}") ]]; then
        log "ERROR: --token-file is required and must be readable for live --apply."
        exit 1
    fi
    apply_args=(apply --plan-dir "${OUTPUT_DIR}")
    if [[ -n "${REALM}" ]]; then
        apply_args+=(--realm "${REALM}")
    fi
    if [[ -n "${TOKEN_FILE}" ]]; then
        apply_args+=(--token-file "${TOKEN_FILE}")
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        apply_args+=(--dry-run)
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/o11y_native_api.py" "${apply_args[@]}"
fi
