#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-otel-rendered"
CHECK_K8S=false
CHECK_LINUX=false
CHECK_PLATFORM_HEC=false
LIVE=false
EXECUTION="local"

usage() {
    cat <<'EOF'
Splunk Observability OTel Collector validation

Usage:
  bash skills/splunk-observability-otel-collector-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR       Rendered output directory
  --check-k8s            Check Kubernetes rendered assets
  --check-linux          Check Linux rendered assets
  --check-platform-hec   Check rendered Splunk Platform HEC helper assets
  --live                 Run live status checks using rendered status scripts
  --execution local|ssh  Linux live validation mode (default: local)
  --help                 Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --check-k8s) CHECK_K8S=true; shift ;;
        --check-linux) CHECK_LINUX=true; shift ;;
        --check-platform-hec) CHECK_PLATFORM_HEC=true; shift ;;
        --live) LIVE=true; shift ;;
        --execution) require_arg "$1" "$#" || exit 1; EXECUTION="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

case "${EXECUTION}" in
    local|ssh) ;;
    *)
        log "ERROR: --execution must be local or ssh."
        exit 1
        ;;
esac

if [[ "${CHECK_K8S}" != "true" && "${CHECK_LINUX}" != "true" && "${CHECK_PLATFORM_HEC}" != "true" ]]; then
    [[ -d "${OUTPUT_DIR}/k8s" ]] && CHECK_K8S=true
    [[ -d "${OUTPUT_DIR}/linux" ]] && CHECK_LINUX=true
    [[ -d "${OUTPUT_DIR}/platform-hec" ]] && CHECK_PLATFORM_HEC=true
fi

if [[ "${CHECK_K8S}" != "true" && "${CHECK_LINUX}" != "true" && "${CHECK_PLATFORM_HEC}" != "true" ]]; then
    log "ERROR: No rendered Kubernetes, Linux, or Splunk Platform HEC assets found under ${OUTPUT_DIR}."
    exit 1
fi

check_file() {
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        log "ERROR: Missing ${path}"
        exit 1
    fi
}

if [[ "${CHECK_K8S}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/k8s/values.yaml"
    check_file "${OUTPUT_DIR}/k8s/create-secret.sh"
    check_file "${OUTPUT_DIR}/k8s/helm-install.sh"
    grep -q '^splunkObservability:' "${OUTPUT_DIR}/k8s/values.yaml" || {
        log "ERROR: Kubernetes values are missing splunkObservability."
        exit 1
    }
    # Tolerant of YAML reformatting: any indentation, optional whitespace around
    # the boolean. Without this, a future yamllint reflow would break validation
    # without changing semantics.
    grep -Eq '^[[:space:]]+create:[[:space:]]*false([[:space:]]|$)' "${OUTPUT_DIR}/k8s/values.yaml" || {
        log "ERROR: Kubernetes values must use externally-created file-backed secrets."
        exit 1
    }
    log "Kubernetes rendered assets passed static validation."
    if [[ "${LIVE}" == "true" ]]; then
        bash "${OUTPUT_DIR}/k8s/status.sh"
    fi
fi

if [[ "${CHECK_PLATFORM_HEC}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/platform-hec/render-hec-service.sh"
    check_file "${OUTPUT_DIR}/platform-hec/apply-hec-service.sh"
    check_file "${OUTPUT_DIR}/platform-hec/status-hec-service.sh"
    check_file "${OUTPUT_DIR}/platform-hec/README.md"
    grep -q 'splunk-hec-service-setup/scripts/setup.sh' "${OUTPUT_DIR}/platform-hec/render-hec-service.sh" || {
        log "ERROR: HEC helper must delegate to splunk-hec-service-setup."
        exit 1
    }
    grep -Eq -- '--token-file|--write-token-file' "${OUTPUT_DIR}/platform-hec/apply-hec-service.sh" || {
        log "ERROR: HEC helper must use file-based token handling."
        exit 1
    }
    log "Splunk Platform HEC helper assets passed static validation."
    if [[ "${LIVE}" == "true" ]]; then
        bash "${OUTPUT_DIR}/platform-hec/status-hec-service.sh"
    fi
fi

if [[ "${CHECK_LINUX}" == "true" ]]; then
    check_file "${OUTPUT_DIR}/linux/install-local.sh"
    check_file "${OUTPUT_DIR}/linux/install-ssh.sh"
    grep -q 'VERIFY_ACCESS_TOKEN=false' "${OUTPUT_DIR}/linux/install-local.sh" || {
        log "ERROR: Linux local install wrapper must disable argv-bearing token verification."
        exit 1
    }
    grep -q 'VERIFY_ACCESS_TOKEN=false' "${OUTPUT_DIR}/linux/install-ssh.sh" || {
        log "ERROR: Linux SSH install wrapper must disable argv-bearing token verification."
        exit 1
    }
    log "Linux rendered assets passed static validation."
    if [[ "${LIVE}" == "true" ]]; then
        if [[ "${EXECUTION}" == "ssh" ]]; then
            bash "${OUTPUT_DIR}/linux/status-ssh.sh"
        else
            bash "${OUTPUT_DIR}/linux/status-local.sh"
        fi
    fi
fi
