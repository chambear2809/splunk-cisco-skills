#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck disable=SC1091
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings 2>/dev/null || true

PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

MODE="render"
SECTIONS=""
SPEC="${SKILL_DIR}/template.example"
OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-ai-agent-monitoring-rendered"
REALM="${SPLUNK_O11Y_REALM:-}"
COLLECTOR_MODE=""
CLUSTER_NAME=""
WORKLOAD_KIND=""
WORKLOAD_NAMESPACE=""
WORKLOAD_NAME=""
CONTAINER_NAME=""
SERVICE_NAME=""
PYTHON_VERSION=""
FRAMEWORKS=""
TRANSLATORS=""
PROVIDER_ADJUNCTS=""
AI_INFRA_PRODUCTS=""
SEND_OTLP_HISTOGRAMS=""
HEC_INDEX=""
HEC_PLATFORM=""
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
PLATFORM_HEC_TOKEN_FILE=""
SERVICE_ACCOUNT_PASSWORD_FILE=""
ENABLE_CONTENT_CAPTURE=false
ACCEPT_CONTENT_CAPTURE=false
ENABLE_EVALUATIONS=false
ACCEPT_EVALUATION_COST=false
JSON_OUTPUT=false
DRY_RUN=false

usage() {
    cat <<'EOF'
Splunk Observability AI Agent Monitoring Setup

Usage:
  setup.sh [MODE] [OPTIONS]

Modes:
  --render                         Render plan tree (default)
  --validate                       Validate rendered output; composable with --render
  --doctor                         Render and validate doctor report
  --discover                       Print source/package/product catalog
  --refresh-package-catalog        Query PyPI and write package-catalog-refreshed.json
  --apply [SECTIONS]               Render, then apply CSV sections

Apply sections:
  collector,hec,loc,python-runtime,kubernetes-runtime,ai-infra-collector,dashboards,detectors

Options:
  --spec PATH
  --output-dir DIR
  --realm REALM
  --collector-mode kubernetes|linux
  --cluster-name NAME
  --workload-kind deployment|statefulset|daemonset
  --workload-namespace NAME
  --workload-name NAME
  --container-name NAME
  --service-name NAME
  --python-version VERSION
  --frameworks CSV
  --translators CSV
  --provider-adjuncts CSV
  --ai-infra-products CSV
  --send-otlp-histograms true|false
  --hec-index INDEX
  --hec-platform enterprise|cloud
  --enable-content-capture
  --accept-content-capture
  --enable-evaluations
  --accept-evaluation-cost
  --o11y-token-file PATH
  --platform-hec-token-file PATH
  --service-account-password-file PATH
  --json
  --dry-run
  --help

Direct-secret flags are rejected:
  --token --access-token --api-token --o11y-token --sf-token --hec-token --password
EOF
}

resolve_abs_path() {
    "${PYTHON_BIN}" - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

reject_direct_secret_flag() {
    reject_secret_arg "$1" "a file-based token option such as --o11y-token-file or --platform-hec-token-file"
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE="render"; shift ;;
        --validate) MODE="validate"; shift ;;
        --doctor) MODE="doctor"; shift ;;
        --discover) MODE="discover"; shift ;;
        --refresh-package-catalog) MODE="refresh-package-catalog"; shift ;;
        --apply)
            MODE="apply"
            if [[ $# -ge 2 && "$2" != --* ]]; then
                SECTIONS="$2"
                shift
            fi
            shift
            ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --collector-mode) require_arg "$1" "$#" || exit 1; COLLECTOR_MODE="$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; CLUSTER_NAME="$2"; shift 2 ;;
        --workload-kind) require_arg "$1" "$#" || exit 1; WORKLOAD_KIND="$2"; shift 2 ;;
        --workload-namespace) require_arg "$1" "$#" || exit 1; WORKLOAD_NAMESPACE="$2"; shift 2 ;;
        --workload-name) require_arg "$1" "$#" || exit 1; WORKLOAD_NAME="$2"; shift 2 ;;
        --container-name) require_arg "$1" "$#" || exit 1; CONTAINER_NAME="$2"; shift 2 ;;
        --service-name) require_arg "$1" "$#" || exit 1; SERVICE_NAME="$2"; shift 2 ;;
        --python-version) require_arg "$1" "$#" || exit 1; PYTHON_VERSION="$2"; shift 2 ;;
        --frameworks) require_arg "$1" "$#" || exit 1; FRAMEWORKS="$2"; shift 2 ;;
        --translators) require_arg "$1" "$#" || exit 1; TRANSLATORS="$2"; shift 2 ;;
        --provider-adjuncts) require_arg "$1" "$#" || exit 1; PROVIDER_ADJUNCTS="$2"; shift 2 ;;
        --ai-infra-products) require_arg "$1" "$#" || exit 1; AI_INFRA_PRODUCTS="$2"; shift 2 ;;
        --send-otlp-histograms) require_arg "$1" "$#" || exit 1; SEND_OTLP_HISTOGRAMS="$2"; shift 2 ;;
        --hec-index) require_arg "$1" "$#" || exit 1; HEC_INDEX="$2"; shift 2 ;;
        --hec-platform) require_arg "$1" "$#" || exit 1; HEC_PLATFORM="$2"; shift 2 ;;
        --enable-content-capture) ENABLE_CONTENT_CAPTURE=true; shift ;;
        --accept-content-capture) ACCEPT_CONTENT_CAPTURE=true; shift ;;
        --enable-evaluations) ENABLE_EVALUATIONS=true; shift ;;
        --accept-evaluation-cost) ACCEPT_EVALUATION_COST=true; shift ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --platform-hec-token-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --service-account-password-file) require_arg "$1" "$#" || exit 1; SERVICE_ACCOUNT_PASSWORD_FILE="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token|--hec-token|--password)
            reject_direct_secret_flag "$1"
            ;;
        --token=*|--access-token=*|--api-token=*|--o11y-token=*|--sf-token=*|--hec-token=*|--password=*)
            reject_direct_secret_flag "${1%%=*}"
            ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

renderer_args() {
    local args=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
    [[ -n "${REALM}" ]] && args+=(--realm "${REALM}")
    [[ -n "${COLLECTOR_MODE}" ]] && args+=(--collector-mode "${COLLECTOR_MODE}")
    [[ -n "${CLUSTER_NAME}" ]] && args+=(--cluster-name "${CLUSTER_NAME}")
    [[ -n "${WORKLOAD_KIND}" ]] && args+=(--workload-kind "${WORKLOAD_KIND}")
    [[ -n "${WORKLOAD_NAMESPACE}" ]] && args+=(--workload-namespace "${WORKLOAD_NAMESPACE}")
    [[ -n "${WORKLOAD_NAME}" ]] && args+=(--workload-name "${WORKLOAD_NAME}")
    [[ -n "${CONTAINER_NAME}" ]] && args+=(--container-name "${CONTAINER_NAME}")
    [[ -n "${SERVICE_NAME}" ]] && args+=(--service-name "${SERVICE_NAME}")
    [[ -n "${PYTHON_VERSION}" ]] && args+=(--python-version "${PYTHON_VERSION}")
    [[ -n "${FRAMEWORKS}" ]] && args+=(--frameworks "${FRAMEWORKS}")
    [[ -n "${TRANSLATORS}" ]] && args+=(--translators "${TRANSLATORS}")
    [[ -n "${PROVIDER_ADJUNCTS}" ]] && args+=(--provider-adjuncts "${PROVIDER_ADJUNCTS}")
    [[ -n "${AI_INFRA_PRODUCTS}" ]] && args+=(--ai-infra-products "${AI_INFRA_PRODUCTS}")
    [[ -n "${SEND_OTLP_HISTOGRAMS}" ]] && args+=(--send-otlp-histograms "${SEND_OTLP_HISTOGRAMS}")
    [[ -n "${HEC_INDEX}" ]] && args+=(--hec-index "${HEC_INDEX}")
    [[ -n "${HEC_PLATFORM}" ]] && args+=(--hec-platform "${HEC_PLATFORM}")
    [[ -n "${O11Y_TOKEN_FILE}" ]] && args+=(--o11y-token-file "${O11Y_TOKEN_FILE}")
    [[ -n "${PLATFORM_HEC_TOKEN_FILE}" ]] && args+=(--platform-hec-token-file "${PLATFORM_HEC_TOKEN_FILE}")
    [[ -n "${SERVICE_ACCOUNT_PASSWORD_FILE}" ]] && args+=(--service-account-password-file "${SERVICE_ACCOUNT_PASSWORD_FILE}")
    [[ "${ENABLE_CONTENT_CAPTURE}" == "true" ]] && args+=(--enable-content-capture)
    [[ "${ACCEPT_CONTENT_CAPTURE}" == "true" ]] && args+=(--accept-content-capture)
    [[ "${ENABLE_EVALUATIONS}" == "true" ]] && args+=(--enable-evaluations)
    [[ "${ACCEPT_EVALUATION_COST}" == "true" ]] && args+=(--accept-evaluation-cost)
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    [[ "${DRY_RUN}" == "true" && "${MODE}" == "render" ]] && args+=(--dry-run)
    printf '%s\n' "${args[@]}"
}

run_render() {
    local args=()
    while IFS= read -r arg; do args+=("$arg"); done < <(renderer_args)
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${args[@]}"
}

run_validate() {
    local args=(--output-dir "${OUTPUT_DIR}")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    [[ "${MODE}" == "doctor" ]] && args+=(--doctor)
    bash "${SCRIPT_DIR}/validate.sh" "${args[@]}"
}

run_apply_section() {
    local section="$1"
    local script="${OUTPUT_DIR}/scripts/apply-${section}.sh"
    if [[ ! -x "${script}" ]]; then
        echo "ERROR: apply script missing for section '${section}': ${script}" >&2
        exit 1
    fi
    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "DRY RUN: ${script}"
        return 0
    fi
    bash "${script}"
}

case "${MODE}" in
    render)
        run_render
        ;;
    validate)
        run_render
        run_validate
        ;;
    doctor)
        run_render || true
        run_validate
        ;;
    discover)
        "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" --discover
        ;;
    refresh-package-catalog)
        "${PYTHON_BIN}" "${SCRIPT_DIR}/refresh_package_catalog.py" --output-dir "${OUTPUT_DIR}" ${JSON_OUTPUT:+--json}
        ;;
	    apply)
	        run_render
	        if [[ -z "${SECTIONS}" ]]; then
	            SECTIONS="hec,collector,loc,python-runtime,kubernetes-runtime,ai-infra-collector,dashboards,detectors"
	        fi
        IFS=',' read -ra section_array <<< "${SECTIONS}"
        for raw_section in "${section_array[@]}"; do
            section="${raw_section// /}"
            [[ -z "${section}" ]] && continue
            echo "==> applying section: ${section}"
            run_apply_section "${section}"
        done
        ;;
    *)
        echo "Unknown mode: ${MODE}" >&2
        usage
        exit 1
        ;;
esac
