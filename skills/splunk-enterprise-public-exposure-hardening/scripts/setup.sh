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

# LDAP defaults (only used when --auth-mode=ldap).
LDAP_STRATEGY_NAME="ldaphost"
LDAP_HOST=""
LDAP_PORT="0"
LDAP_SSL_ENABLED="true"
LDAP_BIND_DN=""
LDAP_BIND_PASSWORD_FILE=""
LDAP_USER_BASE_DN=""
LDAP_USER_BASE_FILTER=""
LDAP_USER_NAME_ATTRIBUTE="sAMAccountName"
LDAP_REAL_NAME_ATTRIBUTE="cn"
LDAP_EMAIL_ATTRIBUTE="mail"
LDAP_GROUP_BASE_DN=""
LDAP_GROUP_BASE_FILTER=""
LDAP_GROUP_NAME_ATTRIBUTE="cn"
LDAP_GROUP_MEMBER_ATTRIBUTE="member"
LDAP_GROUP_MAPPING_ATTRIBUTE="dn"
LDAP_NESTED_GROUPS="true"
LDAP_ANONYMOUS_REFERRALS="0"
LDAP_ENABLE_RANGE_RETRIEVAL="false"
LDAP_SIZELIMIT="1000"
LDAP_PAGELIMIT="-1"
LDAP_TIME_LIMIT="15"
LDAP_NETWORK_TIMEOUT="20"
LDAP_CHARSET=""
LDAP_PUBLIC_READER_GROUP=""
ALLOW_CLEARTEXT_LDAP="false"
ALLOW_ANONYMOUS_LDAP_BIND="false"
ALLOW_SCRIPTED_AUTH="false"
FEDERATION_SERVICE_ACCOUNT_PASSWORD_FILE=""

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
  --auth-mode native|saml|reverse-proxy-sso|ldap  (default: native)
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

LDAP (only used when --auth-mode=ldap):
  --ldap-strategy-name NAME                       (default: ldaphost)
  --ldap-host HOSTNAME                            (required for ldap mode)
  --ldap-port PORT                                (0=auto: 636 SSL on, 389 off)
  --ldap-ssl-enabled true|false                   (default: true)
  --ldap-bind-dn DN                               (empty=anon bind, requires ack)
  --ldap-bind-password-file PATH                  (file path, never argv)
  --ldap-user-base-dn DN[;DN...]                  (semicolon for multi-tree)
  --ldap-user-base-filter LDAP_FILTER
  --ldap-user-name-attribute NAME                 (default: sAMAccountName)
  --ldap-real-name-attribute NAME                 (default: cn)
  --ldap-email-attribute NAME                     (default: mail)
  --ldap-group-base-dn DN[;DN...]                 (semicolon for multi-tree)
  --ldap-group-base-filter LDAP_FILTER
  --ldap-group-name-attribute NAME                (default: cn)
  --ldap-group-member-attribute NAME              (default: member)
  --ldap-group-mapping-attribute NAME             (default: dn)
  --ldap-nested-groups true|false                 (default: true)
  --ldap-anonymous-referrals 0|1                  (default: 0; spec default 1)
  --ldap-enable-range-retrieval true|false        (default: false)
  --ldap-sizelimit N                              (default: 1000; lowercase!)
  --ldap-pagelimit N                              (default: -1)
  --ldap-time-limit SECONDS                       (default: 15; spec hard cap 30)
  --ldap-network-timeout SECONDS                  (default: 20; must > time-limit)
  --ldap-charset CHARSET                          (default: empty / UTF-8)
  --ldap-public-reader-group GROUP_NAME           (LDAP group -> role_public_reader)
  --allow-cleartext-ldap                          (ack; required for SSL=false)
  --allow-anonymous-ldap-bind                     (ack; required for empty bind-dn)

Auth refusal:
  --allow-scripted-auth                           (ack required if authType=Scripted)

Federation:
  --federation-service-account-password-file PATH (file path; rotate helper)

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
        --ldap-strategy-name) require_arg "$1" $# || exit 1; LDAP_STRATEGY_NAME="$2"; shift 2 ;;
        --ldap-host) require_arg "$1" $# || exit 1; LDAP_HOST="$2"; shift 2 ;;
        --ldap-port) require_arg "$1" $# || exit 1; LDAP_PORT="$2"; shift 2 ;;
        --ldap-ssl-enabled) require_arg "$1" $# || exit 1; LDAP_SSL_ENABLED="$2"; shift 2 ;;
        --ldap-bind-dn) require_arg "$1" $# || exit 1; LDAP_BIND_DN="$2"; shift 2 ;;
        --ldap-bind-password-file) require_arg "$1" $# || exit 1; LDAP_BIND_PASSWORD_FILE="$2"; shift 2 ;;
        --ldap-user-base-dn) require_arg "$1" $# || exit 1; LDAP_USER_BASE_DN="$2"; shift 2 ;;
        --ldap-user-base-filter) require_arg "$1" $# || exit 1; LDAP_USER_BASE_FILTER="$2"; shift 2 ;;
        --ldap-user-name-attribute) require_arg "$1" $# || exit 1; LDAP_USER_NAME_ATTRIBUTE="$2"; shift 2 ;;
        --ldap-real-name-attribute) require_arg "$1" $# || exit 1; LDAP_REAL_NAME_ATTRIBUTE="$2"; shift 2 ;;
        --ldap-email-attribute) require_arg "$1" $# || exit 1; LDAP_EMAIL_ATTRIBUTE="$2"; shift 2 ;;
        --ldap-group-base-dn) require_arg "$1" $# || exit 1; LDAP_GROUP_BASE_DN="$2"; shift 2 ;;
        --ldap-group-base-filter) require_arg "$1" $# || exit 1; LDAP_GROUP_BASE_FILTER="$2"; shift 2 ;;
        --ldap-group-name-attribute) require_arg "$1" $# || exit 1; LDAP_GROUP_NAME_ATTRIBUTE="$2"; shift 2 ;;
        --ldap-group-member-attribute) require_arg "$1" $# || exit 1; LDAP_GROUP_MEMBER_ATTRIBUTE="$2"; shift 2 ;;
        --ldap-group-mapping-attribute) require_arg "$1" $# || exit 1; LDAP_GROUP_MAPPING_ATTRIBUTE="$2"; shift 2 ;;
        --ldap-nested-groups) require_arg "$1" $# || exit 1; LDAP_NESTED_GROUPS="$2"; shift 2 ;;
        --ldap-anonymous-referrals) require_arg "$1" $# || exit 1; LDAP_ANONYMOUS_REFERRALS="$2"; shift 2 ;;
        --ldap-enable-range-retrieval) require_arg "$1" $# || exit 1; LDAP_ENABLE_RANGE_RETRIEVAL="$2"; shift 2 ;;
        --ldap-sizelimit) require_arg "$1" $# || exit 1; LDAP_SIZELIMIT="$2"; shift 2 ;;
        --ldap-pagelimit) require_arg "$1" $# || exit 1; LDAP_PAGELIMIT="$2"; shift 2 ;;
        --ldap-time-limit) require_arg "$1" $# || exit 1; LDAP_TIME_LIMIT="$2"; shift 2 ;;
        --ldap-network-timeout) require_arg "$1" $# || exit 1; LDAP_NETWORK_TIMEOUT="$2"; shift 2 ;;
        --ldap-charset) require_arg "$1" $# || exit 1; LDAP_CHARSET="$2"; shift 2 ;;
        --ldap-public-reader-group) require_arg "$1" $# || exit 1; LDAP_PUBLIC_READER_GROUP="$2"; shift 2 ;;
        --allow-cleartext-ldap) ALLOW_CLEARTEXT_LDAP="true"; shift ;;
        --allow-anonymous-ldap-bind) ALLOW_ANONYMOUS_LDAP_BIND="true"; shift ;;
        --allow-scripted-auth) ALLOW_SCRIPTED_AUTH="true"; shift ;;
        --federation-service-account-password-file) require_arg "$1" $# || exit 1; FEDERATION_SERVICE_ACCOUNT_PASSWORD_FILE="$2"; shift 2 ;;
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
    validate_choice "${AUTH_MODE}" native saml reverse-proxy-sso ldap
    validate_choice "${ENABLE_FIPS}" true false
    validate_choice "${FIPS_VERSION}" 140-2 140-3
    validate_choice "${LDAP_SSL_ENABLED}" true false
    validate_choice "${LDAP_NESTED_GROUPS}" true false
    validate_choice "${LDAP_ANONYMOUS_REFERRALS}" 0 1
    validate_choice "${LDAP_ENABLE_RANGE_RETRIEVAL}" true false

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
        --ldap-strategy-name "${LDAP_STRATEGY_NAME}"
        --ldap-host "${LDAP_HOST}"
        --ldap-port "${LDAP_PORT}"
        --ldap-ssl-enabled "${LDAP_SSL_ENABLED}"
        --ldap-bind-dn "${LDAP_BIND_DN}"
        --ldap-bind-password-file "${LDAP_BIND_PASSWORD_FILE}"
        --ldap-user-base-dn "${LDAP_USER_BASE_DN}"
        --ldap-user-base-filter "${LDAP_USER_BASE_FILTER}"
        --ldap-user-name-attribute "${LDAP_USER_NAME_ATTRIBUTE}"
        --ldap-real-name-attribute "${LDAP_REAL_NAME_ATTRIBUTE}"
        --ldap-email-attribute "${LDAP_EMAIL_ATTRIBUTE}"
        --ldap-group-base-dn "${LDAP_GROUP_BASE_DN}"
        --ldap-group-base-filter "${LDAP_GROUP_BASE_FILTER}"
        --ldap-group-name-attribute "${LDAP_GROUP_NAME_ATTRIBUTE}"
        --ldap-group-member-attribute "${LDAP_GROUP_MEMBER_ATTRIBUTE}"
        --ldap-group-mapping-attribute "${LDAP_GROUP_MAPPING_ATTRIBUTE}"
        --ldap-nested-groups "${LDAP_NESTED_GROUPS}"
        --ldap-anonymous-referrals "${LDAP_ANONYMOUS_REFERRALS}"
        --ldap-enable-range-retrieval "${LDAP_ENABLE_RANGE_RETRIEVAL}"
        --ldap-sizelimit "${LDAP_SIZELIMIT}"
        --ldap-pagelimit "${LDAP_PAGELIMIT}"
        --ldap-time-limit "${LDAP_TIME_LIMIT}"
        --ldap-network-timeout "${LDAP_NETWORK_TIMEOUT}"
        --ldap-charset "${LDAP_CHARSET}"
        --ldap-public-reader-group "${LDAP_PUBLIC_READER_GROUP}"
        --federation-service-account-password-file "${FEDERATION_SERVICE_ACCOUNT_PASSWORD_FILE}"
    )
    if [[ "${ACCEPT_PUBLIC_EXPOSURE}" == "true" ]]; then
        RENDER_ARGS+=(--accept-public-exposure)
    fi
    if [[ "${ALLOW_CLEARTEXT_LDAP}" == "true" ]]; then
        RENDER_ARGS+=(--allow-cleartext-ldap)
    fi
    if [[ "${ALLOW_ANONYMOUS_LDAP_BIND}" == "true" ]]; then
        RENDER_ARGS+=(--allow-anonymous-ldap-bind)
    fi
    if [[ "${ALLOW_SCRIPTED_AUTH}" == "true" ]]; then
        RENDER_ARGS+=(--allow-scripted-auth)
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
