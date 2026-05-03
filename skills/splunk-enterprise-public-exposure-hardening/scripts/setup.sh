#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-public-exposure-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
ACCEPT_PUBLIC_EXPOSURE=false
OUTPUT_DIR=""
TOPOLOGY="single-search-head"
PUBLIC_FQDN=""
HEC_FQDN=""
PROXY_CIDR=""
INDEXER_CLUSTER_CIDR=""
BASTION_CIDR=""
ENABLE_WEB="true"
ENABLE_HEC="false"
ENABLE_S2S="false"
HEC_MTLS="false"
S2S_MTLS="true"
FORWARDER_MTLS="true"
SPLUNK_HOME_VALUE="/opt/splunk"
SERVICE_USER="splunk"
SPLUNK_VERSION="10.2.2"
TLS_POLICY="tls12"
ENABLE_TLS13="false"
CA_BUNDLE_PATH="/opt/splunk/etc/auth/cabundle.pem"
SERVER_CERT_PATH="/opt/splunk/etc/auth/splunkweb/cert.pem"
SERVER_KEY_PATH="/opt/splunk/etc/auth/splunkweb/privkey.pem"
REQUIRED_SANS=""
AUTH_MODE="native"
SAML_IDP_METADATA_PATH=""
SAML_ENTITY_ID=""
SAML_SIGNATURE_ALGORITHM="RSA-SHA256"
PROXY_SSO_TRUSTED_IP=""
MIN_PASSWORD_LENGTH="14"
EXPIRE_PASSWORD_DAYS="90"
LOCKOUT_ATTEMPTS="5"
LOCKOUT_MINS="30"
PASSWORD_HISTORY_COUNT="24"
PUBLIC_READER_ALLOWED_INDEXES="main,summary"
PUBLIC_READER_SRCH_JOBS_QUOTA="3"
PUBLIC_READER_SRCH_MAX_TIME="300"
PUBLIC_READER_SRCH_TIME_WIN="86400"
PUBLIC_READER_SRCH_DISK_QUOTA="100"
HEC_MAX_CONTENT_LENGTH="838860800"
LOGIN_RATE_PER_MINUTE="5"
STREAMING_SEARCH_TIMEOUT="600"
ADMIN_PASSWORD_FILE=""
PASS4SYMMKEY_FILE=""
SSL_KEY_PASSWORD_FILE=""
SAML_SIGNING_CERT_FILE=""
SAML_SIGNING_KEY_FILE=""
HEC_MTLS_CA_BUNDLE_FILE=""
EXTERNAL_PROBE_CMD=""
SVD_FLOOR_FILE=""
ENABLE_FIPS="false"
FIPS_VERSION="140-3"
ALLOWED_UNARCHIVE_COMMANDS=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Public Internet Exposure Hardening

Usage: $(basename "$0") [OPTIONS]

Phases:
  --phase render|preflight|apply|validate|all   (default: render)
  --accept-public-exposure                       Required for apply / all

Topology:
  --topology single-search-head|shc-with-hec|shc-with-hec-and-hf
  --public-fqdn FQDN                             (required)
  --hec-fqdn FQDN                                (default: --public-fqdn)
  --proxy-cidr CIDR[,CIDR...]                    (required)
  --indexer-cluster-cidr CIDR                    (recommended for clustered)
  --bastion-cidr CIDR                            (admin allowlist)

Surface enables:
  --enable-web true|false       (default: true)
  --enable-hec true|false       (default: false)
  --enable-s2s true|false       (default: false)
  --hec-mtls true|false         (default: false)
  --s2s-mtls true|false         (default: true)
  --forwarder-mtls true|false   (default: true)

Splunk runtime:
  --splunk-home PATH            (default: /opt/splunk)
  --service-user NAME           (default: splunk)
  --splunk-version X.Y.Z        (default: 10.2.2; SVD floor enforced)

Crypto:
  --tls-policy tls12|tls12_13   (default: tls12)
  --enable-tls13 true|false     (default: false)
  --ca-bundle-path PATH
  --server-cert-path PATH
  --server-key-path PATH
  --required-sans CSV

Auth:
  --auth-mode native|saml|reverse-proxy-sso       (default: native)
  --saml-idp-metadata-path PATH
  --saml-entity-id URL
  --saml-signature-algorithm ALG                  (default: RSA-SHA256)
  --proxy-sso-trusted-ip IP

Policy:
  --min-password-length N                         (default: 14)
  --expire-password-days N                        (default: 90)
  --lockout-attempts N                            (default: 5)
  --lockout-mins N                                (default: 30)
  --password-history-count N                      (default: 24)
  --public-reader-allowed-indexes CSV             (default: main,summary)
  --public-reader-srch-jobs-quota N               (default: 3)
  --public-reader-srch-max-time N                 (default: 300)
  --public-reader-srch-time-win N                 (default: 86400)
  --public-reader-srch-disk-quota N               (default: 100)

Sizing:
  --hec-max-content-length BYTES                  (default: 838860800)
  --login-rate-per-minute N                       (default: 5)
  --streaming-search-timeout SECONDS              (default: 600)

Secrets (file paths only — never values on argv):
  --admin-password-file PATH
  --pass4symmkey-file PATH
  --ssl-key-password-file PATH
  --saml-signing-cert-file PATH
  --saml-signing-key-file PATH
  --hec-mtls-ca-bundle-file PATH

Validation:
  --external-probe-cmd "ssh probe@bastion nc -zv"

FIPS / unarchive (defense in depth):
  --enable-fips true|false                        (default: false)
  --fips-version 140-2|140-3                      (default: 140-3)
  --allowed-unarchive-commands CSV                (SVD-2026-0302 allowlist)

Render output:
  --output-dir PATH                               (default: <project>/${DEFAULT_RENDER_DIR_NAME})
  --svd-floor-file PATH                           (override embedded floor)
  --dry-run
  --json

Examples:
  $(basename "$0") --phase render --topology single-search-head \\
      --public-fqdn splunk.example.com --proxy-cidr 10.0.10.0/24
  $(basename "$0") --phase preflight --public-fqdn splunk.example.com \\
      --proxy-cidr 10.0.10.0/24 \\
      --external-probe-cmd "ssh probe@bastion.example.com nc -zv"
  $(basename "$0") --phase apply --public-fqdn splunk.example.com \\
      --proxy-cidr 10.0.10.0/24 --accept-public-exposure \\
      --pass4symmkey-file /tmp/splunk_pass4symmkey

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --accept-public-exposure) ACCEPT_PUBLIC_EXPOSURE=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --topology) require_arg "$1" $# || exit 1; TOPOLOGY="$2"; shift 2 ;;
        --public-fqdn) require_arg "$1" $# || exit 1; PUBLIC_FQDN="$2"; shift 2 ;;
        --hec-fqdn) require_arg "$1" $# || exit 1; HEC_FQDN="$2"; shift 2 ;;
        --proxy-cidr) require_arg "$1" $# || exit 1; PROXY_CIDR="$2"; shift 2 ;;
        --indexer-cluster-cidr) require_arg "$1" $# || exit 1; INDEXER_CLUSTER_CIDR="$2"; shift 2 ;;
        --bastion-cidr) require_arg "$1" $# || exit 1; BASTION_CIDR="$2"; shift 2 ;;
        --enable-web) require_arg "$1" $# || exit 1; ENABLE_WEB="$2"; shift 2 ;;
        --enable-hec) require_arg "$1" $# || exit 1; ENABLE_HEC="$2"; shift 2 ;;
        --enable-s2s) require_arg "$1" $# || exit 1; ENABLE_S2S="$2"; shift 2 ;;
        --hec-mtls) require_arg "$1" $# || exit 1; HEC_MTLS="$2"; shift 2 ;;
        --s2s-mtls) require_arg "$1" $# || exit 1; S2S_MTLS="$2"; shift 2 ;;
        --forwarder-mtls) require_arg "$1" $# || exit 1; FORWARDER_MTLS="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --service-user) require_arg "$1" $# || exit 1; SERVICE_USER="$2"; shift 2 ;;
        --splunk-version) require_arg "$1" $# || exit 1; SPLUNK_VERSION="$2"; shift 2 ;;
        --tls-policy) require_arg "$1" $# || exit 1; TLS_POLICY="$2"; shift 2 ;;
        --enable-tls13) require_arg "$1" $# || exit 1; ENABLE_TLS13="$2"; shift 2 ;;
        --ca-bundle-path) require_arg "$1" $# || exit 1; CA_BUNDLE_PATH="$2"; shift 2 ;;
        --server-cert-path) require_arg "$1" $# || exit 1; SERVER_CERT_PATH="$2"; shift 2 ;;
        --server-key-path) require_arg "$1" $# || exit 1; SERVER_KEY_PATH="$2"; shift 2 ;;
        --required-sans) require_arg "$1" $# || exit 1; REQUIRED_SANS="$2"; shift 2 ;;
        --auth-mode) require_arg "$1" $# || exit 1; AUTH_MODE="$2"; shift 2 ;;
        --saml-idp-metadata-path) require_arg "$1" $# || exit 1; SAML_IDP_METADATA_PATH="$2"; shift 2 ;;
        --saml-entity-id) require_arg "$1" $# || exit 1; SAML_ENTITY_ID="$2"; shift 2 ;;
        --saml-signature-algorithm) require_arg "$1" $# || exit 1; SAML_SIGNATURE_ALGORITHM="$2"; shift 2 ;;
        --proxy-sso-trusted-ip) require_arg "$1" $# || exit 1; PROXY_SSO_TRUSTED_IP="$2"; shift 2 ;;
        --min-password-length) require_arg "$1" $# || exit 1; MIN_PASSWORD_LENGTH="$2"; shift 2 ;;
        --expire-password-days) require_arg "$1" $# || exit 1; EXPIRE_PASSWORD_DAYS="$2"; shift 2 ;;
        --lockout-attempts) require_arg "$1" $# || exit 1; LOCKOUT_ATTEMPTS="$2"; shift 2 ;;
        --lockout-mins) require_arg "$1" $# || exit 1; LOCKOUT_MINS="$2"; shift 2 ;;
        --password-history-count) require_arg "$1" $# || exit 1; PASSWORD_HISTORY_COUNT="$2"; shift 2 ;;
        --public-reader-allowed-indexes) require_arg "$1" $# || exit 1; PUBLIC_READER_ALLOWED_INDEXES="$2"; shift 2 ;;
        --public-reader-srch-jobs-quota) require_arg "$1" $# || exit 1; PUBLIC_READER_SRCH_JOBS_QUOTA="$2"; shift 2 ;;
        --public-reader-srch-max-time) require_arg "$1" $# || exit 1; PUBLIC_READER_SRCH_MAX_TIME="$2"; shift 2 ;;
        --public-reader-srch-time-win) require_arg "$1" $# || exit 1; PUBLIC_READER_SRCH_TIME_WIN="$2"; shift 2 ;;
        --public-reader-srch-disk-quota) require_arg "$1" $# || exit 1; PUBLIC_READER_SRCH_DISK_QUOTA="$2"; shift 2 ;;
        --hec-max-content-length) require_arg "$1" $# || exit 1; HEC_MAX_CONTENT_LENGTH="$2"; shift 2 ;;
        --login-rate-per-minute) require_arg "$1" $# || exit 1; LOGIN_RATE_PER_MINUTE="$2"; shift 2 ;;
        --streaming-search-timeout) require_arg "$1" $# || exit 1; STREAMING_SEARCH_TIMEOUT="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --pass4symmkey-file) require_arg "$1" $# || exit 1; PASS4SYMMKEY_FILE="$2"; shift 2 ;;
        --ssl-key-password-file) require_arg "$1" $# || exit 1; SSL_KEY_PASSWORD_FILE="$2"; shift 2 ;;
        --saml-signing-cert-file) require_arg "$1" $# || exit 1; SAML_SIGNING_CERT_FILE="$2"; shift 2 ;;
        --saml-signing-key-file) require_arg "$1" $# || exit 1; SAML_SIGNING_KEY_FILE="$2"; shift 2 ;;
        --hec-mtls-ca-bundle-file) require_arg "$1" $# || exit 1; HEC_MTLS_CA_BUNDLE_FILE="$2"; shift 2 ;;
        --external-probe-cmd) require_arg "$1" $# || exit 1; EXTERNAL_PROBE_CMD="$2"; shift 2 ;;
        --svd-floor-file) require_arg "$1" $# || exit 1; SVD_FLOOR_FILE="$2"; shift 2 ;;
        --enable-fips) require_arg "$1" $# || exit 1; ENABLE_FIPS="$2"; shift 2 ;;
        --fips-version) require_arg "$1" $# || exit 1; FIPS_VERSION="$2"; shift 2 ;;
        --allowed-unarchive-commands) require_arg "$1" $# || exit 1; ALLOWED_UNARCHIVE_COMMANDS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
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

validate_args() {
    validate_choice "${PHASE}" render preflight apply validate all
    validate_choice "${TOPOLOGY}" single-search-head shc-with-hec shc-with-hec-and-hf
    validate_choice "${ENABLE_WEB}" true false
    validate_choice "${ENABLE_HEC}" true false
    validate_choice "${ENABLE_S2S}" true false
    validate_choice "${HEC_MTLS}" true false
    validate_choice "${S2S_MTLS}" true false
    validate_choice "${FORWARDER_MTLS}" true false
    validate_choice "${TLS_POLICY}" tls12 tls12_13
    validate_choice "${ENABLE_TLS13}" true false
    validate_choice "${AUTH_MODE}" native saml reverse-proxy-sso
    validate_choice "${ENABLE_FIPS}" true false
    validate_choice "${FIPS_VERSION}" 140-2 140-3

    if [[ -z "${PUBLIC_FQDN}" ]]; then
        log "ERROR: --public-fqdn is required"
        exit 1
    fi
    if [[ -z "${PROXY_CIDR}" ]]; then
        log "ERROR: --proxy-cidr is required"
        exit 1
    fi
    if [[ "${PHASE}" == "apply" || "${PHASE}" == "all" ]]; then
        if [[ "${ACCEPT_PUBLIC_EXPOSURE}" != "true" ]]; then
            log "ERROR: --accept-public-exposure is required for --phase=${PHASE}."
            log "       This skill binds Splunk to a public-facing FQDN. Acknowledge the change explicitly."
            exit 1
        fi
    fi
    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

build_renderer_args() {
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --topology "${TOPOLOGY}"
        --public-fqdn "${PUBLIC_FQDN}"
        --hec-fqdn "${HEC_FQDN}"
        --proxy-cidr "${PROXY_CIDR}"
        --indexer-cluster-cidr "${INDEXER_CLUSTER_CIDR}"
        --bastion-cidr "${BASTION_CIDR}"
        --enable-web "${ENABLE_WEB}"
        --enable-hec "${ENABLE_HEC}"
        --enable-s2s "${ENABLE_S2S}"
        --hec-mtls "${HEC_MTLS}"
        --s2s-mtls "${S2S_MTLS}"
        --forwarder-mtls "${FORWARDER_MTLS}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --service-user "${SERVICE_USER}"
        --splunk-version "${SPLUNK_VERSION}"
        --tls-policy "${TLS_POLICY}"
        --enable-tls13 "${ENABLE_TLS13}"
        --ca-bundle-path "${CA_BUNDLE_PATH}"
        --server-cert-path "${SERVER_CERT_PATH}"
        --server-key-path "${SERVER_KEY_PATH}"
        --required-sans "${REQUIRED_SANS}"
        --auth-mode "${AUTH_MODE}"
        --saml-idp-metadata-path "${SAML_IDP_METADATA_PATH}"
        --saml-entity-id "${SAML_ENTITY_ID}"
        --saml-signature-algorithm "${SAML_SIGNATURE_ALGORITHM}"
        --proxy-sso-trusted-ip "${PROXY_SSO_TRUSTED_IP}"
        --min-password-length "${MIN_PASSWORD_LENGTH}"
        --expire-password-days "${EXPIRE_PASSWORD_DAYS}"
        --lockout-attempts "${LOCKOUT_ATTEMPTS}"
        --lockout-mins "${LOCKOUT_MINS}"
        --password-history-count "${PASSWORD_HISTORY_COUNT}"
        --public-reader-allowed-indexes "${PUBLIC_READER_ALLOWED_INDEXES}"
        --public-reader-srch-jobs-quota "${PUBLIC_READER_SRCH_JOBS_QUOTA}"
        --public-reader-srch-max-time "${PUBLIC_READER_SRCH_MAX_TIME}"
        --public-reader-srch-time-win "${PUBLIC_READER_SRCH_TIME_WIN}"
        --public-reader-srch-disk-quota "${PUBLIC_READER_SRCH_DISK_QUOTA}"
        --hec-max-content-length "${HEC_MAX_CONTENT_LENGTH}"
        --login-rate-per-minute "${LOGIN_RATE_PER_MINUTE}"
        --streaming-search-timeout "${STREAMING_SEARCH_TIMEOUT}"
        --admin-password-file "${ADMIN_PASSWORD_FILE}"
        --pass4symmkey-file "${PASS4SYMMKEY_FILE}"
        --ssl-key-password-file "${SSL_KEY_PASSWORD_FILE}"
        --saml-signing-cert-file "${SAML_SIGNING_CERT_FILE}"
        --saml-signing-key-file "${SAML_SIGNING_KEY_FILE}"
        --hec-mtls-ca-bundle-file "${HEC_MTLS_CA_BUNDLE_FILE}"
        --external-probe-cmd "${EXTERNAL_PROBE_CMD}"
        --enable-fips "${ENABLE_FIPS}"
        --fips-version "${FIPS_VERSION}"
        --allowed-unarchive-commands "${ALLOWED_UNARCHIVE_COMMANDS}"
    )
    if [[ "${ACCEPT_PUBLIC_EXPOSURE}" == "true" ]]; then
        RENDER_ARGS+=(--accept-public-exposure)
    fi
    if [[ -n "${SVD_FLOOR_FILE}" ]]; then
        RENDER_ARGS+=(--svd-floor-file "${SVD_FLOOR_FILE}")
    fi
}

render_dir() {
    printf '%s/public-exposure' "${OUTPUT_DIR}"
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered_script() {
    local script_path="$1" dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${script_path})"
        return 0
    fi
    if [[ ! -x "${dir}/${script_path}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${script_path}"
        exit 1
    fi
    (cd "${dir}" && "./${script_path}")
}

main() {
    validate_args
    build_renderer_args
    if [[ "${DRY_RUN}" == "true" ]]; then
        if [[ "${JSON_OUTPUT}" == "true" ]]; then
            exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
        fi
        python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
        exit 0
    fi
    case "${PHASE}" in
        render)
            render_assets
            ;;
        preflight)
            render_assets
            run_rendered_script preflight.sh
            ;;
        apply)
            render_assets
            run_rendered_script "splunk/apply-search-head.sh"
            ;;
        validate)
            render_assets
            run_rendered_script validate.sh
            ;;
        all)
            render_assets
            run_rendered_script preflight.sh
            run_rendered_script "splunk/apply-search-head.sh"
            run_rendered_script validate.sh
            ;;
    esac
}

main "$@"
