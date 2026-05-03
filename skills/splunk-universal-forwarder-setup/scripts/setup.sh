#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

PROJECT_PKG_DIR="${SCRIPT_DIR}/../../../splunk-ta"
RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-universal-forwarder-rendered"

PHASE="all"
TARGET_OS="auto"
TARGET_ARCH="auto"
EXECUTION_MODE="local"
SOURCE="auto"
PACKAGE_TYPE="auto"
PACKAGE_URL=""
LOCAL_FILE=""
CHECKSUM=""
ALLOW_STALE_LATEST=false
DRY_RUN=false
JSON_OUTPUT=false
OUTPUT_DIR=""
SPLUNK_HOME=""
SERVICE_USER=""
ADMIN_USER="admin"
ADMIN_PASSWORD_FILE=""
ENROLL_MODE="none"
DEPLOYMENT_SERVER=""
SERVER_LIST=""
CLOUD_CREDENTIALS_PACKAGE=""
CLIENT_NAME=""
PHONE_HOME_INTERVAL="60"
TCPOUT_GROUP="default-autolb-group"
USE_ACK="true"
BOOT_START=true
SPLUNK_REMOTE_SUDO="${SPLUNK_REMOTE_SUDO:-true}"

PACKAGE_PATH=""
PACKAGE_ON_TARGET=""
PACKAGE_STAGED=false
INSTALL_CLEANUP_REGISTERED=false
LATEST_UF_METADATA=""
LATEST_UF_METADATA_LIVE=false
INSTALL_ACTION=""
INSTALLED_VERSION=""
PACKAGE_VERSION=""
ADMIN_PASSWORD=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Universal Forwarder Setup

Usage: $(basename "$0") [OPTIONS]

Core options:
  --phase render|download|install|enroll|status|all
  --target-os auto|linux|macos|windows|freebsd|solaris|aix
  --target-arch auto|amd64|x64|x86|arm64|ppc64le|s390x|intel|universal2|freebsd13-amd64|freebsd14-amd64|sparc|powerpc
  --execution local|ssh|render
  --source auto|splunk-auth|remote|local
  --url latest|URL
  --file PATH
  --package-type auto|tgz|rpm|deb|msi|dmg|pkg|txz|p5p|tar-z
  --allow-stale-latest
  --output-dir PATH
  --dry-run
  --json

Install options:
  --splunk-home PATH
  --service-user USER
  --no-boot-start
  --checksum sha256:<value>

Enrollment:
  --enroll none|deployment-server|enterprise-indexers|splunk-cloud
  --deployment-server HOST:PORT
  --server-list HOST:9997[,HOST:9997...]
  --cloud-credentials-package PATH
  --client-name NAME
  --phone-home-interval SECONDS
  --use-ack true|false

Security:
  --admin-user USER
  --admin-password-file PATH

Examples:
  $(basename "$0") --phase all --target-os linux --source remote --url latest \\
    --enroll deployment-server --deployment-server ds01.example.com:8089 \\
    --admin-password-file /tmp/uf_admin_password

  $(basename "$0") --phase render --target-os windows --source local \\
    --file C:\\\\Temp\\\\splunkforwarder.msi --admin-password-file C:\\\\Temp\\\\uf_password.txt \\
    --enroll enterprise-indexers --server-list idx01.example.com:9997,idx02.example.com:9997

Notes:
  Linux and macOS support local/SSH apply in v1. Windows renders an
  administrator-run PowerShell/MSI bootstrap script. FreeBSD, Solaris, and AIX
  are recognized by latest resolution and metadata, but install/apply is not
  automated in v1.
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

validate_no_newline() {
    local value="${1:-}"
    local label="${2:-value}"
    if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* ]]; then
        log "ERROR: ${label} must not contain newlines."
        exit 1
    fi
}

validate_positive_int() {
    local value="${1:-}"
    local label="${2:-value}"
    if [[ ! "${value}" =~ ^[0-9]+$ || "${value}" -lt 1 ]]; then
        log "ERROR: ${label} must be a positive integer."
        exit 1
    fi
}

validate_host_port() {
    local value="${1:-}"
    local label="${2:-HOST:PORT}"
    local port=""
    validate_no_newline "${value}" "${label}"
    if [[ "${value}" =~ ^\[[^]]+\]:([0-9]+)$ ]]; then
        port="${BASH_REMATCH[1]}"
    elif [[ "${value}" =~ ^[^[:space:],:]+:([0-9]+)$ ]]; then
        port="${BASH_REMATCH[1]}"
    fi
    if [[ -n "${port}" && "${port}" -ge 1 && "${port}" -le 65535 ]]; then
        return 0
    fi
    log "ERROR: ${label} must be HOST:PORT or [IPv6]:PORT with a port from 1 to 65535."
    exit 1
}

validate_server_list() {
    local value="${1:-}"
    local item
    local -a _uf_servers=()
    validate_no_newline "${value}" "server list"
    IFS=',' read -ra _uf_servers <<< "${value}"
    if [[ "${#_uf_servers[@]}" -eq 0 ]]; then
        log "ERROR: server list must contain at least one HOST:PORT value."
        exit 1
    fi
    for item in "${_uf_servers[@]}"; do
        item="${item#"${item%%[![:space:]]*}"}"
        item="${item%"${item##*[![:space:]]}"}"
        [[ -n "${item}" ]] || { log "ERROR: server list contains an empty item."; exit 1; }
        validate_host_port "${item}" "server list item"
    done
}

normalize_server_list_value() {
    local value="${1:-}"
    python3 - "${value}" <<'PY'
import sys

items = [item.strip() for item in sys.argv[1].split(",")]
print(",".join(item for item in items if item), end="")
PY
}

validate_conf_stanza_token() {
    local value="${1:-}"
    local label="${2:-configuration token}"
    validate_no_newline "${value}" "${label}"
    if [[ "${value}" == *"["* || "${value}" == *"]"* ]]; then
        log "ERROR: ${label} must not contain square brackets."
        exit 1
    fi
}

validate_target_arch() {
    case "${TARGET_OS}:${TARGET_ARCH}" in
        linux:amd64|linux:arm64|linux:ppc64le|linux:s390x) ;;
        macos:intel|macos:universal2) ;;
        windows:x64|windows:x86) ;;
        freebsd:freebsd13-amd64|freebsd:freebsd14-amd64) ;;
        solaris:amd64|solaris:sparc) ;;
        aix:powerpc) ;;
        *)
            log "ERROR: Target architecture '${TARGET_ARCH}' is not valid for target OS '${TARGET_OS}'."
            exit 1
            ;;
    esac
}

validate_target_package_type() {
    local package_type="${1:-${PACKAGE_TYPE}}"
    [[ "${package_type}" != "auto" ]] || return 0
    case "${TARGET_OS}:${package_type}" in
        linux:tgz|linux:rpm|linux:deb) ;;
        macos:tgz|macos:dmg|macos:pkg) ;;
        windows:msi) ;;
        freebsd:tgz|freebsd:txz) ;;
        solaris:tar-z|solaris:p5p) ;;
        aix:tgz) ;;
        *)
            log "ERROR: Package type '${package_type}' is not valid for target OS '${TARGET_OS}'."
            exit 1
            ;;
    esac
}

ensure_prompted_value() {
    local var_name="$1"
    local prompt="$2"
    local default_value="${3:-}"
    local current_value="${!var_name:-}"
    if [[ -z "${current_value}" && "${DRY_RUN}" != "true" ]] && hbs_is_interactive; then
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
    if [[ -z "${current_value}" && "${DRY_RUN}" != "true" ]] && hbs_is_interactive; then
        current_value="$(hbs_prompt_secret_path "${prompt}")"
        printf -v "${var_name}" '%s' "${current_value}"
    fi
    if [[ -z "${!var_name:-}" ]]; then
        log "ERROR: ${prompt} is required."
        exit 1
    fi
}

phase_includes_render() {
    [[ "${PHASE}" == "render" || "${EXECUTION_MODE}" == "render" ]]
}

phase_includes_download() {
    [[ "${PHASE}" == "download" || "${PHASE}" == "install" || "${PHASE}" == "all" ]]
}

phase_includes_install() {
    [[ "${PHASE}" == "install" || "${PHASE}" == "all" ]]
}

phase_includes_enroll() {
    [[ "${PHASE}" == "enroll" || "${PHASE}" == "all" ]]
}

phase_includes_status() {
    [[ "${PHASE}" == "status" || "${PHASE}" == "all" ]]
}

normalize_target_os() {
    case "${TARGET_OS}" in
        darwin|osx) TARGET_OS="macos" ;;
        win) TARGET_OS="windows" ;;
    esac
}

detect_target_os() {
    [[ "${TARGET_OS}" != "auto" ]] && { normalize_target_os; return 0; }
    case "$(uname -s 2>/dev/null || printf unknown)" in
        Linux) TARGET_OS="linux" ;;
        Darwin) TARGET_OS="macos" ;;
        FreeBSD) TARGET_OS="freebsd" ;;
        SunOS) TARGET_OS="solaris" ;;
        AIX) TARGET_OS="aix" ;;
        *) TARGET_OS="linux" ;;
    esac
}

normalize_target_arch() {
    local arch="${TARGET_ARCH}"
    if [[ "${arch}" == "auto" ]]; then
        case "${TARGET_OS}" in
            windows) TARGET_ARCH="x64" ;;
            macos)
                if [[ "$(uname -s 2>/dev/null || true)" == "Darwin" ]]; then
                    case "$(uname -m 2>/dev/null || true)" in
                        x86_64|amd64) TARGET_ARCH="intel" ;;
                        *) TARGET_ARCH="universal2" ;;
                    esac
                else
                    TARGET_ARCH="universal2"
                fi
                ;;
            linux)
                if [[ "$(uname -s 2>/dev/null || true)" == "Linux" ]]; then
                    case "$(uname -m 2>/dev/null || true)" in
                        x86_64|amd64) TARGET_ARCH="amd64" ;;
                        aarch64|arm64) TARGET_ARCH="arm64" ;;
                        ppc64le) TARGET_ARCH="ppc64le" ;;
                        s390x) TARGET_ARCH="s390x" ;;
                        *) TARGET_ARCH="amd64" ;;
                    esac
                else
                    TARGET_ARCH="amd64"
                fi
                ;;
            freebsd) TARGET_ARCH="freebsd14-amd64" ;;
            solaris) TARGET_ARCH="amd64" ;;
            aix) TARGET_ARCH="powerpc" ;;
            *) TARGET_ARCH="amd64" ;;
        esac
        return 0
    fi
    case "${TARGET_OS}:${arch}" in
        windows:x86_64|windows:amd64) TARGET_ARCH="x64" ;;
        linux:x86_64|linux:x64) TARGET_ARCH="amd64" ;;
        linux:aarch64) TARGET_ARCH="arm64" ;;
        macos:x86_64|macos:amd64|macos:x64) TARGET_ARCH="intel" ;;
        macos:arm64|macos:aarch64|macos:universal) TARGET_ARCH="universal2" ;;
        freebsd:amd64|freebsd:x86_64|freebsd:x64) TARGET_ARCH="freebsd14-amd64" ;;
        freebsd:freebsd13-amd64|freebsd:freebsd14-amd64) TARGET_ARCH="${arch}" ;;
        solaris:x86_64|solaris:x64) TARGET_ARCH="amd64" ;;
        aix:ppc|aix:ppc64) TARGET_ARCH="powerpc" ;;
    esac
}

normalize_execution_mode_for_target() {
    if [[ "${TARGET_OS}" == "windows" && "${EXECUTION_MODE}" == "local" && "${PHASE}" =~ ^(render|install|enroll|all)$ ]]; then
        EXECUTION_MODE="render"
    fi
}

default_splunk_home() {
    case "${TARGET_OS}" in
        macos) printf '%s' "/Applications/splunkforwarder" ;;
        windows) printf '%s' 'C:\Program Files\SplunkUniversalForwarder' ;;
        *) printf '%s' "/opt/splunkforwarder" ;;
    esac
}

default_service_user() {
    case "${TARGET_OS}" in
        linux) printf '%s' "splunkfwd" ;;
        macos) id -un ;;
        *) printf '%s' "" ;;
    esac
}

resolve_latest_package_type() {
    local hbs_execution
    if [[ "${PACKAGE_TYPE}" != "auto" ]]; then
        hbs_normalize_universal_forwarder_package_type "${PACKAGE_TYPE}"
        return 0
    fi
    case "${TARGET_OS}" in
        linux)
            if [[ "${TARGET_ARCH}" == "amd64" || "${TARGET_ARCH}" == "arm64" ]]; then
                hbs_execution="${EXECUTION_MODE}"
                [[ "${hbs_execution}" == "render" ]] && hbs_execution="local"
                hbs_preferred_latest_package_type "${hbs_execution}"
            else
                printf '%s' "tgz"
            fi
            ;;
        macos) printf '%s' "tgz" ;;
        windows) printf '%s' "msi" ;;
        freebsd) printf '%s' "tgz" ;;
        solaris) printf '%s' "tar-z" ;;
        aix) printf '%s' "tgz" ;;
        *) printf '%s' "tgz" ;;
    esac
}

effective_package_type_for_apply_state() {
    if [[ "${PACKAGE_TYPE}" != "auto" ]]; then
        hbs_normalize_universal_forwarder_package_type "${PACKAGE_TYPE}"
        return 0
    fi
    case "${TARGET_OS}" in
        linux|macos|freebsd|aix) printf '%s' "tgz" ;;
        windows) printf '%s' "msi" ;;
        solaris) printf '%s' "tar-z" ;;
        *) printf '%s' "tgz" ;;
    esac
}

v1_apply_state() {
    local effective_package_type
    effective_package_type="$(effective_package_type_for_apply_state)"
    case "${TARGET_OS}:${effective_package_type}" in
        linux:tgz|linux:rpm|linux:deb|macos:tgz) printf '%s' "local-ssh" ;;
        macos:dmg) printf '%s' "download-only" ;;
        windows:msi) printf '%s' "render-only" ;;
        *) printf '%s' "unsupported-v1" ;;
    esac
}

ensure_platform_defaults() {
    detect_target_os
    normalize_target_arch
    if [[ -z "${SPLUNK_HOME}" ]]; then
        SPLUNK_HOME="$(default_splunk_home)"
    fi
    if [[ -z "${SERVICE_USER}" ]]; then
        SERVICE_USER="$(default_service_user)"
    fi
    if [[ -z "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(hbs_resolve_abs_path "${SCRIPT_DIR}/../../../${DEFAULT_RENDER_DIR_NAME}")"
    else
        OUTPUT_DIR="$(hbs_resolve_abs_path "${OUTPUT_DIR}")"
    fi
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
    elif [[ -n "${SPLUNK_USERNAME:-${SB_USER:-}}" || -n "${SPLUNK_PASSWORD:-${SB_PASS:-}}" ]]; then
        SOURCE="splunk-auth"
    else
        SOURCE="remote"
    fi
}

render_deploymentclient_conf() {
    cat <<EOF
# Rendered by splunk-universal-forwarder-setup. Review before applying.
[deployment-client]
phoneHomeIntervalInSecs = ${PHONE_HOME_INTERVAL}
EOF
    if [[ -n "${CLIENT_NAME}" ]]; then
        printf 'clientName = %s\n' "${CLIENT_NAME}"
    fi
    cat <<EOF

[target-broker:deploymentServer]
targetUri = ${DEPLOYMENT_SERVER}
EOF
}

render_outputs_conf() {
    cat <<EOF
# Rendered by splunk-universal-forwarder-setup. Review before applying.
[tcpout]
defaultGroup = ${TCPOUT_GROUP}

[tcpout:${TCPOUT_GROUP}]
server = ${SERVER_LIST}
useACK = ${USE_ACK}
autoLBFrequency = 30
forceTimebasedAutoLB = true
EOF
}

build_apply_source_command() {
    local -a apply_cmd
    [[ "${EXECUTION_MODE}" != "render" ]] || return 0

    apply_cmd=(
        bash "${SCRIPT_DIR}/setup.sh"
        --phase all
        --target-os "${TARGET_OS}"
        --target-arch "${TARGET_ARCH}"
        --execution "${EXECUTION_MODE}"
        --enroll "${ENROLL_MODE}"
        --package-type "${PACKAGE_TYPE}"
        --splunk-home "${SPLUNK_HOME}"
    )
    [[ "${SOURCE}" != "auto" ]] && apply_cmd+=(--source "${SOURCE}")
    [[ -n "${PACKAGE_URL}" ]] && apply_cmd+=(--url "${PACKAGE_URL}")
    if [[ -n "${LOCAL_FILE}" ]]; then
        apply_cmd+=(--file "${LOCAL_FILE}")
    elif [[ "${SOURCE}" == "local" && -n "${PACKAGE_PATH}" ]]; then
        apply_cmd+=(--file "${PACKAGE_PATH}")
    fi
    [[ -n "${CHECKSUM}" ]] && apply_cmd+=(--checksum "${CHECKSUM}")
    [[ "${ALLOW_STALE_LATEST}" == "true" ]] && apply_cmd+=(--allow-stale-latest)
    [[ -n "${SERVICE_USER}" ]] && apply_cmd+=(--service-user "${SERVICE_USER}")
    [[ "${BOOT_START}" == "false" ]] && apply_cmd+=(--no-boot-start)
    [[ -n "${ADMIN_USER}" ]] && apply_cmd+=(--admin-user "${ADMIN_USER}")
    [[ -n "${ADMIN_PASSWORD_FILE}" ]] && apply_cmd+=(--admin-password-file "${ADMIN_PASSWORD_FILE}")
    [[ -n "${DEPLOYMENT_SERVER}" ]] && apply_cmd+=(--deployment-server "${DEPLOYMENT_SERVER}")
    [[ -n "${SERVER_LIST}" ]] && apply_cmd+=(--server-list "${SERVER_LIST}")
    [[ -n "${CLOUD_CREDENTIALS_PACKAGE}" ]] && apply_cmd+=(--cloud-credentials-package "${CLOUD_CREDENTIALS_PACKAGE}")
    [[ -n "${CLIENT_NAME}" ]] && apply_cmd+=(--client-name "${CLIENT_NAME}")
    [[ -n "${PHONE_HOME_INTERVAL}" ]] && apply_cmd+=(--phone-home-interval "${PHONE_HOME_INTERVAL}")
    [[ -n "${TCPOUT_GROUP}" ]] && apply_cmd+=(--tcpout-group "${TCPOUT_GROUP}")
    [[ -n "${USE_ACK}" ]] && apply_cmd+=(--use-ack "${USE_ACK}")

    hbs_shell_join "${apply_cmd[@]}"
}

build_renderer_args() {
    local source_command
    source_command="$(build_apply_source_command)"
    RENDER_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --target-os "${TARGET_OS}"
        --target-arch "${TARGET_ARCH}"
        --package-type "${PACKAGE_TYPE}"
        --package-path "${PACKAGE_PATH:-${LOCAL_FILE}}"
        --splunk-home "${SPLUNK_HOME}"
        --service-user "${SERVICE_USER}"
        --admin-user "${ADMIN_USER}"
        --admin-password-file "${ADMIN_PASSWORD_FILE}"
        --enroll "${ENROLL_MODE}"
        --deployment-server "${DEPLOYMENT_SERVER}"
        --server-list "${SERVER_LIST}"
        --cloud-credentials-package "${CLOUD_CREDENTIALS_PACKAGE}"
        --client-name "${CLIENT_NAME}"
        --phone-home-interval "${PHONE_HOME_INTERVAL}"
        --tcpout-group "${TCPOUT_GROUP}"
        --use-ack "${USE_ACK}"
    )
    [[ -n "${source_command}" ]] && RENDER_ARGS+=(--source-command "${source_command}")
    return 0
}

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    [[ "${DRY_RUN}" == "true" ]] && extra_args+=(--dry-run)
    build_renderer_args
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" "${extra_args[@]}"
}

prepare_render_package_path() {
    [[ -n "${LOCAL_FILE}" && -z "${PACKAGE_PATH}" ]] || return 0
    if [[ "${TARGET_OS}" == "windows" ]]; then
        PACKAGE_PATH="${LOCAL_FILE}"
        validate_package_type_matches_path "${PACKAGE_PATH}" "${PACKAGE_TYPE}"
        return 0
    fi

    PACKAGE_PATH="$(hbs_resolve_abs_path "${LOCAL_FILE}")"
    if [[ "${PACKAGE_TYPE}" == "auto" ]]; then
        PACKAGE_TYPE="$(hbs_detect_package_type "${PACKAGE_PATH}")" || PACKAGE_TYPE="auto"
    else
        validate_package_type_matches_path "${PACKAGE_PATH}" "${PACKAGE_TYPE}"
    fi
    validate_target_package_type
}

dry_run_plan() {
    local apply_state
    apply_state="$(v1_apply_state)"
    build_renderer_args
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        python3 - "${PHASE}" "${TARGET_OS}" "${TARGET_ARCH}" "${PACKAGE_TYPE}" "${SOURCE}" "${EXECUTION_MODE}" "${ENROLL_MODE}" "${SPLUNK_HOME}" "${SERVICE_USER}" "${apply_state}" <<'PY'
import json
import sys

keys = ["phase", "target_os", "target_arch", "package_type", "source", "execution", "enroll", "splunk_home", "service_user", "v1_apply"]
print(json.dumps({"workflow": "splunk-universal-forwarder-setup", **dict(zip(keys, sys.argv[1:]))}, indent=2, sort_keys=True))
PY
    else
        log "DRY RUN: Splunk Universal Forwarder ${PHASE} for ${TARGET_OS}/${TARGET_ARCH} using source ${SOURCE}, package type ${PACKAGE_TYPE}, execution ${EXECUTION_MODE}, enrollment ${ENROLL_MODE}, v1 apply ${apply_state}."
    fi
}

validate_inputs() {
    validate_choice "${PHASE}" render download install enroll status all
    validate_choice "${TARGET_OS}" linux macos windows freebsd solaris aix
    validate_choice "${EXECUTION_MODE}" local ssh render
    validate_choice "${SOURCE}" auto splunk-auth remote local
    PACKAGE_TYPE="$(hbs_normalize_universal_forwarder_package_type "${PACKAGE_TYPE}")"
    validate_choice "${PACKAGE_TYPE}" auto tgz rpm deb msi dmg pkg txz p5p tar-z
    validate_choice "${ENROLL_MODE}" none deployment-server enterprise-indexers splunk-cloud
    validate_choice "${USE_ACK}" true false
    validate_target_arch
    validate_target_package_type

    validate_positive_int "${PHONE_HOME_INTERVAL}" "phone-home interval"
    validate_no_newline "${ADMIN_USER}" "admin user"
    validate_no_newline "${CLIENT_NAME}" "client name"
    validate_conf_stanza_token "${TCPOUT_GROUP}" "tcpout group"
    validate_no_newline "${SPLUNK_HOME}" "Splunk home"
    validate_no_newline "${SERVICE_USER}" "service user"
    validate_no_newline "${LOCAL_FILE}" "package file path"
    validate_no_newline "${PACKAGE_URL}" "package URL"
    validate_no_newline "${CLOUD_CREDENTIALS_PACKAGE}" "Splunk Cloud credentials package path"

    if [[ "${EXECUTION_MODE}" == "ssh" && "${TARGET_OS}" == "windows" ]]; then
        log "ERROR: Windows WinRM/SSH apply is not supported in v1. Use --execution render."
        exit 1
    fi
    if [[ "${TARGET_OS}" == "windows" && "${PHASE}" == "status" && "${DRY_RUN}" != "true" ]]; then
        log "ERROR: Windows status checks require target-side validation in v1. Run the generated PowerShell script on the Windows host and verify the SplunkForwarder service there."
        exit 1
    fi
    if [[ "${TARGET_OS}" == "windows" && "${EXECUTION_MODE}" != "render" && "${PHASE}" != "download" ]]; then
        log "ERROR: Windows v1 renders an administrator-run PowerShell script. Use --execution render or --phase download."
        exit 1
    fi
    if [[ "${TARGET_OS}" =~ ^(freebsd|solaris|aix)$ ]] && [[ "${PHASE}" =~ ^(install|enroll|all)$ ]] && [[ "${EXECUTION_MODE}" != "render" && "${DRY_RUN}" != "true" ]]; then
        log "ERROR: ${TARGET_OS} packages are recognized by latest resolution, but install/apply is unsupported in v1."
        exit 1
    fi
    if [[ "${TARGET_OS}" == "macos" && "${PACKAGE_TYPE}" == "dmg" && "${PHASE}" =~ ^(install|all)$ ]] && [[ "${EXECUTION_MODE}" != "render" && "${DRY_RUN}" != "true" ]]; then
        log "ERROR: macOS .dmg packages are download/verify only in this automation. Use --package-type tgz for automated apply."
        exit 1
    fi
    if [[ "${ENROLL_MODE}" == "deployment-server" ]]; then
        ensure_prompted_value DEPLOYMENT_SERVER "Deployment server HOST:PORT"
        validate_host_port "${DEPLOYMENT_SERVER}" "deployment server"
    elif [[ "${ENROLL_MODE}" == "enterprise-indexers" ]]; then
        ensure_prompted_value SERVER_LIST "Indexer server list"
        validate_server_list "${SERVER_LIST}"
        SERVER_LIST="$(normalize_server_list_value "${SERVER_LIST}")"
    elif [[ "${ENROLL_MODE}" == "splunk-cloud" ]]; then
        ensure_prompted_path CLOUD_CREDENTIALS_PACKAGE "Splunk Cloud UF credentials package path"
    fi
}

load_secret_values() {
    if admin_password_required; then
        ensure_prompted_path ADMIN_PASSWORD_FILE "Admin password file path"
        ADMIN_PASSWORD="$(read_secret_file "${ADMIN_PASSWORD_FILE}")"
    fi
}

admin_password_required() {
    if phase_includes_install && [[ "${INSTALL_ACTION:-fresh-install}" == "fresh-install" ]]; then
        return 0
    fi
    if phase_includes_enroll && [[ "${ENROLL_MODE}" == "splunk-cloud" ]]; then
        return 0
    fi
    return 1
}

require_universal_forwarder_package() {
    local package_path="${1:-}"
    local lower_name
    lower_name="$(basename "${package_path}" | tr '[:upper:]' '[:lower:]')"
    if [[ "${lower_name}" != *splunkforwarder* && "${lower_name}" != *universalforwarder* ]]; then
        log "ERROR: Universal Forwarder setup requires a splunkforwarder package, not ${package_path}."
        log "Use splunk-enterprise-host-setup for full Splunk Enterprise or heavy forwarder hosts."
        exit 1
    fi
}

validate_package_type_matches_path() {
    local package_path="${1:-}"
    local explicit_package_type="${2:-auto}"
    local detected_package_type=""

    [[ -n "${package_path}" && "${explicit_package_type}" != "auto" ]] || return 0
    detected_package_type="$(hbs_detect_package_type "${package_path}")" || return 0
    if [[ "${detected_package_type}" != "${explicit_package_type}" ]]; then
        log "ERROR: --package-type ${explicit_package_type} does not match detected package type ${detected_package_type} for ${package_path}."
        exit 1
    fi
}

pick_package_path() {
    local download_user="" download_pass="" download_target latest_package_type="" resolved_metadata="" resolved_url="" latest_version=""
    local official_sha512="" official_sha512_url="" stale_cache_rc=0

    resolve_source_auto
    LATEST_UF_METADATA=""
    LATEST_UF_METADATA_LIVE=false

    case "${SOURCE}" in
        local)
            ensure_prompted_value LOCAL_FILE "Local Universal Forwarder package path"
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
                    log "INFO: Auto-selected ${latest_package_type} for latest Universal Forwarder resolution."
                fi
                log "Resolving latest official Splunk Universal Forwarder ${TARGET_OS}/${TARGET_ARCH}/${latest_package_type} download URL"
                if resolved_metadata="$(hbs_resolve_latest_universal_forwarder_download_metadata "${TARGET_OS}" "${TARGET_ARCH}" "${latest_package_type}")"; then
                    LATEST_UF_METADATA_LIVE=true
                else
                    if [[ "${ALLOW_STALE_LATEST}" != "true" ]]; then
                        log "ERROR: Failed to resolve the latest official Splunk Universal Forwarder ${TARGET_OS}/${TARGET_ARCH}/${latest_package_type} package. Re-run with --allow-stale-latest or provide --url."
                        exit 1
                    fi
                    log "WARN: Live latest resolution failed; attempting stale metadata fallback for ${TARGET_OS}/${TARGET_ARCH}/${latest_package_type}."
                    if resolved_metadata="$(hbs_read_latest_universal_forwarder_metadata_cache "${PROJECT_PKG_DIR}" "${TARGET_OS}" "${TARGET_ARCH}" "${latest_package_type}")"; then
                        :
                    else
                        stale_cache_rc=$?
                        if [[ "${stale_cache_rc}" -eq 2 ]]; then
                            log "ERROR: Cached latest metadata for ${TARGET_OS}/${TARGET_ARCH}/${latest_package_type} is older than 30 days. Provide --url or refresh live latest resolution."
                        else
                            log "ERROR: No usable cached latest metadata exists for ${TARGET_OS}/${TARGET_ARCH}/${latest_package_type}. Provide --url or retry once live latest resolution succeeds."
                        fi
                        exit 1
                    fi
                fi

                latest_version="$(hbs_latest_enterprise_metadata_field "${resolved_metadata}" "version")"
                resolved_url="$(hbs_latest_enterprise_metadata_field "${resolved_metadata}" "package_url")"
                [[ -n "${latest_version}" && -n "${resolved_url}" ]] || {
                    log "ERROR: Latest Universal Forwarder metadata was incomplete for ${TARGET_OS}/${TARGET_ARCH}/${latest_package_type}."
                    exit 1
                }
                LATEST_UF_METADATA="${resolved_metadata}"
                PACKAGE_URL="${resolved_url}"
                PACKAGE_TYPE="${latest_package_type}"
                log "Resolved latest Splunk Universal Forwarder ${latest_version} package: ${PACKAGE_URL}"
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
    validate_package_type_matches_path "${PACKAGE_PATH}" "${PACKAGE_TYPE}"
    validate_target_package_type
    require_universal_forwarder_package "${PACKAGE_PATH}"

    if [[ -n "${LATEST_UF_METADATA}" ]]; then
        official_sha512_url="$(hbs_latest_enterprise_metadata_field "${LATEST_UF_METADATA}" "sha512_url")"
        official_sha512="$(hbs_latest_enterprise_metadata_field "${LATEST_UF_METADATA}" "sha512" 2>/dev/null || true)"
        if [[ -z "${official_sha512}" ]]; then
            log "Fetching official SHA512 from ${official_sha512_url}"
            official_sha512="$(hbs_fetch_expected_sha512 "${official_sha512_url}" "${download_user}" "${download_pass}")" || exit 1
            LATEST_UF_METADATA="$(hbs_latest_enterprise_metadata_with_sha512 "${LATEST_UF_METADATA}" "${official_sha512}")"
        fi
        log "Verifying ${PACKAGE_PATH} against Splunk's official SHA512 checksum"
        hbs_verify_sha512_checksum "${PACKAGE_PATH}" "${official_sha512}" || exit 1
        if [[ "${LATEST_UF_METADATA_LIVE}" == "true" ]]; then
            hbs_write_latest_universal_forwarder_metadata_cache "${PROJECT_PKG_DIR}" "${TARGET_OS}" "${TARGET_ARCH}" "${PACKAGE_TYPE}" "${LATEST_UF_METADATA}" || exit 1
        fi
    elif [[ "${PACKAGE_URL:-}" =~ ^https://download\.splunk\.com/ ]] && [[ -z "${CHECKSUM}" ]]; then
        # Operator pointed --url at the official Splunk download host but
        # did not pass --checksum. Try to fetch the matching .sha512 sidecar
        # (Splunk publishes one alongside every package) and verify against
        # it. Fail closed on any failure: an explicit Splunk URL is
        # high-trust enough that we should not silently fall through to "no
        # integrity check at all". Operators on internal mirrors who really
        # cannot fetch the sidecar can override with --checksum sha256:...
        # or sha512:... .
        local sidecar_url="${PACKAGE_URL}.sha512"
        log "Fetching SHA512 sidecar from ${sidecar_url} (no --checksum was provided)"
        local sidecar_hash=""
        sidecar_hash="$(hbs_fetch_expected_sha512 "${sidecar_url}" "${download_user}" "${download_pass}" 2>/dev/null || true)"
        if [[ -z "${sidecar_hash}" ]]; then
            log "ERROR: Could not fetch SHA512 sidecar at ${sidecar_url}."
            log "       The package was downloaded from ${PACKAGE_URL} but cannot be"
            log "       integrity-verified. Pass --checksum sha256:<hex> (or sha512:<hex>)"
            log "       if your environment cannot reach the sidecar URL."
            exit 1
        fi
        log "Verifying ${PACKAGE_PATH} against ${sidecar_url}"
        hbs_verify_sha512_checksum "${PACKAGE_PATH}" "${sidecar_hash}" || exit 1
    fi
    hbs_verify_checksum "${PACKAGE_PATH}" "${CHECKSUM}"
}

splunk_cli_cmd() {
    hbs_shell_join "${SPLUNK_HOME}/bin/splunk" "$@"
}

run_splunk_as_service_user() {
    local raw_cmd="${1:-}"
    if [[ -n "${SERVICE_USER}" ]]; then
        hbs_run_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}"
    else
        hbs_run_target_cmd "${EXECUTION_MODE}" "${raw_cmd}"
    fi
}

run_splunk_as_service_user_with_input() {
    local raw_cmd="${1:-}"
    local stdin_content="${2:-}"
    if [[ -n "${SERVICE_USER}" ]]; then
        hbs_run_as_user_cmd_with_stdin "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}" "${stdin_content}"
    else
        hbs_run_target_cmd_with_stdin "${EXECUTION_MODE}" "${raw_cmd}" "${stdin_content}"
    fi
}

capture_splunk_as_service_user() {
    local raw_cmd="${1:-}"
    if [[ -n "${SERVICE_USER}" ]]; then
        hbs_capture_as_user_cmd "${EXECUTION_MODE}" "${SERVICE_USER}" "${raw_cmd}"
    else
        hbs_capture_target_cmd "${EXECUTION_MODE}" "${raw_cmd}"
    fi
}

target_has_splunk_install() {
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_shell_join test -x "${SPLUNK_HOME}/bin/splunk")" >/dev/null 2>&1
}

target_install_is_universal_forwarder() {
    local version_output version_file_output
    version_output="$(capture_splunk_as_service_user "$(splunk_cli_cmd version)" 2>/dev/null || true)"
    version_file_output="$(hbs_capture_target_cmd "${EXECUTION_MODE}" "$(hbs_shell_join cat "${SPLUNK_HOME}/etc/splunk.version")" 2>/dev/null || true)"
    [[ "${version_output}" == *"Universal Forwarder"* || "${version_output}" == *"SplunkForwarder"* || "${version_file_output}" == *"splunkforwarder"* ]]
}

resolve_requested_package_version() {
    local package_version=""
    if [[ -n "${LATEST_UF_METADATA}" ]]; then
        package_version="$(hbs_latest_enterprise_metadata_field "${LATEST_UF_METADATA}" "version" 2>/dev/null || true)"
    fi
    if [[ -z "${package_version}" && -n "${PACKAGE_PATH}" ]]; then
        package_version="$(hbs_extract_splunk_package_version "${PACKAGE_PATH}")"
    fi
    printf '%s' "${package_version}"
}

capture_installed_splunk_version() {
    local version_output version
    version_output="$(capture_splunk_as_service_user "$(splunk_cli_cmd version)" 2>/dev/null || true)"
    version="$(hbs_extract_splunk_version "${version_output}")"
    printf '%s' "${version}"
}

determine_install_action() {
    PACKAGE_VERSION="$(resolve_requested_package_version)"
    INSTALLED_VERSION=""
    INSTALL_ACTION="fresh-install"
    if ! target_has_splunk_install; then
        return 0
    fi
    if ! target_install_is_universal_forwarder; then
        log "ERROR: Existing install at ${SPLUNK_HOME} is not a Universal Forwarder. Refusing to install UF over Splunk Enterprise."
        exit 1
    fi
    INSTALL_ACTION="upgrade"
    INSTALLED_VERSION="$(capture_installed_splunk_version)"
    if [[ -n "${INSTALLED_VERSION}" && -n "${PACKAGE_VERSION}" ]] && hbs_versions_equal "${INSTALLED_VERSION}" "${PACKAGE_VERSION}"; then
        INSTALL_ACTION="same-version"
    fi
}

ensure_service_user_exists() {
    [[ "${TARGET_OS}" == "linux" && -n "${SERVICE_USER}" ]] || return 0
    local create_cmd sudo_prefix
    sudo_prefix="$(hbs_target_sudo_prefix "${EXECUTION_MODE}")"
    create_cmd=$(
        cat <<EOF
set -euo pipefail
service_user=$(hbs_shell_join "${SERVICE_USER}")
splunk_home=$(hbs_shell_join "${SPLUNK_HOME}")
sudo_prefix=$(hbs_shell_join "${sudo_prefix}")

run_privileged() {
    if [[ -n "\${sudo_prefix}" ]]; then
        "\${sudo_prefix}" "\$@"
    else
        "\$@"
    fi
}

if ! id -u "\${service_user}" >/dev/null 2>&1; then
    if [[ -e "\${splunk_home}" ]]; then
        run_privileged useradd -r -M -d "\${splunk_home}" -s /bin/false "\${service_user}"
    else
        run_privileged useradd -r -m -d "\${splunk_home}" -s /bin/false "\${service_user}"
    fi
fi
EOF
    )
    hbs_run_target_cmd "${EXECUTION_MODE}" "${create_cmd}" >/dev/null || {
        log "ERROR: Failed to ensure service user ${SERVICE_USER} exists on target."
        exit 1
    }
}

ensure_splunk_ownership() {
    [[ -n "${SERVICE_USER}" ]] || return 0
    if [[ "${EXECUTION_MODE}" == "local" ]] && [[ "$(id -un)" == "${SERVICE_USER}" ]] && [[ -w "${SPLUNK_HOME}" ]]; then
        return 0
    fi
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join chown -R "${SERVICE_USER}:${SERVICE_USER}" "${SPLUNK_HOME}")")" || true
}

validate_install_constraints() {
    # Keep this case statement aligned with validate_target_package_type() and
    # the macOS row in reference.md. Operators sometimes pass --package-type
    # macos:pkg expecting an automated install path; the v1 install heredoc
    # only knows how to drive .tgz on macOS, so we reject .dmg and .pkg
    # explicitly with a clear next-step rather than the generic catch-all.
    case "${TARGET_OS}:${PACKAGE_TYPE}" in
        linux:tgz|linux:rpm|linux:deb|macos:tgz) ;;
        macos:dmg)
            log "ERROR: macOS .dmg packages are download/verify only in v1. Use --package-type tgz for automation."
            exit 1
            ;;
        macos:pkg)
            log "ERROR: macOS .pkg packages are render/download only in v1; the install path requires GUI interaction. Use --package-type tgz for automation, or run the .pkg installer manually after this script downloads + verifies it."
            exit 1
            ;;
        *)
            log "ERROR: Package type ${PACKAGE_TYPE} is not supported for automated ${TARGET_OS} install in v1."
            exit 1
            ;;
    esac
    if [[ "${PACKAGE_TYPE}" == "deb" && "${SPLUNK_HOME}" != "/opt/splunkforwarder" ]]; then
        log "ERROR: DEB installs only support /opt/splunkforwarder."
        exit 1
    fi
}

install_package_to_target() {
    local install_action install_parent install_cmd sudo_prefix tmp_root
    PACKAGE_ON_TARGET="$(hbs_stage_file_for_execution "${EXECUTION_MODE}" "${PACKAGE_PATH}" "$(basename "${PACKAGE_PATH}")")"
    PACKAGE_STAGED=false
    [[ "${EXECUTION_MODE}" == "ssh" ]] && PACKAGE_STAGED=true
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
        echo "ERROR: Target path \${target_home} already exists but is not a Universal Forwarder install." >&2
        exit 1
    fi
    run_privileged mkdir -p "\${install_parent}" "\${tmp_root}"
elif [[ "\${install_action}" == "upgrade" ]]; then
    if [[ ! -x "\${target_home}/bin/splunk" ]]; then
        echo "ERROR: Expected an existing Universal Forwarder install at \${target_home} for tgz upgrade." >&2
        exit 1
    fi
    run_privileged mkdir -p "\${tmp_root}"
else
    echo "ERROR: Unsupported install action '\${install_action}' for tgz package." >&2
    exit 1
fi

extract_dir=\$(run_privileged mktemp -d "\${tmp_root%/}/splunk-uf-install.XXXXXX")
cleanup() { run_privileged rm -rf "\${extract_dir}"; }
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
            if not safe_relative_path(member.linkname):
                fail(f"{member.name} -> {member.linkname}")
            link_target = os.path.abspath(os.path.join(os.path.dirname(target), member.linkname))
            if os.path.commonpath([destination, link_target]) != destination:
                fail(f"{member.name} -> {member.linkname}")
    try:
        archive.extractall(destination, members=members, filter="data")
    except TypeError:
        archive.extractall(destination, members=members)
PY
if [[ ! -d "\${extract_dir}/splunkforwarder" ]]; then
    echo "ERROR: Extracted package did not contain a splunkforwarder/ directory." >&2
    exit 1
fi
if [[ "\${install_action}" == "fresh-install" ]]; then
    run_privileged mv "\${extract_dir}/splunkforwarder" "\${target_home}"
else
    run_privileged cp -a "\${extract_dir}/splunkforwarder/." "\${target_home}/"
fi
EOF
            )
            hbs_run_target_cmd "${EXECUTION_MODE}" "${install_cmd}"
            ;;
        rpm)
            install_cmd="$(hbs_shell_join rpm -Uvh)"
            if [[ "${SPLUNK_HOME}" != "/opt/splunkforwarder" ]]; then
                install_cmd+=" $(hbs_shell_join --prefix "${SPLUNK_HOME}")"
            fi
            install_cmd+=" $(hbs_shell_join "${PACKAGE_ON_TARGET}")"
            hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "${install_cmd}")"
            ;;
        deb)
            hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join dpkg -i "${PACKAGE_ON_TARGET}")")"
            ;;
    esac
}

cleanup_user_seed_artifacts() {
    local user_seed_path user_seed_dir cleanup_cmd
    user_seed_path="${SPLUNK_HOME}/etc/system/local/user-seed.conf"
    user_seed_dir="$(dirname "${user_seed_path}")"
    hbs_remove_target_path "${EXECUTION_MODE}" "${user_seed_path}"
    cleanup_cmd="if [[ -d $(hbs_shell_join "${user_seed_dir}") ]]; then $(hbs_prefix_with_sudo "${EXECUTION_MODE}" "$(hbs_shell_join find "${user_seed_dir}" -maxdepth 1 -type f -name 'user-seed.conf.bak.*' -delete)"); fi"
    hbs_run_target_cmd "${EXECUTION_MODE}" "${cleanup_cmd}" >/dev/null 2>&1 || true
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
    [[ "${BOOT_START}" == "true" && "${TARGET_OS}" == "linux" && -n "${SERVICE_USER}" ]] || return 0
    local cmd
    cmd="$(splunk_cli_cmd enable boot-start -user "${SERVICE_USER}" --accept-license --answer-yes --no-prompt)"
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_prefix_with_sudo "${EXECUTION_MODE}" "${cmd}")" || true
}

stop_splunk_if_running() {
    if capture_splunk_as_service_user "$(splunk_cli_cmd status)" >/dev/null 2>&1; then
        log "Stopping existing Universal Forwarder before upgrade"
        run_splunk_as_service_user "$(splunk_cli_cmd stop)"
    else
        log "INFO: Universal Forwarder was not running before upgrade; proceeding."
    fi
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

finalize_fresh_install() {
    ensure_service_user_exists
    ensure_splunk_ownership
    write_user_seed
    start_splunk
    cleanup_user_seed_artifacts
    enable_boot_start
}

finalize_upgrade() {
    ensure_service_user_exists
    ensure_splunk_ownership
    start_splunk
    enable_boot_start
}

perform_install_phase() {
    validate_install_constraints
    case "${INSTALL_ACTION}" in
        fresh-install)
            log "Installing Splunk Universal Forwarder ${PACKAGE_TYPE} package"
            install_package_to_target
            finalize_fresh_install
            ;;
        upgrade)
            if [[ -n "${INSTALLED_VERSION}" && -n "${PACKAGE_VERSION}" ]]; then
                log "Upgrading Universal Forwarder from ${INSTALLED_VERSION} to ${PACKAGE_VERSION}"
            else
                log "Upgrading existing Universal Forwarder with ${PACKAGE_TYPE} package"
            fi
            stop_splunk_if_running
            install_package_to_target
            finalize_upgrade
            ;;
        same-version)
            log "Installed Universal Forwarder version ${INSTALLED_VERSION:-unknown} already matches requested package; skipping install."
            cleanup_user_seed_artifacts
            ;;
        *)
            log "ERROR: Unsupported install action '${INSTALL_ACTION}'."
            exit 1
            ;;
    esac
}

splunk_auth_stdin() {
    printf '%s\n%s\n' "${ADMIN_USER}" "${ADMIN_PASSWORD}"
}

apply_enrollment() {
    local needs_restart=false staged_cloud_package
    case "${ENROLL_MODE}" in
        none)
            return 0
            ;;
        deployment-server)
            hbs_write_target_file "${EXECUTION_MODE}" "${SPLUNK_HOME}/etc/system/local/deploymentclient.conf" "600" "$(render_deploymentclient_conf)"
            needs_restart=true
            ;;
        enterprise-indexers)
            hbs_write_target_file "${EXECUTION_MODE}" "${SPLUNK_HOME}/etc/system/local/outputs.conf" "600" "$(render_outputs_conf)"
            needs_restart=true
            ;;
        splunk-cloud)
            staged_cloud_package="$(hbs_stage_file_for_execution "${EXECUTION_MODE}" "${CLOUD_CREDENTIALS_PACKAGE}" "$(basename "${CLOUD_CREDENTIALS_PACKAGE}")")"
            run_splunk_as_service_user_with_input "$(splunk_cli_cmd install app "${staged_cloud_package}")" "$(splunk_auth_stdin)"
            if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
                hbs_remove_target_path "${EXECUTION_MODE}" "${staged_cloud_package}"
            fi
            needs_restart=true
            ;;
    esac
    if [[ "${needs_restart}" == "true" ]]; then
        restart_splunk
    fi
}

run_status() {
    log "Checking Universal Forwarder at ${SPLUNK_HOME}"
    hbs_run_target_cmd "${EXECUTION_MODE}" "$(hbs_shell_join test -x "${SPLUNK_HOME}/bin/splunk")"
    capture_splunk_as_service_user "$(splunk_cli_cmd version)"
    capture_splunk_as_service_user "$(splunk_cli_cmd status)"
    case "${ENROLL_MODE}" in
        deployment-server)
            capture_splunk_as_service_user "$(splunk_cli_cmd btool deploymentclient list --debug)" >/dev/null
            ;;
        enterprise-indexers|splunk-cloud)
            capture_splunk_as_service_user "$(splunk_cli_cmd btool outputs list --debug)" >/dev/null
            ;;
    esac
    log "OK: Universal Forwarder status checks completed."
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --target-os) require_arg "$1" $# || exit 1; TARGET_OS="$2"; shift 2 ;;
        --target-arch) require_arg "$1" $# || exit 1; TARGET_ARCH="$2"; shift 2 ;;
        --execution) require_arg "$1" $# || exit 1; EXECUTION_MODE="$2"; shift 2 ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --url) require_arg "$1" $# || exit 1; PACKAGE_URL="$2"; shift 2 ;;
        --file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --package-type) require_arg "$1" $# || exit 1; PACKAGE_TYPE="$2"; shift 2 ;;
        --allow-stale-latest) ALLOW_STALE_LATEST=true; shift ;;
        --checksum) require_arg "$1" $# || exit 1; CHECKSUM="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME="$2"; shift 2 ;;
        --service-user) require_arg "$1" $# || exit 1; SERVICE_USER="$2"; shift 2 ;;
        --no-boot-start) BOOT_START=false; shift ;;
        --admin-user) require_arg "$1" $# || exit 1; ADMIN_USER="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --enroll) require_arg "$1" $# || exit 1; ENROLL_MODE="$2"; shift 2 ;;
        --deployment-server) require_arg "$1" $# || exit 1; DEPLOYMENT_SERVER="$2"; shift 2 ;;
        --server-list) require_arg "$1" $# || exit 1; SERVER_LIST="$2"; shift 2 ;;
        --cloud-credentials-package) require_arg "$1" $# || exit 1; CLOUD_CREDENTIALS_PACKAGE="$2"; shift 2 ;;
        --client-name) require_arg "$1" $# || exit 1; CLIENT_NAME="$2"; shift 2 ;;
        --phone-home-interval) require_arg "$1" $# || exit 1; PHONE_HOME_INTERVAL="$2"; shift 2 ;;
        --tcpout-group) require_arg "$1" $# || exit 1; TCPOUT_GROUP="$2"; shift 2 ;;
        --use-ack) require_arg "$1" $# || exit 1; USE_ACK="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_platform_defaults
normalize_execution_mode_for_target
validate_inputs

if [[ "${DRY_RUN}" == "true" && "${PHASE}" != "render" ]]; then
    dry_run_plan
    exit 0
fi

if [[ "${PHASE}" == "render" ]]; then
    prepare_render_package_path
    render_assets
    exit 0
fi

if [[ "${EXECUTION_MODE}" == "ssh" ]]; then
    load_splunk_ssh_credentials
    if [[ "${SPLUNK_SSH_USER}" != "root" && "${SPLUNK_REMOTE_SUDO}" == "true" ]]; then
        log "INFO: SSH UF setup assumes ${SPLUNK_SSH_USER} can run sudo non-interactively on the target host."
    fi
fi

if phase_includes_download; then
    pick_package_path
fi

if [[ "${PHASE}" == "download" ]]; then
    log "Downloaded package ready at ${PACKAGE_PATH}"
    exit 0
fi

if [[ "${EXECUTION_MODE}" == "render" ]]; then
    render_assets
    exit 0
fi

if [[ "${TARGET_OS}" == "windows" ]]; then
    render_assets
    exit 0
fi

if phase_includes_install; then
    if [[ -z "${PACKAGE_PATH}" ]]; then
        pick_package_path
    fi
    determine_install_action
fi

load_secret_values

if phase_includes_install; then
    perform_install_phase
fi

if phase_includes_enroll; then
    apply_enrollment
fi

if phase_includes_status; then
    run_status
fi

if [[ "${INSTALL_CLEANUP_REGISTERED}" == "true" ]]; then
    cleanup_install_artifacts
    trap - EXIT
fi
log "Universal Forwarder setup completed."
