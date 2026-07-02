#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIGINAL_ARGS=("$@")
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/platform_version_helpers.sh"

# This internal marker is used only by the read-only validator. Never let a
# caller use it to relax fresh-install guards in setup/apply workflows.
unset SOK_VALIDATE_EXISTING

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
OPERATOR_IMAGE=""
CHART_VERSION=""
OPERATOR_CHART_ARCHIVE=""
ENTERPRISE_CHART_ARCHIVE=""
CRD_MANIFEST=""
SPLUNK_VERSION="$(spv_enterprise_default)"
SPLUNK_IMAGE=""
STORAGE_CLASS=""
ETC_STORAGE="10Gi"
VAR_STORAGE="100Gi"
STANDALONE_REPLICAS="1"
INDEXER_REPLICAS="3"
SEARCH_HEAD_REPLICAS="3"
SITE_COUNT="2"
SITE_ZONES=""
MANAGER_SITE="site1"
SEARCH_HEAD_SITE="site2"
MANAGER_ZONE=""
SEARCH_HEAD_ZONE=""
LICENSE_FILE=""
SMARTSTORE_BUCKET=""
SMARTSTORE_PREFIX=""
SMARTSTORE_INDEXES="main"
SMARTSTORE_PROVIDER="aws"
SMARTSTORE_REGION=""
SMARTSTORE_ENDPOINT=""
SMARTSTORE_SECRET_REF=""
CONFIRM_SMARTSTORE_INDEX_INVENTORY=false
CONFIRM_SMARTSTORE_PATH_OWNERSHIP=false
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
KUBERNETES_VERSION=""
EXPECTED_KUBE_CONTEXT=""
EXPECTED_API_SERVER=""
EXPECTED_CLUSTER_UID=""
ALLOW_UNVERIFIED_VERSIONS=false
OPERATOR_SCOPE="namespace"
WATCH_NAMESPACES=""
DEPLOYMENT_PROFILE="development"
ALLOW_UPGRADE=false
CONFIRM_SPLUNK_10_4_UPGRADE_READINESS=false
ENTERPRISE_VALUES_OVERLAY=""
OPERATOR_VALUES_OVERLAY=""
INDEXING_INGESTION_SEPARATION=false
INGESTOR_REPLICAS="3"
INGESTOR_SERVICE_ACCOUNT=""
QUEUE_PROVIDER="sqs"
QUEUE_NAME=""
QUEUE_DLQ=""
QUEUE_REGION=""
QUEUE_ENDPOINT=""
QUEUE_SECRET_REF=""
OBJECT_STORAGE_PATH=""
OBJECT_STORAGE_ENDPOINT=""
EXISTING_LICENSE_MANAGER=""
EXISTING_LICENSE_MANAGER_NAMESPACE=""
SPLUNK_SERVICE_ACCOUNT=""
SPLUNK_IRSA_ROLE_ARN=""
SPLUNK_IRSA_TOKEN_EXPIRATION="3600"
DISABLE_MONITORING_CONSOLE=false
POD_VERSION="10.4.0_1.6.0"
CONFIRM_NEW_POD_INSTALL=false
INSTALLER_PATH="/path/to/kubernetes-installer-standalone"
INSTALLER_SHA256=""
PRIMARY_SEARCH_NAME=""
SECONDARY_SEARCH_NAME=""
CLUSTER_MANAGER_APPS=""
SEARCH_DEPLOYER_APPS=""
LICENSE_MANAGER_APPS=""
ITSI_APPS=""
ITSI_SOURCE_BUNDLE=""
ITSI_SOURCE_SHA256=""
ITSI_JDK_SHA256=""
INGRESS_CERTIFICATE_FILE=""
INGRESS_PRIVATE_KEY_FILE=""
INGRESS_DOMAIN=""
INGRESS_CA_FILE=""
SOK_ONLY_OPTIONS=()
POD_ONLY_OPTIONS=()

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Kubernetes Setup

Usage: $(basename "$0") [OPTIONS]

Core options:
  --target sok|pod                         Setup target (default: sok)
  --architecture s1|c3|m4                  SOK SVA architecture (default: s1)
  --pod-profile PROFILE                    POD small|medium|large|xlarge, optionally -es or -itsi
  --phase render|preflight|apply|status|all
  --apply                                  Apply after rendering when phase is render
  --dry-run                                Show planned work without rendering or executing
  --json                                   Emit JSON plan/metadata for render or dry-run only
  --output-dir PATH                        Render output directory (default: ./splunk-enterprise-k8s-rendered)

Shared options:
  --license-file PATH                      SOK license file, or POD license-file CSV
  --allow-upgrade                          Gated SOK upgrade; POD mutation remains a handoff
  --allow-unverified-versions              Explicit override for an unverified version tuple

SOK options:
  --namespace NAME                         Splunk Enterprise namespace (default: splunk-operator)
  --operator-namespace NAME                Operator namespace (default: splunk-operator)
  --release-name NAME                      Enterprise Helm release (default: splunk-enterprise)
  --operator-release-name NAME             Operator Helm release (default: splunk-operator)
  --operator-version VERSION               Splunk Operator version (default: 3.1.0)
  --operator-image IMAGE                   Private-registry Operator image mirror
  --chart-version VERSION                  Helm chart version (default: follows --operator-version)
  --operator-chart-archive PATH            Reviewed local Operator chart archive
  --enterprise-chart-archive PATH          Reviewed local Enterprise chart archive
  --crd-manifest PATH                      Reviewed local SOK CRD manifest
  --splunk-version VERSION                 Splunk Enterprise version (default: $(spv_enterprise_default))
  --splunk-image IMAGE                     Override Splunk Enterprise image
  --storage-class NAME                     Kubernetes StorageClass override
  --etc-storage SIZE                       /opt/splunk/etc PVC size (default: 10Gi)
  --var-storage SIZE                       /opt/splunk/var PVC size (default: 100Gi)
  --standalone-replicas N                  Verified S1 requires exactly 1 (default: 1)
  --indexer-replicas N                     C3 total indexers; M4 indexers per site (default: 3)
  --search-head-replicas N                 C3/M4 search head count (default: 3)
  --site-count N                           Verified M4 site count (default/required: 2)
  --site-zones CSV                         M4 Kubernetes zone labels, one per site
  --manager-site SITE                      M4 Splunk site for Cluster Manager (default: site1)
  --search-head-site SITE                  M4 Splunk site for SHC (default: site2)
  --manager-zone ZONE                      M4 Cluster Manager zone
  --search-head-zone ZONE                  M4 Search Head Cluster zone
  --smartstore-bucket NAME                 S3 bucket name for SmartStore
  --smartstore-prefix PATH                 Optional SmartStore prefix within the bucket
  --smartstore-indexes CSV                SmartStore-managed index inventory (default: main)
  --smartstore-provider aws|minio          S3 provider contract (default: aws)
  --smartstore-region REGION              SmartStore AWS region
  --smartstore-endpoint URL                SmartStore endpoint override
  --smartstore-secret-ref NAME             Existing Kubernetes secret for SmartStore credentials
  --confirm-smartstore-index-inventory     Confirm the complete production index inventory
  --confirm-smartstore-path-ownership      Confirm no other active deployment shares the remote path
  --eks-cluster-name NAME                  Render/run EKS kubeconfig helper
  --aws-region REGION                      AWS region for EKS and SmartStore helpers
  --kubernetes-version VERSION             Validate an offline Kubernetes server version
  --expected-kube-context NAME             Reviewed kubectl context for live helpers
  --expected-api-server URL                Reviewed Kubernetes API server URL
  --expected-cluster-uid UID               Reviewed kube-system namespace UID
  --operator-scope namespace|cluster       Operator RBAC scope (default: namespace)
  --watch-namespaces CSV                   Namespaces watched by a cluster-scoped operator
  --deployment-profile development|production
  --splunk-service-account NAME            Existing SmartStore AWS IRSA service account
  --splunk-irsa-role-arn ARN               Exact IAM role annotation for that service account
  --splunk-irsa-token-expiration SECONDS   Exact projected token TTL (600..86400; default: 3600)
  --existing-license-manager NAME          Existing LicenseManager custom resource
  --existing-license-manager-namespace NS  Namespace for the existing LicenseManager
  --disable-monitoring-console             Do not render a MonitoringConsole CR
  --enterprise-values-overlay PATH         Reviewed non-secret Enterprise chart overlay
  --operator-values-overlay PATH           Reviewed non-secret operator chart overlay
  --confirm-splunk-10-4-upgrade-readiness Confirm required 10.4 backup/KV/app/TLS checks
  --indexing-ingestion-separation          Enable SOK 3.1 Queue/ObjectStorage/IngestorCluster
  --ingestor-replicas N                    Ingestor count (default: 3)
  --ingestor-service-account NAME          Reserved handoff; rejected by verified SOK 3.1 I&I
  --queue-provider sqs|sqs_cp               Queue provider (default: sqs)
  --queue-name NAME                        SQS queue name
  --queue-dlq NAME                         SQS dead-letter queue name
  --queue-region REGION                    SQS authentication region
  --queue-endpoint URL                     Optional SQS endpoint
  --queue-secret-ref NAME                  Required existing Queue credential Secret
  --object-storage-path PATH               S3 bucket/prefix for oversized messages
  --object-storage-endpoint URL            Optional S3 endpoint
  --accept-splunk-general-terms            Required for every SOK Operator reconciliation

POD options:
  --controller-ips CSV                     Controller node IPs
  --worker-ips CSV                         Worker node IPs
  --ssh-user USER                          Sudo-capable SSH user (default: splunkadmin)
  --ssh-private-key-file PATH              SSH private key path on bastion
  --installer-path PATH                    POD installer binary (required for live phases)
  --installer-sha256 HEX                   Independently reviewed installer SHA-256
  --pod-version VERSION                    Coupled POD bundle (default: 10.4.0_1.6.0)
  --confirm-new-pod-install                One-time reviewed attestation for a new cluster
  --primary-search-name NAME               Immutable primary standalone/SHC name
  --secondary-search-name NAME             Immutable ES/ITSI standalone/SHC name
  --indexer-apps CSV                       App packages for indexer cluster scope
  --cluster-manager-apps CSV               App packages local to Cluster Manager
  --search-apps CSV                        App packages for SHC cluster scope
  --search-deployer-apps CSV               App packages local to SHC deployer
  --standalone-apps CSV                    App packages for pod-small standalone local scope
  --premium-apps CSV                       Enterprise Security package (ES profiles only)
  --itsi-apps CSV                          Repacked ITSI/JDK apps for ITSI search tier
  --itsi-source-bundle PATH                Original ITSI 4.21.2 bundle used to prove repackaging
  --itsi-source-sha256 HEX                 Reviewed SHA-256 of the original ITSI bundle
  --itsi-jdk-sha256 HEX                    Reviewed SHA-256 of the POD OpenJDK 17 app
  --license-manager-apps CSV               Apps local to POD License Manager
  --ingress-certificate-file PATH          Custom PEM chain; requires key, CA, and domain
  --ingress-private-key-file PATH          Custom PEM key; requires certificate, CA, and domain
  --ingress-domain NAME                    Record/validate DNS suffix; required with a custom certificate
  --ingress-ca-file PATH                   Required trust bundle for a custom certificate

Examples:
  $(basename "$0") --target sok --architecture c3 --accept-splunk-general-terms
  $(basename "$0") --target sok --phase apply --output-dir ./splunk-enterprise-k8s-rendered
  $(basename "$0") --target pod --pod-profile pod-medium --controller-ips 10.10.10.1,10.10.10.2,10.10.10.3

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) require_arg "$1" $# || exit 1; TARGET="$2"; shift 2 ;;
        --architecture) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); ARCHITECTURE="$2"; shift 2 ;;
        --pod-profile) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); POD_PROFILE="$2"; shift 2 ;;
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --namespace) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); NAMESPACE="$2"; shift 2 ;;
        --operator-namespace) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OPERATOR_NAMESPACE="$2"; shift 2 ;;
        --release-name) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); RELEASE_NAME="$2"; shift 2 ;;
        --operator-release-name) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OPERATOR_RELEASE_NAME="$2"; shift 2 ;;
        --operator-version) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OPERATOR_VERSION="$2"; shift 2 ;;
        --operator-image) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OPERATOR_IMAGE="$2"; shift 2 ;;
        --chart-version) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); CHART_VERSION="$2"; shift 2 ;;
        --operator-chart-archive) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OPERATOR_CHART_ARCHIVE="$2"; shift 2 ;;
        --enterprise-chart-archive) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); ENTERPRISE_CHART_ARCHIVE="$2"; shift 2 ;;
        --crd-manifest) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); CRD_MANIFEST="$2"; shift 2 ;;
        --splunk-version) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SPLUNK_VERSION="$2"; shift 2 ;;
        --splunk-image) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SPLUNK_IMAGE="$2"; shift 2 ;;
        --storage-class) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); STORAGE_CLASS="$2"; shift 2 ;;
        --etc-storage) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); ETC_STORAGE="$2"; shift 2 ;;
        --var-storage) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); VAR_STORAGE="$2"; shift 2 ;;
        --standalone-replicas) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); STANDALONE_REPLICAS="$2"; shift 2 ;;
        --indexer-replicas) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); INDEXER_REPLICAS="$2"; shift 2 ;;
        --search-head-replicas) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SEARCH_HEAD_REPLICAS="$2"; shift 2 ;;
        --site-count) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SITE_COUNT="$2"; shift 2 ;;
        --site-zones) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SITE_ZONES="$2"; shift 2 ;;
        --manager-site) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); MANAGER_SITE="$2"; shift 2 ;;
        --search-head-site) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SEARCH_HEAD_SITE="$2"; shift 2 ;;
        --manager-zone) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); MANAGER_ZONE="$2"; shift 2 ;;
        --search-head-zone) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SEARCH_HEAD_ZONE="$2"; shift 2 ;;
        --license-file) require_arg "$1" $# || exit 1; LICENSE_FILE="$2"; shift 2 ;;
        --smartstore-bucket) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SMARTSTORE_BUCKET="$2"; shift 2 ;;
        --smartstore-prefix) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SMARTSTORE_PREFIX="$2"; shift 2 ;;
        --smartstore-indexes) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SMARTSTORE_INDEXES="$2"; shift 2 ;;
        --smartstore-provider) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SMARTSTORE_PROVIDER="$2"; shift 2 ;;
        --smartstore-region) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SMARTSTORE_REGION="$2"; shift 2 ;;
        --smartstore-endpoint) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SMARTSTORE_ENDPOINT="$2"; shift 2 ;;
        --smartstore-secret-ref) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SMARTSTORE_SECRET_REF="$2"; shift 2 ;;
        --confirm-smartstore-index-inventory) SOK_ONLY_OPTIONS+=("$1"); CONFIRM_SMARTSTORE_INDEX_INVENTORY=true; shift ;;
        --confirm-smartstore-path-ownership) SOK_ONLY_OPTIONS+=("$1"); CONFIRM_SMARTSTORE_PATH_OWNERSHIP=true; shift ;;
        --eks-cluster-name)
            require_arg "$1" $# || exit 1
            [[ -n "$2" ]] || { log "ERROR: --eks-cluster-name must not be empty."; exit 1; }
            SOK_ONLY_OPTIONS+=("$1")
            EKS_CLUSTER_NAME="$2"
            shift 2
            ;;
        --aws-region) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); AWS_REGION="$2"; shift 2 ;;
        --controller-ips) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); CONTROLLER_IPS="$2"; shift 2 ;;
        --worker-ips) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); WORKER_IPS="$2"; shift 2 ;;
        --ssh-user) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); SSH_USER="$2"; shift 2 ;;
        --ssh-private-key-file) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); SSH_PRIVATE_KEY_FILE="$2"; shift 2 ;;
        --indexer-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); INDEXER_APPS="$2"; shift 2 ;;
        --search-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); SEARCH_APPS="$2"; shift 2 ;;
        --standalone-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); STANDALONE_APPS="$2"; shift 2 ;;
        --premium-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); PREMIUM_APPS="$2"; shift 2 ;;
        --accept-splunk-general-terms) SOK_ONLY_OPTIONS+=("$1"); ACCEPT_SPLUNK_GENERAL_TERMS=true; shift ;;
        --kubernetes-version) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); KUBERNETES_VERSION="$2"; shift 2 ;;
        --expected-kube-context) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); EXPECTED_KUBE_CONTEXT="$2"; shift 2 ;;
        --expected-api-server) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); EXPECTED_API_SERVER="$2"; shift 2 ;;
        --expected-cluster-uid) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); EXPECTED_CLUSTER_UID="$2"; shift 2 ;;
        --allow-unverified-versions) ALLOW_UNVERIFIED_VERSIONS=true; shift ;;
        --operator-scope) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OPERATOR_SCOPE="$2"; shift 2 ;;
        --watch-namespaces) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); WATCH_NAMESPACES="$2"; shift 2 ;;
        --deployment-profile) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); DEPLOYMENT_PROFILE="$2"; shift 2 ;;
        --allow-upgrade) ALLOW_UPGRADE=true; shift ;;
        --confirm-splunk-10-4-upgrade-readiness)
            SOK_ONLY_OPTIONS+=("$1")
            CONFIRM_SPLUNK_10_4_UPGRADE_READINESS=true
            shift
            ;;
        --enterprise-values-overlay) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); ENTERPRISE_VALUES_OVERLAY="$2"; shift 2 ;;
        --operator-values-overlay) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OPERATOR_VALUES_OVERLAY="$2"; shift 2 ;;
        --indexing-ingestion-separation) SOK_ONLY_OPTIONS+=("$1"); INDEXING_INGESTION_SEPARATION=true; shift ;;
        --ingestor-replicas) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); INGESTOR_REPLICAS="$2"; shift 2 ;;
        --ingestor-service-account) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); INGESTOR_SERVICE_ACCOUNT="$2"; shift 2 ;;
        --queue-provider) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); QUEUE_PROVIDER="$2"; shift 2 ;;
        --queue-name) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); QUEUE_NAME="$2"; shift 2 ;;
        --queue-dlq) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); QUEUE_DLQ="$2"; shift 2 ;;
        --queue-region) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); QUEUE_REGION="$2"; shift 2 ;;
        --queue-endpoint) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); QUEUE_ENDPOINT="$2"; shift 2 ;;
        --queue-secret-ref) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); QUEUE_SECRET_REF="$2"; shift 2 ;;
        --object-storage-path) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OBJECT_STORAGE_PATH="$2"; shift 2 ;;
        --object-storage-endpoint) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); OBJECT_STORAGE_ENDPOINT="$2"; shift 2 ;;
        --existing-license-manager) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); EXISTING_LICENSE_MANAGER="$2"; shift 2 ;;
        --existing-license-manager-namespace) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); EXISTING_LICENSE_MANAGER_NAMESPACE="$2"; shift 2 ;;
        --splunk-service-account) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SPLUNK_SERVICE_ACCOUNT="$2"; shift 2 ;;
        --splunk-irsa-role-arn) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SPLUNK_IRSA_ROLE_ARN="$2"; shift 2 ;;
        --splunk-irsa-token-expiration) require_arg "$1" $# || exit 1; SOK_ONLY_OPTIONS+=("$1"); SPLUNK_IRSA_TOKEN_EXPIRATION="$2"; shift 2 ;;
        --disable-monitoring-console) SOK_ONLY_OPTIONS+=("$1"); DISABLE_MONITORING_CONSOLE=true; shift ;;
        --pod-version) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); POD_VERSION="$2"; shift 2 ;;
        --confirm-new-pod-install) POD_ONLY_OPTIONS+=("$1"); CONFIRM_NEW_POD_INSTALL=true; shift ;;
        --installer-path) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); INSTALLER_PATH="$2"; shift 2 ;;
        --installer-sha256) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); INSTALLER_SHA256="$2"; shift 2 ;;
        --primary-search-name) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); PRIMARY_SEARCH_NAME="$2"; shift 2 ;;
        --secondary-search-name) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); SECONDARY_SEARCH_NAME="$2"; shift 2 ;;
        --cluster-manager-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); CLUSTER_MANAGER_APPS="$2"; shift 2 ;;
        --search-deployer-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); SEARCH_DEPLOYER_APPS="$2"; shift 2 ;;
        --license-manager-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); LICENSE_MANAGER_APPS="$2"; shift 2 ;;
        --itsi-apps) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); ITSI_APPS="$2"; shift 2 ;;
        --itsi-source-bundle) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); ITSI_SOURCE_BUNDLE="$2"; shift 2 ;;
        --itsi-source-sha256) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); ITSI_SOURCE_SHA256="$2"; shift 2 ;;
        --itsi-jdk-sha256) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); ITSI_JDK_SHA256="$2"; shift 2 ;;
        --ingress-certificate-file) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); INGRESS_CERTIFICATE_FILE="$2"; shift 2 ;;
        --ingress-private-key-file) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); INGRESS_PRIVATE_KEY_FILE="$2"; shift 2 ;;
        --ingress-domain) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); INGRESS_DOMAIN="$2"; shift 2 ;;
        --ingress-ca-file) require_arg "$1" $# || exit 1; POD_ONLY_OPTIONS+=("$1"); INGRESS_CA_FILE="$2"; shift 2 ;;
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
        all) return 0 ;;
        render) [[ "${APPLY}" == "true" ]] ;;
        *) return 1 ;;
    esac
}

validate_csv_files() {
    local value="$1" option="$2" item
    [[ -n "${value}" ]] || return 0
    local items=()
    IFS=',' read -r -a items <<<"${value}"
    for item in "${items[@]}"; do
        item="${item#"${item%%[![:space:]]*}"}"
        item="${item%"${item##*[![:space:]]}"}"
        if [[ -z "${item}" || ! -f "${item}" ]]; then
            log "ERROR: ${option} file not found: ${item:-<empty>}"
            exit 1
        fi
        if [[ -L "${item}" ]]; then
            log "ERROR: ${option} must not be a symbolic link: ${item}"
            exit 1
        fi
    done
}

canonicalize_csv_files() {
    local value="$1" item resolved result="" separator=""
    [[ -n "${value}" ]] || { printf ''; return 0; }
    local items=()
    IFS=',' read -r -a items <<<"${value}"
    for item in "${items[@]}"; do
        item="${item#"${item%%[![:space:]]*}"}"
        item="${item%"${item##*[![:space:]]}"}"
        if [[ -f "${item}" ]]; then
            resolved="$(resolve_abs_path "${item}")"
        else
            resolved="${item}"
        fi
        result+="${separator}${resolved}"
        separator=","
    done
    printf '%s' "${result}"
}

require_private_file_mode() {
    local path="$1" option="$2" mode
    [[ -f "${path}" ]] || return 0
    if mode="$(stat -f '%Lp' "${path}" 2>/dev/null)"; then
        :
    else
        mode="$(stat -c '%a' "${path}")"
    fi
    if (( (8#${mode}) & 077 )); then
        log "ERROR: ${option} must not be readable or writable by group/others (use chmod 600): ${path}"
        exit 1
    fi
}

csv_count() {
    local value="$1" item count=0
    local items=()
    IFS=',' read -r -a items <<<"${value}"
    for item in "${items[@]}"; do
        [[ -n "${item//[[:space:]]/}" ]] && ((count += 1))
    done
    printf '%s' "${count}"
}

csv_has_duplicates() {
    local value="$1" item seen="|" canonical
    local items=()
    IFS=',' read -r -a items <<<"${value}"
    for item in "${items[@]}"; do
        item="${item#"${item%%[![:space:]]*}"}"
        item="${item%"${item##*[![:space:]]}"}"
        [[ -n "${item}" ]] || continue
        canonical="${item}"
        [[ ! -f "${item}" ]] || canonical="$(resolve_abs_path "${item}")"
        if [[ "${seen}" == *"|${canonical}|"* ]]; then
            return 0
        fi
        seen+="${canonical}|"
    done
    return 1
}

validate_pod_app_archives() {
    local value="$1" option="$2" item lower_item
    [[ -n "${value}" ]] || return 0
    local items=()
    IFS=',' read -r -a items <<<"${value}"
    for item in "${items[@]}"; do
        lower_item="$(printf '%s' "${item}" | tr '[:upper:]' '[:lower:]')"
        case "${lower_item}" in
            *.spl|*.tgz|*.tar.gz) ;;
            *)
                log "ERROR: ${option} supports .spl, .tgz, or .tar.gz app archives: ${item}"
                exit 1
                ;;
        esac
    done
}

validate_args() {
    command -v python3 >/dev/null || { log "ERROR: Python 3.9+ is required."; exit 1; }
    python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else "ERROR: Python 3.9+ is required.")'
    validate_choice "${TARGET}" sok pod
    validate_choice "${ARCHITECTURE}" s1 c3 m4
    validate_choice "${PHASE}" render preflight apply status all
    if [[ -n "${POD_PROFILE}" ]]; then
        validate_choice "${POD_PROFILE}" \
            pod-small pod-medium pod-large pod-xlarge \
            pod-small-es pod-medium-es pod-large-es pod-xlarge-es \
            pod-small-itsi pod-medium-itsi pod-large-itsi pod-xlarge-itsi
    fi
    validate_choice "${OPERATOR_SCOPE}" namespace cluster
    validate_choice "${DEPLOYMENT_PROFILE}" development production
    validate_choice "${QUEUE_PROVIDER}" sqs sqs_cp
    validate_choice "${SMARTSTORE_PROVIDER}" aws minio
    if [[ "${DRY_RUN}" != "true" && ( "${PHASE}" == "preflight" || "${PHASE}" == "apply" || "${PHASE}" == "status" ) ]]; then
        local original_option
        for original_option in "${ORIGINAL_ARGS[@]}"; do
            [[ "${original_option}" == --* ]] || continue
            case "${original_option}" in
                --target|--phase|--output-dir) ;;
                *)
                    log "ERROR: ${original_option} is a render-time option and is not accepted for an existing-bundle ${PHASE} phase. Rerender explicitly if configuration must change."
                    exit 1
                    ;;
            esac
        done
    fi
    if [[ "${TARGET}" == "pod" && ${#SOK_ONLY_OPTIONS[@]} -gt 0 ]]; then
        log "ERROR: SOK-only options are not valid with --target pod: ${SOK_ONLY_OPTIONS[*]}"
        exit 1
    fi
    if [[ "${TARGET}" == "sok" && ${#POD_ONLY_OPTIONS[@]} -gt 0 ]]; then
        log "ERROR: POD-only options are not valid with --target sok: ${POD_ONLY_OPTIONS[*]}"
        exit 1
    fi
    if [[ "${TARGET}" == "pod" && -z "${POD_PROFILE}" && ( "${PHASE}" == "render" || "${PHASE}" == "all" || "${DRY_RUN}" == "true" ) ]]; then
        log "ERROR: --pod-profile is required for Splunk POD."
        exit 1
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
        if [[ "${ARCHITECTURE}" == "m4" && "${INDEXER_REPLICAS}" -lt 2 ]]; then
            log "ERROR: --indexer-replicas must be at least 2 per SOK M4 site."
            exit 1
        fi
        if [[ ( "${ARCHITECTURE}" == "c3" || "${ARCHITECTURE}" == "m4" ) && "${SEARCH_HEAD_REPLICAS}" -lt 3 ]]; then
            log "ERROR: --search-head-replicas must be at least 3 for SOK C3/M4."
            exit 1
        fi
    fi

    if [[ "${TARGET}" == "sok" && "${LICENSE_FILE}" == *,* ]]; then
        log "ERROR: SOK --license-file accepts one file; POD accepts a CSV list."
        exit 1
    fi
    validate_csv_files "${LICENSE_FILE}" "--license-file"
    if csv_has_duplicates "${LICENSE_FILE}"; then
        log "ERROR: --license-file must contain unique license files."
        exit 1
    fi
    [[ -z "${LICENSE_FILE}" ]] || LICENSE_FILE="$(canonicalize_csv_files "${LICENSE_FILE}")"
    if [[ "${TARGET}" == "pod" && -n "${SSH_PRIVATE_KEY_FILE}" && "${SSH_PRIVATE_KEY_FILE}" != "/path/to/ssh-private-key" && ! -f "${SSH_PRIVATE_KEY_FILE}" ]]; then
        log "ERROR: SSH private key file not found: ${SSH_PRIVATE_KEY_FILE}"
        exit 1
    fi
    if [[ -f "${SSH_PRIVATE_KEY_FILE}" ]]; then
        require_private_file_mode "${SSH_PRIVATE_KEY_FILE}" "--ssh-private-key-file"
        SSH_PRIVATE_KEY_FILE="$(resolve_abs_path "${SSH_PRIVATE_KEY_FILE}")"
    fi
    if [[ -x "${INSTALLER_PATH}" ]]; then
        INSTALLER_PATH="$(resolve_abs_path "${INSTALLER_PATH}")"
    fi
    if [[ -n "${ENTERPRISE_VALUES_OVERLAY}" ]]; then
        validate_csv_files "${ENTERPRISE_VALUES_OVERLAY}" "--enterprise-values-overlay"
        ENTERPRISE_VALUES_OVERLAY="$(resolve_abs_path "${ENTERPRISE_VALUES_OVERLAY}")"
    fi
    if [[ -n "${OPERATOR_VALUES_OVERLAY}" ]]; then
        validate_csv_files "${OPERATOR_VALUES_OVERLAY}" "--operator-values-overlay"
        OPERATOR_VALUES_OVERLAY="$(resolve_abs_path "${OPERATOR_VALUES_OVERLAY}")"
    fi
    if [[ -n "${OPERATOR_CHART_ARCHIVE}" ]]; then
        validate_csv_files "${OPERATOR_CHART_ARCHIVE}" "--operator-chart-archive"
        OPERATOR_CHART_ARCHIVE="$(resolve_abs_path "${OPERATOR_CHART_ARCHIVE}")"
    fi
    if [[ -n "${ENTERPRISE_CHART_ARCHIVE}" ]]; then
        validate_csv_files "${ENTERPRISE_CHART_ARCHIVE}" "--enterprise-chart-archive"
        ENTERPRISE_CHART_ARCHIVE="$(resolve_abs_path "${ENTERPRISE_CHART_ARCHIVE}")"
    fi
    if [[ -n "${CRD_MANIFEST}" ]]; then
        validate_csv_files "${CRD_MANIFEST}" "--crd-manifest"
        CRD_MANIFEST="$(resolve_abs_path "${CRD_MANIFEST}")"
    fi
    if [[ -n "${INGRESS_CERTIFICATE_FILE}" || -n "${INGRESS_PRIVATE_KEY_FILE}" ]]; then
        if [[ -z "${INGRESS_CERTIFICATE_FILE}" || -z "${INGRESS_PRIVATE_KEY_FILE}" ]]; then
            log "ERROR: POD ingress certificate and private-key files must be supplied together."
            exit 1
        fi
        validate_csv_files "${INGRESS_CERTIFICATE_FILE}" "--ingress-certificate-file"
        validate_csv_files "${INGRESS_PRIVATE_KEY_FILE}" "--ingress-private-key-file"
        require_private_file_mode "${INGRESS_PRIVATE_KEY_FILE}" "--ingress-private-key-file"
        INGRESS_CERTIFICATE_FILE="$(resolve_abs_path "${INGRESS_CERTIFICATE_FILE}")"
        INGRESS_PRIVATE_KEY_FILE="$(resolve_abs_path "${INGRESS_PRIVATE_KEY_FILE}")"
    fi
    if [[ -n "${INGRESS_CA_FILE}" ]]; then
        validate_csv_files "${INGRESS_CA_FILE}" "--ingress-ca-file"
        INGRESS_CA_FILE="$(resolve_abs_path "${INGRESS_CA_FILE}")"
    fi
    if [[ -n "${ITSI_SOURCE_BUNDLE}" ]]; then
        validate_csv_files "${ITSI_SOURCE_BUNDLE}" "--itsi-source-bundle"
        validate_pod_app_archives "${ITSI_SOURCE_BUNDLE}" "--itsi-source-bundle"
        ITSI_SOURCE_BUNDLE="$(resolve_abs_path "${ITSI_SOURCE_BUNDLE}")"
    fi
    if pod_phase_needs_concrete_inputs; then
        if [[ "${ALLOW_UPGRADE}" != "true" && "${CONFIRM_NEW_POD_INSTALL}" != "true" ]]; then
            log "ERROR: POD live deployment requires --confirm-new-pod-install after proving the reviewed node list is unused."
            exit 1
        fi
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
        if [[ -z "${INSTALLER_PATH}" || "${INSTALLER_PATH}" == "/path/to/kubernetes-installer-standalone" || ! -f "${INSTALLER_PATH}" || -L "${INSTALLER_PATH}" || ! -x "${INSTALLER_PATH}" ]]; then
            log "ERROR: --installer-path must point to the executable POD installer for live workflows."
            exit 1
        fi
        if [[ ! "${INSTALLER_SHA256}" =~ ^[0-9a-fA-F]{64}$ ]]; then
            log "ERROR: POD live workflows require --installer-sha256 with an independently reviewed digest."
            exit 1
        fi
        INSTALLER_PATH="$(resolve_abs_path "${INSTALLER_PATH}")"
        if [[ -z "${PRIMARY_SEARCH_NAME}" ]]; then
            log "ERROR: --primary-search-name is required before POD preflight/apply because search-tier names are immutable."
            exit 1
        fi
        if [[ "${POD_PROFILE}" == *-es || "${POD_PROFILE}" == *-itsi ]] && [[ -z "${SECONDARY_SEARCH_NAME}" ]]; then
            log "ERROR: --secondary-search-name is required for POD ES/ITSI profiles."
            exit 1
        fi
        local app_option app_value
        while IFS='|' read -r app_option app_value; do
            if [[ -n "${app_value}" ]]; then
                validate_csv_files "${app_value}" "${app_option}"
                validate_pod_app_archives "${app_value}" "${app_option}"
            fi
        done <<EOF
--indexer-apps|${INDEXER_APPS}
--cluster-manager-apps|${CLUSTER_MANAGER_APPS}
--search-apps|${SEARCH_APPS}
--search-deployer-apps|${SEARCH_DEPLOYER_APPS}
--standalone-apps|${STANDALONE_APPS}
--premium-apps|${PREMIUM_APPS}
--itsi-apps|${ITSI_APPS}
--license-manager-apps|${LICENSE_MANAGER_APPS}
EOF
        if [[ "${POD_PROFILE}" == *-es ]]; then
            if [[ -z "${PREMIUM_APPS}" || -z "${INDEXER_APPS}" ]]; then
                log "ERROR: POD ES profiles require --premium-apps and --indexer-apps (including Splunk_TA_ForIndexers)."
                exit 1
            fi
        fi
        if [[ "${POD_PROFILE}" == *-itsi ]]; then
            if [[ -z "${ITSI_APPS}" || -z "${ITSI_SOURCE_BUNDLE}" || -z "${ITSI_SOURCE_SHA256}" || -z "${ITSI_JDK_SHA256}" || -z "${INDEXER_APPS}" || -z "${LICENSE_MANAGER_APPS}" || "$(csv_count "${LICENSE_FILE}")" -lt 2 ]]; then
                log "ERROR: POD ITSI profiles require --itsi-source-bundle, --itsi-source-sha256, --itsi-jdk-sha256, --itsi-apps, --indexer-apps, --license-manager-apps, and distinct Enterprise plus ITSI licenses."
                exit 1
            fi
        fi
        if [[ "${POD_PROFILE}" == *-es && "$(csv_count "${LICENSE_FILE}")" -lt 2 ]]; then
            log "ERROR: POD ES profiles require distinct Enterprise and ES license files."
            exit 1
        fi
    fi
    INDEXER_APPS="$(canonicalize_csv_files "${INDEXER_APPS}")"
    CLUSTER_MANAGER_APPS="$(canonicalize_csv_files "${CLUSTER_MANAGER_APPS}")"
    SEARCH_APPS="$(canonicalize_csv_files "${SEARCH_APPS}")"
    SEARCH_DEPLOYER_APPS="$(canonicalize_csv_files "${SEARCH_DEPLOYER_APPS}")"
    STANDALONE_APPS="$(canonicalize_csv_files "${STANDALONE_APPS}")"
    PREMIUM_APPS="$(canonicalize_csv_files "${PREMIUM_APPS}")"
    ITSI_APPS="$(canonicalize_csv_files "${ITSI_APPS}")"
    LICENSE_MANAGER_APPS="$(canonicalize_csv_files "${LICENSE_MANAGER_APPS}")"
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
        if [[ -L "${OUTPUT_DIR}" ]]; then
            log "ERROR: --output-dir must not be a symbolic link: ${OUTPUT_DIR}"
            exit 1
        fi
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
    if [[ -L "${OUTPUT_DIR}/${TARGET}" ]]; then
        log "ERROR: Render target must not be a symbolic link: ${OUTPUT_DIR}/${TARGET}"
        exit 1
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
        --operator-image "${OPERATOR_IMAGE}"
        --chart-version "${CHART_VERSION}"
        --operator-chart-archive "${OPERATOR_CHART_ARCHIVE}"
        --enterprise-chart-archive "${ENTERPRISE_CHART_ARCHIVE}"
        --crd-manifest "${CRD_MANIFEST}"
        --splunk-version "${SPLUNK_VERSION}"
        --storage-class "${STORAGE_CLASS}"
        --etc-storage "${ETC_STORAGE}"
        --var-storage "${VAR_STORAGE}"
        --standalone-replicas "${STANDALONE_REPLICAS}"
        --indexer-replicas "${INDEXER_REPLICAS}"
        --search-head-replicas "${SEARCH_HEAD_REPLICAS}"
        --site-count "${SITE_COUNT}"
        --site-zones "${SITE_ZONES}"
        --manager-site "${MANAGER_SITE}"
        --search-head-site "${SEARCH_HEAD_SITE}"
        --manager-zone "${MANAGER_ZONE}"
        --search-head-zone "${SEARCH_HEAD_ZONE}"
        --license-file "${LICENSE_FILE}"
        --smartstore-bucket "${SMARTSTORE_BUCKET}"
        --smartstore-prefix "${SMARTSTORE_PREFIX}"
        --smartstore-indexes "${SMARTSTORE_INDEXES}"
        --smartstore-provider "${SMARTSTORE_PROVIDER}"
        --smartstore-region "${SMARTSTORE_REGION}"
        --smartstore-endpoint "${SMARTSTORE_ENDPOINT}"
        --smartstore-secret-ref "${SMARTSTORE_SECRET_REF}"
        --aws-region "${AWS_REGION}"
        --controller-ips "${CONTROLLER_IPS}"
        --worker-ips "${WORKER_IPS}"
        --ssh-user "${SSH_USER}"
        --ssh-private-key-file "${SSH_PRIVATE_KEY_FILE}"
        --indexer-apps "${INDEXER_APPS}"
        --search-apps "${SEARCH_APPS}"
        --standalone-apps "${STANDALONE_APPS}"
        --premium-apps "${PREMIUM_APPS}"
        --kubernetes-version "${KUBERNETES_VERSION}"
        --expected-kube-context "${EXPECTED_KUBE_CONTEXT}"
        --expected-api-server "${EXPECTED_API_SERVER}"
        --expected-cluster-uid "${EXPECTED_CLUSTER_UID}"
        --operator-scope "${OPERATOR_SCOPE}"
        --watch-namespaces "${WATCH_NAMESPACES}"
        --deployment-profile "${DEPLOYMENT_PROFILE}"
        --enterprise-values-overlay "${ENTERPRISE_VALUES_OVERLAY}"
        --operator-values-overlay "${OPERATOR_VALUES_OVERLAY}"
        --ingestor-replicas "${INGESTOR_REPLICAS}"
        --ingestor-service-account "${INGESTOR_SERVICE_ACCOUNT}"
        --queue-provider "${QUEUE_PROVIDER}"
        --queue-name "${QUEUE_NAME}"
        --queue-dlq "${QUEUE_DLQ}"
        --queue-region "${QUEUE_REGION}"
        --queue-endpoint "${QUEUE_ENDPOINT}"
        --queue-secret-ref "${QUEUE_SECRET_REF}"
        --object-storage-path "${OBJECT_STORAGE_PATH}"
        --object-storage-endpoint "${OBJECT_STORAGE_ENDPOINT}"
        --existing-license-manager "${EXISTING_LICENSE_MANAGER}"
        --existing-license-manager-namespace "${EXISTING_LICENSE_MANAGER_NAMESPACE}"
        --splunk-service-account "${SPLUNK_SERVICE_ACCOUNT}"
        --splunk-irsa-role-arn "${SPLUNK_IRSA_ROLE_ARN}"
        --splunk-irsa-token-expiration "${SPLUNK_IRSA_TOKEN_EXPIRATION}"
        --pod-version "${POD_VERSION}"
        --installer-path "${INSTALLER_PATH}"
        --installer-sha256 "${INSTALLER_SHA256}"
        --primary-search-name "${PRIMARY_SEARCH_NAME}"
        --secondary-search-name "${SECONDARY_SEARCH_NAME}"
        --cluster-manager-apps "${CLUSTER_MANAGER_APPS}"
        --search-deployer-apps "${SEARCH_DEPLOYER_APPS}"
        --license-manager-apps "${LICENSE_MANAGER_APPS}"
        --itsi-apps "${ITSI_APPS}"
        --itsi-source-bundle "${ITSI_SOURCE_BUNDLE}"
        --itsi-source-sha256 "${ITSI_SOURCE_SHA256}"
        --itsi-jdk-sha256 "${ITSI_JDK_SHA256}"
        --ingress-certificate-file "${INGRESS_CERTIFICATE_FILE}"
        --ingress-private-key-file "${INGRESS_PRIVATE_KEY_FILE}"
        --ingress-domain "${INGRESS_DOMAIN}"
        --ingress-ca-file "${INGRESS_CA_FILE}"
    )
    if [[ -n "${POD_PROFILE}" ]]; then
        RENDER_ARGS+=(--pod-profile "${POD_PROFILE}")
    fi
    if [[ -n "${SPLUNK_IMAGE}" ]]; then
        RENDER_ARGS+=(--splunk-image "${SPLUNK_IMAGE}")
    fi
    if [[ -n "${EKS_CLUSTER_NAME}" ]]; then
        RENDER_ARGS+=(--eks-cluster-name "${EKS_CLUSTER_NAME}")
    fi
    if [[ "${ACCEPT_SPLUNK_GENERAL_TERMS}" == "true" ]]; then
        RENDER_ARGS+=(--accept-splunk-general-terms)
    fi
    if [[ "${ALLOW_UNVERIFIED_VERSIONS}" == "true" ]]; then
        RENDER_ARGS+=(--allow-unverified-versions)
    fi
    if [[ "${ALLOW_UPGRADE}" == "true" ]]; then
        RENDER_ARGS+=(--allow-upgrade)
    fi
    if [[ "${CONFIRM_SPLUNK_10_4_UPGRADE_READINESS}" == "true" ]]; then
        RENDER_ARGS+=(--confirm-splunk-10-4-upgrade-readiness)
    fi
    if [[ "${CONFIRM_NEW_POD_INSTALL}" == "true" ]]; then
        RENDER_ARGS+=(--confirm-new-pod-install)
    fi
    if [[ "${CONFIRM_SMARTSTORE_INDEX_INVENTORY}" == "true" ]]; then
        RENDER_ARGS+=(--confirm-smartstore-index-inventory)
    fi
    if [[ "${CONFIRM_SMARTSTORE_PATH_OWNERSHIP}" == "true" ]]; then
        RENDER_ARGS+=(--confirm-smartstore-path-ownership)
    fi
    if [[ "${INDEXING_INGESTION_SEPARATION}" == "true" ]]; then
        RENDER_ARGS+=(--indexing-ingestion-separation)
    fi
    if [[ "${DISABLE_MONITORING_CONSOLE}" == "true" ]]; then
        RENDER_ARGS+=(--disable-monitoring-console)
    fi
}

render_assets() {
    local extra_args=()
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        extra_args+=(--json)
    fi
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
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

run_strict_validation() {
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: ${SCRIPT_DIR}/validate.sh --target ${TARGET} --output-dir ${OUTPUT_DIR} --strict"
        return 0
    fi
    bash "${SCRIPT_DIR}/validate.sh" \
        --target "${TARGET}" \
        --output-dir "${OUTPUT_DIR}" \
        --strict
}

run_apply() {
    local preflight_already="${1:-false}"
    local validation_already="${2:-false}"
    local dir
    dir="$(render_dir)"
    if [[ "${validation_already}" != "true" ]]; then
        run_strict_validation
    fi
    if [[ "${TARGET}" == "sok" ]]; then
        run_rendered_script "apply.sh"
        return 0
    fi
    if [[ "${preflight_already}" != "true" ]]; then
        run_preflight
    fi
    run_rendered_script "deploy.sh"
}

run_status() {
    if [[ "${TARGET}" == "pod" ]]; then
        run_rendered_script "wait-ready.sh"
        return 0
    fi
    run_rendered_script "status.sh"
}

require_rendered_bundle() {
    [[ "${DRY_RUN}" == "true" ]] && return 0
    local dir
    dir="$(render_dir)"
    if [[ ! -d "${dir}" ]]; then
        log "ERROR: No reviewed ${TARGET} bundle exists under ${dir}. Run --phase render first."
        exit 1
    fi
    if ! python3 "${SCRIPT_DIR}/bundle_verify.py" verify "${dir}" "${TARGET}"; then
        log "ERROR: Rendered bundle integrity verification failed. Rerender from reviewed inputs/overlays."
        exit 1
    fi
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
            require_rendered_bundle
            run_strict_validation
            run_preflight
            ;;
        apply)
            require_rendered_bundle
            run_apply
            ;;
        status)
            require_rendered_bundle
            run_status
            ;;
        all)
            render_assets
            run_strict_validation
            run_preflight
            run_apply true true
            run_status
            ;;
    esac
}

main "$@"
