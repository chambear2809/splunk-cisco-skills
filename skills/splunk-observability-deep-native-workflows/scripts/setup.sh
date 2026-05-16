#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON:-python3}"
fi

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-deep-native-rendered"

usage() {
    cat <<'EOF'
Splunk Observability deep native workflows

Usage:
  bash skills/splunk-observability-deep-native-workflows/scripts/setup.sh [mode] --spec SPEC [options]

Modes:
  --render              Validate and render a workflow packet
  --validate            Validate a spec and/or rendered output
  --json                Emit JSON output where supported

Options:
  --spec PATH           YAML or JSON workflow spec
  --output-dir DIR      Rendered output directory
  --realm REALM         Observability realm, such as us0
  --help                Show this help

This skill is render-only. Direct secret flags such as --token, --access-token,
--api-token, --o11y-token, and --sf-token are rejected.
EOF
}

RENDER=false
VALIDATE=false
JSON_OUTPUT=false
SPEC=""
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
REALM="${SPLUNK_O11Y_REALM:-}"

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --validate) VALIDATE=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token|--password|--client-secret)
            reject_secret_arg "$1" "a file-backed downstream apply workflow"
            exit 1
            ;;
        --token=*|--access-token=*|--api-token=*|--o11y-token=*|--sf-token=*|--password=*|--client-secret=*)
            reject_secret_arg "${1%%=*}" "a file-backed downstream apply workflow"
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

if [[ "${RENDER}" != "true" && "${VALIDATE}" != "true" ]]; then
    RENDER=true
fi

json_flag=()
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    json_flag=(--json)
fi

if [[ -z "${SPEC}" ]]; then
    log "ERROR: --spec is required."
    exit 1
fi

case "${SPEC}" in
    *.json|*.JSON) ;;
    *)
        if ! "${PYTHON_BIN}" -c 'import yaml' >/dev/null 2>&1; then
            log "ERROR: YAML specs require PyYAML for ${PYTHON_BIN}."
            log "Install repo Python dependencies with: ${PYTHON_BIN} -m pip install -r requirements-agent.txt"
            exit 1
        fi
        ;;
esac

if [[ "${RENDER}" == "true" ]]; then
    render_args=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
    if [[ -n "${REALM}" ]]; then
        render_args+=(--realm "${REALM}")
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_workflows.py" "${render_args[@]}" "${json_flag[@]}"
fi

if [[ "${VALIDATE}" == "true" ]]; then
    validate_args=(--validate --spec "${SPEC}")
    if [[ -d "${OUTPUT_DIR}" ]]; then
        validate_args+=(--output-dir "${OUTPUT_DIR}")
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_workflows.py" "${validate_args[@]}" "${json_flag[@]}"
fi
