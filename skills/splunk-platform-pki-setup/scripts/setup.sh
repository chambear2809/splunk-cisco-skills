#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-platform-pki-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
ACCEPT_PKI_ROTATION=false
OUTPUT_DIR=""

# Mode + target
MODE="private"
TARGET="core5"
PUBLIC_CA_NAME="vault"

# Per-role FQDNs / hosts
CM_FQDN=""
PEER_HOSTS=""
SHC_DEPLOYER_FQDN=""
SHC_MEMBERS=""
LM_FQDN=""
DS_FQDN=""
MC_FQDN=""
SINGLE_SH_FQDN=""
PUBLIC_FQDN=""
HEC_FQDN=""
DS_CLIENTS=""
UF_FLEET_GROUPS=""
DMZ_HF_HOSTS=""
EP_FQDN=""
EP_DATA_SOURCE_FQDN=""
FEDERATION_PROVIDER_HOSTS=""
LDAP_HOST=""

# CA distinguished name
CA_COUNTRY="US"
CA_STATE=""
CA_LOCALITY=""
CA_ORGANIZATION="Example Corp"
CA_ORGANIZATIONAL_UNIT="Splunk Platform Engineering"
CA_COMMON_NAME="Example Corp Splunk Root CA"
CA_EMAIL=""
INCLUDE_INTERMEDIATE_CA="true"
ROOT_CA_DAYS="3650"
INTERMEDIATE_CA_DAYS="1825"
LEAF_DAYS="825"

# Algorithm policy
TLS_POLICY="splunk-modern"
TLS_VERSION_FLOOR="tls1.2"
ALLOW_DEPRECATED_TLS=false
KEY_ALGORITHM="rsa-2048"
KEY_FORMAT="pkcs1"

# mTLS surfaces
ENABLE_MTLS="s2s,hec"

# Optional surfaces
ENCRYPT_REPLICATION_PORT="false"
SAML_SP="false"
LDAPS="false"
INCLUDE_EDGE_PROCESSOR="false"

# FIPS
FIPS_MODE="none"

# Splunk runtime
SPLUNK_HOME_VALUE="/opt/splunk"
SPLUNK_VERSION="10.2.2"
CERT_INSTALL_SUBDIR="myssl"

# Secret file paths
ADMIN_PASSWORD_FILE=""
IDXC_SECRET_FILE=""
CA_KEY_PASSWORD_FILE=""
INTERMEDIATE_CA_KEY_PASSWORD_FILE=""
LEAF_KEY_PASSWORD_FILE=""
SAML_SP_KEY_PASSWORD_FILE=""

# Algorithm policy override
ALGORITHM_POLICY_FILE=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Platform PKI Setup

Usage: $(basename "$0") [OPTIONS]

Phases:
  --phase render|preflight|apply|rotate|validate|inventory|all   (default: render)
  --accept-pki-rotation                                          Required for apply / all

Mode + target:
  --mode private|public                                          (default: private)
  --target CSV                                                   (default: core5)
                                  Valid: core5, indexer-cluster, shc, license-manager,
                                  deployment-server, monitoring-console, federated-search,
                                  dmz-hf, uf-fleet, saml-sp, ldaps, edge-processor, all
  --public-ca-name vault|acme|adcs|ejbca|other                   (default: vault)

Per-role FQDNs / hosts:
  --cm-fqdn FQDN
  --peer-hosts CSV
  --shc-deployer-fqdn FQDN
  --shc-members CSV
  --lm-fqdn FQDN
  --ds-fqdn FQDN
  --mc-fqdn FQDN
  --single-sh-fqdn FQDN
  --public-fqdn FQDN
  --hec-fqdn FQDN
  --ds-clients CSV
  --uf-fleet-groups CSV
  --dmz-hf-hosts CSV
  --ep-fqdn FQDN
  --ep-data-source-fqdn FQDN
  --federation-provider-hosts CSV
  --ldap-host FQDN

CA distinguished name (Private mode):
  --ca-country CC                                                (default: US)
  --ca-state STATE
  --ca-locality CITY
  --ca-organization ORG                                          (default: Example Corp)
  --ca-organizational-unit OU
  --ca-common-name CN                                            (default: Example Corp Splunk Root CA)
  --ca-email EMAIL
  --include-intermediate-ca true|false                           (default: true)
  --root-ca-days N                                               (default: 3650)
  --intermediate-ca-days N                                       (default: 1825)
  --leaf-days N                                                  (default: 825; cap 825 in private mode)

Algorithm policy:
  --tls-policy splunk-modern|fips-140-3|stig                     (default: splunk-modern)
  --tls-version-floor tls1.2                                     (only valid value)
  --allow-deprecated-tls                                         (relax lower bound; not recommended)
  --key-algorithm rsa-2048|rsa-3072|rsa-4096|ecdsa-p256|ecdsa-p384|ecdsa-p521  (default: rsa-2048)
  --key-format pkcs1|pkcs8                                       (default: pkcs1; pkcs8 for EP/DBX)

mTLS:
  --enable-mtls CSV                                              (default: s2s,hec)
                                  Valid: none, s2s, hec, splunkd, all

Optional surfaces:
  --encrypt-replication-port true|false                          (default: false)
  --saml-sp true|false                                           (default: false)
  --ldaps true|false                                             (default: false)
  --include-edge-processor true|false                            (default: false)

FIPS:
  --fips-mode none|140-2|140-3                                   (default: none)

Splunk runtime:
  --splunk-home PATH                                             (default: /opt/splunk)
  --splunk-version X.Y.Z                                         (default: 10.2.2)
  --cert-install-subdir NAME                                     (default: myssl)

Secrets (file paths only, never values on argv):
  --admin-password-file PATH
  --idxc-secret-file PATH
  --ca-key-password-file PATH
  --intermediate-ca-key-password-file PATH
  --leaf-key-password-file PATH
  --saml-sp-key-password-file PATH

Render output:
  --output-dir PATH                                              (default: <project>/${DEFAULT_RENDER_DIR_NAME})
  --algorithm-policy-file PATH                                   (override the bundled JSON)
  --dry-run
  --json
  --help

Examples:
  $(basename "$0") --phase render --mode private \\
      --target indexer-cluster,shc,license-manager,deployment-server,monitoring-console \\
      --cm-fqdn cm01.example.com \\
      --peer-hosts idx01.example.com,idx02.example.com,idx03.example.com \\
      --shc-deployer-fqdn deployer01.example.com \\
      --shc-members sh01.example.com,sh02.example.com,sh03.example.com \\
      --lm-fqdn lm01.example.com --ds-fqdn ds01.example.com --mc-fqdn mc01.example.com \\
      --enable-mtls s2s,hec --include-intermediate-ca true

  $(basename "$0") --phase render --mode public --public-ca-name vault \\
      --target indexer-cluster,shc \\
      --cm-fqdn cm01.example.com --peer-hosts idx01,idx02,idx03 \\
      --shc-deployer-fqdn deployer01 --shc-members sh01,sh02,sh03

  $(basename "$0") --phase preflight --target core5 \\
      --single-sh-fqdn sh01.example.com \\
      --admin-password-file /tmp/splunk_admin_password

  $(basename "$0") --phase apply --target shc --shc-deployer-fqdn deployer01 \\
      --shc-members sh01,sh02,sh03 --accept-pki-rotation \\
      --leaf-key-password-file /tmp/pki_leaf_key_password \\
      --admin-password-file /tmp/splunk_admin_password

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --accept-pki-rotation) ACCEPT_PKI_ROTATION=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --mode) require_arg "$1" $# || exit 1; MODE="$2"; shift 2 ;;
        --target) require_arg "$1" $# || exit 1; TARGET="$2"; shift 2 ;;
        --public-ca-name) require_arg "$1" $# || exit 1; PUBLIC_CA_NAME="$2"; shift 2 ;;
        --cm-fqdn) require_arg "$1" $# || exit 1; CM_FQDN="$2"; shift 2 ;;
        --peer-hosts) require_arg "$1" $# || exit 1; PEER_HOSTS="$2"; shift 2 ;;
        --shc-deployer-fqdn) require_arg "$1" $# || exit 1; SHC_DEPLOYER_FQDN="$2"; shift 2 ;;
        --shc-members) require_arg "$1" $# || exit 1; SHC_MEMBERS="$2"; shift 2 ;;
        --lm-fqdn) require_arg "$1" $# || exit 1; LM_FQDN="$2"; shift 2 ;;
        --ds-fqdn) require_arg "$1" $# || exit 1; DS_FQDN="$2"; shift 2 ;;
        --mc-fqdn) require_arg "$1" $# || exit 1; MC_FQDN="$2"; shift 2 ;;
        --single-sh-fqdn) require_arg "$1" $# || exit 1; SINGLE_SH_FQDN="$2"; shift 2 ;;
        --public-fqdn) require_arg "$1" $# || exit 1; PUBLIC_FQDN="$2"; shift 2 ;;
        --hec-fqdn) require_arg "$1" $# || exit 1; HEC_FQDN="$2"; shift 2 ;;
        --ds-clients) require_arg "$1" $# || exit 1; DS_CLIENTS="$2"; shift 2 ;;
        --uf-fleet-groups) require_arg "$1" $# || exit 1; UF_FLEET_GROUPS="$2"; shift 2 ;;
        --dmz-hf-hosts) require_arg "$1" $# || exit 1; DMZ_HF_HOSTS="$2"; shift 2 ;;
        --ep-fqdn) require_arg "$1" $# || exit 1; EP_FQDN="$2"; shift 2 ;;
        --ep-data-source-fqdn) require_arg "$1" $# || exit 1; EP_DATA_SOURCE_FQDN="$2"; shift 2 ;;
        --federation-provider-hosts) require_arg "$1" $# || exit 1; FEDERATION_PROVIDER_HOSTS="$2"; shift 2 ;;
        --ldap-host) require_arg "$1" $# || exit 1; LDAP_HOST="$2"; shift 2 ;;
        --ca-country) require_arg "$1" $# || exit 1; CA_COUNTRY="$2"; shift 2 ;;
        --ca-state) require_arg "$1" $# || exit 1; CA_STATE="$2"; shift 2 ;;
        --ca-locality) require_arg "$1" $# || exit 1; CA_LOCALITY="$2"; shift 2 ;;
        --ca-organization) require_arg "$1" $# || exit 1; CA_ORGANIZATION="$2"; shift 2 ;;
        --ca-organizational-unit) require_arg "$1" $# || exit 1; CA_ORGANIZATIONAL_UNIT="$2"; shift 2 ;;
        --ca-common-name) require_arg "$1" $# || exit 1; CA_COMMON_NAME="$2"; shift 2 ;;
        --ca-email) require_arg "$1" $# || exit 1; CA_EMAIL="$2"; shift 2 ;;
        --include-intermediate-ca) require_arg "$1" $# || exit 1; INCLUDE_INTERMEDIATE_CA="$2"; shift 2 ;;
        --root-ca-days) require_arg "$1" $# || exit 1; ROOT_CA_DAYS="$2"; shift 2 ;;
        --intermediate-ca-days) require_arg "$1" $# || exit 1; INTERMEDIATE_CA_DAYS="$2"; shift 2 ;;
        --leaf-days) require_arg "$1" $# || exit 1; LEAF_DAYS="$2"; shift 2 ;;
        --tls-policy) require_arg "$1" $# || exit 1; TLS_POLICY="$2"; shift 2 ;;
        --tls-version-floor) require_arg "$1" $# || exit 1; TLS_VERSION_FLOOR="$2"; shift 2 ;;
        --allow-deprecated-tls) ALLOW_DEPRECATED_TLS=true; shift ;;
        --key-algorithm) require_arg "$1" $# || exit 1; KEY_ALGORITHM="$2"; shift 2 ;;
        --key-format) require_arg "$1" $# || exit 1; KEY_FORMAT="$2"; shift 2 ;;
        --enable-mtls) require_arg "$1" $# || exit 1; ENABLE_MTLS="$2"; shift 2 ;;
        --encrypt-replication-port) require_arg "$1" $# || exit 1; ENCRYPT_REPLICATION_PORT="$2"; shift 2 ;;
        --saml-sp) require_arg "$1" $# || exit 1; SAML_SP="$2"; shift 2 ;;
        --ldaps) require_arg "$1" $# || exit 1; LDAPS="$2"; shift 2 ;;
        --include-edge-processor) require_arg "$1" $# || exit 1; INCLUDE_EDGE_PROCESSOR="$2"; shift 2 ;;
        --fips-mode) require_arg "$1" $# || exit 1; FIPS_MODE="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME_VALUE="$2"; shift 2 ;;
        --splunk-version) require_arg "$1" $# || exit 1; SPLUNK_VERSION="$2"; shift 2 ;;
        --cert-install-subdir) require_arg "$1" $# || exit 1; CERT_INSTALL_SUBDIR="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --idxc-secret-file) require_arg "$1" $# || exit 1; IDXC_SECRET_FILE="$2"; shift 2 ;;
        --ca-key-password-file) require_arg "$1" $# || exit 1; CA_KEY_PASSWORD_FILE="$2"; shift 2 ;;
        --intermediate-ca-key-password-file) require_arg "$1" $# || exit 1; INTERMEDIATE_CA_KEY_PASSWORD_FILE="$2"; shift 2 ;;
        --leaf-key-password-file) require_arg "$1" $# || exit 1; LEAF_KEY_PASSWORD_FILE="$2"; shift 2 ;;
        --saml-sp-key-password-file) require_arg "$1" $# || exit 1; SAML_SP_KEY_PASSWORD_FILE="$2"; shift 2 ;;
        --algorithm-policy-file) require_arg "$1" $# || exit 1; ALGORITHM_POLICY_FILE="$2"; shift 2 ;;
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
    validate_choice "${PHASE}" render preflight apply rotate validate inventory all
    validate_choice "${MODE}" private public
    validate_choice "${PUBLIC_CA_NAME}" vault acme adcs ejbca other
    validate_choice "${TLS_POLICY}" splunk-modern fips-140-3 stig
    validate_choice "${TLS_VERSION_FLOOR}" tls1.2
    validate_choice "${KEY_ALGORITHM}" rsa-2048 rsa-3072 rsa-4096 ecdsa-p256 ecdsa-p384 ecdsa-p521
    validate_choice "${KEY_FORMAT}" pkcs1 pkcs8
    validate_choice "${ENCRYPT_REPLICATION_PORT}" true false
    validate_choice "${SAML_SP}" true false
    validate_choice "${LDAPS}" true false
    validate_choice "${INCLUDE_EDGE_PROCESSOR}" true false
    validate_choice "${INCLUDE_INTERMEDIATE_CA}" true false
    validate_choice "${FIPS_MODE}" none 140-2 140-3

    if [[ "${PHASE}" == "apply" || "${PHASE}" == "all" ]]; then
        if [[ "${ACCEPT_PKI_ROTATION}" != "true" ]]; then
            log "ERROR: --accept-pki-rotation is required for --phase=${PHASE}."
            log "       This skill swaps serving certs and triggers downstream restart."
            log "       Acknowledge the change explicitly."
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
        --mode "${MODE}"
        --target "${TARGET}"
        --public-ca-name "${PUBLIC_CA_NAME}"
        --cm-fqdn "${CM_FQDN}"
        --peer-hosts "${PEER_HOSTS}"
        --shc-deployer-fqdn "${SHC_DEPLOYER_FQDN}"
        --shc-members "${SHC_MEMBERS}"
        --lm-fqdn "${LM_FQDN}"
        --ds-fqdn "${DS_FQDN}"
        --mc-fqdn "${MC_FQDN}"
        --single-sh-fqdn "${SINGLE_SH_FQDN}"
        --public-fqdn "${PUBLIC_FQDN}"
        --hec-fqdn "${HEC_FQDN}"
        --ds-clients "${DS_CLIENTS}"
        --uf-fleet-groups "${UF_FLEET_GROUPS}"
        --dmz-hf-hosts "${DMZ_HF_HOSTS}"
        --ep-fqdn "${EP_FQDN}"
        --ep-data-source-fqdn "${EP_DATA_SOURCE_FQDN}"
        --federation-provider-hosts "${FEDERATION_PROVIDER_HOSTS}"
        --ldap-host "${LDAP_HOST}"
        --ca-country "${CA_COUNTRY}"
        --ca-state "${CA_STATE}"
        --ca-locality "${CA_LOCALITY}"
        --ca-organization "${CA_ORGANIZATION}"
        --ca-organizational-unit "${CA_ORGANIZATIONAL_UNIT}"
        --ca-common-name "${CA_COMMON_NAME}"
        --ca-email "${CA_EMAIL}"
        --include-intermediate-ca "${INCLUDE_INTERMEDIATE_CA}"
        --root-ca-days "${ROOT_CA_DAYS}"
        --intermediate-ca-days "${INTERMEDIATE_CA_DAYS}"
        --leaf-days "${LEAF_DAYS}"
        --tls-policy "${TLS_POLICY}"
        --tls-version-floor "${TLS_VERSION_FLOOR}"
        --key-algorithm "${KEY_ALGORITHM}"
        --key-format "${KEY_FORMAT}"
        --enable-mtls "${ENABLE_MTLS}"
        --encrypt-replication-port "${ENCRYPT_REPLICATION_PORT}"
        --saml-sp "${SAML_SP}"
        --ldaps "${LDAPS}"
        --include-edge-processor "${INCLUDE_EDGE_PROCESSOR}"
        --fips-mode "${FIPS_MODE}"
        --splunk-home "${SPLUNK_HOME_VALUE}"
        --splunk-version "${SPLUNK_VERSION}"
        --cert-install-subdir "${CERT_INSTALL_SUBDIR}"
        --admin-password-file "${ADMIN_PASSWORD_FILE}"
        --idxc-secret-file "${IDXC_SECRET_FILE}"
        --ca-key-password-file "${CA_KEY_PASSWORD_FILE}"
        --intermediate-ca-key-password-file "${INTERMEDIATE_CA_KEY_PASSWORD_FILE}"
        --leaf-key-password-file "${LEAF_KEY_PASSWORD_FILE}"
        --saml-sp-key-password-file "${SAML_SP_KEY_PASSWORD_FILE}"
    )
    if [[ "${ALLOW_DEPRECATED_TLS}" == "true" ]]; then
        RENDER_ARGS+=(--allow-deprecated-tls)
    fi
    if [[ "${ACCEPT_PKI_ROTATION}" == "true" ]]; then
        RENDER_ARGS+=(--accept-pki-rotation)
    fi
    if [[ -n "${ALGORITHM_POLICY_FILE}" ]]; then
        RENDER_ARGS+=(--algorithm-policy-file "${ALGORITHM_POLICY_FILE}")
    fi
}

render_dir() {
    printf '%s/platform-pki' "${OUTPUT_DIR}"
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
            log "apply: cert install is per-host. Stage the rendered cert PEMs"
            log "        on each target host and run pki/install/install-leaf.sh"
            log "        per host. Then run the rotation runbook at"
            log "        $(render_dir)/pki/rotate/plan-rotation.md"
            ;;
        rotate)
            render_assets
            log "rotate: see $(render_dir)/pki/rotate/plan-rotation.md"
            log "        This skill DOES NOT exec the rolling restart; rolling"
            log "        restart is owned by splunk-indexer-cluster-setup."
            ;;
        validate)
            render_assets
            run_rendered_script validate.sh
            ;;
        inventory)
            render_assets
            run_rendered_script inventory.sh
            ;;
        all)
            render_assets
            run_rendered_script preflight.sh
            log "apply: cert install is per-host. See pki/install/install-leaf.sh."
            log "rotate: see pki/rotate/plan-rotation.md (delegates to splunk-indexer-cluster-setup)."
            run_rendered_script validate.sh
            ;;
    esac
}

main "$@"
