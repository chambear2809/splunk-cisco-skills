#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-otel-rendered"
if [[ -n "${PYTHON:-}" ]]; then
    PYTHON_BIN="${PYTHON}"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

require_orchestration_python() {
    local detected="unknown"
    if [[ "${PYTHON_BIN}" == */* ]]; then
        [[ -x "${PYTHON_BIN}" ]] || {
            log "ERROR: orchestration Python is not executable: ${PYTHON_BIN}"
            exit 1
        }
    else
        command -v "${PYTHON_BIN}" >/dev/null 2>&1 || {
            log "ERROR: orchestration Python was not found: ${PYTHON_BIN}"
            exit 1
        }
    fi
    if ! "${PYTHON_BIN}" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
        detected="$("${PYTHON_BIN}" --version 2>&1 || true)"
        log "ERROR: setup/render orchestration requires Python 3.9 or newer (found: ${detected:-unknown})."
        log "       Set PYTHON to a Python 3.9+ executable; generated Linux target helpers require only Python 3.6+."
        exit 1
    fi
}

usage() {
    cat <<'EOF'
Splunk Observability OTel Collector setup

Usage:
  bash skills/splunk-observability-otel-collector-setup/scripts/setup.sh [mode] [--realm REALM] [options]

Modes:
  --render-k8s                  Render Kubernetes Helm assets
  --render-linux                Render Linux installer assets
  --render-ta                   Render Splunkbase 7125/8698/8699 TA deployment assets
  --apply-k8s                   Render and apply Kubernetes assets
  --apply-linux                 Render and apply Linux assets
  --apply-ta                    Render and apply Splunkbase 7125/8698/8699 TA assets
  --dry-run                     Show the plan without writing or applying
  --json                        Emit JSON dry-run output

Destination:
  --realm REALM                 Required for Observability, Linux, and TA paths;
                                optional for a Platform-only Kubernetes release

Secret files:
  --o11y-token-file PATH        Splunk Observability access token file
  --platform-hec-token-file PATH
                                Splunk Platform HEC token file for Kubernetes logs

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
  --k8s-objects-file PATH       Typed YAML/JSON Kubernetes object receiver list
  --accept-cluster-wide-object-rbac
                                Accept generated get/list/watch ClusterRole rules
  --o11y-ingest-url URL         Override Observability ingest URL
  --o11y-api-url URL            Override Observability API URL
  --platform-hec-url URL        Splunk Platform HEC URL for Kubernetes logs
  --accept-insecure-platform-hec
                                Explicitly allow a reviewed plaintext HTTP HEC URL
  --platform-hec-index INDEX    Splunk index for Kubernetes logs (default: k8s_logs)
  --platform-metrics-index INDEX
                                Splunk metrics index for Platform metric export
  --platform-traces-index INDEX Splunk index for experimental Platform trace export
  --platform-otlp-endpoint ENDPOINT
                                Splunk Connect for OTLP endpoint for Kubernetes logs
  --platform-otlp-protocol grpc|http
  --platform-otlp-insecure true|false
  --platform-hec-ca-file PATH   HEC server CA certificate
  --platform-hec-client-cert-file PATH
  --platform-hec-client-key-file PATH
  --platform-otlp-ca-file PATH  OTLP server CA certificate
  --platform-otlp-client-cert-file PATH
  --platform-otlp-client-key-file PATH
  --eks-cluster-name NAME       Render an aws eks update-kubeconfig helper
  --aws-region REGION           AWS region for EKS kubeconfig helper
  --priority-class-name NAME    Set agent, gateway, and cluster receiver priority class
  --render-priority-class       Render a priority class manifest helper
  --windows-nodes               Render values for Windows worker nodes
  --agent-enabled true|false    Enable the agent DaemonSet (default: true)
  --disable-cluster-receiver    Disable the cluster receiver deployment
  --gateway                     Enable the collector gateway deployment
  --gateway-replicas N          Gateway replica count (default: 3)
  --enable-network-explorer     Enable the one-replica Collector gateway
                                compatibility profile and render the separate
                                upstream eBPF chart handoff
  --disable-agent-host-network  Set agent.hostNetwork=false
  --enable-platform-persistent-queue
  --platform-persistent-queue-path PATH
  --enable-platform-fsync
  --platform-metrics-enabled true|false
  --platform-logs-enabled true|false
                                Enable the Platform log export pipeline without
                                enabling container or journald collection
  --platform-traces-enabled true|false
  --accept-experimental-platform-traces
                                Acknowledge the experimental Platform trace path
  --target-allocator-enabled true|false
  --k8s-entities-enabled true|false
  --entity-events-enabled true|false
  --fips-enabled true|false
  --instrumentation-installation-job true|false
  --instrumentation-kubectl-image-tag TAG
                                Kubectl tag for the install Job (default: v1.35.1; server +/-1)
  --enable-secure-app           Enable Splunk Observability Secure Application features
  --enable-prometheus-autodetect
  --enable-istio-autodetect
  --enable-obi                  Enable OBI; requires elevated runtime privileges
  --enable-certmanager          Use an existing cert-manager for Operator webhook certificates
  --skip-operator-crds          Do not install OpenTelemetry Operator CRDs
  --enable-logs                 Enable Kubernetes container log collection
  --enable-journald             Enable Linux-node journald collection; requires
                                an agent and a Platform log destination
  --enable-events               Enable Kubernetes event collection

Linux options:
  --execution local|ssh         Linux apply execution mode (default: local)
  --linux-host HOST             SSH host for --execution ssh
  --ssh-user USER               SSH user for --execution ssh
  --ssh-port PORT               SSH port (default: 22)
  --ssh-key-file PATH           SSH private key file
  --linux-mode agent|gateway    Linux collector mode (default: agent)
  --memory-mib MIB              Linux installer memory limit (default: 512)
  --listen-interface ADDR       Receiver listen interface (agent defaults to loopback)
  --api-url URL                 Linux installer API endpoint override
  --ingest-url URL              Linux installer ingest endpoint override
  --trace-url URL               Rejected: removed from the upstream installer
  --hec-url URL                 Rejected: deprecated by the upstream installer
  --collector-config PATH       Existing custom collector config on the Linux host
  --linux-health-endpoint URL   Required with --collector-config; status health URL
  --health-endpoint URL         Alias for --linux-health-endpoint
  --service-user USER           splunk-otel-collector service user
  --service-group GROUP         splunk-otel-collector service group
  --skip-collector-repo         Use a preconfigured package repository
  --repo-channel primary|beta   (`test` is rejected because it disables package verification)
  --deployment-environment NAME Resource environment value
  --service-name NAME           Service name for host instrumentation
  --instrumentation-mode MODE   none, preload, or systemd (default: none)
  --instrumentation-sdks LIST   Optional comma-separated SDK list
  --npm-path PATH               npm path for Node.js zero-code instrumentation
  --otlp-endpoint HOST:PORT     OTLP endpoint for activated SDKs
  --otlp-endpoint-protocol PROTOCOL
  --metrics-exporter LIST       SDK metrics exporter list, or none
  --logs-exporter EXPORTER      SDK logs exporter, or none
  --instrumentation-version VER splunk-otel-auto-instrumentation version
                                (audited executable pin: 0.158.0; other versions rejected)
  --enable-logs                 Enable SDK log export when auto-instrumentation is active
  --collector-version VERSION   Collector package version (audited-only: 0.158.0)
  --godebug VALUE               GODEBUG value for collector service
  --obi-version VERSION         OBI version when enabled (audited-only: v0.6.0)
  --obi-install-dir PATH        OBI install directory
  --installer-url URL           Pinned Linux installer URL
  --installer-sha256 SHA256     Expected installer SHA-256

Splunk Add-On for OpenTelemetry Collector (Splunkbase 7125/8698/8699):
  --ta-target deployment-server|heavy-forwarder|universal-forwarder
                                TA runtime target (default: deployment-server)
  --ta-package-path PATH        Audited 7125/8698/8699 .tgz; may be repeated for DS
  --ta-package-flavor auto|multi-os|linux-x86-64|windows-x86-64
  --ta-mode agent|gateway|agent-to-gateway
  --ta-listen-interface ADDR    Default is localhost for agent, 0.0.0.0 for gateway
  --ta-gateway-url HOST:PORT    Required for --ta-mode agent-to-gateway
  --ta-collector-log-level error|warn|info|debug
  --ta-collector-env KEY=VALUE  Extra collector env var; may be repeated
  --ta-collector-cmd-arg ARG    Extra collector command arg; may be repeated
  --ta-serverclass-whitelist FILTER
                                Deployment-server client filter (default: no match)
  --ta-enable-opamp             Add --feature-gates=+splunk.opamp.enabled
  --splunk-version VERSION      Check version against audited TA compatibility
  --ta-secret-mode placeholder|inputs-conf|legacy-file|environment
  --accept-ta-token-in-conf     Required before apply writes token into inputs.conf
  --ta-fips-required            Refuse unless --accept-ta-regulated-override is set
  --ta-fedramp-required         Refuse unless --accept-ta-regulated-override is set
  --accept-ta-regulated-override
                                Render warning packet for unsupported regulated target
  --accept-unaudited-ta-package Allow apply of a structurally audited but non-official digest

Other:
  PYTHON=/path/to/python        Orchestration interpreter (Python 3.9+ required)
  --output-dir DIR              Rendered output directory
  --all-signals                 Enable all base signals; Kubernetes also needs a log destination
                                and nonempty --deployment-environment for auto-instrumentation
  --enable-metrics              Request metrics; controls Kubernetes output and Linux SDK metrics
  --enable-traces               Request traces (default true)
  --enable-profiling            Request profiling and enable it for activated Linux SDKs
  --enable-memory-profiling     Enable Linux SDK memory profiling independently
  --enable-discovery            Enable supported discovery paths
  --enable-autoinstrumentation  Enable target-specific auto-instrumentation
  --disable-metrics             Linux default config needs --collector-config to honor this
  --disable-traces              Linux default config needs --collector-config to honor this
  --disable-logs
  --disable-journald
  --disable-profiling
  --disable-memory-profiling
  --disable-discovery
  --disable-autoinstrumentation
  --help                        Show this help

Direct token flags such as --access-token, --o11y-token, --hec-token, --platform-hec-token, and --ta-access-token are rejected.
EOF
}

bool_text() {
    if [[ "$1" == "true" ]]; then
        printf 'true'
    else
        printf 'false'
    fi
}

require_bool_value() {
    local option="$1"
    local value="$2"
    case "${value}" in
        true|false) return 0 ;;
        *)
            log "ERROR: ${option} must be true or false."
            return 1
            ;;
    esac
}

ta_env_is_secret_like() {
    local raw="$1"
    local key="${raw%%=*}"
    local value=""
    local key_lower value_lower
    local key_pattern='(token|secret|password|api[_-]?key|access[_-]?key|authorization|credential|private[_-]?key|headers?|cookie)'
    local assignment_pattern='(splunk_access_token|splunk_hec_token|access_token[[:space:]]*=|token[[:space:]]*=|password[[:space:]]*=|secret[[:space:]]*=|api[_-]?key[[:space:]]*=|access[_-]?key[[:space:]]*=|authorization[[:space:]]*[:=]|bearer[[:space:]]+)'

    if [[ "${raw}" == *"="* ]]; then
        value="${raw#*=}"
    fi
    key_lower="$(printf '%s' "${key}" | tr '[:upper:]' '[:lower:]')"
    value_lower="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')"
    [[ "${key_lower}" =~ ${key_pattern} || "${value_lower}" =~ ${assignment_pattern} ]]
}

ta_cmd_arg_is_secret_like() {
    local value_lower
    local secret_flag_pattern='^--?(splunk[-_])?(access[-_]?token|token|password|secret|api[-_]?key|access[-_]?key|authorization|headers?|cookie)(=|$)'
    local assignment_pattern='(splunk_access_token|splunk_hec_token|access_token[[:space:]]*=|token[[:space:]]*=|password[[:space:]]*=|secret[[:space:]]*=|api[_-]?key[[:space:]]*=|access[_-]?key[[:space:]]*=|authorization[[:space:]]*[:=]|bearer[[:space:]]+)'

    value_lower="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    [[ "${value_lower}" =~ ${secret_flag_pattern} || "${value_lower}" =~ ${assignment_pattern} ]]
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
    "${PYTHON_BIN}" - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

resolve_abs_nosymlink_path() {
    local label="$1" value="$2"
    "${PYTHON_BIN}" - "${label}" "${value}" <<'PY'
import os
from pathlib import Path
import stat
import sys

label, raw = sys.argv[1:]
candidate = Path(os.path.abspath(os.path.expanduser(raw)))
try:
    info = os.lstat(candidate)
except FileNotFoundError:
    info = None
except OSError as exc:
    raise SystemExit("ERROR: %s cannot be inspected safely: %s" % (label, exc))
if info is not None and stat.S_ISLNK(info.st_mode):
    raise SystemExit("ERROR: %s must not be a symlink: %s" % (label, candidate))
print(candidate, end="")
PY
}

reject_generated_subtree_input() {
    local label="$1" path="$2"
    [[ -n "${path}" ]] || return 0
    if "${PYTHON_BIN}" - "${OUTPUT_DIR}" "${path}" <<'PY'
from pathlib import Path
import sys

output = Path(sys.argv[1]).resolve()
candidate = Path(sys.argv[2]).resolve()
managed = [
    output / name
    for name in ("k8s", "linux", "ta", "platform-hec", "platform-hec-service-rendered")
]
raise SystemExit(0 if any(candidate == root or root in candidate.parents for root in managed) else 1)
PY
    then
        log "ERROR: ${label} is inside a generated subtree that rendering replaces. Move it outside k8s/, linux/, ta/, platform-hec/, or platform-hec-service-rendered/."
        return 1
    fi
}

RENDER_K8S=false
RENDER_LINUX=false
RENDER_TA=false
RENDER_PLATFORM_HEC_HELPER=false
APPLY_K8S=false
APPLY_LINUX=false
APPLY_TA=false
DRY_RUN=false
JSON_OUTPUT=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
REALM="${SPLUNK_O11Y_REALM:-}"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
PLATFORM_HEC_TOKEN_FILE=""
EXTRA_VALUES_FILES=()
K8S_OBJECTS_FILE=""
ACCEPT_CLUSTER_WIDE_OBJECT_RBAC=false

NAMESPACE="splunk-otel"
RELEASE_NAME="splunk-otel-collector"
CLUSTER_NAME=""
DISTRIBUTION=""
CLOUD_PROVIDER=""
CHART_VERSION="0.158.0"
KUBE_CONTEXT=""
PLATFORM_HEC_URL=""
PLATFORM_HEC_INDEX="k8s_logs"
PLATFORM_METRICS_INDEX=""
PLATFORM_TRACES_INDEX=""
PLATFORM_OTLP_ENDPOINT=""
PLATFORM_OTLP_PROTOCOL="grpc"
PLATFORM_OTLP_INSECURE=false
PLATFORM_HEC_CA_FILE=""
PLATFORM_HEC_CLIENT_CERT_FILE=""
PLATFORM_HEC_CLIENT_KEY_FILE=""
PLATFORM_OTLP_CA_FILE=""
PLATFORM_OTLP_CLIENT_CERT_FILE=""
PLATFORM_OTLP_CLIENT_KEY_FILE=""
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
AGENT_ENABLED=true
GATEWAY_ENABLED=false
GATEWAY_REPLICAS="3"
NETWORK_EXPLORER_ENABLED=false
WINDOWS_NODES=false
CLUSTER_RECEIVER_ENABLED=true
AGENT_HOST_NETWORK=true
PLATFORM_PERSISTENT_QUEUE_ENABLED=false
PLATFORM_PERSISTENT_QUEUE_PATH="/var/addon/splunk/exporter_queue"
PLATFORM_FSYNC_ENABLED=false
PLATFORM_LOGS_ENABLED=false
PLATFORM_METRICS_ENABLED=false
PLATFORM_TRACES_ENABLED=false
ACCEPT_EXPERIMENTAL_PLATFORM_TRACES=false
ACCEPT_INSECURE_PLATFORM_HEC=false
TARGET_ALLOCATOR_ENABLED=false
K8S_ENTITIES_ENABLED=false
ENTITY_EVENTS_ENABLED=false
FIPS_ENABLED=false
INSTRUMENTATION_INSTALLATION_JOB=true
INSTRUMENTATION_KUBECTL_IMAGE_TAG="v1.35.1"

EXECUTION="local"
LINUX_HOST=""
SSH_USER=""
SSH_PORT="22"
SSH_KEY_FILE=""
LINUX_MODE="agent"
MEMORY_MIB="512"
LISTEN_INTERFACE=""
LINUX_API_URL=""
LINUX_INGEST_URL=""
COLLECTOR_CONFIG=""
LINUX_HEALTH_ENDPOINT=""
SERVICE_USER=""
SERVICE_GROUP=""
SKIP_COLLECTOR_REPO=false
REPO_CHANNEL="primary"
DEPLOYMENT_ENVIRONMENT=""
SERVICE_NAME=""
INSTRUMENTATION_MODE="none"
INSTRUMENTATION_SDKS=""
NPM_PATH=""
OTLP_ENDPOINT=""
OTLP_ENDPOINT_PROTOCOL=""
METRICS_EXPORTER=""
LOGS_EXPORTER=""
INSTRUMENTATION_VERSION="0.158.0"
COLLECTOR_VERSION="0.158.0"
GODEBUG_VALUE=""
OBI_VERSION=""
OBI_INSTALL_DIR=""
INSTALLER_URL="https://raw.githubusercontent.com/signalfx/splunk-otel-collector/v0.158.0/packaging/installer/install.sh"
INSTALLER_SHA256="cea51eefdf12a906e45db06ea0943931903df1328d9779a4dbfa7d17c0bb4b1b"

TA_TARGET="deployment-server"
TA_PACKAGE_PATHS=()
TA_PACKAGE_FLAVOR="auto"
TA_MODE="agent"
TA_LISTEN_INTERFACE=""
TA_GATEWAY_URL=""
TA_COLLECTOR_LOG_LEVEL="error"
TA_COLLECTOR_ENVS=()
TA_COLLECTOR_CMD_ARGS=()
TA_SERVERCLASS_WHITELIST=""
TA_ENABLE_OPAMP=false
SPLUNK_VERSION=""
TA_SECRET_MODE="placeholder"
ACCEPT_TA_TOKEN_IN_CONF=false
TA_FIPS_REQUIRED=false
TA_FEDRAMP_REQUIRED=false
ACCEPT_TA_REGULATED_OVERRIDE=false
ACCEPT_UNAUDITED_TA_PACKAGE=false

ENABLE_METRICS=true
ENABLE_TRACES=true
ENABLE_LOGS=false
ENABLE_JOURNALD=false
ENABLE_PROFILING=false
ENABLE_MEMORY_PROFILING=false
ENABLE_EVENTS=false
ENABLE_DISCOVERY=false
ENABLE_AUTOINSTRUMENTATION=false
ENABLE_PROMETHEUS_AUTODETECT=false
ENABLE_ISTIO_AUTODETECT=false
ENABLE_OBI=false
ENABLE_OPERATOR_CRDS=true
ENABLE_CERTMANAGER=false
ENABLE_SECURE_APP=false
ALL_SIGNALS=false
EVENTS_EXPLICIT=false
METRICS_EXPLICIT=false
TRACES_EXPLICIT=false
LOGS_EXPLICIT=false

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render-k8s) RENDER_K8S=true; shift ;;
        --render-linux) RENDER_LINUX=true; shift ;;
        --render-ta) RENDER_TA=true; shift ;;
        --apply-k8s) APPLY_K8S=true; RENDER_K8S=true; shift ;;
        --apply-linux) APPLY_LINUX=true; RENDER_LINUX=true; shift ;;
        --apply-ta) APPLY_TA=true; RENDER_TA=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --platform-hec-token-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --allow-loose-token-perms)
            log "ERROR: --allow-loose-token-perms is not supported; token files must have mode 600."
            exit 1
            ;;
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
        --k8s-objects-file) require_arg "$1" "$#" || exit 1; K8S_OBJECTS_FILE="$2"; shift 2 ;;
        --accept-cluster-wide-object-rbac) ACCEPT_CLUSTER_WIDE_OBJECT_RBAC=true; shift ;;
        --o11y-ingest-url) require_arg "$1" "$#" || exit 1; O11Y_INGEST_URL="$2"; shift 2 ;;
        --o11y-api-url) require_arg "$1" "$#" || exit 1; O11Y_API_URL="$2"; shift 2 ;;
        --platform-hec-url) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_URL="$2"; shift 2 ;;
        --accept-insecure-platform-hec) ACCEPT_INSECURE_PLATFORM_HEC=true; shift ;;
        --platform-hec-index) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_INDEX="$2"; shift 2 ;;
        --platform-metrics-index) require_arg "$1" "$#" || exit 1; PLATFORM_METRICS_INDEX="$2"; shift 2 ;;
        --platform-traces-index) require_arg "$1" "$#" || exit 1; PLATFORM_TRACES_INDEX="$2"; shift 2 ;;
        --platform-otlp-endpoint) require_arg "$1" "$#" || exit 1; PLATFORM_OTLP_ENDPOINT="$2"; shift 2 ;;
        --platform-otlp-protocol) require_arg "$1" "$#" || exit 1; PLATFORM_OTLP_PROTOCOL="$2"; shift 2 ;;
        --platform-otlp-insecure) require_arg "$1" "$#" || exit 1; PLATFORM_OTLP_INSECURE="$2"; shift 2 ;;
        --platform-hec-ca-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_CA_FILE="$2"; shift 2 ;;
        --platform-hec-client-cert-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_CLIENT_CERT_FILE="$2"; shift 2 ;;
        --platform-hec-client-key-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_CLIENT_KEY_FILE="$2"; shift 2 ;;
        --platform-otlp-ca-file) require_arg "$1" "$#" || exit 1; PLATFORM_OTLP_CA_FILE="$2"; shift 2 ;;
        --platform-otlp-client-cert-file) require_arg "$1" "$#" || exit 1; PLATFORM_OTLP_CLIENT_CERT_FILE="$2"; shift 2 ;;
        --platform-otlp-client-key-file) require_arg "$1" "$#" || exit 1; PLATFORM_OTLP_CLIENT_KEY_FILE="$2"; shift 2 ;;
        --eks-cluster-name) require_arg "$1" "$#" || exit 1; EKS_CLUSTER_NAME="$2"; shift 2 ;;
        --aws-region) require_arg "$1" "$#" || exit 1; AWS_REGION="$2"; shift 2 ;;
        --priority-class-name) require_arg "$1" "$#" || exit 1; PRIORITY_CLASS_NAME="$2"; shift 2 ;;
        --render-priority-class) RENDER_PRIORITY_CLASS=true; shift ;;
        --agent-enabled) require_arg "$1" "$#" || exit 1; AGENT_ENABLED="$2"; shift 2 ;;
        --disable-agent) AGENT_ENABLED=false; shift ;;
        --gateway) GATEWAY_ENABLED=true; shift ;;
        --gateway-enabled) require_arg "$1" "$#" || exit 1; GATEWAY_ENABLED="$2"; shift 2 ;;
        --gateway-replicas) require_arg "$1" "$#" || exit 1; GATEWAY_REPLICAS="$2"; shift 2 ;;
        --enable-network-explorer) NETWORK_EXPLORER_ENABLED=true; shift ;;
        --network-explorer-enabled) require_arg "$1" "$#" || exit 1; NETWORK_EXPLORER_ENABLED="$2"; shift 2 ;;
        --windows-nodes) WINDOWS_NODES=true; shift ;;
        --disable-cluster-receiver) CLUSTER_RECEIVER_ENABLED=false; shift ;;
        --cluster-receiver-enabled) require_arg "$1" "$#" || exit 1; CLUSTER_RECEIVER_ENABLED="$2"; shift 2 ;;
        --disable-agent-host-network) AGENT_HOST_NETWORK=false; shift ;;
        --agent-host-network) require_arg "$1" "$#" || exit 1; AGENT_HOST_NETWORK="$2"; shift 2 ;;
        --enable-platform-persistent-queue) PLATFORM_PERSISTENT_QUEUE_ENABLED=true; shift ;;
        --platform-persistent-queue-enabled) require_arg "$1" "$#" || exit 1; PLATFORM_PERSISTENT_QUEUE_ENABLED="$2"; shift 2 ;;
        --platform-persistent-queue-path) require_arg "$1" "$#" || exit 1; PLATFORM_PERSISTENT_QUEUE_PATH="$2"; shift 2 ;;
        --enable-platform-fsync) PLATFORM_FSYNC_ENABLED=true; shift ;;
        --platform-fsync-enabled) require_arg "$1" "$#" || exit 1; PLATFORM_FSYNC_ENABLED="$2"; shift 2 ;;
        --platform-logs-enabled) require_arg "$1" "$#" || exit 1; PLATFORM_LOGS_ENABLED="$2"; shift 2 ;;
        --enable-platform-logs) PLATFORM_LOGS_ENABLED=true; shift ;;
        --platform-metrics-enabled) require_arg "$1" "$#" || exit 1; PLATFORM_METRICS_ENABLED="$2"; shift 2 ;;
        --enable-platform-metrics) PLATFORM_METRICS_ENABLED=true; shift ;;
        --platform-traces-enabled) require_arg "$1" "$#" || exit 1; PLATFORM_TRACES_ENABLED="$2"; shift 2 ;;
        --enable-platform-traces) PLATFORM_TRACES_ENABLED=true; shift ;;
        --accept-experimental-platform-traces) ACCEPT_EXPERIMENTAL_PLATFORM_TRACES=true; shift ;;
        --target-allocator-enabled) require_arg "$1" "$#" || exit 1; TARGET_ALLOCATOR_ENABLED="$2"; shift 2 ;;
        --k8s-entities-enabled) require_arg "$1" "$#" || exit 1; K8S_ENTITIES_ENABLED="$2"; shift 2 ;;
        --entity-events-enabled) require_arg "$1" "$#" || exit 1; ENTITY_EVENTS_ENABLED="$2"; shift 2 ;;
        --fips-enabled) require_arg "$1" "$#" || exit 1; FIPS_ENABLED="$2"; shift 2 ;;
        --instrumentation-installation-job) require_arg "$1" "$#" || exit 1; INSTRUMENTATION_INSTALLATION_JOB="$2"; shift 2 ;;
        --instrumentation-kubectl-image-tag) require_arg "$1" "$#" || exit 1; INSTRUMENTATION_KUBECTL_IMAGE_TAG="$2"; shift 2 ;;
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
        --trace-url|--trace-url=*|--linux-trace-url|--linux-trace-url=*)
            log "ERROR: --trace-url was removed from the upstream Linux installer and is not supported."
            exit 1
            ;;
        --hec-url|--hec-url=*|--linux-hec-url|--linux-hec-url=*)
            log "ERROR: --hec-url is deprecated upstream; use --collector-config or the Splunk Platform/Universal Forwarder handoff."
            exit 1
            ;;
        --collector-config) require_arg "$1" "$#" || exit 1; COLLECTOR_CONFIG="$2"; shift 2 ;;
        --linux-health-endpoint|--health-endpoint) require_arg "$1" "$#" || exit 1; LINUX_HEALTH_ENDPOINT="$2"; shift 2 ;;
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
        --installer-sha256) require_arg "$1" "$#" || exit 1; INSTALLER_SHA256="$2"; shift 2 ;;
        --ta-target) require_arg "$1" "$#" || exit 1; TA_TARGET="$2"; shift 2 ;;
        --ta-package-path) require_arg "$1" "$#" || exit 1; TA_PACKAGE_PATHS+=("$2"); shift 2 ;;
        --ta-package-flavor) require_arg "$1" "$#" || exit 1; TA_PACKAGE_FLAVOR="$2"; shift 2 ;;
        --ta-mode) require_arg "$1" "$#" || exit 1; TA_MODE="$2"; shift 2 ;;
        --ta-listen-interface) require_arg "$1" "$#" || exit 1; TA_LISTEN_INTERFACE="$2"; shift 2 ;;
        --ta-gateway-url) require_arg "$1" "$#" || exit 1; TA_GATEWAY_URL="$2"; shift 2 ;;
        --ta-collector-log-level) require_arg "$1" "$#" || exit 1; TA_COLLECTOR_LOG_LEVEL="$2"; shift 2 ;;
        --ta-collector-env) require_arg "$1" "$#" || exit 1; TA_COLLECTOR_ENVS+=("$2"); shift 2 ;;
        --ta-collector-env=*) TA_COLLECTOR_ENVS+=("${1#*=}"); shift ;;
        --ta-collector-cmd-arg) require_arg "$1" "$#" || exit 1; TA_COLLECTOR_CMD_ARGS+=("$2"); shift 2 ;;
        --ta-collector-cmd-arg=*) TA_COLLECTOR_CMD_ARGS+=("${1#*=}"); shift ;;
        --ta-serverclass-whitelist) require_arg "$1" "$#" || exit 1; TA_SERVERCLASS_WHITELIST="$2"; shift 2 ;;
        --ta-enable-opamp) TA_ENABLE_OPAMP=true; shift ;;
        --splunk-version) require_arg "$1" "$#" || exit 1; SPLUNK_VERSION="$2"; shift 2 ;;
        --ta-secret-mode) require_arg "$1" "$#" || exit 1; TA_SECRET_MODE="$2"; shift 2 ;;
        --accept-ta-token-in-conf) ACCEPT_TA_TOKEN_IN_CONF=true; shift ;;
        --ta-fips-required) TA_FIPS_REQUIRED=true; shift ;;
        --ta-fedramp-required) TA_FEDRAMP_REQUIRED=true; shift ;;
        --accept-ta-regulated-override) ACCEPT_TA_REGULATED_OVERRIDE=true; shift ;;
        --accept-unaudited-ta-package) ACCEPT_UNAUDITED_TA_PACKAGE=true; shift ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --all-signals)
            ALL_SIGNALS=true
            ENABLE_METRICS=true
            ENABLE_TRACES=true
            ENABLE_LOGS=true
            ENABLE_PROFILING=true
            ENABLE_DISCOVERY=true
            ENABLE_AUTOINSTRUMENTATION=true
            METRICS_EXPLICIT=true
            TRACES_EXPLICIT=true
            LOGS_EXPLICIT=true
            shift
            ;;
        --disable-metrics) ENABLE_METRICS=false; METRICS_EXPLICIT=true; shift ;;
        --disable-traces) ENABLE_TRACES=false; TRACES_EXPLICIT=true; shift ;;
        --enable-metrics) ENABLE_METRICS=true; METRICS_EXPLICIT=true; shift ;;
        --enable-traces) ENABLE_TRACES=true; TRACES_EXPLICIT=true; shift ;;
        --enable-logs) ENABLE_LOGS=true; LOGS_EXPLICIT=true; shift ;;
        --enable-journald) ENABLE_JOURNALD=true; shift ;;
        --enable-profiling) ENABLE_PROFILING=true; shift ;;
        --enable-memory-profiling) ENABLE_MEMORY_PROFILING=true; shift ;;
        --enable-events) ENABLE_EVENTS=true; EVENTS_EXPLICIT=true; shift ;;
        --enable-discovery) ENABLE_DISCOVERY=true; shift ;;
        --enable-autoinstrumentation) ENABLE_AUTOINSTRUMENTATION=true; shift ;;
        --disable-logs) ENABLE_LOGS=false; LOGS_EXPLICIT=true; shift ;;
        --disable-journald) ENABLE_JOURNALD=false; shift ;;
        --disable-profiling) ENABLE_PROFILING=false; shift ;;
        --disable-memory-profiling) ENABLE_MEMORY_PROFILING=false; shift ;;
        --disable-events) ENABLE_EVENTS=false; EVENTS_EXPLICIT=true; shift ;;
        --disable-discovery) ENABLE_DISCOVERY=false; shift ;;
        --disable-autoinstrumentation) ENABLE_AUTOINSTRUMENTATION=false; shift ;;
        --enable-prometheus-autodetect) ENABLE_PROMETHEUS_AUTODETECT=true; shift ;;
        --enable-istio-autodetect) ENABLE_ISTIO_AUTODETECT=true; shift ;;
        --enable-obi) ENABLE_OBI=true; shift ;;
        --enable-secure-app) ENABLE_SECURE_APP=true; shift ;;
        --enable-certmanager) ENABLE_CERTMANAGER=true; shift ;;
        --skip-operator-crds|--disable-operator-crds) ENABLE_OPERATOR_CRDS=false; shift ;;
        --access-token|--o11y-token|--token|--api-token|--sf-token|--access-token=*|--o11y-token=*|--token=*|--api-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "--o11y-token-file"
            exit 1
            ;;
        --hec-token|--hec-token=*)
            log "ERROR: --hec-token would expose a secret in process listings. Use --platform-hec-token-file for Splunk Platform HEC; legacy Observability access tokens use --o11y-token-file."
            exit 1
            ;;
        --platform-hec-token|--platform-hec-token=*)
            reject_secret_arg "${1%%=*}" "--platform-hec-token-file"
            exit 1
            ;;
        --ta-access-token|--splunk-access-token|--otel-ta-access-token|--ta-access-token=*|--splunk-access-token=*|--otel-ta-access-token=*)
            reject_secret_arg "${1%%=*}" "--o11y-token-file"
            exit 1
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            unknown_name="${1%%=*}"
            unknown_lower="$(printf '%s' "${unknown_name}" | tr '[:upper:]' '[:lower:]')"
            if [[ "$1" == *=* ]]; then
                log "ERROR: Unknown option: ${unknown_name}=__REDACTED__"
            elif [[ "${unknown_lower}" =~ (token|secret|password|api[-_]?key|access[-_]?key|authorization|headers?|cookie|credential|private[-_]?key) ]]; then
                log "ERROR: Unknown secret-like option: ${unknown_name}=__REDACTED__"
            else
                log "ERROR: Unknown option: $1"
            fi
            usage
            exit 1
            ;;
    esac
done

if [[ "${JSON_OUTPUT}" == "true" && "${DRY_RUN}" != "true" ]]; then
    log "ERROR: --json requires --dry-run."
    exit 1
fi

require_orchestration_python
OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

if [[ "${RENDER_K8S}" != "true" && "${RENDER_LINUX}" != "true" && "${RENDER_TA}" != "true" && "${RENDER_PLATFORM_HEC_HELPER}" != "true" && "${APPLY_K8S}" != "true" && "${APPLY_LINUX}" != "true" && "${APPLY_TA}" != "true" ]]; then
    RENDER_K8S=true
    RENDER_LINUX=true
fi

if [[ "${ALL_SIGNALS}" == "true" && "${RENDER_K8S}" == "true" && "${EVENTS_EXPLICIT}" != "true" ]]; then
    ENABLE_EVENTS=true
fi

O11Y_DESTINATION_ENABLED=false
if [[ "${ENABLE_METRICS}" == "true" || "${ENABLE_TRACES}" == "true" || "${ENABLE_PROFILING}" == "true" ||
      "${K8S_ENTITIES_ENABLED}" == "true" ||
      "${ENTITY_EVENTS_ENABLED}" == "true" || "${ENABLE_SECURE_APP}" == "true" ]]; then
    O11Y_DESTINATION_ENABLED=true
fi

if [[ -z "${REALM}" ]] && {
    [[ "${RENDER_LINUX}" == "true" ]] ||
    [[ "${RENDER_TA}" == "true" ]] ||
    { [[ "${RENDER_K8S}" == "true" ]] && [[ "${O11Y_DESTINATION_ENABLED}" == "true" ]]; }
}; then
    log "ERROR: --realm is required for enabled Splunk Observability, Linux, and TA paths."
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
    PLATFORM_HEC_TOKEN_FILE="${OUTPUT_DIR}/.secrets/splunk_platform_hec_token"
fi

# Persist canonical local paths so rendered handoffs work from any directory.
[[ -z "${O11Y_TOKEN_FILE}" ]] || O11Y_TOKEN_FILE="$(resolve_abs_nosymlink_path "--o11y-token-file" "${O11Y_TOKEN_FILE}")"
[[ -z "${PLATFORM_HEC_TOKEN_FILE}" ]] || PLATFORM_HEC_TOKEN_FILE="$(resolve_abs_nosymlink_path "--platform-hec-token-file" "${PLATFORM_HEC_TOKEN_FILE}")"
[[ -z "${PLATFORM_HEC_CA_FILE}" ]] || PLATFORM_HEC_CA_FILE="$(resolve_abs_nosymlink_path "--platform-hec-ca-file" "${PLATFORM_HEC_CA_FILE}")"
[[ -z "${PLATFORM_HEC_CLIENT_CERT_FILE}" ]] || PLATFORM_HEC_CLIENT_CERT_FILE="$(resolve_abs_nosymlink_path "--platform-hec-client-cert-file" "${PLATFORM_HEC_CLIENT_CERT_FILE}")"
[[ -z "${PLATFORM_HEC_CLIENT_KEY_FILE}" ]] || PLATFORM_HEC_CLIENT_KEY_FILE="$(resolve_abs_nosymlink_path "--platform-hec-client-key-file" "${PLATFORM_HEC_CLIENT_KEY_FILE}")"
[[ -z "${PLATFORM_OTLP_CA_FILE}" ]] || PLATFORM_OTLP_CA_FILE="$(resolve_abs_nosymlink_path "--platform-otlp-ca-file" "${PLATFORM_OTLP_CA_FILE}")"
[[ -z "${PLATFORM_OTLP_CLIENT_CERT_FILE}" ]] || PLATFORM_OTLP_CLIENT_CERT_FILE="$(resolve_abs_nosymlink_path "--platform-otlp-client-cert-file" "${PLATFORM_OTLP_CLIENT_CERT_FILE}")"
[[ -z "${PLATFORM_OTLP_CLIENT_KEY_FILE}" ]] || PLATFORM_OTLP_CLIENT_KEY_FILE="$(resolve_abs_nosymlink_path "--platform-otlp-client-key-file" "${PLATFORM_OTLP_CLIENT_KEY_FILE}")"
[[ -z "${SSH_KEY_FILE}" ]] || SSH_KEY_FILE="$(resolve_abs_nosymlink_path "--ssh-key-file" "${SSH_KEY_FILE}")"
[[ -z "${K8S_OBJECTS_FILE}" ]] || K8S_OBJECTS_FILE="$(resolve_abs_nosymlink_path "--k8s-objects-file" "${K8S_OBJECTS_FILE}")"
for index in "${!EXTRA_VALUES_FILES[@]}"; do
    EXTRA_VALUES_FILES[index]="$(resolve_abs_nosymlink_path "--extra-values-file" "${EXTRA_VALUES_FILES[index]}")"
done
for index in "${!TA_PACKAGE_PATHS[@]}"; do
    TA_PACKAGE_PATHS[index]="$(resolve_abs_nosymlink_path "--ta-package-path" "${TA_PACKAGE_PATHS[index]}")"
done

reject_generated_subtree_input "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1
reject_generated_subtree_input "--platform-hec-token-file" "${PLATFORM_HEC_TOKEN_FILE}" || exit 1
reject_generated_subtree_input "--platform-hec-ca-file" "${PLATFORM_HEC_CA_FILE}" || exit 1
reject_generated_subtree_input "--platform-hec-client-cert-file" "${PLATFORM_HEC_CLIENT_CERT_FILE}" || exit 1
reject_generated_subtree_input "--platform-hec-client-key-file" "${PLATFORM_HEC_CLIENT_KEY_FILE}" || exit 1
reject_generated_subtree_input "--platform-otlp-ca-file" "${PLATFORM_OTLP_CA_FILE}" || exit 1
reject_generated_subtree_input "--platform-otlp-client-cert-file" "${PLATFORM_OTLP_CLIENT_CERT_FILE}" || exit 1
reject_generated_subtree_input "--platform-otlp-client-key-file" "${PLATFORM_OTLP_CLIENT_KEY_FILE}" || exit 1
reject_generated_subtree_input "--ssh-key-file" "${SSH_KEY_FILE}" || exit 1
reject_generated_subtree_input "--k8s-objects-file" "${K8S_OBJECTS_FILE}" || exit 1
for path in "${EXTRA_VALUES_FILES[@]}"; do
    reject_generated_subtree_input "--extra-values-file" "${path}" || exit 1
done
for path in "${TA_PACKAGE_PATHS[@]}"; do
    reject_generated_subtree_input "--ta-package-path" "${path}" || exit 1
done

require_bool_value "--agent-enabled" "${AGENT_ENABLED}" || exit 1
require_bool_value "--gateway-enabled" "${GATEWAY_ENABLED}" || exit 1
require_bool_value "--network-explorer-enabled" "${NETWORK_EXPLORER_ENABLED}" || exit 1
require_bool_value "--cluster-receiver-enabled" "${CLUSTER_RECEIVER_ENABLED}" || exit 1
require_bool_value "--agent-host-network" "${AGENT_HOST_NETWORK}" || exit 1
require_bool_value "--platform-persistent-queue-enabled" "${PLATFORM_PERSISTENT_QUEUE_ENABLED}" || exit 1
require_bool_value "--platform-fsync-enabled" "${PLATFORM_FSYNC_ENABLED}" || exit 1
require_bool_value "--platform-logs-enabled" "${PLATFORM_LOGS_ENABLED}" || exit 1
require_bool_value "--platform-metrics-enabled" "${PLATFORM_METRICS_ENABLED}" || exit 1
require_bool_value "--platform-traces-enabled" "${PLATFORM_TRACES_ENABLED}" || exit 1
require_bool_value "--platform-otlp-insecure" "${PLATFORM_OTLP_INSECURE}" || exit 1
require_bool_value "--target-allocator-enabled" "${TARGET_ALLOCATOR_ENABLED}" || exit 1
require_bool_value "--k8s-entities-enabled" "${K8S_ENTITIES_ENABLED}" || exit 1
require_bool_value "--entity-events-enabled" "${ENTITY_EVENTS_ENABLED}" || exit 1
require_bool_value "--fips-enabled" "${FIPS_ENABLED}" || exit 1
require_bool_value "--instrumentation-installation-job" "${INSTRUMENTATION_INSTALLATION_JOB}" || exit 1

if [[ "${NETWORK_EXPLORER_ENABLED}" == "true" ]]; then
    GATEWAY_ENABLED=true
    case "${GATEWAY_REPLICAS}" in
        1|3) GATEWAY_REPLICAS=1 ;;
        *)
            log "ERROR: Network Explorer requires --gateway-replicas 1 (or omit the option)."
            exit 1
            ;;
    esac
fi

case "${PLATFORM_OTLP_PROTOCOL}" in
    grpc|http) ;;
    *)
        log "ERROR: --platform-otlp-protocol must be grpc or http."
        exit 1
        ;;
esac

case "${TA_TARGET}" in
    deployment-server|heavy-forwarder|universal-forwarder) ;;
    *)
        log "ERROR: --ta-target must be deployment-server, heavy-forwarder, or universal-forwarder."
        exit 1
        ;;
esac

case "${TA_PACKAGE_FLAVOR}" in
    auto|multi-os|linux-x86-64|windows-x86-64) ;;
    *)
        log "ERROR: --ta-package-flavor must be auto, multi-os, linux-x86-64, or windows-x86-64."
        exit 1
        ;;
esac

case "${TA_MODE}" in
    agent|gateway|agent-to-gateway) ;;
    *)
        log "ERROR: --ta-mode must be agent, gateway, or agent-to-gateway."
        exit 1
        ;;
esac

case "${TA_COLLECTOR_LOG_LEVEL}" in
    error|warn|info|debug) ;;
    *)
        log "ERROR: --ta-collector-log-level must be error, warn, info, or debug."
        exit 1
        ;;
esac

case "${TA_SECRET_MODE}" in
    placeholder|inputs-conf|legacy-file|environment) ;;
    *)
        log "ERROR: --ta-secret-mode must be placeholder, inputs-conf, legacy-file, or environment."
        exit 1
        ;;
esac

if [[ "${TA_MODE}" == "agent-to-gateway" && -z "${TA_GATEWAY_URL}" ]]; then
    log "ERROR: --ta-gateway-url is required when --ta-mode agent-to-gateway."
    exit 1
fi

for ta_env in "${TA_COLLECTOR_ENVS[@]}"; do
    if [[ "${ta_env}" == *$'\n'* || "${ta_env}" == *$'\r'* ]]; then
        log "ERROR: --ta-collector-env must be a single-line KEY=VALUE."
        exit 1
    fi
    if ta_env_is_secret_like "${ta_env}"; then
        log "ERROR: secret-like TA collector env / secret-like --ta-collector-env values are not accepted; use a TA secret mode or runtime environment injection."
        exit 1
    fi
    if [[ ! "${ta_env}" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
        log "ERROR: --ta-collector-env must be KEY=VALUE with a shell-style environment key."
        exit 1
    fi
done

for ta_cmd_arg in "${TA_COLLECTOR_CMD_ARGS[@]}"; do
    if [[ "${ta_cmd_arg}" == *$'\n'* || "${ta_cmd_arg}" == *$'\r'* ]]; then
        log "ERROR: --ta-collector-cmd-arg must be a single-line value."
        exit 1
    fi
    if ta_cmd_arg_is_secret_like "${ta_cmd_arg}"; then
        log "ERROR: secret-like TA collector command args / secret-like --ta-collector-cmd-arg values are not accepted; use a TA secret mode or runtime environment injection."
        exit 1
    fi
done

if [[ ("${TA_FIPS_REQUIRED}" == "true" || "${TA_FEDRAMP_REQUIRED}" == "true") && "${ACCEPT_TA_REGULATED_OVERRIDE}" != "true" ]]; then
    log "ERROR: Splunkbase marks app 7125 FIPS-incompatible; its FedRAMP status is not documented."
    log "       Pass --accept-ta-regulated-override to render a warning packet."
    exit 1
fi

if [[ "${APPLY_TA}" == "true" && "${TA_SECRET_MODE}" == "placeholder" ]]; then
    log "ERROR: --apply-ta cannot use --ta-secret-mode placeholder; choose inputs-conf, legacy-file, or environment."
    exit 1
fi

if [[ "${APPLY_TA}" == "true" && "${#TA_PACKAGE_PATHS[@]}" -eq 0 ]]; then
    log "ERROR: --apply-ta requires at least one --ta-package-path."
    exit 1
fi

PLATFORM_HEC_TOKEN_REQUIRED=false
if [[ -n "${PLATFORM_HEC_URL}" ]] && {
    [[ "${PLATFORM_METRICS_ENABLED}" == "true" ]] ||
    [[ "${PLATFORM_TRACES_ENABLED}" == "true" ]] ||
    { [[ "${PLATFORM_LOGS_ENABLED}" == "true" ]] && [[ -z "${PLATFORM_OTLP_ENDPOINT}" ]]; } ||
    { [[ "${ENABLE_LOGS}" == "true" || "${ENABLE_JOURNALD}" == "true" ]] && [[ -z "${PLATFORM_OTLP_ENDPOINT}" ]]; }
}; then
    PLATFORM_HEC_TOKEN_REQUIRED=true
fi

if [[ "${PLATFORM_HEC_TOKEN_REQUIRED}" == "true" && -z "${PLATFORM_HEC_TOKEN_FILE}" ]]; then
    log "ERROR: --platform-hec-url requires --platform-hec-token-file."
    exit 1
fi

if [[ "${APPLY_LINUX}" == "true" || ( "${APPLY_K8S}" == "true" && "${O11Y_DESTINATION_ENABLED}" == "true" ) ]]; then
    if [[ -z "${O11Y_TOKEN_FILE}" || ! -r "${O11Y_TOKEN_FILE}" ]]; then
        log "ERROR: Apply requires a readable --o11y-token-file."
        exit 1
    fi
fi

if [[ "${APPLY_TA}" == "true" && "${TA_SECRET_MODE}" == "inputs-conf" ]]; then
    if [[ "${ACCEPT_TA_TOKEN_IN_CONF}" != "true" ]]; then
        log "ERROR: --apply-ta with --ta-secret-mode inputs-conf requires --accept-ta-token-in-conf."
        exit 1
    fi
    if [[ -z "${O11Y_TOKEN_FILE}" || ! -r "${O11Y_TOKEN_FILE}" ]]; then
        log "ERROR: --apply-ta with --ta-secret-mode inputs-conf requires a readable --o11y-token-file."
        exit 1
    fi
fi

if [[ "${APPLY_TA}" == "true" && "${TA_SECRET_MODE}" == "legacy-file" ]]; then
    if [[ -z "${O11Y_TOKEN_FILE}" || ! -r "${O11Y_TOKEN_FILE}" ]]; then
        log "ERROR: --apply-ta with --ta-secret-mode legacy-file requires a readable --o11y-token-file."
        exit 1
    fi
fi

if [[ "${APPLY_K8S}" == "true" && "${PLATFORM_HEC_TOKEN_REQUIRED}" == "true" && ! -r "${PLATFORM_HEC_TOKEN_FILE}" ]]; then
    log "ERROR: Kubernetes Platform HEC apply requires a readable --platform-hec-token-file."
    exit 1
fi

# Token-permission preflight. Tokens MUST be nonempty, non-symlink regular
# files with mode 600 (owner read/write only); there is no bypass.
# Use BSD/GNU stat-compatible probes; macOS uses `-f %A`, Linux uses `-c %a`.
_token_perm_octal() {
    local target="$1"
    local mode=""
    if mode="$(stat -c '%a' "${target}" 2>/dev/null)"; then
        printf '%s' "${mode}"
        return 0
    fi
    if mode="$(stat -f '%A' "${target}" 2>/dev/null)"; then
        printf '%s' "${mode}"
        return 0
    fi
    printf ''
}

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" ]] || return 0
    if [[ ! -f "${path}" || -L "${path}" || ! -r "${path}" || ! -s "${path}" ]]; then
        log "ERROR: ${label} must be a readable, nonempty, non-symlink regular file: ${path}"
        return 1
    fi
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then
        log "ERROR: Could not verify mode 600 for ${label} (${path})."
        return 1
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        log "ERROR: ${label} (${path}) is mode ${mode}; tokens must be mode 600."
        log "       Run 'chmod 600 ${path}' to fix."
        return 1
    fi
    return 0
}

if [[ "${APPLY_K8S}" == "true" || "${APPLY_LINUX}" == "true" || ( "${APPLY_TA}" == "true" && ( "${TA_SECRET_MODE}" == "inputs-conf" || "${TA_SECRET_MODE}" == "legacy-file" ) ) ]]; then
    if [[ "${APPLY_LINUX}" == "true" || ( "${APPLY_K8S}" == "true" && "${O11Y_DESTINATION_ENABLED}" == "true" ) ||
          ( "${APPLY_TA}" == "true" && ( "${TA_SECRET_MODE}" == "inputs-conf" || "${TA_SECRET_MODE}" == "legacy-file" ) ) ]]; then
        _check_token_perms "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1
    fi
    if [[ "${PLATFORM_HEC_TOKEN_REQUIRED}" == "true" ]]; then
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
    primary|beta) ;;
    *)
        log "ERROR: --repo-channel must be primary or beta; test disables upstream package verification."
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
    --k8s-objects-file "${K8S_OBJECTS_FILE}"
    --o11y-ingest-url "${O11Y_INGEST_URL}"
    --o11y-api-url "${O11Y_API_URL}"
    --platform-hec-url "${PLATFORM_HEC_URL}"
    --platform-hec-index "${PLATFORM_HEC_INDEX}"
    --platform-metrics-index "${PLATFORM_METRICS_INDEX}"
    --platform-traces-index "${PLATFORM_TRACES_INDEX}"
    --platform-otlp-endpoint "${PLATFORM_OTLP_ENDPOINT}"
    --platform-otlp-protocol "${PLATFORM_OTLP_PROTOCOL}"
    --platform-otlp-insecure "$(bool_text "${PLATFORM_OTLP_INSECURE}")"
    --platform-hec-ca-file "${PLATFORM_HEC_CA_FILE}"
    --platform-hec-client-cert-file "${PLATFORM_HEC_CLIENT_CERT_FILE}"
    --platform-hec-client-key-file "${PLATFORM_HEC_CLIENT_KEY_FILE}"
    --platform-otlp-ca-file "${PLATFORM_OTLP_CA_FILE}"
    --platform-otlp-client-cert-file "${PLATFORM_OTLP_CLIENT_CERT_FILE}"
    --platform-otlp-client-key-file "${PLATFORM_OTLP_CLIENT_KEY_FILE}"
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
    --agent-enabled "$(bool_text "${AGENT_ENABLED}")"
    --gateway-enabled "$(bool_text "${GATEWAY_ENABLED}")"
    --gateway-replicas "${GATEWAY_REPLICAS}"
    --network-explorer-enabled "$(bool_text "${NETWORK_EXPLORER_ENABLED}")"
    --windows-nodes "$(bool_text "${WINDOWS_NODES}")"
    --cluster-receiver-enabled "$(bool_text "${CLUSTER_RECEIVER_ENABLED}")"
    --agent-host-network "$(bool_text "${AGENT_HOST_NETWORK}")"
    --platform-persistent-queue-enabled "$(bool_text "${PLATFORM_PERSISTENT_QUEUE_ENABLED}")"
    --platform-persistent-queue-path "${PLATFORM_PERSISTENT_QUEUE_PATH}"
    --platform-fsync-enabled "$(bool_text "${PLATFORM_FSYNC_ENABLED}")"
    --platform-logs-enabled "$(bool_text "${PLATFORM_LOGS_ENABLED}")"
    --platform-metrics-enabled "$(bool_text "${PLATFORM_METRICS_ENABLED}")"
    --platform-traces-enabled "$(bool_text "${PLATFORM_TRACES_ENABLED}")"
    --target-allocator-enabled "$(bool_text "${TARGET_ALLOCATOR_ENABLED}")"
    --k8s-entities-enabled "$(bool_text "${K8S_ENTITIES_ENABLED}")"
    --entity-events-enabled "$(bool_text "${ENTITY_EVENTS_ENABLED}")"
    --fips-enabled "$(bool_text "${FIPS_ENABLED}")"
    --instrumentation-installation-job "$(bool_text "${INSTRUMENTATION_INSTALLATION_JOB}")"
    --instrumentation-kubectl-image-tag "${INSTRUMENTATION_KUBECTL_IMAGE_TAG}"
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
    --collector-config "${COLLECTOR_CONFIG}"
    --linux-health-endpoint "${LINUX_HEALTH_ENDPOINT}"
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
    --installer-sha256 "${INSTALLER_SHA256}"
    --ta-target "${TA_TARGET}"
    --ta-package-flavor "${TA_PACKAGE_FLAVOR}"
    --ta-mode "${TA_MODE}"
    --ta-listen-interface "${TA_LISTEN_INTERFACE}"
    --ta-gateway-url "${TA_GATEWAY_URL}"
    --ta-collector-log-level "${TA_COLLECTOR_LOG_LEVEL}"
    --ta-serverclass-whitelist "${TA_SERVERCLASS_WHITELIST}"
    --splunk-version "${SPLUNK_VERSION}"
    --ta-secret-mode "${TA_SECRET_MODE}"
    --enable-metrics "$(bool_text "${ENABLE_METRICS}")"
    --enable-traces "$(bool_text "${ENABLE_TRACES}")"
    --enable-logs "$(bool_text "${ENABLE_LOGS}")"
    --enable-journald "$(bool_text "${ENABLE_JOURNALD}")"
    --enable-profiling "$(bool_text "${ENABLE_PROFILING}")"
    --enable-memory-profiling "$(bool_text "${ENABLE_MEMORY_PROFILING}")"
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
for ta_package_path in "${TA_PACKAGE_PATHS[@]}"; do
    RENDER_ARGS+=(--ta-package-path "${ta_package_path}")
done
for ta_collector_env in "${TA_COLLECTOR_ENVS[@]}"; do
    RENDER_ARGS+=(--ta-collector-env "${ta_collector_env}")
done
for ta_collector_cmd_arg in "${TA_COLLECTOR_CMD_ARGS[@]}"; do
    RENDER_ARGS+=("--ta-collector-cmd-arg=${ta_collector_cmd_arg}")
done
for extra_values_file in "${EXTRA_VALUES_FILES[@]}"; do
    RENDER_ARGS+=(--extra-values-file "${extra_values_file}")
done

if [[ "${RENDER_K8S}" == "true" ]]; then
    RENDER_ARGS+=(--render-k8s)
fi
if [[ "${RENDER_LINUX}" == "true" ]]; then
    RENDER_ARGS+=(--render-linux)
fi
if [[ "${RENDER_TA}" == "true" ]]; then
    RENDER_ARGS+=(--render-ta)
fi
if [[ "${METRICS_EXPLICIT}" == "true" ]]; then
    RENDER_ARGS+=(--metrics-explicit)
fi
if [[ "${TRACES_EXPLICIT}" == "true" ]]; then
    RENDER_ARGS+=(--traces-explicit)
fi
if [[ "${LOGS_EXPLICIT}" == "true" ]]; then
    RENDER_ARGS+=(--logs-explicit)
fi
if [[ "${RENDER_PLATFORM_HEC_HELPER}" == "true" ]]; then
    RENDER_ARGS+=(--render-platform-hec-helper)
fi
if [[ "${TA_ENABLE_OPAMP}" == "true" ]]; then
    RENDER_ARGS+=(--ta-enable-opamp)
fi
if [[ "${ACCEPT_TA_TOKEN_IN_CONF}" == "true" ]]; then
    RENDER_ARGS+=(--accept-ta-token-in-conf)
fi
if [[ "${TA_FIPS_REQUIRED}" == "true" ]]; then
    RENDER_ARGS+=(--ta-fips-required)
fi
if [[ "${TA_FEDRAMP_REQUIRED}" == "true" ]]; then
    RENDER_ARGS+=(--ta-fedramp-required)
fi
if [[ "${ACCEPT_TA_REGULATED_OVERRIDE}" == "true" ]]; then
    RENDER_ARGS+=(--accept-ta-regulated-override)
fi
if [[ "${ACCEPT_UNAUDITED_TA_PACKAGE}" == "true" ]]; then
    RENDER_ARGS+=(--ta-allow-unaudited-package)
fi
if [[ "${ACCEPT_EXPERIMENTAL_PLATFORM_TRACES}" == "true" ]]; then
    RENDER_ARGS+=(--accept-experimental-platform-traces)
fi
if [[ "${ACCEPT_CLUSTER_WIDE_OBJECT_RBAC}" == "true" ]]; then
    RENDER_ARGS+=(--accept-cluster-wide-object-rbac)
fi
if [[ "${ACCEPT_INSECURE_PLATFORM_HEC}" == "true" ]]; then
    RENDER_ARGS+=(--accept-insecure-platform-hec)
fi
if [[ "${DRY_RUN}" == "true" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi

"${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"

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
    run_rendered_script "${OUTPUT_DIR}/k8s/preflight.sh"
    run_rendered_script "${OUTPUT_DIR}/k8s/validate-secrets.sh"
    run_optional_rendered_script "${OUTPUT_DIR}/k8s/priority-class.sh"
    run_rendered_script "${OUTPUT_DIR}/k8s/create-secret.sh"
    run_rendered_script "${OUTPUT_DIR}/k8s/helm-install.sh"
    run_rendered_script "${OUTPUT_DIR}/k8s/status.sh"
fi

if [[ "${APPLY_LINUX}" == "true" ]]; then
    if [[ "${EXECUTION}" == "ssh" ]]; then
        run_rendered_script "${OUTPUT_DIR}/linux/install-ssh.sh"
        run_rendered_script "${OUTPUT_DIR}/linux/status-ssh.sh"
    else
        run_rendered_script "${OUTPUT_DIR}/linux/install-local.sh"
        run_rendered_script "${OUTPUT_DIR}/linux/status-local.sh"
    fi
fi

if [[ "${APPLY_TA}" == "true" ]]; then
    run_rendered_script "${OUTPUT_DIR}/ta/preflight-ta.sh"
    run_rendered_script "${OUTPUT_DIR}/ta/stage-ta-package.sh"
    if [[ "${TA_TARGET}" == "deployment-server" ]]; then
        run_rendered_script "${OUTPUT_DIR}/ta/apply-deployment-server.sh"
        run_rendered_script "${OUTPUT_DIR}/ta/status-ta.sh"
    else
        run_rendered_script "${OUTPUT_DIR}/ta/apply-local-uf.sh"
        if [[ "${TA_TARGET}" == "heavy-forwarder" ]]; then
            ta_splunk_home="${SPLUNK_HOME:-/opt/splunk}"
        else
            ta_splunk_home="${SPLUNK_HOME:-/opt/splunkforwarder}"
        fi
        if [[ -x "${ta_splunk_home}/bin/splunk" ]]; then
            run_rendered_script "${OUTPUT_DIR}/ta/status-ta.sh"
        else
            log "TA apply completed; skipping runtime status because ${ta_splunk_home}/bin/splunk is unavailable."
            log "Run ${OUTPUT_DIR}/ta/status-ta.sh on the target ${TA_TARGET} before declaring completion."
        fi
    fi
fi
