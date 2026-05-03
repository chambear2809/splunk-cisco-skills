#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-dashboard-rendered"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON:-python3}"
fi

usage() {
    cat <<'EOF'
Splunk Observability dashboard builder

Usage:
  bash skills/splunk-observability-dashboard-builder/scripts/setup.sh [mode] --spec SPEC [options]

Modes:
  --render              Validate and render classic API payloads
  --validate            Validate a spec and/or rendered payloads
  --apply               Render, then create dashboard group/charts/dashboard through the API
  --update-existing     With --apply, fetch existing objects and PUT full updates by ID
  --discover-metrics    Query Observability metric metadata
  --dry-run             For apply, show API creation sequence without live writes
  --json                Emit JSON output where supported

Options:
  --spec PATH           YAML or JSON dashboard spec
  --output-dir DIR      Rendered output directory
  --realm REALM         Observability realm, such as us0
  --token-file PATH     File containing Observability API token for live API operations
  --query TEXT          Metric discovery query
  --limit N             Metric discovery result limit
  --help                Show this help

Direct token flags such as --token, --access-token, --api-token, --o11y-token, and --sf-token are rejected.
EOF
}

RENDER=false
VALIDATE=false
APPLY=false
UPDATE_EXISTING=false
DISCOVER_METRICS=false
DRY_RUN=false
JSON_OUTPUT=false

SPEC=""
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
REALM="${SPLUNK_O11Y_REALM:-}"
TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
QUERY=""
LIMIT="25"

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --validate) VALIDATE=true; shift ;;
        --apply) APPLY=true; RENDER=true; shift ;;
        --update-existing) UPDATE_EXISTING=true; shift ;;
        --discover-metrics) DISCOVER_METRICS=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --token-file) require_arg "$1" "$#" || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --query) require_arg "$1" "$#" || exit 1; QUERY="$2"; shift 2 ;;
        --limit) require_arg "$1" "$#" || exit 1; LIMIT="$2"; shift 2 ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token)
            reject_secret_arg "$1" "--token-file"
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

if [[ "${RENDER}" != "true" && "${VALIDATE}" != "true" && "${APPLY}" != "true" && "${DISCOVER_METRICS}" != "true" ]]; then
    RENDER=true
fi

json_flag=()
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    json_flag=(--json)
fi

if [[ "${DISCOVER_METRICS}" == "true" ]]; then
    if [[ -z "${REALM}" ]]; then
        log "ERROR: --realm is required for --discover-metrics."
        exit 1
    fi
    if [[ -z "${TOKEN_FILE}" || ! -r "${TOKEN_FILE}" ]]; then
        log "ERROR: --token-file is required and must be readable for --discover-metrics."
        exit 1
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/o11y_dashboard_api.py" discover-metrics \
        --realm "${REALM}" \
        --token-file "${TOKEN_FILE}" \
        --query "${QUERY}" \
        --limit "${LIMIT}"
    exit $?
fi

if [[ -z "${SPEC}" ]]; then
    log "ERROR: --spec is required for render, validate, and apply."
    exit 1
fi

case "${SPEC}" in
    *.json|*.JSON) ;;
    *)
        if ! "${PYTHON_BIN}" -c 'import yaml' >/dev/null 2>&1; then
            log "ERROR: YAML dashboard specs require PyYAML for ${PYTHON_BIN}."
            log "Install repo Python dependencies with: ${PYTHON_BIN} -m pip install -r requirements-agent.txt"
            log "Or use the JSON example at skills/splunk-observability-dashboard-builder/templates/dashboard.example.json."
            exit 1
        fi
        ;;
esac

if [[ "${VALIDATE}" == "true" && "${RENDER}" != "true" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_dashboard.py" --spec "${SPEC}" "${json_flag[@]}"
    exit $?
fi

if [[ "${RENDER}" == "true" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_dashboard.py" \
        --spec "${SPEC}" \
        --output-dir "${OUTPUT_DIR}" \
        "${json_flag[@]}"
    "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_dashboard.py" \
        --spec "${SPEC}" \
        --output-dir "${OUTPUT_DIR}"
fi

if [[ "${APPLY}" == "true" ]]; then
    if [[ "${DRY_RUN}" != "true" && (-z "${TOKEN_FILE}" || ! -r "${TOKEN_FILE}") ]]; then
        log "ERROR: --token-file is required and must be readable for --apply."
        exit 1
    fi
    if [[ "${DRY_RUN}" != "true" && "${UPDATE_EXISTING}" != "true" ]]; then
        log "WARN: --apply always CREATES new dashboard groups, charts, and dashboards in this version."
        log "      It does not update existing objects. Re-running --apply against the same plan"
        log "      will produce duplicate dashboards in Splunk Observability Cloud. To update an"
        log "      existing dashboard, GET it from the API, modify it, and PUT it back manually,"
        log "      or wait for the v2 reconciler that supports id-based updates."
    elif [[ "${DRY_RUN}" != "true" ]]; then
        log "INFO: --update-existing will GET existing dashboard/chart objects before PUT updates."
    fi
    apply_args=(apply --plan-dir "${OUTPUT_DIR}")
    if [[ "${UPDATE_EXISTING}" == "true" ]]; then
        apply_args+=(--update-existing)
    fi
    if [[ -n "${TOKEN_FILE}" ]]; then
        apply_args+=(--token-file "${TOKEN_FILE}")
    fi
    if [[ -n "${REALM}" ]]; then
        apply_args+=(--realm "${REALM}")
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        apply_args+=(--dry-run)
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/o11y_dashboard_api.py" "${apply_args[@]}"
fi
