#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_RENDER_DIR_NAME="splunk-enterprise-k8s-rendered"
TARGET="sok"
OUTPUT_DIR=""
JSON_OUTPUT=false
LIVE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Kubernetes Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --target sok|pod          Rendered target to validate (default: sok)
  --output-dir PATH         Render output directory (default: ./splunk-enterprise-k8s-rendered)
  --live                    Run rendered status commands after static checks
  --json                    Emit machine-readable validation result
  --help                    Show this help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) require_arg "$1" $# || exit 1; TARGET="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

json_array() {
    python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]), end="")
PY
}

json_string() {
    python3 - "$1" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1]), end="")
PY
}

metadata_field() {
    local metadata_file="$1" field="$2"
    python3 - "${metadata_file}" "${field}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = json.load(handle)
value = payload.get(sys.argv[2], "")
print(value if value is not None else "", end="")
PY
}

run_sok_helm_template_checks() {
    local render_dir="$1"
    local metadata_file="${render_dir}/metadata.json"
    HELM_TEMPLATE_CHECKED=false
    HELM_TEMPLATE_OK=true
    HELM_TEMPLATE_SKIPPED=""

    if ! command -v helm >/dev/null 2>&1; then
        HELM_TEMPLATE_SKIPPED="helm not found"
        return 0
    fi

    HELM_TEMPLATE_CHECKED=true
    local chart_version operator_namespace namespace release_name operator_release_name
    chart_version="$(metadata_field "${metadata_file}" chart_version)"
    operator_namespace="$(metadata_field "${metadata_file}" operator_namespace)"
    namespace="$(metadata_field "${metadata_file}" namespace)"
    release_name="$(metadata_field "${metadata_file}" release_name)"
    operator_release_name="$(metadata_field "${metadata_file}" operator_release_name)"

    if ! (
        cd "${render_dir}" && \
        helm repo add splunk https://splunk.github.io/splunk-operator/ --force-update >/dev/null && \
        helm repo update splunk >/dev/null && \
        helm template "${operator_release_name}" splunk/splunk-operator \
            --version "${chart_version}" \
            --namespace "${operator_namespace}" \
            --values operator-values.yaml >/dev/null && \
        helm template "${release_name}" splunk/splunk-enterprise \
            --version "${chart_version}" \
            --namespace "${namespace}" \
            --values enterprise-values.yaml >/dev/null
    ); then
        HELM_TEMPLATE_OK=false
    fi
}

main() {
    validate_choice "${TARGET}" sok pod
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi

    local render_dir="${OUTPUT_DIR}/${TARGET}"
    local missing=()
    local required=()
    if [[ "${TARGET}" == "sok" ]]; then
        required=(
            README.md
            metadata.json
            namespace.yaml
            crds-install.sh
            preflight.sh
            operator-values.yaml
            enterprise-values.yaml
            helm-install-operator.sh
            helm-install-enterprise.sh
            status.sh
        )
    else
        required=(
            README.md
            metadata.json
            cluster-config.yaml
            preflight.sh
            deploy.sh
            status-workers.sh
            status.sh
            get-creds.sh
            web-docs.sh
        )
    fi

    local file
    for file in "${required[@]}"; do
        if [[ ! -f "${render_dir}/${file}" ]]; then
            missing+=("${file}")
        fi
    done

    local ok=true
    if (( ${#missing[@]} > 0 )); then
        ok=false
    fi

    HELM_TEMPLATE_CHECKED=false
    HELM_TEMPLATE_OK=true
    HELM_TEMPLATE_SKIPPED=""
    if [[ "${TARGET}" == "sok" && "${ok}" == "true" ]]; then
        run_sok_helm_template_checks "${render_dir}"
        if [[ "${HELM_TEMPLATE_OK}" != "true" ]]; then
            ok=false
        fi
    fi

    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        printf '{"target":%s,"render_dir":%s,"ok":%s,"missing":%s,"helm_template_checked":%s,"helm_template_ok":%s,"helm_template_skipped":%s}\n' \
            "$(json_string "${TARGET}")" \
            "$(json_string "${render_dir}")" \
            "${ok}" \
            "$(json_array "${missing[@]}")" \
            "${HELM_TEMPLATE_CHECKED}" \
            "${HELM_TEMPLATE_OK}" \
            "$(json_string "${HELM_TEMPLATE_SKIPPED}")"
    else
        if [[ "${ok}" == "true" ]]; then
            log "Rendered ${TARGET} assets are present under ${render_dir}."
            if [[ "${TARGET}" == "sok" && "${HELM_TEMPLATE_CHECKED}" == "true" ]]; then
                log "Helm template checks passed for Splunk Operator and Enterprise charts."
            elif [[ "${TARGET}" == "sok" && -n "${HELM_TEMPLATE_SKIPPED}" ]]; then
                log "WARNING: Skipped Helm template checks: ${HELM_TEMPLATE_SKIPPED}."
            fi
        else
            if (( ${#missing[@]} > 0 )); then
                log "ERROR: Missing rendered ${TARGET} assets under ${render_dir}: ${missing[*]}"
            fi
            if [[ "${TARGET}" == "sok" && "${HELM_TEMPLATE_CHECKED}" == "true" && "${HELM_TEMPLATE_OK}" != "true" ]]; then
                log "ERROR: Helm template checks failed for rendered SOK values."
            fi
        fi
    fi

    if [[ "${ok}" != "true" ]]; then
        exit 1
    fi

    if [[ "${LIVE}" == "true" ]]; then
        if [[ "${TARGET}" == "pod" ]]; then
            (cd "${render_dir}" && ./status-workers.sh)
        fi
        (cd "${render_dir}" && ./status.sh)
    fi
}

main "$@"
