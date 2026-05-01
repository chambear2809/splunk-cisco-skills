#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-enterprise-k8s-rendered"

TARGET="sok"
ARCHITECTURE="s1"
POD_PROFILE=""
PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""
NAMESPACE="splunk-operator"
OPERATOR_NAMESPACE="splunk-operator"
RELEASE_NAME="splunk-enterprise"
OPERATOR_RELEASE_NAME="splunk-operator"
OPERATOR_VERSION="3.1.0"
CHART_VERSION=""
SPLUNK_VERSION="10.2.0"
SPLUNK_IMAGE=""
STORAGE_CLASS=""
ETC_STORAGE="10Gi"
VAR_STORAGE="100Gi"
STANDALONE_REPLICAS="1"
INDEXER_REPLICAS="3"
SEARCH_HEAD_REPLICAS="3"
SITE_COUNT="3"
SITE_ZONES=""
LICENSE_FILE=""
SMARTSTORE_BUCKET=""
SMARTSTORE_PREFIX=""
SMARTSTORE_REGION=""
SMARTSTORE_ENDPOINT=""
SMARTSTORE_SECRET_REF=""
EKS_CLUSTER_NAME=""
AWS_REGION=""
CONTROLLER_IPS=""
WORKER_IPS=""
SSH_USER="splunkadmin"
SSH_PRIVATE_KEY_FILE="/path/to/ssh-private-key"
INDEXER_APPS=""
SEARCH_APPS=""
STANDALONE_APPS=""
PREMIUM_APPS=""
ACCEPT_SPLUNK_GENERAL_TERMS=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Kubernetes Setup

Usage: $(basename "$0") [OPTIONS]

Core options:
  --target sok|pod                         Setup target (default: sok)
  --architecture s1|c3|m4                  SOK SVA architecture (default: s1)
  --pod-profile PROFILE                    POD profile: pod-small|pod-medium|pod-large and -es variants
  --phase render|preflight|apply|status|all
  --apply                                  Apply after rendering when phase is render
  --dry-run                                Show planned work without rendering or executing
  --json                                   Emit JSON plan/metadata for render or dry-run only
  --output-dir PATH                        Render output directory (default: ./splunk-enterprise-k8s-rendered)

SOK options:
  --namespace NAME                         Splunk Enterprise namespace (default: splunk-operator)
  --operator-namespace NAME                Operator namespace (default: splunk-operator)
  --release-name NAME                      Enterprise Helm release (default: splunk-enterprise)
  --operator-release-name NAME             Operator Helm release (default: splunk-operator)
  --operator-version VERSION               Splunk Operator version (default: 3.1.0)
  --chart-version VERSION                  Helm chart version (default: follows --operator-version)
  --splunk-version VERSION                 Splunk Enterprise version (default: 10.2.0)
  --splunk-image IMAGE                     Override Splunk Enterprise image
  --storage-class NAME                     Kubernetes StorageClass override
  --etc-storage SIZE                       /opt/splunk/etc PVC size (default: 10Gi)
  --var-storage SIZE                       /opt/splunk/var PVC size (default: 100Gi)
  --standalone-replicas N                  S1 standalone count (default: 1)
  --indexer-replicas N                     C3 total indexers; M4 indexers per site (default: 3)
  --search-head-replicas N                 C3/M4 search head count (default: 3)
  --site-count N                           M4 site count (default: 3)
  --site-zones CSV                         M4 Kubernetes zone labels, one per site
  --license-file PATH                      Local license file path for rendered ConfigMap helper
  --smartstore-bucket NAME                 S3 bucket/path for SmartStore
  --smartstore-prefix PATH                 Optional SmartStore prefix within the bucket
  --smartstore-region REGION              SmartStore AWS region
  --smartstore-endpoint URL                SmartStore endpoint override
  --smartstore-secret-ref NAME             Existing Kubernetes secret for SmartStore credentials
  --eks-cluster-name NAME                  Render/run EKS kubeconfig helper
  --aws-region REGION                      AWS region for EKS and SmartStore helpers
  --accept-splunk-general-terms            Required for Splunk Enterprise 10.x container images

POD options:
  --controller-ips CSV                     Controller node IPs
  --worker-ips CSV                         Worker node IPs
  --ssh-user USER                          Sudo-capable SSH user (default: splunkadmin)
  --ssh-private-key-file PATH              SSH private key path on bastion
  --indexer-apps CSV                       App packages for indexer cluster scope
  --search-apps CSV                        App packages for SHC cluster scope
  --standalone-apps CSV                    App packages for pod-small standalone local scope
  --premium-apps CSV                       Premium app packages for POD ES profiles

Examples:
  $(basename "$0") --target sok --architecture c3 --accept-splunk-general-terms
  $(basename "$0") --target sok --phase apply --architecture s1 --accept-splunk-general-terms
  $(basename "$0") --target pod --pod-profile pod-medium --controller-ips 10.10.10.1,10.10.10.2,10.10.10.3

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) require_arg "$1" $# || exit 1; TARGET="$2"; shift 2 ;;
        --architecture) require_arg "$1" $# || exit 1; ARCHITECTURE="$2"; shift 2 ;;
        --pod-profile) require_arg "$1" $# || exit 1; POD_PROFILE="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --namespace) require_arg "$1" $# || exit 1; NAMESPACE="$2"; shift 2 ;;
        --operator-namespace) require_arg "$1" $# || exit 1; OPERATOR_NAMESPACE="$2"; shift 2 ;;
        --release-name) require_arg "$1" $# || exit 1; RELEASE_NAME="$2"; shift 2 ;;
        --operator-release-name) require_arg "$1" $# || exit 1; OPERATOR_RELEASE_NAME="$2"; shift 2 ;;
        --operator-version) require_arg "$1" $# || exit 1; OPERATOR_VERSION="$2"; shift 2 ;;
        --chart-version) require_arg "$1" $# || exit 1; CHART_VERSION="$2"; shift 2 ;;
        --splunk-version) require_arg "$1" $# || exit 1; SPLUNK_VERSION="$2"; shift 2 ;;
        --splunk-image) require_arg "$1" $# || exit 1; SPLUNK_IMAGE="$2"; shift 2 ;;
        --storage-class) require_arg "$1" $# || exit 1; STORAGE_CLASS="$2"; shift 2 ;;
        --etc-storage) require_arg "$1" $# || exit 1; ETC_STORAGE="$2"; shift 2 ;;
        --var-storage) require_arg "$1" $# || exit 1; VAR_STORAGE="$2"; shift 2 ;;
        --standalone-replicas) require_arg "$1" $# || exit 1; STANDALONE_REPLICAS="$2"; shift 2 ;;
        --indexer-replicas) require_arg "$1" $# || exit 1; INDEXER_REPLICAS="$2"; shift 2 ;;
        --search-head-replicas) require_arg "$1" $# || exit 1; SEARCH_HEAD_REPLICAS="$2"; shift 2 ;;
        --site-count) require_arg "$1" $# || exit 1; SITE_COUNT="$2"; shift 2 ;;
        --site-zones) require_arg "$1" $# || exit 1; SITE_ZONES="$2"; shift 2 ;;
        --license-file) require_arg "$1" $# || exit 1; LICENSE_FILE="$2"; shift 2 ;;
        --smartstore-bucket) require_arg "$1" $# || exit 1; SMARTSTORE_BUCKET="$2"; shift 2 ;;
        --smartstore-prefix) require_arg "$1" $# || exit 1; SMARTSTORE_PREFIX="$2"; shift 2 ;;
        --smartstore-region) require_arg "$1" $# || exit 1; SMARTSTORE_REGION="$2"; shift 2 ;;
        --smartstore-endpoint) require_arg "$1" $# || exit 1; SMARTSTORE_ENDPOINT="$2"; shift 2 ;;
        --smartstore-secret-ref) require_arg "$1" $# || exit 1; SMARTSTORE_SECRET_REF="$2"; shift 2 ;;
        --eks-cluster-name) require_arg "$1" $# || exit 1; EKS_CLUSTER_NAME="$2"; shift 2 ;;
        --aws-region) require_arg "$1" $# || exit 1; AWS_REGION="$2"; shift 2 ;;
        --controller-ips) require_arg "$1" $# || exit 1; CONTROLLER_IPS="$2"; shift 2 ;;
        --worker-ips) require_arg "$1" $# || exit 1; WORKER_IPS="$2"; shift 2 ;;
        --ssh-user) require_arg "$1" $# || exit 1; SSH_USER="$2"; shift 2 ;;
        --ssh-private-key-file) require_arg "$1" $# || exit 1; SSH_PRIVATE_KEY_FILE="$2"; shift 2 ;;
        --indexer-apps) require_arg "$1" $# || exit 1; INDEXER_APPS="$2"; shift 2 ;;
        --search-apps) require_arg "$1" $# || exit 1; SEARCH_APPS="$2"; shift 2 ;;
        --standalone-apps) require_arg "$1" $# || exit 1; STANDALONE_APPS="$2"; shift 2 ;;
        --premium-apps) require_arg "$1" $# || exit 1; PREMIUM_APPS="$2"; shift 2 ;;
        --accept-splunk-general-terms) ACCEPT_SPLUNK_GENERAL_TERMS=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

validate_positive_int() {
    local value="$1" option="$2"
    if [[ ! "${value}" =~ ^[0-9]+$ ]] || (( value < 1 )); then
        log "ERROR: ${option} must be a positive integer."
        exit 1
    fi
}

pod_phase_needs_concrete_inputs() {
    [[ "${TARGET}" == "pod" ]] || return 1
    [[ "${DRY_RUN}" != "true" ]] || return 1
    case "${PHASE}" in
        preflight|apply|all) return 0 ;;
        render) [[ "${APPLY}" == "true" ]] ;;
        *) return 1 ;;
    esac
}

validate_args() {
    validate_choice "${TARGET}" sok pod
    validate_choice "${ARCHITECTURE}" s1 c3 m4
    validate_choice "${PHASE}" render preflight apply status all
    if [[ -n "${POD_PROFILE}" ]]; then
        validate_choice "${POD_PROFILE}" pod-small pod-medium pod-large pod-small-es pod-medium-es pod-large-es
    fi
    validate_positive_int "${STANDALONE_REPLICAS}" "--standalone-replicas"
    validate_positive_int "${INDEXER_REPLICAS}" "--indexer-replicas"
    validate_positive_int "${SEARCH_HEAD_REPLICAS}" "--search-head-replicas"
    validate_positive_int "${SITE_COUNT}" "--site-count"
    if [[ "${TARGET}" == "sok" ]]; then
        if [[ "${ARCHITECTURE}" == "c3" && "${INDEXER_REPLICAS}" -lt 3 ]]; then
            log "ERROR: --indexer-replicas must be at least 3 for SOK C3."
            exit 1
        fi
        if [[ ( "${ARCHITECTURE}" == "c3" || "${ARCHITECTURE}" == "m4" ) && "${SEARCH_HEAD_REPLICAS}" -lt 3 ]]; then
            log "ERROR: --search-head-replicas must be at least 3 for SOK C3/M4."
            exit 1
        fi
    fi

    if [[ -n "${LICENSE_FILE}" && ! -f "${LICENSE_FILE}" ]]; then
        log "ERROR: License file not found: ${LICENSE_FILE}"
        exit 1
    fi
    if [[ "${TARGET}" == "pod" && -n "${SSH_PRIVATE_KEY_FILE}" && "${SSH_PRIVATE_KEY_FILE}" != "/path/to/ssh-private-key" && ! -f "${SSH_PRIVATE_KEY_FILE}" ]]; then
        log "ERROR: SSH private key file not found: ${SSH_PRIVATE_KEY_FILE}"
        exit 1
    fi
    if pod_phase_needs_concrete_inputs; then
        if [[ -z "${CONTROLLER_IPS}" ]]; then
            log "ERROR: --controller-ips is required for POD preflight/apply workflows."
            exit 1
        fi
        if [[ -z "${WORKER_IPS}" ]]; then
            log "ERROR: --worker-ips is required for POD preflight/apply workflows."
            exit 1
        fi
        if [[ -z "${LICENSE_FILE}" ]]; then
            log "ERROR: --license-file is required for POD preflight/apply workflows."
            exit 1
        fi
        if [[ -z "${SSH_PRIVATE_KEY_FILE}" || "${SSH_PRIVATE_KEY_FILE}" == "/path/to/ssh-private-key" ]]; then
            log "ERROR: --ssh-private-key-file must point to the bastion SSH key for POD preflight/apply workflows."
            exit 1
        fi
    fi
    if [[ -n "${EKS_CLUSTER_NAME}" && -z "${AWS_REGION}" ]]; then
        log "ERROR: --aws-region is required with --eks-cluster-name."
        exit 1
    fi
    if [[ -n "${SMARTSTORE_BUCKET}" && -z "${SMARTSTORE_REGION}" && -z "${SMARTSTORE_ENDPOINT}" ]]; then
        log "ERROR: --smartstore-region or --smartstore-endpoint is required with --smartstore-bucket."
        exit 1
    fi
    if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" && ( "${PHASE}" != "render" || "${APPLY}" == "true" ) ]]; then
        log "ERROR: --json is supported only for render-only or --dry-run workflows."
        exit 1
    fi

    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --target "${TARGET}"
        --architecture "${ARCHITECTURE}"
        --output-dir "${OUTPUT_DIR}"
        --namespace "${NAMESPACE}"
        --operator-namespace "${OPERATOR_NAMESPACE}"
        --release-name "${RELEASE_NAME}"
        --operator-release-name "${OPERATOR_RELEASE_NAME}"
        --operator-version "${OPERATOR_VERSION}"
        --chart-version "${CHART_VERSION}"
        --splunk-version "${SPLUNK_VERSION}"
        --storage-class "${STORAGE_CLASS}"
        --etc-storage "${ETC_STORAGE}"
        --var-storage "${VAR_STORAGE}"
        --standalone-replicas "${STANDALONE_REPLICAS}"
        --indexer-replicas "${INDEXER_REPLICAS}"
        --search-head-replicas "${SEARCH_HEAD_REPLICAS}"
        --site-count "${SITE_COUNT}"
        --site-zones "${SITE_ZONES}"
        --license-file "${LICENSE_FILE}"
        --smartstore-bucket "${SMARTSTORE_BUCKET}"
        --smartstore-prefix "${SMARTSTORE_PREFIX}"
        --smartstore-region "${SMARTSTORE_REGION}"
        --smartstore-endpoint "${SMARTSTORE_ENDPOINT}"
        --smartstore-secret-ref "${SMARTSTORE_SECRET_REF}"
        --eks-cluster-name "${EKS_CLUSTER_NAME}"
        --aws-region "${AWS_REGION}"
        --controller-ips "${CONTROLLER_IPS}"
        --worker-ips "${WORKER_IPS}"
        --ssh-user "${SSH_USER}"
        --ssh-private-key-file "${SSH_PRIVATE_KEY_FILE}"
        --indexer-apps "${INDEXER_APPS}"
        --search-apps "${SEARCH_APPS}"
        --standalone-apps "${STANDALONE_APPS}"
        --premium-apps "${PREMIUM_APPS}"
    )
    if [[ -n "${POD_PROFILE}" ]]; then
        RENDER_ARGS+=(--pod-profile "${POD_PROFILE}")
    fi
    if [[ -n "${SPLUNK_IMAGE}" ]]; then
        RENDER_ARGS+=(--splunk-image "${SPLUNK_IMAGE}")
    fi
    if [[ "${ACCEPT_SPLUNK_GENERAL_TERMS}" == "true" ]]; then
        RENDER_ARGS+=(--accept-splunk-general-terms)
    fi
}

render_assets() {
    local extra_args=()
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        extra_args+=(--json)
    fi
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" "${extra_args[@]}"
}

render_dir() {
    printf '%s/%s' "${OUTPUT_DIR}" "${TARGET}"
}

run_rendered_script() {
    local script_name="$1"
    local dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_name})"
        return 0
    fi
    if [[ ! -x "${dir}/${script_name}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_name}"
        exit 1
    fi
    (cd "${dir}" && "./${script_name}")
}

run_preflight() {
    run_rendered_script "preflight.sh"
}

run_apply() {
    if [[ "${TARGET}" == "sok" ]]; then
        if [[ -n "${EKS_CLUSTER_NAME}" ]]; then
            run_rendered_script "eks-update-kubeconfig.sh"
        fi
        run_rendered_script "crds-install.sh"
        run_rendered_script "helm-install-operator.sh"
        if [[ -n "${LICENSE_FILE}" ]]; then
            run_rendered_script "create-license-configmap.sh"
        fi
        run_rendered_script "helm-install-enterprise.sh"
        return 0
    fi
    run_rendered_script "deploy.sh"
}

run_status() {
    if [[ "${TARGET}" == "pod" ]]; then
        run_rendered_script "status-workers.sh"
    fi
    run_rendered_script "status.sh"
}

main() {
    validate_args
    build_renderer_args

    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        fi
        python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
        case "${PHASE}" in
            preflight) run_preflight ;;
            apply) run_apply ;;
            status) run_status ;;
            all)
                run_preflight
                run_apply
                run_status
                ;;
            render) ;;
        esac
        exit 0
    fi

    case "${PHASE}" in
        render)
            render_assets
            if [[ "${APPLY}" == "true" ]]; then
                run_apply
            fi
            ;;
        preflight)
            render_assets
            run_preflight
            ;;
        apply)
            render_assets
            run_apply
            ;;
        status)
            run_status
            ;;
        all)
            render_assets
            run_preflight
            run_apply
            run_status
            ;;
    esac
}

main "$@"
