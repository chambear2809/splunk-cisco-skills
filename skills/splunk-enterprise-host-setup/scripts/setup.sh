#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/platform_version_helpers.sh"

PROJECT_PKG_DIR="${SCRIPT_DIR}/../../../splunk-ta"
SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
SERVICE_USER="${SERVICE_USER:-splunk}"
MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"
WEB_PORT="${SPLUNK_WEB_PORT:-8000}"
APPSERVER_PORT="${SPLUNK_APPSERVER_PORT:-8065}"
KVSTORE_PORT="${SPLUNK_KVSTORE_PORT:-8191}"
IPC_BROKER_PORT="${SPLUNK_IPC_BROKER_PORT:-8194}"
POSTGRES_PORT="${SPLUNK_POSTGRES_PORT:-5432}"
POSTGRES_PRIMARY_PORT="${SPLUNK_POSTGRES_PRIMARY_PORT:-5433}"
POSTGRES_REPLICA_PORT="${SPLUNK_POSTGRES_REPLICA_PORT:-5434}"
POSTGRES_PATRONI_PORT="${SPLUNK_POSTGRES_PATRONI_PORT:-8008}"
POSTGRES_PGBOUNCER_PORT="${SPLUNK_POSTGRES_PGBOUNCER_PORT:-6432}"
POSTGRES_NANNY_PORT="${SPLUNK_POSTGRES_NANNY_PORT:-5435}"
NASCENT_ETCD_PEER_PORT="${SPLUNK_NASCENT_ETCD_PEER_PORT:-2380}"
NASCENT_ETCD_CLIENT_PORT="${SPLUNK_NASCENT_ETCD_CLIENT_PORT:-2379}"
RECEIVER_PORT="9997"
REPLICATION_PORT="9887"
REPLICATION_FACTOR="3"
SEARCH_FACTOR="2"
SHC_REPLICATION_PORT="8081"
SHC_REPLICATION_FACTOR="3"
IDXC_LABEL="primary_indexers"
SHCLUSTER_LABEL="primary_search"
INDEXER_DISCOVERY_NAME="cluster_manager"
TCPOUT_GROUP="default-autolb-group"
SPLUNK_REMOTE_SUDO="${SPLUNK_REMOTE_SUDO:-true}"

PHASE="all"
SOURCE="auto"
PACKAGE_TYPE="auto"
EXECUTION_MODE="local"
HOST_BOOTSTRAP_ROLE=""
DEPLOYMENT_MODE="standalone"
CLUSTER_SITE="single"
FORWARDING_MODE=""
CHECKSUM=""
PACKAGE_URL=""
LOCAL_FILE=""
ALLOW_STALE_LATEST=false
ADMIN_USER="admin"
ADMIN_PASSWORD_FILE=""
IDXC_SECRET_FILE=""
DISCOVERY_SECRET_FILE=""
SHC_SECRET_FILE=""
CLUSTER_MANAGER_URI=""
DEPLOYER_URI=""
SERVER_LIST=""
SHC_MEMBERS=""
CURRENT_SHC_MEMBER_URI=""
ADVERTISE_HOST=""
ENABLE_WEB=""
BOOT_START=true
BOOTSTRAP_SHC=false

PACKAGE_PATH=""
PACKAGE_ON_TARGET=""
PACKAGE_STAGED=false
INSTALL_CLEANUP_REGISTERED=false
ADMIN_PASSWORD=""
IDXC_SECRET=""
DISCOVERY_SECRET=""
SHC_SECRET=""
LATEST_ENTERPRISE_METADATA=""
LATEST_ENTERPRISE_METADATA_LIVE=false
INSTALL_ACTION=""
INSTALLED_VERSION=""
PACKAGE_VERSION=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Host Setup

Usage: $(basename "$0") [OPTIONS]

Core options:
  --phase download|install|configure|cluster|all
  --source auto|splunk-auth|remote|local
  --url URL|latest
  --file PATH
  --package-type auto|tgz|rpm|deb
  --allow-stale-latest
  --execution local|ssh
  --host-bootstrap-role standalone-search-tier|standalone-indexer|heavy-forwarder|cluster-manager|indexer-peer|shc-deployer|shc-member
  --deployment-mode standalone|clustered
  --cluster-site single
  --checksum sha256:<value>
  --splunk-home PATH
  --service-user USER
  --advertise-host HOST
  --mgmt-port PORT (default: 8089; fresh installs)
  --web-port PORT (default: 8000; fresh installs; enables Splunk Web)
  --appserver-port PORT (default: 8065; fresh installs)
  --kvstore-port PORT (default: 8191; fresh installs)
  --ipc-broker-port PORT (default: 8194; fresh installs)
  --postgres-port PORT (default: 5432; fresh installs)
  --postgres-primary-port PORT (default: 5433; fresh installs)
  --postgres-replica-port PORT (default: 5434; fresh installs)
  --postgres-patroni-port PORT (default: 8008; fresh installs)
  --postgres-pgbouncer-port PORT (default: 6432; fresh installs)
  --postgres-nanny-port PORT (default: 5435; fresh installs)
  --nascent-etcd-peer-port PORT (default: 2380; fresh installs)
  --nascent-etcd-client-port PORT (default: 2379; fresh installs)

Port options accept non-standard values. Omit them to use Splunk's standard
ports. Fresh installs verify that the selected ports are free and configure
them before the first start, including the PostgreSQL and Nascent sidecar ports
used by Splunk Enterprise 10.6.

If --url is omitted or set to latest for a remote/authenticated download, the
script resolves the latest official Splunk Enterprise Linux package from
splunk.com. With --package-type auto, latest resolution prefers deb/rpm based
on the target OS family and falls back to tgz. Latest official downloads also
require successful verification against Splunk's official SHA512 checksum.

Security / auth:
  --admin-user USER
  --admin-password-file PATH
  --idxc-secret-file PATH
  --discovery-secret-file PATH
  --shc-secret-file PATH

Role-specific options:
  --enable-web
  --no-boot-start
  --receiver-port PORT
  --forwarding-mode indexer-discovery|server-list
  --server-list HOST:PORT[,HOST:PORT...]
  --cluster-manager-uri URI
  --replication-factor N
  --search-factor N
  --replication-port PORT
  --idxc-label LABEL
  --indexer-discovery-name NAME
  --tcpout-group NAME
  --deployer-uri URI
  --shcluster-label LABEL
  --shc-replication-port PORT
  --shc-replication-factor N
  --shc-members URI[,URI...]
  --current-shc-member-uri URI
  --bootstrap-shc

Examples:
  $(basename "$0") --phase all --execution local --host-bootstrap-role standalone-search-tier \\
    --source local --file /tmp/splunk-10.0.0-linux-x86_64.tgz \\
    --admin-password-file /tmp/splunk_admin_password --enable-web

	  $(basename "$0") --phase all --execution ssh --host-bootstrap-role heavy-forwarder \\
	    --deployment-mode clustered --source remote --package-type tgz \\
	    --admin-password-file /tmp/splunk_admin_password \\
	    --cluster-manager-uri https://cm01.example.com:8089 \\
	    --discovery-secret-file /tmp/splunk_idxc_secret
EOF
    exit "${exit_code}"
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

ensure_prompted_value() {
    local var_name="$1"
    local prompt="$2"
    local default_value="${3:-}"
    local current_value="${!var_name:-}"

    if [[ -z "${current_value}" ]] && hbs_is_interactive; then
        current_value="$(hbs_prompt_value "${prompt}" "${default_value}")"
        printf -v "${var_name}" '%s' "${current_value}"
    fi

    if [[ -z "${!var_name:-}" ]]; then
        log "ERROR: ${prompt} is required."
        exit 1
    fi
}

ensure_prompted_path() {
    local var_name="$1"
    local prompt="$2"
    local current_value="${!var_name:-}"

    if [[ -z "${current_value}" ]] && hbs_is_interactive; then
        current_value="$(hbs_prompt_secret_path "${prompt}")"
        printf -v "${var_name}" '%s' "${current_value}"
    fi

    if [[ -z "${!var_name:-}" ]]; then
        log "ERROR: ${prompt} is required."
        exit 1
    fi
}

phase_includes_download() {
    [[ "${PHASE}" == "download" || "${PHASE}" == "install" || "${PHASE}" == "all" ]]
}

phase_includes_install() {
    [[ "${PHASE}" == "install" || "${PHASE}" == "all" ]]
}

phase_includes_configure() {
    [[ "${PHASE}" == "configure" || "${PHASE}" == "all" ]]
}

phase_includes_cluster() {
    [[ "${PHASE}" == "cluster" || "${PHASE}" == "all" ]]
}

role_defaults_enable_web() {
    case "${HOST_BOOTSTRAP_ROLE:-}" in
        standalone-search-tier|shc-member)
            printf '%s' "true"
            ;;
        *)
            printf '%s' "false"
            ;;
    esac
}

role_uses_splunk_enterprise() {
    [[ -n "${HOST_BOOTSTRAP_ROLE:-}" ]]
}

resolve_source_auto() {
    if [[ "${SOURCE}" != "auto" ]]; then
        return 0
    fi

    if [[ -n "${LOCAL_FILE}" ]]; then
        SOURCE="local"
    elif [[ -n "${PACKAGE_URL}" && "${PACKAGE_URL}" != "latest" ]]; then
        if [[ -n "${SPLUNK_USERNAME:-${SB_USER:-}}" || -n "${SPLUNK_PASSWORD:-${SB_PASS:-}}" ]]; then
            SOURCE="splunk-auth"
        else
            SOURCE="remote"
        fi
    else
        if [[ -n "${SPLUNK_USERNAME:-${SB_USER:-}}" || -n "${SPLUNK_PASSWORD:-${SB_PASS:-}}" ]]; then
            SOURCE="splunk-auth"
        else
            SOURCE="remote"
        fi
    fi
}

load_secret_values() {
    if admin_password_required; then
        ensure_prompted_path ADMIN_PASSWORD_FILE "Admin password file path"
        ADMIN_PASSWORD="$(read_secret_file "${ADMIN_PASSWORD_FILE}")"
    fi

    if [[ -n "${IDXC_SECRET_FILE}" ]]; then
        IDXC_SECRET="$(read_secret_file "${IDXC_SECRET_FILE}")"
    fi
    if [[ -n "${DISCOVERY_SECRET_FILE}" ]]; then
        DISCOVERY_SECRET="$(read_secret_file "${DISCOVERY_SECRET_FILE}")"
    fi
    if [[ -n "${SHC_SECRET_FILE}" ]]; then
        SHC_SECRET="$(read_secret_file "${SHC_SECRET_FILE}")"
    fi
    if [[ -z "${DISCOVERY_SECRET}" && -n "${IDXC_SECRET}" ]]; then
        DISCOVERY_SECRET="${IDXC_SECRET}"
    fi
}

admin_password_required() {
    local install_action="${INSTALL_ACTION:-fresh-install}"

    if phase_includes_install && [[ "${install_action}" == "fresh-install" ]]; then
        return 0
    fi

    if phase_includes_configure; then
        case "${HOST_BOOTSTRAP_ROLE}" in
            standalone-search-tier|shc-member)
                if [[ "${ENABLE_WEB}" == "true" ]]; then
                    return 0
                fi
                ;;
        esac
    fi

    if phase_includes_cluster && [[ "${DEPLOYMENT_MODE}" == "clustered" ]] && [[ "${HOST_BOOTSTRAP_ROLE}" == "shc-member" ]]; then
        return 0
    fi

    return 1
}

resolve_latest_package_type() {
    local preferred_type="${PACKAGE_TYPE}"

    if [[ "${preferred_type}" != "auto" ]]; then
        printf '%s' "${preferred_type}"
        return 0
    fi

    hbs_preferred_latest_package_type "${EXECUTION_MODE}"
}

pick_package_path() {
    local download_user="" download_pass="" download_target latest_package_type="" resolved_metadata="" resolved_url="" latest_version=""
    local official_sha512="" official_sha512_url="" stale_cache_rc=0

    resolve_source_auto
    LATEST_ENTERPRISE_METADATA=""
    LATEST_ENTERPRISE_METADATA_LIVE=false

    case "${SOURCE}" in
        local)
            ensure_prompted_value LOCAL_FILE "Local Splunk package path"
            PACKAGE_PATH="$(hbs_resolve_abs_path "${LOCAL_FILE}")"
            [[ -f "${PACKAGE_PATH}" ]] || { log "ERROR: Package not found: ${PACKAGE_PATH}"; exit 1; }
            ;;
        remote|splunk-auth)
            if [[ "${SOURCE}" == "splunk-auth" ]]; then
                download_user="${SPLUNK_USERNAME:-${SB_USER:-}}"
                download_pass="${SPLUNK_PASSWORD:-${SB_PASS:-}}"
                if [[ -z "${download_user}" && -z "${download_pass}" ]]; then
                    log "ERROR: --source splunk-auth requires SPLUNK_USERNAME/SPLUNK_PASSWORD or SB_USER/SB_PASS."
                    exit 1
                fi
            fi

            if [[ -z "${PACKAGE_URL}" || "${PACKAGE_URL}" == "latest" ]]; then
                latest_package_type="$(resolve_latest_package_type)"
                if [[ "${PACKAGE_TYPE}" == "auto" ]]; then
                    if [[ "${latest_package_type}" == "tgz" ]]; then
                        log "INFO: Could not map the target OS family to deb or rpm; defaulting latest official download resolution to tgz."
                    else
                        log "INFO: Auto-selected ${latest_package_type} for latest official download resolution from the target OS family."
                    fi
                fi
                log "Resolving latest official Splunk Enterprise ${latest_package_type} download URL"
                if resolved_metadata="$(hbs_resolve_latest_enterprise_download_metadata "${latest_package_type}")"; then
                    LATEST_ENTERPRISE_METADATA_LIVE=true
                else
                    if [[ "${ALLOW_STALE_LATEST}" != "true" ]]; then
                        log "ERROR: Failed to resolve the latest official Splunk Enterprise ${latest_package_type} package. Re-run with --allow-stale-latest or provide --url."
                        exit 1
                    fi

                    log "WARN: Live latest resolution failed; attempting stale metadata fallback for ${latest_package_type}."
                    if resolved_metadata="$(hbs_read_latest_enterprise_metadata_cache "${PROJECT_PKG_DIR}" "${latest_package_type}")"; then
                        :
                    else
                        stale_cache_rc=$?
                        if [[ "${stale_cache_rc}" -eq 2 ]]; then
                            log "ERROR: Cached latest metadata for ${latest_package_type} is older than 30 days. Provide --url or refresh live latest resolution."
                        else
                            log "ERROR: No usable cached latest metadata exists for ${latest_package_type}. Provide --url or retry once live resolution succeeds."
                        fi
                        exit 1
                    fi
                fi

                latest_version="$(hbs_latest_enterprise_metadata_field "${resolved_metadata}" "version")"
                resolved_url="$(hbs_latest_enterprise_metadata_field "${resolved_metadata}" "package_url")"
                [[ -n "${latest_version}" && -n "${resolved_url}" ]] || {
                    log "ERROR: Latest Splunk Enterprise metadata was incomplete for package type ${latest_package_type}."
                    exit 1
                }

                LATEST_ENTERPRISE_METADATA="${resolved_metadata}"
                PACKAGE_URL="${resolved_url}"
                log "Resolved latest Splunk Enterprise ${latest_version} package: ${PACKAGE_URL}"
                PACKAGE_TYPE="${latest_package_type}"
            else
                ensure_prompted_value PACKAGE_URL "Package download URL"
            fi
            download_target="$(hbs_build_cached_download_path "${PROJECT_PKG_DIR}" "${PACKAGE_URL}")"
            PACKAGE_PATH="${download_target}"

            if [[ ! -f "${PACKAGE_PATH}" ]]; then
                log "Downloading package to ${PACKAGE_PATH}"
                hbs_download_file "${PACKAGE_URL}" "${PACKAGE_PATH}" "${download_user}" "${download_pass}"
            else
                log "Reusing cached package ${PACKAGE_PATH}"
            fi
            ;;
        *)
            log "ERROR: Unsupported source '${SOURCE}'."
            exit 1
            ;;
    esac

    if [[ "${PACKAGE_TYPE}" == "auto" ]]; then
        PACKAGE_TYPE="$(hbs_detect_package_type "${PACKAGE_PATH}")"
    fi
    if role_uses_splunk_enterprise; then
        hbs_require_enterprise_package_for_role "${PACKAGE_PATH}" "${HOST_BOOTSTRAP_ROLE}"
    fi

    if [[ -n "${LATEST_ENTERPRISE_METADATA}" ]]; then
        official_sha512_url="$(hbs_latest_enterprise_metadata_field "${LATEST_ENTERPRISE_METADATA}" "sha512_url")"
        official_sha512="$(hbs_latest_enterprise_metadata_field "${LATEST_ENTERPRISE_METADATA}" "sha512" 2>/dev/null || true)"
        if [[ -z "${official_sha512}" ]]; then
            log "Fetching official SHA512 from ${official_sha512_url}"
            official_sha512="$(hbs_fetch_expected_sha512 "${official_sha512_url}" "${download_user}" "${download_pass}")" || exit 1
            LATEST_ENTERPRISE_METADATA="$(hbs_latest_enterprise_metadata_with_sha512 "${LATEST_ENTERPRISE_METADATA}" "${official_sha512}")"
        fi

        log "Verifying ${PACKAGE_PATH} against Splunk's official SHA512 checksum"
        hbs_verify_sha512_checksum "${PACKAGE_PATH}" "${official_sha512}" || exit 1

        if [[ "${LATEST_ENTERPRISE_METADATA_LIVE}" == "true" ]]; then
            hbs_write_latest_enterprise_metadata_cache "${PROJECT_PKG_DIR}" "${PACKAGE_TYPE}" "${LATEST_ENTERPRISE_METADATA}" || exit 1
        fi
    fi

    hbs_verify_checksum "${PACKAGE_PATH}" "${CHECKSUM}"
    PACKAGE_VERSION="$(resolve_requested_package_version)"
    if [[ -z "${PACKAGE_VERSION}" ]]; then
        log "ERROR: Could not determine the Splunk Enterprise package version; retain the official versioned filename or use --url latest."
        exit 1
    fi
    spv_require_supported_enterprise_version "${PACKAGE_VERSION}" || exit 1
}

target_has_splunk_install() {
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_shell_join test -x "${SPLUNK_HOME}/bin/splunk")" >/dev/null 2>&1
}

resolve_requested_package_version() {
    local package_version=""

    if [[ -n "${LATEST_ENTERPRISE_METADATA}" ]]; then
        package_version="$(hbs_latest_enterprise_metadata_field "${LATEST_ENTERPRISE_METADATA}" "version" 2>/dev/null || true)"
    fi
    if [[ -z "${package_version}" && -n "${PACKAGE_PATH}" ]]; then
        package_version="$(hbs_extract_splunk_package_version "${PACKAGE_PATH}")"
    fi

    printf '%s' "${package_version}"
}

enterprise_106_sidecars_enabled() {
    [[ "${PACKAGE_VERSION:-}" =~ ^10\.6(\.|$) ]]
}

validate_sidecar_port_values() {
    enterprise_106_sidecars_enabled || return 0
    local i j port_value
    local -a sidecar_ports=(
        "${MGMT_PORT}" "${WEB_PORT}" "${APPSERVER_PORT}" "${KVSTORE_PORT}" "${IPC_BROKER_PORT}"
        "${POSTGRES_PORT}" "${POSTGRES_PRIMARY_PORT}" "${POSTGRES_REPLICA_PORT}"
        "${POSTGRES_PATRONI_PORT}" "${POSTGRES_PGBOUNCER_PORT}" "${POSTGRES_NANNY_PORT}"
        "${NASCENT_ETCD_PEER_PORT}" "${NASCENT_ETCD_CLIENT_PORT}"
    )
    for port_value in "${sidecar_ports[@]}"; do
        if [[ ! "${port_value}" =~ ^[1-9][0-9]{0,4}$ ]] || (( port_value > 65535 )); then
            log "ERROR: Configured service ports must be numeric values from 1 through 65535."
            return 1
        fi
    done
    for port_value in "${sidecar_ports[@]:5}"; do
        if (( port_value < 1024 )); then
            log "ERROR: PostgreSQL and Nascent sidecar ports must be from 1024 through 65535."
            return 1
        fi
    done
    for ((i = 0; i < ${#sidecar_ports[@]}; i++)); do
        for ((j = i + 1; j < ${#sidecar_ports[@]}; j++)); do
            if [[ "${sidecar_ports[i]}" == "${sidecar_ports[j]}" ]]; then
                log "ERROR: All selected Splunk service and sidecar ports must be distinct."
                return 1
            fi
        done
    done
}

capture_installed_splunk_version() {
    local version_output version
    version_output="$(capture_splunk_as_service_user "$(splunk_cli_cmd version)" 2>/dev/null || true)"
    version="$(hbs_extract_splunk_version "${version_output}")"
    printf '%s' "${version}"
}

require_supported_installed_enterprise_version() {
    local installed_version
    installed_version="$(capture_installed_splunk_version)"
    if [[ -z "${installed_version}" ]]; then
        log "ERROR: Could not determine the installed Splunk Enterprise version before a self-managed configuration operation."
        exit 1
    fi
    spv_require_supported_enterprise_version "${installed_version}" || exit 1
}

determine_install_action() {
    PACKAGE_VERSION="$(resolve_requested_package_version)"
    INSTALLED_VERSION=""
    INSTALL_ACTION="fresh-install"

    if ! target_has_splunk_install; then
        return 0
    fi

    INSTALL_ACTION="upgrade"
    INSTALLED_VERSION="$(capture_installed_splunk_version)"

    if [[ -n "${INSTALLED_VERSION}" && -n "${PACKAGE_VERSION}" ]] && hbs_versions_equal "${INSTALLED_VERSION}" "${PACKAGE_VERSION}"; then
        INSTALL_ACTION="same-version"
    fi
}

host_bootstrap_role_is_clustered() {
    case "${HOST_BOOTSTRAP_ROLE:-}" in
        cluster-manager|indexer-peer|shc-deployer|shc-member)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

warn_clustered_upgrade_scope() {
    [[ "${INSTALL_ACTION}" == "upgrade" ]] || return 0

    if [[ "${DEPLOYMENT_MODE}" == "clustered" ]] || host_bootstrap_role_is_clustered; then
        log "WARN: Clustered upgrades are per-host only; sequence hosts and verify cluster health outside this script."
    fi
}

ensure_role_defaults() {
    if phase_includes_install || phase_includes_configure || phase_includes_cluster; then
        ensure_prompted_value HOST_BOOTSTRAP_ROLE "Host bootstrap role"
    fi

    if [[ -z "${ENABLE_WEB}" ]]; then
        ENABLE_WEB="$(role_defaults_enable_web)"
    fi

    if [[ -z "${FORWARDING_MODE}" && "${HOST_BOOTSTRAP_ROLE}" == "heavy-forwarder" ]]; then
        if [[ "${DEPLOYMENT_MODE}" == "clustered" ]]; then
            FORWARDING_MODE="indexer-discovery"
        elif [[ -n "${SERVER_LIST}" ]]; then
            FORWARDING_MODE="server-list"
        elif [[ -n "${CLUSTER_MANAGER_URI}" ]]; then
            FORWARDING_MODE="indexer-discovery"
        else
            FORWARDING_MODE="server-list"
        fi
    fi

    if [[ -z "${ADVERTISE_HOST}" ]] && (phase_includes_install || phase_includes_cluster); then
        ADVERTISE_HOST="$(hbs_detect_advertise_host "${EXECUTION_MODE}")"
    fi
}

validate_inputs() {
    validate_choice "${PHASE}" download install configure cluster all
    validate_choice "${SOURCE}" auto splunk-auth remote local
    validate_choice "${PACKAGE_TYPE}" auto tgz rpm deb
    validate_choice "${EXECUTION_MODE}" local ssh
    validate_choice "${DEPLOYMENT_MODE}" standalone clustered
    validate_choice "${CLUSTER_SITE}" single

    local -a configured_ports=(
        "${MGMT_PORT}" "${WEB_PORT}" "${APPSERVER_PORT}" "${KVSTORE_PORT}" "${IPC_BROKER_PORT}"
    )
    if enterprise_106_sidecars_enabled; then
        configured_ports+=(
            "${POSTGRES_PORT}" "${POSTGRES_PRIMARY_PORT}" "${POSTGRES_REPLICA_PORT}"
            "${POSTGRES_PATRONI_PORT}" "${POSTGRES_PGBOUNCER_PORT}" "${POSTGRES_NANNY_PORT}"
            "${NASCENT_ETCD_PEER_PORT}" "${NASCENT_ETCD_CLIENT_PORT}"
        )
    fi
    local i j port_value
    for port_value in "${configured_ports[@]}"; do
        if [[ ! "${port_value}" =~ ^[1-9][0-9]{0,4}$ ]] || (( port_value > 65535 )); then
            log "ERROR: Configured service ports must be numeric values from 1 through 65535."
            exit 1
        fi
    done
    for ((i = 0; i < ${#configured_ports[@]}; i++)); do
        for ((j = i + 1; j < ${#configured_ports[@]}; j++)); do
            if [[ "${configured_ports[i]}" == "${configured_ports[j]}" ]]; then
                log "ERROR: All selected Splunk service and sidecar ports must be distinct."
                exit 1
            fi
        done
    done

    if [[ -n "${HOST_BOOTSTRAP_ROLE}" ]]; then
        validate_choice "${HOST_BOOTSTRAP_ROLE}" standalone-search-tier standalone-indexer heavy-forwarder cluster-manager indexer-peer shc-deployer shc-member
    fi

    if [[ -n "${FORWARDING_MODE}" ]]; then
        validate_choice "${FORWARDING_MODE}" indexer-discovery server-list
    fi

    if [[ "${DEPLOYMENT_MODE}" == "clustered" && "${HOST_BOOTSTRAP_ROLE}" == standalone-* ]]; then
        log "ERROR: Standalone roles cannot be used with --deployment-mode clustered."
        exit 1
    fi

    if phase_includes_cluster && [[ "${DEPLOYMENT_MODE}" == "clustered" ]] && [[ "${HOST_BOOTSTRAP_ROLE}" == "shc-member" ]]; then
        if [[ "${BOOTSTRAP_SHC}" == "true" && -n "${CURRENT_SHC_MEMBER_URI}" ]]; then
            log "ERROR: --bootstrap-shc cannot be combined with --current-shc-member-uri."
            exit 1
        fi
        if [[ "${BOOTSTRAP_SHC}" != "true" && -z "${CURRENT_SHC_MEMBER_URI}" ]]; then
            log "ERROR: Adding an SHC member requires --current-shc-member-uri unless --bootstrap-shc is set."
            exit 1
        fi
    fi
}

ensure_service_user_exists() {
    local create_cmd
    create_cmd="id -u $(hbs_shell_join "${SERVICE_USER}") >/dev/null 2>&1 || useradd -r -m -d $(hbs_shell_join "${SPLUNK_HOME}") -s /bin/false $(hbs_shell_join "${SERVICE_USER}")"
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join bash -c "${create_cmd}")")" >/dev/null 2>&1 || {
        log "ERROR: Failed to ensure service user ${SERVICE_USER} exists on target."
        exit 1
    }
}

ensure_splunk_ownership() {
    if [[ "${EXECUTION_MODE}" == "local" ]] && [[ "$(id -un)" == "${SERVICE_USER}" ]] && [[ -w "${SPLUNK_HOME}" ]]; then
        return 0
    fi
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown -R "${SERVICE_USER}" "${SPLUNK_HOME}")")"
}

write_splunk_config() {
    local target_path="$1" content="$2"
    local apps_root="${SPLUNK_HOME}/etc/apps" relative_path app_name app_relative app_dir local_dir
    # Role drop-ins are the only files written through this helper. Create and
    # own their dedicated app root before hbs_write_target_file creates metadata
    # or the local file; never chown a shared Splunk parent or arbitrary path.
    if [[ "${target_path}" != "${apps_root}/ZZZ_cisco_skills_"* ]]; then
        log "ERROR: Refusing managed config outside ZZZ_cisco_skills_* app roots: ${target_path}"
        exit 1
    fi
    relative_path="${target_path#${apps_root}/}"
    app_name="${relative_path%%/*}"
    app_relative="${relative_path#*/}"
    if [[ "${app_name}" != ZZZ_cisco_skills_* || "${app_relative}" != local/* || "${app_relative}" == *..* ]]; then
        log "ERROR: Refusing unsafe managed config path: ${target_path}"
        exit 1
    fi
    app_dir="${apps_root}/${app_name}"
    local_dir="${app_dir}/local"
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join install -d -m 750 "${app_dir}" "${local_dir}")")" || {
        log "ERROR: Failed to create managed app directories: ${app_dir}"
        exit 1
    }
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown "${SERVICE_USER}" "${app_dir}" "${local_dir}")")" || {
        log "ERROR: Failed to set managed app directory ownership: ${app_dir}"
        exit 1
    }
    hbs_write_target_file "${EXECUTION_MODE}" "${target_path}" "600" "${content}" || {
        log "ERROR: Failed to write Splunk configuration: ${target_path}"
        exit 1
    }
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown "${SERVICE_USER}" "${target_path}")")" || {
        log "ERROR: Failed to set Splunk config ownership on ${target_path}."
        exit 1
    }
}

write_shc_member_system_local_config() {
    local content="$1" fragment_local helper_local fragment_target helper_target target_path merge_cmd rc
    fragment_local="$(mktemp)"
    printf '%s' "${content}" > "${fragment_local}"
    helper_local="$(mktemp)"
    cp "${SCRIPT_DIR}/merge_server_conf_sections.py" "${helper_local}"
    chmod 600 "${helper_local}"
    fragment_target="$(hbs_stage_file_for_execution "${EXECUTION_MODE}" "${fragment_local}" "splunk-shc-member-server.$$.$RANDOM")" || {
        rm -f "${fragment_local}" "${helper_local}"
        return 1
    }
    helper_target="$(hbs_stage_file_for_execution "${EXECUTION_MODE}" "${helper_local}" "splunk-merge-server-conf.$$.$RANDOM.py")" || {
        rm -f "${fragment_local}" "${helper_local}"
        hbs_remove_target_path "${EXECUTION_MODE}" "${fragment_target}"
        return 1
    }
    target_path="${SPLUNK_HOME}/etc/system/local/server.conf"
    merge_cmd="$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join python3 "${helper_target}" "${target_path}" "${fragment_target}" --owner-user "${SERVICE_USER}")")"
    if hbs_run_target_cmd "${EXECUTION_MODE}" "${merge_cmd}"; then
        rc=0
    else
        rc=$?
    fi
    rm -f "${fragment_local}" "${helper_local}"
    hbs_remove_target_path "${EXECUTION_MODE}" "${fragment_target}"
    hbs_remove_target_path "${EXECUTION_MODE}" "${helper_target}"
    return "${rc}"
}

install_package_to_target() {
    local install_action install_parent install_cmd sudo_prefix tmp_root

    PACKAGE_ON_TARGET="$(hbs_stage_file_for_execution "${EXECUTION_MODE}" "${PACKAGE_PATH}" "$(basename "${PACKAGE_PATH}")")"
    PACKAGE_STAGED=false
    if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
        PACKAGE_STAGED=true
    fi
    register_install_cleanup
    install_action="${INSTALL_ACTION:-fresh-install}"

    case "${PACKAGE_TYPE}" in
        tgz)
            install_parent="$(dirname "${SPLUNK_HOME}")"
            sudo_prefix="$(hbs_target_sudo_prefix "${EXECUTION_MODE}")"
            tmp_root="${SPLUNK_REMOTE_TMPDIR:-/tmp}"
            install_cmd=$(
                cat <<EOF
set -euo pipefail
target_home=$(hbs_shell_join "${SPLUNK_HOME}")
install_parent=$(hbs_shell_join "${install_parent}")
package_path=$(hbs_shell_join "${PACKAGE_ON_TARGET}")
tmp_root=$(hbs_shell_join "${tmp_root}")
sudo_prefix=$(hbs_shell_join "${sudo_prefix}")
install_action=$(hbs_shell_join "${install_action}")

run_privileged() {
    if [[ -n "\${sudo_prefix}" ]]; then
        "\${sudo_prefix}" "\$@"
    else
        "\$@"
    fi
}

if [[ "\${install_action}" == "fresh-install" ]]; then
    if [[ -e "\${target_home}" ]]; then
        echo "ERROR: Target path \${target_home} already exists but is not a Splunk install." >&2
        exit 1
    fi
    run_privileged mkdir -p "\${install_parent}" "\${tmp_root}"
elif [[ "\${install_action}" == "upgrade" ]]; then
    if [[ ! -x "\${target_home}/bin/splunk" ]]; then
        echo "ERROR: Expected an existing Splunk install at \${target_home} for tgz upgrade." >&2
        exit 1
    fi
    run_privileged mkdir -p "\${tmp_root}"
else
    echo "ERROR: Unsupported install action '\${install_action}' for tgz package." >&2
    exit 1
fi

extract_dir=\$(run_privileged mktemp -d "\${tmp_root%/}/splunk-install.XXXXXX")
cleanup() {
    run_privileged rm -rf "\${extract_dir}"
}
trap cleanup EXIT

run_privileged python3 - "\${package_path}" "\${extract_dir}" <<'PY'
import os
from pathlib import PurePosixPath
import sys
import tarfile


def fail(message):
    print(f"ERROR: Unsafe package archive member: {message}", file=sys.stderr)
    sys.exit(1)


def safe_relative_path(value):
    normalized = str(value or "").replace("\\\\", "/").strip()
    path = PurePosixPath(normalized)
    return bool(normalized) and not path.is_absolute() and ".." not in path.parts


def safe_link_target(member, destination, member_target):
    linkname = str(member.linkname or "").replace("\\\\", "/")
    link_path = PurePosixPath(linkname)
    if not linkname or link_path.is_absolute():
        return False
    base = os.path.dirname(member_target) if member.issym() else destination
    link_target = os.path.abspath(os.path.join(base, linkname))
    try:
        return os.path.commonpath([destination, link_target]) == destination
    except ValueError:
        return False


archive_path, destination = sys.argv[1], sys.argv[2]
destination = os.path.abspath(destination)
with tarfile.open(archive_path, "r:*") as archive:
    members = archive.getmembers()
    for member in members:
        if not safe_relative_path(member.name):
            fail(member.name)
        target = os.path.abspath(os.path.join(destination, member.name))
        if os.path.commonpath([destination, target]) != destination:
            fail(member.name)
        if member.isdev() or member.isfifo():
            fail(f"{member.name} uses a special file type")
        if member.issym() or member.islnk():
            if not safe_link_target(member, destination, target):
                fail(f"{member.name} -> {member.linkname}")
    try:
        archive.extractall(destination, members=members, filter="data")
    except TypeError:
        archive.extractall(destination, members=members)
PY
if ! run_privileged test -d "\${extract_dir}/splunk"; then
    echo "ERROR: Extracted package did not contain a splunk/ directory." >&2
    run_privileged ls -la "\${extract_dir}" 2>/dev/null | head -n 20 >&2 || true
    exit 1
fi

if [[ "\${install_action}" == "fresh-install" ]]; then
    run_privileged mv "\${extract_dir}/splunk" "\${target_home}"
else
    run_privileged cp -a "\${extract_dir}/splunk/." "\${target_home}/"
fi
EOF
            )
            hbs_run_target_cmd "${EXECUTION_MODE}" "${install_cmd}"
            ;;
        rpm)
            install_cmd="$(hbs_shell_join rpm -Uvh)"
            if [[ "${SPLUNK_HOME}" != "/opt/splunk" ]]; then
                install_cmd+=" $(hbs_shell_join --prefix "${SPLUNK_HOME}")"
            fi
            install_cmd+=" $(hbs_shell_join "${PACKAGE_ON_TARGET}")"
            hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "${install_cmd}")"
            ;;
        deb)
            hbs_run_target_cmd "${EXECUTION_MODE}" \
                "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join dpkg -i "${PACKAGE_ON_TARGET}")")"
            ;;
    esac
}

validate_install_constraints() {
    if [[ "${PACKAGE_TYPE}" == "deb" && "${SPLUNK_HOME}" != "/opt/splunk" ]]; then
        log "ERROR: DEB installs only support /opt/splunk."
        exit 1
    fi
}

write_user_seed() {
    local user_seed_path content
    user_seed_path="${SPLUNK_HOME}/etc/system/local/user-seed.conf"
    content=$'[user_info]\n'
    content+="USERNAME = ${ADMIN_USER}"$'\n'
    content+="PASSWORD = ${ADMIN_PASSWORD}"$'\n'
    cleanup_user_seed_artifacts
    hbs_write_target_file "${EXECUTION_MODE}" "${user_seed_path}" "600" "${content}" "false" || return 1
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown "${SERVICE_USER}" "${user_seed_path}")")" || return 1
    log "Wrote the initial admin seed with mode 600 and owner ${SERVICE_USER}."
}

splunk_cli_cmd() {
    hbs_shell_join "${SPLUNK_HOME}/bin/splunk" "$@"
}

run_splunk_as_service_user() {
    local raw_cmd="${1:-}"
    hbs_run_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}"
}

run_splunk_as_service_user_with_input() {
    local raw_cmd="${1:-}"
    local stdin_content="${2:-}"
    hbs_run_as_user_cmd_with_stdin "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}" "${stdin_content}"
}

capture_splunk_as_service_user() {
    local raw_cmd="${1:-}"
    hbs_capture_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}"
}

run_splunk_authenticated() {
    local raw_cmd="${1:-}"
    local auth_cmd auth_file="${SPLUNK_HOME}/.cisco-skills-admin-password.$$" helper_file="${SPLUNK_HOME}/.cisco-skills-auth-pty.$$" rc
    hbs_write_target_file "${EXECUTION_MODE}" "${auth_file}" "600" "${ADMIN_PASSWORD}" "false" || return 1
    hbs_copy_file_to_target "${EXECUTION_MODE}" "${SCRIPT_DIR}/splunk_cli_auth_pty.py" "${helper_file}" "700" "false" || {
        hbs_remove_target_path "${EXECUTION_MODE}" "${auth_file}"
        return 1
    }
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown "${SERVICE_USER}" "${auth_file}" "${helper_file}")")" || {
        hbs_remove_target_path "${EXECUTION_MODE}" "${auth_file}"
        hbs_remove_target_path "${EXECUTION_MODE}" "${helper_file}"
        return 1
    }
    auth_cmd="$(hbs_shell_join python3 "${helper_file}" \
        --splunk "${SPLUNK_HOME}/bin/splunk" --username "${ADMIN_USER}" \
        --password-file "${auth_file}" --cache-dir "${SPLUNK_HOME}/.splunk" \
        --command "${raw_cmd}")"
    if run_splunk_as_service_user "${auth_cmd}"; then
        rc=0
    else
        rc=$?
    fi
    hbs_remove_target_path "${EXECUTION_MODE}" "${auth_file}"
    hbs_remove_target_path "${EXECUTION_MODE}" "${helper_file}"
    return "${rc}"
}

start_splunk() {
    run_splunk_as_service_user "$(splunk_cli_cmd start --accept-license --answer-yes --no-prompt)"
}

configure_fresh_install_ports() {
    [[ "${INSTALL_ACTION}" == "fresh-install" ]] || return 0
    local system_local server_conf web_conf start_web_server
    system_local="${SPLUNK_HOME}/etc/system/local"
    server_conf=$'[kvstore]\nport = '"${KVSTORE_PORT}"$'\n\n[ipc_broker]\n'
    server_conf+=$'port = '"${IPC_BROKER_PORT}"$'\n'
    if enterprise_106_sidecars_enabled; then
        server_conf+=$'postgres:postgres:address = '"${POSTGRES_PORT}"$'\n'
        # Splunk 10.6's default file retains these deprecated aliases; keep their
        # values aligned with the canonical primary/replica sidecar addresses.
        server_conf+=$'postgres:traefik_primary:address = '"${POSTGRES_PRIMARY_PORT}"$'\n'
        server_conf+=$'postgres:traefik_replica:address = '"${POSTGRES_REPLICA_PORT}"$'\n'
        server_conf+=$'postgres:postgres-primary:address = '"${POSTGRES_PRIMARY_PORT}"$'\n'
        server_conf+=$'postgres:postgres-replica:address = '"${POSTGRES_REPLICA_PORT}"$'\n'
        server_conf+=$'postgres:patroni:address = '"${POSTGRES_PATRONI_PORT}"$'\n'
        server_conf+=$'postgres:pgbouncer:address = '"${POSTGRES_PGBOUNCER_PORT}"$'\n'
        server_conf+=$'postgres:postgres_nanny:address = '"${POSTGRES_NANNY_PORT}"$'\n'
        server_conf+=$'nascent:etcd_peer:address = '"${NASCENT_ETCD_PEER_PORT}"$'\n'
        server_conf+=$'nascent:etcd_client:address = '"${NASCENT_ETCD_CLIENT_PORT}"$'\n'
    fi
    start_web_server=0
    [[ "${ENABLE_WEB}" != "true" ]] || start_web_server=1
    web_conf=$'[settings]\nmgmtHostPort = 0.0.0.0:'"${MGMT_PORT}"$'\nhttpport = '"${WEB_PORT}"$'\n'
    web_conf+=$'appServerPorts = '"${APPSERVER_PORT}"$'\n'
    web_conf+=$'startwebserver = '"${start_web_server}"$'\n'
    hbs_write_target_file "${EXECUTION_MODE}" "${system_local}/server.conf" "600" "${server_conf}" "false" || return 1
    hbs_write_target_file "${EXECUTION_MODE}" "${system_local}/web.conf" "600" "${web_conf}" "false" || return 1
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown "${SERVICE_USER}" "${system_local}/server.conf" "${system_local}/web.conf")")" || return 1
}

assert_fresh_install_ports_free() {
    [[ "${INSTALL_ACTION}" == "fresh-install" ]] || return 0
    local port output
    local -a configured_ports=(
        "${MGMT_PORT}" "${WEB_PORT}" "${APPSERVER_PORT}" "${KVSTORE_PORT}" "${IPC_BROKER_PORT}"
    )
    local selected_port_log="mgmt=${MGMT_PORT}, web=${WEB_PORT}, appserver=${APPSERVER_PORT}, kvstore=${KVSTORE_PORT}, ipc_broker=${IPC_BROKER_PORT}"
    if enterprise_106_sidecars_enabled; then
        configured_ports+=(
            "${POSTGRES_PORT}" "${POSTGRES_PRIMARY_PORT}" "${POSTGRES_REPLICA_PORT}"
            "${POSTGRES_PATRONI_PORT}" "${POSTGRES_PGBOUNCER_PORT}" "${POSTGRES_NANNY_PORT}"
            "${NASCENT_ETCD_PEER_PORT}" "${NASCENT_ETCD_CLIENT_PORT}"
        )
        selected_port_log+=", postgres=${POSTGRES_PORT}/${POSTGRES_PRIMARY_PORT}/${POSTGRES_REPLICA_PORT}/${POSTGRES_PATRONI_PORT}/${POSTGRES_PGBOUNCER_PORT}/${POSTGRES_NANNY_PORT}, nascent=${NASCENT_ETCD_PEER_PORT}/${NASCENT_ETCD_CLIENT_PORT}"
    fi
    log "Checking selected ports: ${selected_port_log}"
    for port in "${configured_ports[@]}"; do
        if ! output="$(hbs_capture_target_cmd "${EXECUTION_MODE}" \
            "if command -v ss >/dev/null 2>&1; then $(hbs_shell_join ss -H -ltn "sport = :${port}"); elif command -v lsof >/dev/null 2>&1; then $(hbs_shell_join lsof -nP "-iTCP:${port}" -sTCP:LISTEN -t) || [[ \$? -eq 1 ]]; else exit 127; fi")"; then
            log "ERROR: Could not verify target port ${port}; install halted before mutation."
            return 1
        fi
        if [[ -n "${output}" ]]; then
            log "ERROR: Target port ${port} is already listening; choose a free alternate port."
            return 1
        fi
    done
}

restart_splunk() {
    if capture_splunk_as_service_user "$(splunk_cli_cmd status)" >/dev/null 2>&1; then
        run_splunk_as_service_user "$(splunk_cli_cmd restart)"
    else
        start_splunk
    fi
}

verify_user_seed_readable() {
    [[ "${INSTALL_ACTION}" == "fresh-install" ]] || return 0
    local user_seed_path raw_cmd metadata
    user_seed_path="${SPLUNK_HOME}/etc/system/local/user-seed.conf"
    raw_cmd="$(hbs_shell_join test -r "${user_seed_path}") && $(hbs_shell_join test -s "${user_seed_path}")"
    if ! hbs_run_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}"; then
        metadata="$(hbs_capture_target_cmd "${EXECUTION_MODE}" \
            "if [[ -e $(hbs_shell_join "${user_seed_path}") ]]; then $(hbs_shell_join stat -c '%U %a %s' "${user_seed_path}"); else printf absent; fi" 2>/dev/null || true)"
        log "ERROR: Initial admin user-seed.conf is missing, empty, or unreadable by ${SERVICE_USER} (target metadata: ${metadata:-unavailable}); refusing to report a successful install."
        return 1
    fi
    log "Verified the initial admin seed is present and readable by ${SERVICE_USER}."
}

verify_initial_admin_account() {
    [[ "${INSTALL_ACTION}" == "fresh-install" ]] || return 0
    local passwd_path attempt
    passwd_path="${SPLUNK_HOME}/etc/passwd"
    for ((attempt = 1; attempt <= 10; attempt++)); do
        if hbs_run_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "$(hbs_shell_join test -s "${passwd_path}")" >/dev/null 2>&1; then
            log "Verified Splunk created its initial local account database."
            return 0
        fi
        sleep 1
    done
    log "ERROR: Splunk started without creating ${passwd_path} from user-seed.conf; initial admin setup is incomplete."
    return 1
}

enable_boot_start() {
    local cmd
    cmd="$(splunk_cli_cmd enable boot-start -user "${SERVICE_USER}" --accept-license --answer-yes --no-prompt)"
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "${cmd}")"
}

enable_web_if_needed() {
    [[ "${ENABLE_WEB}" == "true" ]] || return 0
    if [[ "${INSTALL_ACTION}" == "fresh-install" ]]; then
        log "Splunk Web was configured before the first start; no authenticated CLI change is needed."
        return 0
    fi
    run_splunk_authenticated "$(splunk_cli_cmd enable webserver)"
}

stop_splunk_if_running() {
    if capture_splunk_as_service_user "$(splunk_cli_cmd status)" >/dev/null 2>&1; then
        log "Stopping existing Splunk instance before upgrade"
        run_splunk_as_service_user "$(splunk_cli_cmd stop)"
    else
        log "INFO: Splunk was not running before upgrade; proceeding with package upgrade."
    fi
}

render_inputs_conf() {
    cat <<EOF
[splunktcp://${RECEIVER_PORT}]
disabled = 0
EOF
}

render_outputs_conf() {
    if [[ "${FORWARDING_MODE}" == "indexer-discovery" ]]; then
        cat <<EOF
[tcpout]
defaultGroup = ${TCPOUT_GROUP}
indexAndForward = false

[indexer_discovery:${INDEXER_DISCOVERY_NAME}]
pass4SymmKey = ${DISCOVERY_SECRET}
manager_uri = ${CLUSTER_MANAGER_URI}

[tcpout:${TCPOUT_GROUP}]
indexerDiscovery = ${INDEXER_DISCOVERY_NAME}
useACK = true
autoLBFrequency = 30
forceTimebasedAutoLB = true
EOF
    else
        cat <<EOF
[tcpout]
defaultGroup = ${TCPOUT_GROUP}
indexAndForward = false

[tcpout:${TCPOUT_GROUP}]
server = ${SERVER_LIST}
useACK = true
autoLBFrequency = 30
forceTimebasedAutoLB = true
EOF
    fi
}

render_cluster_manager_server_conf() {
    cat <<EOF
[clustering]
mode = manager
replication_factor = ${REPLICATION_FACTOR}
search_factor = ${SEARCH_FACTOR}
pass4SymmKey = ${IDXC_SECRET}
cluster_label = ${IDXC_LABEL}

[indexer_discovery]
pass4SymmKey = ${DISCOVERY_SECRET}
polling_rate = 60
indexerWeightByDiskCapacity = true
EOF
}

render_indexer_peer_server_conf() {
    cat <<EOF
[clustering]
mode = peer
manager_uri = ${CLUSTER_MANAGER_URI}
pass4SymmKey = ${IDXC_SECRET}

[replication_port://${REPLICATION_PORT}]
disabled = false
EOF
}

render_shc_deployer_server_conf() {
    cat <<EOF
[shclustering]
pass4SymmKey = ${SHC_SECRET}
shcluster_label = ${SHCLUSTER_LABEL}
EOF
}

render_shc_member_server_conf() {
    local local_mgmt_uri="$1"

    cat <<EOF
[shclustering]
disabled = 0
mgmt_uri = ${local_mgmt_uri}
replication_factor = ${SHC_REPLICATION_FACTOR}
conf_deploy_fetch_url = ${DEPLOYER_URI}
pass4SymmKey = ${SHC_SECRET}
shcluster_label = ${SHCLUSTER_LABEL}

# Dedicated replication_port stanza matches 'splunk init shcluster-config'
# canonical output (and the indexer-peer path above), not a [shclustering] key.
[replication_port://${SHC_REPLICATION_PORT}]
disabled = false
EOF

    if [[ -n "${CLUSTER_MANAGER_URI}" ]]; then
        cat <<EOF

[clustering]
mode = searchhead
manager_uri = ${CLUSTER_MANAGER_URI}
pass4SymmKey = ${IDXC_SECRET}
EOF
    fi
}

configure_base_role() {
    local needs_restart=false

    case "${HOST_BOOTSTRAP_ROLE}" in
        standalone-search-tier)
            enable_web_if_needed
            ;;
        standalone-indexer|indexer-peer)
            write_splunk_config "${SPLUNK_HOME}/etc/apps/ZZZ_cisco_skills_receiving/local/inputs.conf" "$(render_inputs_conf)"
            needs_restart=true
            ;;
        heavy-forwarder)
            if [[ "${FORWARDING_MODE}" == "indexer-discovery" ]]; then
                ensure_prompted_value CLUSTER_MANAGER_URI "Cluster manager URI"
                if [[ -z "${DISCOVERY_SECRET}" ]]; then
                    ensure_prompted_path DISCOVERY_SECRET_FILE "Indexer discovery secret file path"
                    DISCOVERY_SECRET="$(read_secret_file "${DISCOVERY_SECRET_FILE}")"
                fi
            else
                ensure_prompted_value SERVER_LIST "Indexer server list"
            fi
            write_splunk_config "${SPLUNK_HOME}/etc/apps/ZZZ_cisco_skills_forwarding/local/outputs.conf" "$(render_outputs_conf)"
            needs_restart=true
            ;;
        shc-member)
            enable_web_if_needed
            ;;
    esac

    if [[ "${needs_restart}" == "true" ]]; then
        restart_splunk
    fi
}

configure_cluster_role() {
    case "${HOST_BOOTSTRAP_ROLE}" in
        cluster-manager)
            if [[ -z "${IDXC_SECRET}" ]]; then
                ensure_prompted_path IDXC_SECRET_FILE "Indexer cluster secret file path"
                IDXC_SECRET="$(read_secret_file "${IDXC_SECRET_FILE}")"
            fi
            if [[ -z "${DISCOVERY_SECRET}" ]]; then
                DISCOVERY_SECRET="${IDXC_SECRET}"
            fi
            write_splunk_config "${SPLUNK_HOME}/etc/apps/ZZZ_cisco_skills_enterprise_role/local/server.conf" "$(render_cluster_manager_server_conf)"
            restart_splunk
            ;;
        indexer-peer)
            ensure_prompted_value CLUSTER_MANAGER_URI "Cluster manager URI"
            if [[ -z "${IDXC_SECRET}" ]]; then
                ensure_prompted_path IDXC_SECRET_FILE "Indexer cluster secret file path"
                IDXC_SECRET="$(read_secret_file "${IDXC_SECRET_FILE}")"
            fi
            write_splunk_config "${SPLUNK_HOME}/etc/apps/ZZZ_cisco_skills_enterprise_role/local/server.conf" "$(render_indexer_peer_server_conf)"
            restart_splunk
            ;;
        shc-deployer)
            if [[ -z "${SHC_SECRET}" ]]; then
                ensure_prompted_path SHC_SECRET_FILE "Search head cluster secret file path"
                SHC_SECRET="$(read_secret_file "${SHC_SECRET_FILE}")"
            fi
            write_splunk_config "${SPLUNK_HOME}/etc/apps/ZZZ_cisco_skills_enterprise_role/local/server.conf" "$(render_shc_deployer_server_conf)"
            restart_splunk
            ;;
        shc-member)
            local local_mgmt_uri
            if [[ -z "${SHC_SECRET}" ]]; then
                ensure_prompted_path SHC_SECRET_FILE "Search head cluster secret file path"
                SHC_SECRET="$(read_secret_file "${SHC_SECRET_FILE}")"
            fi
            ensure_prompted_value DEPLOYER_URI "Search head cluster deployer URI"
            local_mgmt_uri="https://${ADVERTISE_HOST}:${MGMT_PORT}"

            if [[ -n "${CLUSTER_MANAGER_URI}" || -n "${IDXC_SECRET}" || -n "${IDXC_SECRET_FILE}" ]]; then
                ensure_prompted_value CLUSTER_MANAGER_URI "Cluster manager URI"
                if [[ -z "${IDXC_SECRET}" ]]; then
                    ensure_prompted_path IDXC_SECRET_FILE "Indexer cluster secret file path"
                    IDXC_SECRET="$(read_secret_file "${IDXC_SECRET_FILE}")"
                fi
            fi

            write_shc_member_system_local_config "$(render_shc_member_server_conf "${local_mgmt_uri}")"
            restart_splunk

            if [[ "${BOOTSTRAP_SHC}" == "true" ]]; then
                ensure_prompted_value SHC_MEMBERS "Search head cluster members list"
                run_splunk_authenticated \
                    "$(splunk_cli_cmd bootstrap shcluster-captain -servers_list "${SHC_MEMBERS}")"
            else
                ensure_prompted_value CURRENT_SHC_MEMBER_URI "Current search head cluster member URI"
                run_splunk_authenticated \
                    "$(splunk_cli_cmd add shcluster-member -current_member_uri "${CURRENT_SHC_MEMBER_URI}")"
            fi
            ;;
    esac
}

remove_user_seed() {
    cleanup_user_seed_artifacts
}

cleanup_user_seed_artifacts() {
    local user_seed_path user_seed_dir cleanup_cmd
    user_seed_path="${SPLUNK_HOME}/etc/system/local/user-seed.conf"
    user_seed_dir="$(dirname "${user_seed_path}")"
    hbs_remove_target_path "${EXECUTION_MODE}" "${user_seed_path}"
    cleanup_cmd="if [[ -d $(hbs_shell_join "${user_seed_dir}") ]]; then $(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join find "${user_seed_dir}" -maxdepth 1 -type f -name 'user-seed.conf.bak.*' -delete)"); fi"
    hbs_run_target_cmd "${EXECUTION_MODE}" "${cleanup_cmd}" >/dev/null 2>&1 || true
}

cleanup_install_artifacts() {
    if [[ "${PACKAGE_STAGED}" == "true" ]]; then
        hbs_remove_target_path "${EXECUTION_MODE}" "${PACKAGE_ON_TARGET}"
    fi
    cleanup_user_seed_artifacts
}

register_install_cleanup() {
    if [[ "${INSTALL_CLEANUP_REGISTERED}" == "true" ]]; then
        return 0
    fi
    trap cleanup_install_artifacts EXIT
    INSTALL_CLEANUP_REGISTERED=true
}

finalize_install() {
    ensure_service_user_exists
    ensure_splunk_ownership
    configure_fresh_install_ports
    write_user_seed
    verify_user_seed_readable || return 1
    start_splunk
    verify_initial_admin_account || return 1
    remove_user_seed
    if [[ "${BOOT_START}" == "true" ]]; then
        enable_boot_start
    fi
}

finalize_upgrade() {
    ensure_service_user_exists
    ensure_splunk_ownership
    start_splunk
    if [[ "${BOOT_START}" == "true" ]]; then
        enable_boot_start
    fi
}

perform_install_phase() {
    case "${INSTALL_ACTION}" in
        fresh-install)
            validate_install_constraints
            log "Installing ${PACKAGE_TYPE} package for role ${HOST_BOOTSTRAP_ROLE}"
            install_package_to_target
            finalize_install
            ;;
        upgrade)
            validate_install_constraints
            if [[ -n "${INSTALLED_VERSION}" && -n "${PACKAGE_VERSION}" ]]; then
                log "Upgrading Splunk from ${INSTALLED_VERSION} to ${PACKAGE_VERSION} for role ${HOST_BOOTSTRAP_ROLE}"
            elif [[ -n "${INSTALLED_VERSION}" ]]; then
                log "Upgrading existing Splunk ${INSTALLED_VERSION} with ${PACKAGE_TYPE} package for role ${HOST_BOOTSTRAP_ROLE}"
            else
                log "Upgrading existing Splunk install with ${PACKAGE_TYPE} package for role ${HOST_BOOTSTRAP_ROLE}"
            fi
            warn_clustered_upgrade_scope
            stop_splunk_if_running
            install_package_to_target
            finalize_upgrade
            ;;
        same-version)
            if [[ -n "${INSTALLED_VERSION}" ]]; then
                log "Installed Splunk version ${INSTALLED_VERSION} already matches the requested package; skipping package install."
            else
                log "Requested package matches the installed Splunk version; skipping package install."
            fi
            cleanup_user_seed_artifacts
            ;;
        *)
            log "ERROR: Unsupported install action '${INSTALL_ACTION}'."
            exit 1
            ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --url) require_arg "$1" $# || exit 1; PACKAGE_URL="$2"; shift 2 ;;
        --file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --package-type) require_arg "$1" $# || exit 1; PACKAGE_TYPE="$2"; shift 2 ;;
        --allow-stale-latest) ALLOW_STALE_LATEST=true; shift ;;
        --execution) require_arg "$1" $# || exit 1; EXECUTION_MODE="$2"; shift 2 ;;
        --host-bootstrap-role) require_arg "$1" $# || exit 1; HOST_BOOTSTRAP_ROLE="$2"; shift 2 ;;
        --deployment-mode) require_arg "$1" $# || exit 1; DEPLOYMENT_MODE="$2"; shift 2 ;;
        --cluster-site) require_arg "$1" $# || exit 1; CLUSTER_SITE="$2"; shift 2 ;;
        --checksum) require_arg "$1" $# || exit 1; CHECKSUM="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME="$2"; shift 2 ;;
        --service-user) require_arg "$1" $# || exit 1; SERVICE_USER="$2"; shift 2 ;;
        --advertise-host) require_arg "$1" $# || exit 1; ADVERTISE_HOST="$2"; shift 2 ;;
        --mgmt-port) require_arg "$1" $# || exit 1; MGMT_PORT="$2"; shift 2 ;;
        --web-port) require_arg "$1" $# || exit 1; WEB_PORT="$2"; ENABLE_WEB="true"; shift 2 ;;
        --appserver-port) require_arg "$1" $# || exit 1; APPSERVER_PORT="$2"; shift 2 ;;
        --kvstore-port) require_arg "$1" $# || exit 1; KVSTORE_PORT="$2"; shift 2 ;;
        --ipc-broker-port) require_arg "$1" $# || exit 1; IPC_BROKER_PORT="$2"; shift 2 ;;
        --postgres-port) require_arg "$1" $# || exit 1; POSTGRES_PORT="$2"; shift 2 ;;
        --postgres-primary-port) require_arg "$1" $# || exit 1; POSTGRES_PRIMARY_PORT="$2"; shift 2 ;;
        --postgres-replica-port) require_arg "$1" $# || exit 1; POSTGRES_REPLICA_PORT="$2"; shift 2 ;;
        --postgres-patroni-port) require_arg "$1" $# || exit 1; POSTGRES_PATRONI_PORT="$2"; shift 2 ;;
        --postgres-pgbouncer-port) require_arg "$1" $# || exit 1; POSTGRES_PGBOUNCER_PORT="$2"; shift 2 ;;
        --postgres-nanny-port) require_arg "$1" $# || exit 1; POSTGRES_NANNY_PORT="$2"; shift 2 ;;
        --nascent-etcd-peer-port) require_arg "$1" $# || exit 1; NASCENT_ETCD_PEER_PORT="$2"; shift 2 ;;
        --nascent-etcd-client-port) require_arg "$1" $# || exit 1; NASCENT_ETCD_CLIENT_PORT="$2"; shift 2 ;;
        --admin-user) require_arg "$1" $# || exit 1; ADMIN_USER="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --idxc-secret-file) require_arg "$1" $# || exit 1; IDXC_SECRET_FILE="$2"; shift 2 ;;
        --discovery-secret-file) require_arg "$1" $# || exit 1; DISCOVERY_SECRET_FILE="$2"; shift 2 ;;
        --shc-secret-file) require_arg "$1" $# || exit 1; SHC_SECRET_FILE="$2"; shift 2 ;;
        --enable-web) ENABLE_WEB="true"; shift ;;
        --no-boot-start) BOOT_START=false; shift ;;
        --receiver-port) require_arg "$1" $# || exit 1; RECEIVER_PORT="$2"; shift 2 ;;
        --forwarding-mode) require_arg "$1" $# || exit 1; FORWARDING_MODE="$2"; shift 2 ;;
        --server-list) require_arg "$1" $# || exit 1; SERVER_LIST="$2"; shift 2 ;;
        --cluster-manager-uri) require_arg "$1" $# || exit 1; CLUSTER_MANAGER_URI="$2"; shift 2 ;;
        --replication-factor) require_arg "$1" $# || exit 1; REPLICATION_FACTOR="$2"; shift 2 ;;
        --search-factor) require_arg "$1" $# || exit 1; SEARCH_FACTOR="$2"; shift 2 ;;
        --replication-port) require_arg "$1" $# || exit 1; REPLICATION_PORT="$2"; shift 2 ;;
        --idxc-label) require_arg "$1" $# || exit 1; IDXC_LABEL="$2"; shift 2 ;;
        --indexer-discovery-name) require_arg "$1" $# || exit 1; INDEXER_DISCOVERY_NAME="$2"; shift 2 ;;
        --tcpout-group) require_arg "$1" $# || exit 1; TCPOUT_GROUP="$2"; shift 2 ;;
        --deployer-uri) require_arg "$1" $# || exit 1; DEPLOYER_URI="$2"; shift 2 ;;
        --shcluster-label) require_arg "$1" $# || exit 1; SHCLUSTER_LABEL="$2"; shift 2 ;;
        --shc-replication-port) require_arg "$1" $# || exit 1; SHC_REPLICATION_PORT="$2"; shift 2 ;;
        --shc-replication-factor) require_arg "$1" $# || exit 1; SHC_REPLICATION_FACTOR="$2"; shift 2 ;;
        --shc-members) require_arg "$1" $# || exit 1; SHC_MEMBERS="$2"; shift 2 ;;
        --current-shc-member-uri) require_arg "$1" $# || exit 1; CURRENT_SHC_MEMBER_URI="$2"; shift 2 ;;
        --bootstrap-shc) BOOTSTRAP_SHC=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_role_defaults
validate_inputs

if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
    if ! load_splunk_ssh_credentials; then
        log "ERROR: Could not load the selected Splunk SSH target credentials."
        exit 1
    fi
    if [[ "${SPLUNK_SSH_USER}" != "root" && "${SPLUNK_REMOTE_SUDO}" == "true" ]]; then
        log "INFO: SSH bootstrap assumes ${SPLUNK_SSH_USER} can run sudo non-interactively on the target host."
    fi
fi

if phase_includes_download; then
    pick_package_path
fi

if [[ "${PHASE}" == "download" ]]; then
    log "Downloaded package ready at ${PACKAGE_PATH}"
    exit 0
fi

if phase_includes_install; then
    if [[ -z "${PACKAGE_PATH}" ]]; then
        pick_package_path
    fi
    determine_install_action
    validate_install_constraints
    validate_sidecar_port_values || exit 1
    assert_fresh_install_ports_free || exit 1
fi

load_secret_values

if phase_includes_install; then
    perform_install_phase
fi

if phase_includes_configure; then
    require_supported_installed_enterprise_version
    log "Applying base configuration for role ${HOST_BOOTSTRAP_ROLE}"
    configure_base_role
fi

if phase_includes_cluster; then
    if [[ "${DEPLOYMENT_MODE}" != "clustered" ]]; then
        log "Skipping cluster phase because deployment mode is standalone."
    else
        require_supported_installed_enterprise_version
        log "Applying clustered configuration for role ${HOST_BOOTSTRAP_ROLE}"
        configure_cluster_role
    fi
fi

if [[ "${INSTALL_CLEANUP_REGISTERED}" == "true" ]]; then
    cleanup_install_artifacts
    trap - EXIT
fi
log "Host bootstrap completed for role ${HOST_BOOTSTRAP_ROLE}"
