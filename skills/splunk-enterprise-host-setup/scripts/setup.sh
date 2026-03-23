#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

PROJECT_PKG_DIR="${SCRIPT_DIR}/../../../splunk-ta"
SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
SERVICE_USER="${SERVICE_USER:-splunk}"
MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"
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
  --mgmt-port PORT

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
    if phase_includes_install; then
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
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "${create_cmd}")" >/dev/null 2>&1 || true
}

ensure_splunk_ownership() {
    if [[ "${EXECUTION_MODE}" == "local" ]] && [[ "$(id -un)" == "${SERVICE_USER}" ]] && [[ -w "${SPLUNK_HOME}" ]]; then
        return 0
    fi
    hbs_run_target_cmd "${EXECUTION_MODE}" \
        "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown -R "${SERVICE_USER}:${SERVICE_USER}" "${SPLUNK_HOME}")")"
}

install_package_to_target() {
    local install_parent install_cmd sudo_prefix tmp_root

    PACKAGE_ON_TARGET="$(hbs_stage_file_for_execution "${EXECUTION_MODE}" "${PACKAGE_PATH}" "$(basename "${PACKAGE_PATH}")")"
    PACKAGE_STAGED=false
    if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
        PACKAGE_STAGED=true
    fi
    register_install_cleanup

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

run_privileged() {
    if [[ -n "\${sudo_prefix}" ]]; then
        "\${sudo_prefix}" "\$@"
    else
        "\$@"
    fi
}

if [[ -x "\${target_home}/bin/splunk" ]]; then
    echo "Existing Splunk install detected at \${target_home}; skipping extract."
    exit 0
fi

if [[ -e "\${target_home}" ]]; then
    echo "ERROR: Target path \${target_home} already exists but is not a Splunk install." >&2
    exit 1
fi

run_privileged mkdir -p "\${install_parent}" "\${tmp_root}"
extract_dir=\$(run_privileged mktemp -d "\${tmp_root%/}/splunk-install.XXXXXX")
cleanup() {
    run_privileged rm -rf "\${extract_dir}"
}
trap cleanup EXIT

run_privileged tar -xzf "\${package_path}" -C "\${extract_dir}"
if [[ ! -d "\${extract_dir}/splunk" ]]; then
    echo "ERROR: Extracted package did not contain a splunk/ directory." >&2
    exit 1
fi
run_privileged mv "\${extract_dir}/splunk" "\${target_home}"
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
    hbs_write_target_file "${EXECUTION_MODE}" "${user_seed_path}" "600" "${content}" "false"
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

splunk_auth_stdin() {
    printf '%s\n%s\n' "${ADMIN_USER}" "${ADMIN_PASSWORD}"
}

run_splunk_authenticated() {
    local raw_cmd="${1:-}"
    run_splunk_as_service_user_with_input "${raw_cmd}" "$(splunk_auth_stdin)"
}

start_splunk() {
    run_splunk_as_service_user "$(splunk_cli_cmd start --accept-license --answer-yes --no-prompt)"
}

restart_splunk() {
    if capture_splunk_as_service_user "$(splunk_cli_cmd status)" >/dev/null 2>&1; then
        run_splunk_as_service_user "$(splunk_cli_cmd restart)"
    else
        start_splunk
    fi
}

enable_boot_start() {
    local cmd
    cmd="$(splunk_cli_cmd enable boot-start -user "${SERVICE_USER}" --accept-license --answer-yes --no-prompt)"
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "${cmd}")"
}

enable_web_if_needed() {
    [[ "${ENABLE_WEB}" == "true" ]] || return 0
    run_splunk_authenticated "$(splunk_cli_cmd enable webserver)"
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

configure_base_role() {
    local needs_restart=false

    case "${HOST_BOOTSTRAP_ROLE}" in
        standalone-search-tier)
            enable_web_if_needed
            ;;
        standalone-indexer|indexer-peer)
            hbs_write_target_file "${EXECUTION_MODE}" "${SPLUNK_HOME}/etc/system/local/inputs.conf" "600" "$(render_inputs_conf)"
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
            hbs_write_target_file "${EXECUTION_MODE}" "${SPLUNK_HOME}/etc/system/local/outputs.conf" "600" "$(render_outputs_conf)"
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
            hbs_write_target_file "${EXECUTION_MODE}" "${SPLUNK_HOME}/etc/system/local/server.conf" "600" "$(render_cluster_manager_server_conf)"
            restart_splunk
            ;;
        indexer-peer)
            ensure_prompted_value CLUSTER_MANAGER_URI "Cluster manager URI"
            if [[ -z "${IDXC_SECRET}" ]]; then
                ensure_prompted_path IDXC_SECRET_FILE "Indexer cluster secret file path"
                IDXC_SECRET="$(read_secret_file "${IDXC_SECRET_FILE}")"
            fi
            hbs_write_target_file "${EXECUTION_MODE}" "${SPLUNK_HOME}/etc/system/local/server.conf" "600" "$(render_indexer_peer_server_conf)"
            restart_splunk
            ;;
        shc-deployer)
            if [[ -z "${SHC_SECRET}" ]]; then
                ensure_prompted_path SHC_SECRET_FILE "Search head cluster secret file path"
                SHC_SECRET="$(read_secret_file "${SHC_SECRET_FILE}")"
            fi
            hbs_write_target_file "${EXECUTION_MODE}" "${SPLUNK_HOME}/etc/system/local/server.conf" "600" "$(render_shc_deployer_server_conf)"
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

            run_splunk_authenticated \
                "$(splunk_cli_cmd init shcluster-config -mgmt_uri "${local_mgmt_uri}" -replication_port "${SHC_REPLICATION_PORT}" -replication_factor "${SHC_REPLICATION_FACTOR}" -conf_deploy_fetch_url "${DEPLOYER_URI}" -secret "${SHC_SECRET}" -shcluster_label "${SHCLUSTER_LABEL}")"
            restart_splunk

            if [[ -n "${CLUSTER_MANAGER_URI}" || -n "${IDXC_SECRET}" || -n "${IDXC_SECRET_FILE}" ]]; then
                ensure_prompted_value CLUSTER_MANAGER_URI "Cluster manager URI"
                if [[ -z "${IDXC_SECRET}" ]]; then
                    ensure_prompted_path IDXC_SECRET_FILE "Indexer cluster secret file path"
                    IDXC_SECRET="$(read_secret_file "${IDXC_SECRET_FILE}")"
                fi
                run_splunk_authenticated \
                    "$(splunk_cli_cmd edit cluster-config -mode searchhead -manager_uri "${CLUSTER_MANAGER_URI}" -secret "${IDXC_SECRET}")"
                restart_splunk
            fi

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
    write_user_seed
    start_splunk
    remove_user_seed
    if [[ "${BOOT_START}" == "true" ]]; then
        enable_boot_start
    fi
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
load_secret_values

if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
    load_splunk_ssh_credentials
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
    validate_install_constraints
    log "Installing ${PACKAGE_TYPE} package for role ${HOST_BOOTSTRAP_ROLE}"
    install_package_to_target
    finalize_install
fi

if phase_includes_configure; then
    log "Applying base configuration for role ${HOST_BOOTSTRAP_ROLE}"
    configure_base_role
fi

if phase_includes_cluster; then
    if [[ "${DEPLOYMENT_MODE}" != "clustered" ]]; then
        log "Skipping cluster phase because deployment mode is standalone."
    else
        log "Applying clustered configuration for role ${HOST_BOOTSTRAP_ROLE}"
        configure_cluster_role
    fi
fi

if [[ "${INSTALL_CLEANUP_REGISTERED}" == "true" ]]; then
    cleanup_install_artifacts
    trap - EXIT
fi
log "Host bootstrap completed for role ${HOST_BOOTSTRAP_ROLE}"
