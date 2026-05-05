#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-otel-rendered"

usage() {
    cat <<'EOF'
Splunk Observability OTel Collector setup

Usage:
  bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh [mode] --realm REALM [options]

Modes:
  --render-k8s                  Render Kubernetes Helm assets
  --render-linux                Render Linux installer assets
  --apply-k8s                   Render and apply Kubernetes assets
  --apply-linux                 Render and apply Linux assets
  --dry-run                     Show the plan without writing or applying
  --json                        Emit JSON dry-run output

Required:
  --realm REALM                 Splunk Observability realm, such as us0

Secret files:
  --o11y-token-file PATH        Splunk Observability access token file
  --platform-hec-token-file PATH
                                Splunk Platform HEC token file for Kubernetes logs
  --allow-loose-token-perms     Skip the chmod-600 token-permission preflight (warns instead)

Splunk Platform HEC helper:
  --render-platform-hec-helper  Render splunk-hec-service-setup handoff scripts
  --hec-platform cloud|enterprise
                                Target Splunk Platform for HEC token creation
  --hec-token-name NAME         HEC token name (default: splunk_otel_k8s_logs)
  --hec-description TEXT        HEC token description
  --hec-default-index INDEX     HEC default index (default: --platform-hec-index)
  --hec-allowed-indexes CSV     HEC allowed indexes (default: default index)
  --hec-source VALUE            HEC default source
  --hec-sourcetype VALUE        HEC default sourcetype
  --hec-use-ack true|false      HEC indexer acknowledgement setting
  --hec-port PORT              Enterprise HEC port (default: 8088)
  --hec-enable-ssl true|false   Enterprise HEC SSL setting
  --hec-splunk-home PATH        Enterprise Splunk home (default: /opt/splunk)
  --hec-app-name NAME           Enterprise app for inputs.conf
  --hec-restart-splunk true|false
                                Restart Splunk after Enterprise apply
  --hec-s2s-indexes-validation disabled|disabled_for_internal|enabled_for_all

Kubernetes options:
  --namespace NAME              Kubernetes namespace (default: splunk-otel)
  --release-name NAME           Helm release name (default: splunk-otel-collector)
  --cluster-name NAME           Cluster name, unless distribution auto-detects it
  --distribution NAME           Chart distribution, such as eks, gke, openshift
  --cloud-provider NAME         Chart cloud provider, such as aws, gcp, azure
  --chart-version VERSION       Pin the Helm chart version
  --kube-context NAME           kubectl/Helm context
  --extra-values-file PATH      Additional Helm values overlay; may be repeated
  --o11y-ingest-url URL         Override Observability ingest URL
  --o11y-api-url URL            Override Observability API URL
  --platform-hec-url URL        Splunk Platform HEC URL for Kubernetes logs
  --platform-hec-index INDEX    Splunk index for Kubernetes logs (default: k8s_logs)
  --eks-cluster-name NAME       Render an aws eks update-kubeconfig helper
  --aws-region REGION           AWS region for EKS kubeconfig helper
  --priority-class-name NAME    Set agent, gateway, and cluster receiver priority class
  --render-priority-class       Render a priority class manifest helper
  --windows-nodes               Render values for Windows worker nodes
  --disable-cluster-receiver    Disable the cluster receiver deployment
  --disable-agent-host-network  Set agent.hostNetwork=false
  --enable-platform-persistent-queue
  --platform-persistent-queue-path PATH
  --enable-platform-fsync
  --enable-secure-app           Enable Splunk Observability Secure Application features
  --enable-prometheus-autodetect
  --enable-istio-autodetect
  --enable-obi                  Enable OBI; requires elevated runtime privileges
  --enable-certmanager          Deprecated chart option; prefer operator auto-generated certs
  --skip-operator-crds          Do not install OpenTelemetry Operator CRDs
  --disable-logs                Disable Kubernetes container log collection
  --disable-events              Disable Kubernetes event collection

Linux options:
  --execution local|ssh         Linux apply execution mode (default: local)
  --linux-host HOST             SSH host for --execution ssh
  --ssh-user USER               SSH user for --execution ssh
  --ssh-port PORT               SSH port (default: 22)
  --ssh-key-file PATH           SSH private key file
  --linux-mode agent|gateway    Linux collector mode (default: agent)
  --memory-mib MIB              Linux installer memory limit (default: 512)
  --listen-interface ADDR       Receiver listen interface (default: 0.0.0.0)
  --api-url URL                 Linux installer API endpoint override
  --ingest-url URL              Linux installer ingest endpoint override
  --trace-url URL               Linux installer trace endpoint override
  --hec-url URL                 Linux installer HEC endpoint override
  --collector-config PATH       Existing custom collector config on the Linux host
  --service-user USER           splunk-otel-collector service user
  --service-group GROUP         splunk-otel-collector service group
  --skip-collector-repo         Use a preconfigured package repository
  --repo-channel primary|beta|test
  --deployment-environment NAME Resource environment value
  --service-name NAME           Service name for host instrumentation
  --instrumentation-mode MODE   none, preload, or systemd (default: systemd)
  --instrumentation-sdks LIST   Optional comma-separated SDK list
  --npm-path PATH               npm path for Node.js zero-code instrumentation
  --otlp-endpoint HOST:PORT     OTLP endpoint for activated SDKs
  --otlp-endpoint-protocol PROTOCOL
  --metrics-exporter LIST       SDK metrics exporter list, or none
  --logs-exporter EXPORTER      SDK logs exporter, or none
  --instrumentation-version VER splunk-otel-auto-instrumentation version
  --collector-version VERSION   Collector package version for Linux installer
  --godebug VALUE               GODEBUG value for collector service
  --obi-version VERSION         OBI version when --enable-obi is set
  --obi-install-dir PATH        OBI install directory
  --installer-url URL           Linux installer URL

Other:
  --output-dir DIR              Rendered output directory
  --all-signals                 Re-enable default signal options
  --disable-metrics
  --disable-traces
  --disable-profiling
  --disable-discovery
  --disable-autoinstrumentation
  --help                        Show this help

Direct token flags such as --access-token, --o11y-token, --hec-token, and --platform-hec-token are rejected.
EOF
}

bool_text() {
    if [[ "$1" == "true" ]]; then
        printf 'true'
    else
        printf 'false'
    fi
}

distribution_allows_cluster_autodetect() {
    case "$1" in
        eks|eks/auto-mode|gke|gke/autopilot|openshift)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

RENDER_K8S=false
RENDER_LINUX=false
RENDER_PLATFORM_HEC_HELPER=false
APPLY_K8S=false
APPLY_LINUX=false
DRY_RUN=false
JSON_OUTPUT=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
REALM="${SPLUNK_O11Y_REALM:-}"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
PLATFORM_HEC_TOKEN_FILE=""
ALLOW_LOOSE_TOKEN_PERMS=false
EXTRA_VALUES_FILES=()

NAMESPACE="splunk-otel"
RELEASE_NAME="splunk-otel-collector"
CLUSTER_NAME=""
DISTRIBUTION=""
CLOUD_PROVIDER=""
CHART_VERSION=""
KUBE_CONTEXT=""
PLATFORM_HEC_URL=""
PLATFORM_HEC_INDEX="k8s_logs"
O11Y_INGEST_URL=""
O11Y_API_URL=""
HEC_PLATFORM="${SPLUNK_PLATFORM:-cloud}"
HEC_TOKEN_NAME="splunk_otel_k8s_logs"
HEC_DESCRIPTION="Managed by splunk-observability-otel-collector-setup"
HEC_DEFAULT_INDEX=""
HEC_ALLOWED_INDEXES=""
HEC_SOURCE=""
HEC_SOURCETYPE=""
HEC_USE_ACK="false"
HEC_PORT="8088"
HEC_ENABLE_SSL="true"
HEC_SPLUNK_HOME="/opt/splunk"
HEC_APP_NAME="splunk_httpinput"
HEC_RESTART_SPLUNK="true"
HEC_S2S_INDEXES_VALIDATION="disabled_for_internal"
EKS_CLUSTER_NAME=""
AWS_REGION=""
PRIORITY_CLASS_NAME=""
RENDER_PRIORITY_CLASS=false
GATEWAY_ENABLED=false
GATEWAY_REPLICAS="1"
WINDOWS_NODES=false
CLUSTER_RECEIVER_ENABLED=true
AGENT_HOST_NETWORK=true
PLATFORM_PERSISTENT_QUEUE_ENABLED=false
PLATFORM_PERSISTENT_QUEUE_PATH="/var/addon/splunk/exporter_queue"
PLATFORM_FSYNC_ENABLED=false

EXECUTION="local"
LINUX_HOST=""
SSH_USER=""
SSH_PORT="22"
SSH_KEY_FILE=""
LINUX_MODE="agent"
MEMORY_MIB="512"
LISTEN_INTERFACE="0.0.0.0"
LINUX_API_URL=""
LINUX_INGEST_URL=""
LINUX_TRACE_URL=""
LINUX_HEC_URL=""
COLLECTOR_CONFIG=""
SERVICE_USER=""
SERVICE_GROUP=""
SKIP_COLLECTOR_REPO=false
REPO_CHANNEL="primary"
DEPLOYMENT_ENVIRONMENT="default"
SERVICE_NAME=""
INSTRUMENTATION_MODE="systemd"
INSTRUMENTATION_SDKS=""
NPM_PATH=""
OTLP_ENDPOINT=""
OTLP_ENDPOINT_PROTOCOL=""
METRICS_EXPORTER=""
LOGS_EXPORTER=""
INSTRUMENTATION_VERSION=""
COLLECTOR_VERSION=""
GODEBUG_VALUE=""
OBI_VERSION=""
OBI_INSTALL_DIR=""
INSTALLER_URL="https://dl.observability.splunkcloud.com/splunk-otel-collector.sh"

ENABLE_METRICS=true
ENABLE_TRACES=true
ENABLE_LOGS=true
ENABLE_PROFILING=true
ENABLE_EVENTS=true
ENABLE_DISCOVERY=true
ENABLE_AUTOINSTRUMENTATION=true
ENABLE_PROMETHEUS_AUTODETECT=false
ENABLE_ISTIO_AUTODETECT=false
ENABLE_OBI=false
ENABLE_OPERATOR_CRDS=true
ENABLE_CERTMANAGER=false
ENABLE_SECURE_APP=false

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render-k8s) RENDER_K8S=true; shift ;;
        --render-linux) RENDER_LINUX=true; shift ;;
        --apply-k8s) APPLY_K8S=true; RENDER_K8S=true; shift ;;
        --apply-linux) APPLY_LINUX=true; RENDER_LINUX=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --platform-hec-token-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --render-platform-hec-helper) RENDER_PLATFORM_HEC_HELPER=true; shift ;;
        --hec-platform) require_arg "$1" "$#" || exit 1; HEC_PLATFORM="$2"; shift 2 ;;
        --hec-token-name) require_arg "$1" "$#" || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --hec-description) require_arg "$1" "$#" || exit 1; HEC_DESCRIPTION="$2"; shift 2 ;;
        --hec-default-index) require_arg "$1" "$#" || exit 1; HEC_DEFAULT_INDEX="$2"; shift 2 ;;
        --hec-allowed-indexes) require_arg "$1" "$#" || exit 1; HEC_ALLOWED_INDEXES="$2"; shift 2 ;;
        --hec-source) require_arg "$1" "$#" || exit 1; HEC_SOURCE="$2"; shift 2 ;;
        --hec-sourcetype) require_arg "$1" "$#" || exit 1; HEC_SOURCETYPE="$2"; shift 2 ;;
        --hec-use-ack) require_arg "$1" "$#" || exit 1; HEC_USE_ACK="$2"; shift 2 ;;
        --hec-port) require_arg "$1" "$#" || exit 1; HEC_PORT="$2"; shift 2 ;;
        --hec-enable-ssl) require_arg "$1" "$#" || exit 1; HEC_ENABLE_SSL="$2"; shift 2 ;;
        --hec-splunk-home) require_arg "$1" "$#" || exit 1; HEC_SPLUNK_HOME="$2"; shift 2 ;;
        --hec-app-name) require_arg "$1" "$#" || exit 1; HEC_APP_NAME="$2"; shift 2 ;;
        --hec-restart-splunk) require_arg "$1" "$#" || exit 1; HEC_RESTART_SPLUNK="$2"; shift 2 ;;
        --hec-s2s-indexes-validation) require_arg "$1" "$#" || exit 1; HEC_S2S_INDEXES_VALIDATION="$2"; shift 2 ;;
        --namespace) require_arg "$1" "$#" || exit 1; NAMESPACE="$2"; shift 2 ;;
        --release-name) require_arg "$1" "$#" || exit 1; RELEASE_NAME="$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; CLUSTER_NAME="$2"; shift 2 ;;
        --distribution) require_arg "$1" "$#" || exit 1; DISTRIBUTION="$2"; shift 2 ;;
        --cloud-provider) require_arg "$1" "$#" || exit 1; CLOUD_PROVIDER="$2"; shift 2 ;;
        --chart-version) require_arg "$1" "$#" || exit 1; CHART_VERSION="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --extra-values-file) require_arg "$1" "$#" || exit 1; EXTRA_VALUES_FILES+=("$2"); shift 2 ;;
        --o11y-ingest-url) require_arg "$1" "$#" || exit 1; O11Y_INGEST_URL="$2"; shift 2 ;;
        --o11y-api-url) require_arg "$1" "$#" || exit 1; O11Y_API_URL="$2"; shift 2 ;;
        --platform-hec-url) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_URL="$2"; shift 2 ;;
        --platform-hec-index) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_INDEX="$2"; shift 2 ;;
        --eks-cluster-name) require_arg "$1" "$#" || exit 1; EKS_CLUSTER_NAME="$2"; shift 2 ;;
        --aws-region) require_arg "$1" "$#" || exit 1; AWS_REGION="$2"; shift 2 ;;
        --priority-class-name) require_arg "$1" "$#" || exit 1; PRIORITY_CLASS_NAME="$2"; shift 2 ;;
        --render-priority-class) RENDER_PRIORITY_CLASS=true; shift ;;
        --gateway) GATEWAY_ENABLED=true; shift ;;
        --gateway-replicas) require_arg "$1" "$#" || exit 1; GATEWAY_REPLICAS="$2"; shift 2 ;;
        --windows-nodes) WINDOWS_NODES=true; shift ;;
        --disable-cluster-receiver) CLUSTER_RECEIVER_ENABLED=false; shift ;;
        --disable-agent-host-network) AGENT_HOST_NETWORK=false; shift ;;
        --enable-platform-persistent-queue) PLATFORM_PERSISTENT_QUEUE_ENABLED=true; shift ;;
        --platform-persistent-queue-path) require_arg "$1" "$#" || exit 1; PLATFORM_PERSISTENT_QUEUE_PATH="$2"; shift 2 ;;
        --enable-platform-fsync) PLATFORM_FSYNC_ENABLED=true; shift ;;
        --execution) require_arg "$1" "$#" || exit 1; EXECUTION="$2"; shift 2 ;;
        --linux-host) require_arg "$1" "$#" || exit 1; LINUX_HOST="$2"; shift 2 ;;
        --ssh-user) require_arg "$1" "$#" || exit 1; SSH_USER="$2"; shift 2 ;;
        --ssh-port) require_arg "$1" "$#" || exit 1; SSH_PORT="$2"; shift 2 ;;
        --ssh-key-file) require_arg "$1" "$#" || exit 1; SSH_KEY_FILE="$2"; shift 2 ;;
        --linux-mode) require_arg "$1" "$#" || exit 1; LINUX_MODE="$2"; shift 2 ;;
        --memory-mib) require_arg "$1" "$#" || exit 1; MEMORY_MIB="$2"; shift 2 ;;
        --listen-interface) require_arg "$1" "$#" || exit 1; LISTEN_INTERFACE="$2"; shift 2 ;;
        --api-url) require_arg "$1" "$#" || exit 1; LINUX_API_URL="$2"; shift 2 ;;
        --ingest-url) require_arg "$1" "$#" || exit 1; LINUX_INGEST_URL="$2"; shift 2 ;;
        --trace-url) require_arg "$1" "$#" || exit 1; LINUX_TRACE_URL="$2"; shift 2 ;;
        --hec-url) require_arg "$1" "$#" || exit 1; LINUX_HEC_URL="$2"; shift 2 ;;
        --collector-config) require_arg "$1" "$#" || exit 1; COLLECTOR_CONFIG="$2"; shift 2 ;;
        --service-user) require_arg "$1" "$#" || exit 1; SERVICE_USER="$2"; shift 2 ;;
        --service-group) require_arg "$1" "$#" || exit 1; SERVICE_GROUP="$2"; shift 2 ;;
        --skip-collector-repo) SKIP_COLLECTOR_REPO=true; shift ;;
        --repo-channel) require_arg "$1" "$#" || exit 1; REPO_CHANNEL="$2"; shift 2 ;;
        --deployment-environment) require_arg "$1" "$#" || exit 1; DEPLOYMENT_ENVIRONMENT="$2"; shift 2 ;;
        --service-name) require_arg "$1" "$#" || exit 1; SERVICE_NAME="$2"; shift 2 ;;
        --instrumentation-mode) require_arg "$1" "$#" || exit 1; INSTRUMENTATION_MODE="$2"; shift 2 ;;
        --instrumentation-sdks) require_arg "$1" "$#" || exit 1; INSTRUMENTATION_SDKS="$2"; shift 2 ;;
        --npm-path) require_arg "$1" "$#" || exit 1; NPM_PATH="$2"; shift 2 ;;
        --otlp-endpoint) require_arg "$1" "$#" || exit 1; OTLP_ENDPOINT="$2"; shift 2 ;;
        --otlp-endpoint-protocol) require_arg "$1" "$#" || exit 1; OTLP_ENDPOINT_PROTOCOL="$2"; shift 2 ;;
        --metrics-exporter) require_arg "$1" "$#" || exit 1; METRICS_EXPORTER="$2"; shift 2 ;;
        --logs-exporter) require_arg "$1" "$#" || exit 1; LOGS_EXPORTER="$2"; shift 2 ;;
        --instrumentation-version) require_arg "$1" "$#" || exit 1; INSTRUMENTATION_VERSION="$2"; shift 2 ;;
        --collector-version) require_arg "$1" "$#" || exit 1; COLLECTOR_VERSION="$2"; shift 2 ;;
        --godebug) require_arg "$1" "$#" || exit 1; GODEBUG_VALUE="$2"; shift 2 ;;
        --obi-version) require_arg "$1" "$#" || exit 1; OBI_VERSION="$2"; shift 2 ;;
        --obi-install-dir) require_arg "$1" "$#" || exit 1; OBI_INSTALL_DIR="$2"; shift 2 ;;
        --installer-url) require_arg "$1" "$#" || exit 1; INSTALLER_URL="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --all-signals)
            ENABLE_METRICS=true
            ENABLE_TRACES=true
            ENABLE_LOGS=true
            ENABLE_PROFILING=true
            ENABLE_EVENTS=true
            ENABLE_DISCOVERY=true
            ENABLE_AUTOINSTRUMENTATION=true
            shift
            ;;
        --disable-metrics) ENABLE_METRICS=false; shift ;;
        --disable-traces) ENABLE_TRACES=false; shift ;;
        --disable-logs) ENABLE_LOGS=false; shift ;;
        --disable-profiling) ENABLE_PROFILING=false; shift ;;
        --disable-events) ENABLE_EVENTS=false; shift ;;
        --disable-discovery) ENABLE_DISCOVERY=false; shift ;;
        --disable-autoinstrumentation) ENABLE_AUTOINSTRUMENTATION=false; shift ;;
        --enable-prometheus-autodetect) ENABLE_PROMETHEUS_AUTODETECT=true; shift ;;
        --enable-istio-autodetect) ENABLE_ISTIO_AUTODETECT=true; shift ;;
        --enable-obi) ENABLE_OBI=true; shift ;;
        --enable-secure-app) ENABLE_SECURE_APP=true; shift ;;
        --enable-certmanager) ENABLE_CERTMANAGER=true; shift ;;
        --skip-operator-crds|--disable-operator-crds) ENABLE_OPERATOR_CRDS=false; shift ;;
        --access-token|--o11y-token|--token|--api-token|--sf-token)
            reject_secret_arg "$1" "--o11y-token-file"
            exit 1
            ;;
        --hec-token)
            reject_secret_arg "$1" "--o11y-token-file"
            exit 1
            ;;
        --platform-hec-token)
            reject_secret_arg "$1" "--platform-hec-token-file"
            exit 1
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

if [[ "${RENDER_K8S}" != "true" && "${RENDER_LINUX}" != "true" && "${RENDER_PLATFORM_HEC_HELPER}" != "true" && "${APPLY_K8S}" != "true" && "${APPLY_LINUX}" != "true" ]]; then
    RENDER_K8S=true
    RENDER_LINUX=true
fi

if [[ -z "${REALM}" ]]; then
    log "ERROR: --realm is required."
    exit 1
fi

if [[ "${RENDER_K8S}" == "true" ]]; then
    if [[ -z "${NAMESPACE}" || -z "${RELEASE_NAME}" ]]; then
        log "ERROR: --namespace and --release-name are required for Kubernetes rendering."
        exit 1
    fi
    if [[ -z "${CLUSTER_NAME}" ]] && ! distribution_allows_cluster_autodetect "${DISTRIBUTION}"; then
        log "ERROR: --cluster-name is required unless --distribution supports chart auto-detection."
        exit 1
    fi
fi

if [[ "${RENDER_PLATFORM_HEC_HELPER}" == "true" && -z "${PLATFORM_HEC_TOKEN_FILE}" ]]; then
    PLATFORM_HEC_TOKEN_FILE="${OUTPUT_DIR}/platform-hec/.splunk_platform_hec_token"
fi

if [[ -n "${PLATFORM_HEC_URL}" && -z "${PLATFORM_HEC_TOKEN_FILE}" ]]; then
    log "ERROR: --platform-hec-url requires --platform-hec-token-file."
    exit 1
fi

if [[ "${APPLY_K8S}" == "true" || "${APPLY_LINUX}" == "true" ]]; then
    if [[ -z "${O11Y_TOKEN_FILE}" || ! -r "${O11Y_TOKEN_FILE}" ]]; then
        log "ERROR: Apply requires a readable --o11y-token-file."
        exit 1
    fi
fi

if [[ "${APPLY_K8S}" == "true" && -n "${PLATFORM_HEC_TOKEN_FILE}" && ! -r "${PLATFORM_HEC_TOKEN_FILE}" ]]; then
    log "ERROR: Kubernetes log apply requires a readable --platform-hec-token-file."
    exit 1
fi

# Token-permission preflight. Tokens MUST be mode 600 (owner read/write only)
# unless the operator explicitly opts out with --allow-loose-token-perms.
# Use BSD/GNU stat-compatible probes; macOS uses `-f %A`, Linux uses `-c %a`.
_token_perm_octal() {
    local target="$1"
    local mode=""
    if mode="$(stat -f '%A' "${target}" 2>/dev/null)"; then
        printf '%s' "${mode}"
        return 0
    fi
    if mode="$(stat -c '%a' "${target}" 2>/dev/null)"; then
        printf '%s' "${mode}"
        return 0
    fi
    printf ''
}

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" && -r "${path}" ]] || return 0
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then
        log "  WARN: Could not stat ${label} (${path}) for permission check; skipping."
        return 0
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS:-false}" == "true" ]]; then
            log "  WARN: ${label} permissions are ${mode}; --allow-loose-token-perms is set, proceeding."
            return 0
        fi
        log "ERROR: ${label} (${path}) is mode ${mode}; tokens must be mode 600."
        log "       Run 'chmod 600 ${path}' to fix, or pass --allow-loose-token-perms to override."
        return 1
    fi
    return 0
}

if [[ "${APPLY_K8S}" == "true" || "${APPLY_LINUX}" == "true" ]]; then
    _check_token_perms "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1
    if [[ -n "${PLATFORM_HEC_TOKEN_FILE}" ]]; then
        _check_token_perms "--platform-hec-token-file" "${PLATFORM_HEC_TOKEN_FILE}" || exit 1
    fi
fi

case "${EXECUTION}" in
    local|ssh) ;;
    *)
        log "ERROR: --execution must be local or ssh."
        exit 1
        ;;
esac

case "${HEC_PLATFORM}" in
    cloud|enterprise) ;;
    *)
        log "ERROR: --hec-platform must be cloud or enterprise."
        exit 1
        ;;
esac

case "${HEC_ENABLE_SSL}" in
    true|false) ;;
    *)
        log "ERROR: --hec-enable-ssl must be true or false."
        exit 1
        ;;
esac

case "${HEC_USE_ACK}" in
    true|false) ;;
    *)
        log "ERROR: --hec-use-ack must be true or false."
        exit 1
        ;;
esac

case "${HEC_RESTART_SPLUNK}" in
    true|false) ;;
    *)
        log "ERROR: --hec-restart-splunk must be true or false."
        exit 1
        ;;
esac

case "${HEC_S2S_INDEXES_VALIDATION}" in
    disabled|disabled_for_internal|enabled_for_all) ;;
    *)
        log "ERROR: --hec-s2s-indexes-validation must be disabled, disabled_for_internal, or enabled_for_all."
        exit 1
        ;;
esac

case "${LINUX_MODE}" in
    agent|gateway) ;;
    *)
        log "ERROR: --linux-mode must be agent or gateway."
        exit 1
        ;;
esac

case "${INSTRUMENTATION_MODE}" in
    none|preload|systemd) ;;
    *)
        log "ERROR: --instrumentation-mode must be none, preload, or systemd."
        exit 1
        ;;
esac

case "${REPO_CHANNEL}" in
    primary|beta|test) ;;
    *)
        log "ERROR: --repo-channel must be primary, beta, or test."
        exit 1
        ;;
esac

case "${OTLP_ENDPOINT_PROTOCOL}" in
    ""|grpc|http/protobuf) ;;
    *)
        log "ERROR: --otlp-endpoint-protocol must be grpc or http/protobuf."
        exit 1
        ;;
esac

if [[ "${APPLY_LINUX}" == "true" && "${EXECUTION}" == "ssh" ]]; then
    if [[ -z "${LINUX_HOST}" || -z "${SSH_USER}" ]]; then
        log "ERROR: --execution ssh requires --linux-host and --ssh-user."
        exit 1
    fi
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --realm "${REALM}"
    --namespace "${NAMESPACE}"
    --release-name "${RELEASE_NAME}"
    --cluster-name "${CLUSTER_NAME}"
    --distribution "${DISTRIBUTION}"
    --cloud-provider "${CLOUD_PROVIDER}"
    --chart-version "${CHART_VERSION}"
    --kube-context "${KUBE_CONTEXT}"
    --o11y-ingest-url "${O11Y_INGEST_URL}"
    --o11y-api-url "${O11Y_API_URL}"
    --platform-hec-url "${PLATFORM_HEC_URL}"
    --platform-hec-index "${PLATFORM_HEC_INDEX}"
    --hec-platform "${HEC_PLATFORM}"
    --hec-token-name "${HEC_TOKEN_NAME}"
    --hec-description "${HEC_DESCRIPTION}"
    --hec-default-index "${HEC_DEFAULT_INDEX}"
    --hec-allowed-indexes "${HEC_ALLOWED_INDEXES}"
    --hec-source "${HEC_SOURCE}"
    --hec-sourcetype "${HEC_SOURCETYPE}"
    --hec-use-ack "${HEC_USE_ACK}"
    --hec-port "${HEC_PORT}"
    --hec-enable-ssl "${HEC_ENABLE_SSL}"
    --hec-splunk-home "${HEC_SPLUNK_HOME}"
    --hec-app-name "${HEC_APP_NAME}"
    --hec-restart-splunk "${HEC_RESTART_SPLUNK}"
    --hec-s2s-indexes-validation "${HEC_S2S_INDEXES_VALIDATION}"
    --eks-cluster-name "${EKS_CLUSTER_NAME}"
    --aws-region "${AWS_REGION}"
    --priority-class-name "${PRIORITY_CLASS_NAME}"
    --render-priority-class "$(bool_text "${RENDER_PRIORITY_CLASS}")"
    --gateway-enabled "$(bool_text "${GATEWAY_ENABLED}")"
    --gateway-replicas "${GATEWAY_REPLICAS}"
    --windows-nodes "$(bool_text "${WINDOWS_NODES}")"
    --cluster-receiver-enabled "$(bool_text "${CLUSTER_RECEIVER_ENABLED}")"
    --agent-host-network "$(bool_text "${AGENT_HOST_NETWORK}")"
    --platform-persistent-queue-enabled "$(bool_text "${PLATFORM_PERSISTENT_QUEUE_ENABLED}")"
    --platform-persistent-queue-path "${PLATFORM_PERSISTENT_QUEUE_PATH}"
    --platform-fsync-enabled "$(bool_text "${PLATFORM_FSYNC_ENABLED}")"
    --o11y-token-file "${O11Y_TOKEN_FILE}"
    --platform-hec-token-file "${PLATFORM_HEC_TOKEN_FILE}"
    --execution "${EXECUTION}"
    --linux-host "${LINUX_HOST}"
    --ssh-user "${SSH_USER}"
    --ssh-port "${SSH_PORT}"
    --ssh-key-file "${SSH_KEY_FILE}"
    --linux-mode "${LINUX_MODE}"
    --memory-mib "${MEMORY_MIB}"
    --listen-interface "${LISTEN_INTERFACE}"
    --linux-api-url "${LINUX_API_URL}"
    --linux-ingest-url "${LINUX_INGEST_URL}"
    --linux-trace-url "${LINUX_TRACE_URL}"
    --linux-hec-url "${LINUX_HEC_URL}"
    --collector-config "${COLLECTOR_CONFIG}"
    --service-user "${SERVICE_USER}"
    --service-group "${SERVICE_GROUP}"
    --skip-collector-repo "$(bool_text "${SKIP_COLLECTOR_REPO}")"
    --repo-channel "${REPO_CHANNEL}"
    --deployment-environment "${DEPLOYMENT_ENVIRONMENT}"
    --service-name "${SERVICE_NAME}"
    --instrumentation-mode "${INSTRUMENTATION_MODE}"
    --instrumentation-sdks "${INSTRUMENTATION_SDKS}"
    --npm-path "${NPM_PATH}"
    --otlp-endpoint "${OTLP_ENDPOINT}"
    --otlp-endpoint-protocol "${OTLP_ENDPOINT_PROTOCOL}"
    --metrics-exporter "${METRICS_EXPORTER}"
    --logs-exporter "${LOGS_EXPORTER}"
    --instrumentation-version "${INSTRUMENTATION_VERSION}"
    --collector-version "${COLLECTOR_VERSION}"
    --godebug "${GODEBUG_VALUE}"
    --obi-version "${OBI_VERSION}"
    --obi-install-dir "${OBI_INSTALL_DIR}"
    --installer-url "${INSTALLER_URL}"
    --enable-metrics "$(bool_text "${ENABLE_METRICS}")"
    --enable-traces "$(bool_text "${ENABLE_TRACES}")"
    --enable-logs "$(bool_text "${ENABLE_LOGS}")"
    --enable-profiling "$(bool_text "${ENABLE_PROFILING}")"
    --enable-events "$(bool_text "${ENABLE_EVENTS}")"
    --enable-discovery "$(bool_text "${ENABLE_DISCOVERY}")"
    --enable-autoinstrumentation "$(bool_text "${ENABLE_AUTOINSTRUMENTATION}")"
    --enable-prometheus-autodetect "$(bool_text "${ENABLE_PROMETHEUS_AUTODETECT}")"
    --enable-istio-autodetect "$(bool_text "${ENABLE_ISTIO_AUTODETECT}")"
    --enable-obi "$(bool_text "${ENABLE_OBI}")"
    --enable-operator-crds "$(bool_text "${ENABLE_OPERATOR_CRDS}")"
    --enable-certmanager "$(bool_text "${ENABLE_CERTMANAGER}")"
    --enable-secure-app "$(bool_text "${ENABLE_SECURE_APP}")"
)
for extra_values_file in "${EXTRA_VALUES_FILES[@]}"; do
    RENDER_ARGS+=(--extra-values-file "${extra_values_file}")
done

if [[ "${RENDER_K8S}" == "true" ]]; then
    RENDER_ARGS+=(--render-k8s)
fi
if [[ "${RENDER_LINUX}" == "true" ]]; then
    RENDER_ARGS+=(--render-linux)
fi
if [[ "${RENDER_PLATFORM_HEC_HELPER}" == "true" ]]; then
    RENDER_ARGS+=(--render-platform-hec-helper)
fi
if [[ "${DRY_RUN}" == "true" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi

python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"

if [[ "${DRY_RUN}" == "true" ]]; then
    exit 0
fi

run_rendered_script() {
    local script_path="$1"
    if [[ ! -f "${script_path}" ]]; then
        log "ERROR: Expected rendered script not found: ${script_path}"
        exit 1
    fi
    log "Running ${script_path}"
    bash "${script_path}"
}

run_optional_rendered_script() {
    local script_path="$1"
    if [[ -f "${script_path}" ]]; then
        log "Running ${script_path}"
        bash "${script_path}"
    fi
}

if [[ "${APPLY_K8S}" == "true" ]]; then
    run_optional_rendered_script "${OUTPUT_DIR}/k8s/eks-update-kubeconfig.sh"
    run_optional_rendered_script "${OUTPUT_DIR}/k8s/priority-class.sh"
    run_rendered_script "${OUTPUT_DIR}/k8s/create-secret.sh"
    run_rendered_script "${OUTPUT_DIR}/k8s/helm-install.sh"
fi

if [[ "${APPLY_LINUX}" == "true" ]]; then
    if [[ "${EXECUTION}" == "ssh" ]]; then
        run_rendered_script "${OUTPUT_DIR}/linux/install-ssh.sh"
    else
        run_rendered_script "${OUTPUT_DIR}/linux/install-local.sh"
    fi
fi
