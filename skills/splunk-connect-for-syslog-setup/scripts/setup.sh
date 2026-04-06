#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

DEFAULT_INDEXES=(
    print
    osnix
    oswinsec
    oswin
    netipam
    netproxy
    netwaf
    netops
    netlb
    netids
    netfw
    netdns
    netdlp
    netauth
    infraops
    gitops
    fireeye
    epintel
    epav
    email
)
OPTIONAL_METRICS_INDEX="_metrics"

DO_SPLUNK_PREP=false
RENDER_HOST=false
RENDER_K8S=false
APPLY_HOST=false
APPLY_K8S=false
INDEXES_ONLY=false
HEC_ONLY=false
INCLUDE_METRICS_INDEX=false
ENABLE_GLOBAL_ARCHIVE=false
ENABLE_SOURCE_TLS=false

HOST_MODE="compose"
RUNTIME=""
OUTPUT_DIR=""
SC4S_ROOT="/opt/sc4s"
SC4S_IMAGE="ghcr.io/splunk/splunk-connect-for-syslog/container3:latest"
SC4S_PERSIST_VOLUME="splunk-sc4s-var"
HEC_TOKEN_NAME="sc4s"
HEC_URL=""
HEC_TLS_VERIFY="yes"
HEC_TOKEN_FILE=""
WRITE_HEC_TOKEN_FILE=""
ARCHIVE_MODE="compliance"
CONTAINER_HOST_NAME=""
NAMESPACE="sc4s"
RELEASE_NAME="sc4s"
REPLICA_COUNT="1"
EXISTING_CERT=""

SK=""
SESSION_READY=false
INDEXES_CREATED=0

CONTEXT_FILE_SPECS=()
CONFIG_FILE_SPECS=()
VENDOR_PORT_SPECS=()
DEFAULT_RENDER_DIR_NAME="sc4s-rendered"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
SC4S Setup Automation

Usage: $(basename "$0") [OPTIONS]

Modes:
  --splunk-prep                  Verify/create default SC4S indexes and HEC token
  --indexes-only                 With --splunk-prep, manage indexes only
  --hec-only                     With --splunk-prep, manage HEC token only
  --render-host                  Render host deployment assets
  --render-k8s                   Render Kubernetes/Helm assets
  --apply-host                   After --render-host, install or upgrade the host deployment
  --apply-k8s                    After --render-k8s, install or upgrade with helm

Common options:
  --output-dir PATH              Render output directory (default: repo-root ./sc4s-rendered)
  --hec-url URL                  HEC URL override; may include /services/collector/event
  --hec-token-name NAME          HEC token name (default: sc4s)
  --hec-token-file PATH          Local-only file containing the HEC token value
  --write-hec-token-file PATH    Write the created HEC token value to PATH when visible via REST
  --hec-tls-verify yes|no        Render HEC TLS verification setting (default: yes)
  --include-metrics-index        Also manage the optional _metrics index
  --context-file NAME=PATH       Copy/embed a SC4S context file
  --config-file NAME=PATH        Copy/embed a SC4S config file
  --vendor-port NAME:PROTO:PORT  Dedicated vendor_product port (tcp|udp|tls)

Host render options:
  --host-mode compose|systemd    Host deployment mode (default: compose)
  --runtime docker|podman        Container runtime (default: docker for compose, podman for systemd)
  --sc4s-root PATH               Target runtime path for systemd or when copying the rendered stack (default: /opt/sc4s)
  --container-image IMAGE        SC4S image (default: ghcr.io/.../container3:latest)
  --persist-volume NAME          Persistent volume name (default: splunk-sc4s-var)
  --enable-global-archive        Render archive settings and mount
  --archive-mode MODE            Archive mode: compliance|diode (default: compliance)
  --enable-source-tls            Render default inbound TLS settings
  --container-host NAME          Optional SC4S_CONTAINER_HOST value for env_file

Kubernetes render options:
  --namespace NAME               Helm namespace (default: sc4s)
  --release-name NAME            Helm release name (default: sc4s)
  --replica-count N              Helm replicaCount (default: 1)
  --existing-cert NAME           Existing Kubernetes TLS secret for SC4S source TLS

Examples:
  $(basename "$0") --splunk-prep
  $(basename "$0") --render-host --hec-token-file /tmp/sc4s_hec_token
  $(basename "$0") --render-k8s --replica-count 2 --hec-token-file /tmp/sc4s_hec_token

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --splunk-prep) DO_SPLUNK_PREP=true; shift ;;
        --render-host) RENDER_HOST=true; shift ;;
        --render-k8s) RENDER_K8S=true; shift ;;
        --apply-host) APPLY_HOST=true; shift ;;
        --apply-k8s) APPLY_K8S=true; shift ;;
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --hec-only) HEC_ONLY=true; shift ;;
        --include-metrics-index) INCLUDE_METRICS_INDEX=true; shift ;;
        --enable-global-archive) ENABLE_GLOBAL_ARCHIVE=true; shift ;;
        --enable-source-tls) ENABLE_SOURCE_TLS=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --host-mode) require_arg "$1" $# || exit 1; HOST_MODE="$2"; shift 2 ;;
        --runtime) require_arg "$1" $# || exit 1; RUNTIME="$2"; shift 2 ;;
        --sc4s-root) require_arg "$1" $# || exit 1; SC4S_ROOT="$2"; shift 2 ;;
        --container-image) require_arg "$1" $# || exit 1; SC4S_IMAGE="$2"; shift 2 ;;
        --persist-volume) require_arg "$1" $# || exit 1; SC4S_PERSIST_VOLUME="$2"; shift 2 ;;
        --hec-token-name) require_arg "$1" $# || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --hec-url) require_arg "$1" $# || exit 1; HEC_URL="$2"; shift 2 ;;
        --hec-tls-verify) require_arg "$1" $# || exit 1; HEC_TLS_VERIFY="$2"; shift 2 ;;
        --hec-token-file) require_arg "$1" $# || exit 1; HEC_TOKEN_FILE="$2"; shift 2 ;;
        --write-hec-token-file) require_arg "$1" $# || exit 1; WRITE_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --archive-mode) require_arg "$1" $# || exit 1; ARCHIVE_MODE="$2"; shift 2 ;;
        --container-host) require_arg "$1" $# || exit 1; CONTAINER_HOST_NAME="$2"; shift 2 ;;
        --namespace) require_arg "$1" $# || exit 1; NAMESPACE="$2"; shift 2 ;;
        --release-name) require_arg "$1" $# || exit 1; RELEASE_NAME="$2"; shift 2 ;;
        --replica-count) require_arg "$1" $# || exit 1; REPLICA_COUNT="$2"; shift 2 ;;
        --existing-cert) require_arg "$1" $# || exit 1; EXISTING_CERT="$2"; shift 2 ;;
        --context-file) require_arg "$1" $# || exit 1; CONTEXT_FILE_SPECS+=("$2"); shift 2 ;;
        --config-file) require_arg "$1" $# || exit 1; CONFIG_FILE_SPECS+=("$2"); shift 2 ;;
        --vendor-port) require_arg "$1" $# || exit 1; VENDOR_PORT_SPECS+=("$2"); shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

normalize_yes_no() {
    case "${1:-}" in
        yes|YES|true|TRUE|True|1|on|ON) printf '%s' "yes" ;;
        no|NO|false|FALSE|False|0|off|OFF) printf '%s' "no" ;;
        *)
            log "ERROR: Expected yes or no, got '${1:-}'."
            exit 1
            ;;
    esac
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

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

path_is_within_dir() {
    python3 - "$1" "$2" <<'PY'
from pathlib import Path
import sys

target = Path(sys.argv[1]).resolve()
base = Path(sys.argv[2]).resolve()
try:
    target.relative_to(base)
    print("yes", end="")
except ValueError:
    print("no", end="")
PY
}

ensure_parent_dir() {
    local target="$1"
    local parent
    parent="$(dirname "${target}")"
    mkdir -p "${parent}"
}

write_text_file() {
    local path="$1" content="$2"
    ensure_parent_dir "${path}"
    printf '%s' "${content}" > "${path}"
}

write_secret_file() {
    local path="$1" content="$2"
    local previous_umask
    ensure_parent_dir "${path}"
    previous_umask="$(umask)"
    umask 077
    printf '%s' "${content}" > "${path}"
    chmod 600 "${path}"
    umask "${previous_umask}"
}

make_executable() {
    chmod 755 "$1"
}

validate_named_file_spec() {
    local spec="$1" kind="$2"
    local name path
    if [[ "${spec}" != *=* ]]; then
        log "ERROR: ${kind} must use NAME=PATH format: ${spec}"
        exit 1
    fi
    name="${spec%%=*}"
    path="${spec#*=}"
    if [[ ! "${name}" =~ ^[A-Za-z0-9._-]+$ ]]; then
        log "ERROR: ${kind} name must use only letters, numbers, dot, dash, or underscore: ${name}"
        exit 1
    fi
    if [[ ! -f "${path}" ]]; then
        log "ERROR: ${kind} source file not found: ${path}"
        exit 1
    fi
}

validate_vendor_spec() {
    local spec="$1"
    local name proto port
    IFS=':' read -r name proto port <<< "${spec}"
    if [[ -z "${name:-}" || -z "${proto:-}" || -z "${port:-}" ]]; then
        log "ERROR: --vendor-port must use NAME:PROTO:PORT format: ${spec}"
        exit 1
    fi
    if [[ ! "${name}" =~ ^[A-Za-z0-9_]+$ ]]; then
        log "ERROR: Vendor product name must use letters, numbers, and underscores only: ${name}"
        exit 1
    fi
    validate_choice "${proto}" tcp udp tls
    if [[ ! "${port}" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
        log "ERROR: Invalid vendor port '${port}' in spec '${spec}'."
        exit 1
    fi
}

validate_args() {
    local has_mode=false spec

    HEC_TLS_VERIFY="$(normalize_yes_no "${HEC_TLS_VERIFY}")"

    if $DO_SPLUNK_PREP || $RENDER_HOST || $RENDER_K8S; then
        has_mode=true
    fi
    if ! $has_mode; then
        log "ERROR: Select at least one mode: --splunk-prep, --render-host, or --render-k8s."
        usage 1
    fi

    if $INDEXES_ONLY && $HEC_ONLY; then
        log "ERROR: --indexes-only and --hec-only cannot be used together."
        exit 1
    fi

    if $APPLY_HOST && ! $RENDER_HOST; then
        log "ERROR: --apply-host requires --render-host."
        exit 1
    fi

    if $APPLY_K8S && ! $RENDER_K8S; then
        log "ERROR: --apply-k8s requires --render-k8s."
        exit 1
    fi

    validate_choice "${HOST_MODE}" compose systemd
    if [[ -n "${RUNTIME}" ]]; then
        validate_choice "${RUNTIME}" docker podman
    fi

    if [[ -z "${RUNTIME}" ]]; then
        if [[ "${HOST_MODE}" == "systemd" ]]; then
            RUNTIME="podman"
        else
            RUNTIME="docker"
        fi
    fi

    if [[ ! "${SC4S_ROOT}" =~ ^/ ]]; then
        log "ERROR: --sc4s-root must be an absolute path."
        exit 1
    fi

    if [[ ! "${REPLICA_COUNT}" =~ ^[0-9]+$ ]] || (( REPLICA_COUNT < 1 )); then
        log "ERROR: --replica-count must be a positive integer."
        exit 1
    fi

    if [[ -n "${HEC_TOKEN_FILE}" && ! -f "${HEC_TOKEN_FILE}" ]]; then
        log "ERROR: HEC token file not found: ${HEC_TOKEN_FILE}"
        exit 1
    fi

    if (( ${#CONTEXT_FILE_SPECS[@]} > 0 )); then
        for spec in "${CONTEXT_FILE_SPECS[@]}"; do
            validate_named_file_spec "${spec}" "Context file"
        done
    fi
    if (( ${#CONFIG_FILE_SPECS[@]} > 0 )); then
        for spec in "${CONFIG_FILE_SPECS[@]}"; do
            validate_named_file_spec "${spec}" "Config file"
        done
    fi
    if (( ${#VENDOR_PORT_SPECS[@]} > 0 )); then
        for spec in "${VENDOR_PORT_SPECS[@]}"; do
            validate_vendor_spec "${spec}"
        done
    fi

    if [[ -n "${WRITE_HEC_TOKEN_FILE}" ]]; then
        WRITE_HEC_TOKEN_FILE="$(resolve_abs_path "${WRITE_HEC_TOKEN_FILE}")"
    fi

    if [[ -n "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
    else
        OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    fi
}

ensure_splunk_context() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
}

ensure_search_session() {
    ensure_splunk_context
    if [[ "${SESSION_READY}" == "true" ]]; then
        return 0
    fi
    SK="$(get_session_key "${SPLUNK_URI}")" || { log "ERROR: Could not authenticate to Splunk REST API."; exit 1; }
    SESSION_READY=true
}

maybe_start_search_session() {
    ensure_splunk_context
    if [[ "${SESSION_READY}" == "true" ]]; then
        return 0
    fi
    if SK="$(get_session_key "${SPLUNK_URI}" 2>/dev/null)"; then
        SESSION_READY=true
        return 0
    fi
    return 1
}

build_index_list() {
    local idx
    for idx in "${DEFAULT_INDEXES[@]}"; do
        printf '%s\n' "${idx}"
    done
    if [[ "${INCLUDE_METRICS_INDEX}" == "true" ]]; then
        printf '%s\n' "${OPTIONAL_METRICS_INDEX}"
    fi
}

index_type_for_name() {
    local idx="$1"
    if [[ "${idx}" == "${OPTIONAL_METRICS_INDEX}" ]]; then
        printf '%s' "metric"
    else
        printf '%s' "event"
    fi
}

warn_if_wrong_metrics_datatype() {
    local idx="$1"
    local datatype

    [[ "${idx}" == "${OPTIONAL_METRICS_INDEX}" ]] || return 0
    datatype="$(platform_get_index_datatype "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null || echo "")"
    case "${datatype}" in
        metric)
            ;;
        event)
            log "WARN: '${idx}' exists but is an event index, not a metrics index."
            log "WARN: Recreate '${idx}' as a metrics index before enabling SC4S metrics."
            ;;
        "")
            log "WARN: Could not determine the datatype of '${idx}'. Verify that it is a metrics index."
            ;;
        *)
            log "WARN: '${idx}' exists with datatype '${datatype}', not 'metric'."
            log "WARN: Recreate '${idx}' as a metrics index before enabling SC4S metrics."
            ;;
    esac
}

assert_secret_output_dir_is_safe() {
    local output_path="$1"
    local default_safe_dir

    [[ -n "${HEC_TOKEN_FILE}" ]] || return 0

    default_safe_dir="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
    if [[ "$(path_is_within_dir "${output_path}" "${_PROJECT_ROOT}")" != "yes" ]]; then
        return 0
    fi

    if [[ "${output_path}" == "${default_safe_dir}" || "${output_path}" == "${default_safe_dir}/host" || "${output_path}" == "${default_safe_dir}/k8s" ]]; then
        log "Rendering secret-bearing files under the gitignored default output path: ${default_safe_dir}"
        return 0
    fi

    log "ERROR: Refusing to render secret-bearing SC4S outputs inside the repo at ${output_path}."
    log "ERROR: Use the default gitignored output path (${default_safe_dir}) or choose an output directory outside the repository."
    exit 1
}

normalize_hec_base_url() {
    local url="${1%/}"
    url="${url%/services/collector/event}"
    url="${url%/services/collector/raw}"
    printf '%s' "${url}"
}

hec_event_url_from_base() {
    local base_url
    base_url="$(normalize_hec_base_url "$1")"
    printf '%s/services/collector/event' "${base_url}"
}

detect_hec_base_url() {
    local stack host

    if [[ -n "${HEC_URL}" ]]; then
        normalize_hec_base_url "${HEC_URL}"
        return 0
    fi

    ensure_splunk_context
    if is_splunk_cloud; then
        stack="${SPLUNK_CLOUD_STACK:-}"
        if [[ -z "${stack}" ]]; then
            log "ERROR: Splunk Cloud detected but SPLUNK_CLOUD_STACK is empty. Pass --hec-url or configure the stack."
            exit 1
        fi
        if _is_staging_splunk_cloud_host "${SPLUNK_URI:-}" || _is_staging_splunk_cloud_host "${SPLUNK_HOST:-}"; then
            printf 'https://http-inputs-%s.stg.splunkcloud.com:443' "${stack}"
        else
            printf 'https://http-inputs-%s.splunkcloud.com:443' "${stack}"
        fi
        return 0
    fi

    host="$(splunk_host_from_uri "${SPLUNK_URI}")"
    if [[ -z "${host}" ]]; then
        host="${SPLUNK_HOST:-}"
    fi
    if [[ -z "${host}" ]]; then
        log "ERROR: Could not determine the Enterprise HEC host. Pass --hec-url or configure SPLUNK_URI."
        exit 1
    fi
    printf 'https://%s:8088' "${host}"
}

rest_create_hec_token() {
    local token_name="$1" body resp http_code
    body=$(form_urlencode_pairs \
        name "${token_name}" \
        index "main" \
        disabled "false" \
        useACK "0") || return 1
    resp=$(splunk_curl_post "${SK}" "${body}" \
        "${SPLUNK_URI}/services/data/inputs/http?output_mode=json" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        201|200|409) return 0 ;;
        *) return 1 ;;
    esac
}

_ACS_HEC_CMD_GROUP=""
acs_hec_command_group() {
    if [[ -n "${_ACS_HEC_CMD_GROUP}" ]]; then
        printf '%s' "${_ACS_HEC_CMD_GROUP}"
        return 0
    fi
    if acs_command hec-token list --count 1 >/dev/null 2>&1; then
        _ACS_HEC_CMD_GROUP="hec-token"
    else
        _ACS_HEC_CMD_GROUP="http-event-collectors"
    fi
    printf '%s' "${_ACS_HEC_CMD_GROUP}"
}

cloud_get_hec_token_state() {
    local token_name="$1" cmd_group hec_list
    cmd_group="$(acs_hec_command_group)"

    if [[ "${cmd_group}" == "hec-token" ]]; then
        hec_list=$(acs_command hec-token list --count 100 2>/dev/null | acs_extract_http_response_json || echo "{}")
    else
        hec_list=$(acs_command http-event-collectors list 2>/dev/null | acs_extract_http_response_json || echo "{}")
    fi

    printf '%s' "${hec_list}" | python3 -c "
import json
import sys

target = sys.argv[1]
try:
    data = json.load(sys.stdin)
    collectors = (
        data.get('http-event-collectors')
        or data.get('http_event_collectors')
        or data.get('tokens')
        or []
    )
    for collector in collectors:
        spec = collector.get('spec', {}) if isinstance(collector, dict) else {}
        name = spec.get('name') or collector.get('name', '')
        if name != target:
            continue
        disabled = str(spec.get('disabled', collector.get('disabled', False))).strip().lower()
        if disabled in ('1', 'true'):
            print('disabled', end='')
        else:
            print('enabled', end='')
        raise SystemExit(0)
    print('missing', end='')
except Exception:
    print('unknown', end='')
" "${token_name}" 2>/dev/null
}

cloud_create_hec_token_via_acs() {
    local token_name="$1" cmd_group
    cmd_group="$(acs_hec_command_group)"
    if [[ "${cmd_group}" == "hec-token" ]]; then
        acs_command hec-token create --name "${token_name}" --default-index "main" --disabled=false >/dev/null 2>&1
    else
        acs_command http-event-collectors create \
            --name "${token_name}" \
            --default-index "main" \
            --disabled false \
            >/dev/null 2>&1
    fi
}

cloud_enable_hec_token_via_acs() {
    local token_name="$1" cmd_group
    cmd_group="$(acs_hec_command_group)"
    if [[ "${cmd_group}" == "hec-token" ]]; then
        acs_command hec-token update "${token_name}" --disabled=false >/dev/null 2>&1
    else
        return 1
    fi
}

rest_enable_hec_token() {
    local token_name="$1" encoded_name resp http_code
    encoded_name="$(_urlencode "http://${token_name}")"
    resp=$(splunk_curl_post "${SK}" "" \
        "${SPLUNK_URI}/services/data/inputs/http/${encoded_name}/enable" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(echo "${resp}" | tail -1)
    case "${http_code}" in
        200|201|409) return 0 ;;
        *) return 1 ;;
    esac
}

write_hec_token_file_if_requested() {
    local token_name="$1" token_record token_value
    [[ -n "${WRITE_HEC_TOKEN_FILE}" ]] || return 0

    if ! maybe_start_search_session; then
        log "WARN: Could not open a Splunk REST session to retrieve the HEC token value."
        return 0
    fi

    token_record="$(rest_get_hec_token_record "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}")"
    token_value="$(rest_json_field "${token_record}" "token")"
    if [[ -z "${token_value}" ]]; then
        log "WARN: Splunk did not return a clear HEC token value for '${token_name}'. Write the token to a local file manually."
        return 0
    fi

    write_secret_file "${WRITE_HEC_TOKEN_FILE}" "${token_value}"$'\n'
    HEC_TOKEN_FILE="${WRITE_HEC_TOKEN_FILE}"
    log "Wrote HEC token value to ${WRITE_HEC_TOKEN_FILE}"
}

warn_about_hec_token_details() {
    local token_name="$1" token_record ack_state indexes_value default_index

    if ! maybe_start_search_session; then
        log "WARN: Could not inspect detailed HEC token settings over Splunk REST."
        return 0
    fi

    token_record="$(rest_get_hec_token_record "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}")"
    ack_state="$(rest_json_field "${token_record}" "useACK")"
    indexes_value="$(rest_json_field "${token_record}" "indexes")"
    default_index="$(rest_json_field "${token_record}" "default_index")"

    case "${ack_state}" in
        1|true|True)
            log "WARN: HEC token '${token_name}' has acknowledgement enabled. SC4S does not support HEC ACK."
            ;;
    esac

    if [[ -n "${indexes_value}" ]]; then
        log "WARN: HEC token '${token_name}' has restricted Selected Indexes (${indexes_value})."
        log "WARN: Leaving Selected Indexes blank is safer for SC4S because lastChanceIndex cannot help if the token disallows an index."
    fi

    if [[ -n "${default_index}" ]]; then
        log "HEC token '${token_name}' default index: ${default_index}"
    fi
}

ensure_hec_token() {
    local state
    log "Checking HEC token '${HEC_TOKEN_NAME}'..."

    ensure_splunk_context
    if is_splunk_cloud; then
        acs_prepare_context || { log "ERROR: ACS context is required for Splunk Cloud HEC management."; exit 1; }
        state="$(cloud_get_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
        case "${state}" in
            enabled)
                log "HEC token '${HEC_TOKEN_NAME}' already exists in Splunk Cloud."
                ;;
            disabled)
                log "HEC token '${HEC_TOKEN_NAME}' exists but is disabled. Enabling it via ACS..."
                if ! cloud_enable_hec_token_via_acs "${HEC_TOKEN_NAME}"; then
                    log "ERROR: Failed to enable disabled HEC token '${HEC_TOKEN_NAME}' via ACS."
                    exit 1
                fi
                state="$(cloud_get_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${HEC_TOKEN_NAME}' is still not enabled after the ACS update."
                    exit 1
                fi
                log "Enabled HEC token '${HEC_TOKEN_NAME}' in Splunk Cloud."
                ;;
            *)
                log "Creating HEC token '${HEC_TOKEN_NAME}' via ACS..."
                if ! cloud_create_hec_token_via_acs "${HEC_TOKEN_NAME}"; then
                    log "ERROR: Failed to create HEC token '${HEC_TOKEN_NAME}' via ACS."
                    exit 1
                fi
                log "Created HEC token '${HEC_TOKEN_NAME}' via ACS."
                ;;
        esac
    else
        ensure_search_session
        state="$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
        case "${state}" in
            enabled)
                log "HEC token '${HEC_TOKEN_NAME}' already exists."
                ;;
            disabled)
                log "HEC token '${HEC_TOKEN_NAME}' exists but is disabled. Enabling it via Splunk REST..."
                if ! rest_enable_hec_token "${HEC_TOKEN_NAME}"; then
                    log "ERROR: Failed to enable disabled HEC token '${HEC_TOKEN_NAME}' via Splunk REST."
                    exit 1
                fi
                state="$(rest_get_hec_token_state "${SK}" "${SPLUNK_URI}" "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${HEC_TOKEN_NAME}' is still not enabled after the REST update."
                    exit 1
                fi
                log "Enabled HEC token '${HEC_TOKEN_NAME}'."
                ;;
            *)
                log "Creating HEC token '${HEC_TOKEN_NAME}' via Splunk REST..."
                if ! rest_create_hec_token "${HEC_TOKEN_NAME}"; then
                    log "ERROR: Failed to create HEC token '${HEC_TOKEN_NAME}' via Splunk REST."
                    exit 1
                fi
                log "Created HEC token '${HEC_TOKEN_NAME}'."
                ;;
        esac
    fi

    warn_about_hec_token_details "${HEC_TOKEN_NAME}"
    write_hec_token_file_if_requested "${HEC_TOKEN_NAME}"
}

ensure_indexes() {
    local idx index_type
    ensure_splunk_context
    if ! is_splunk_cloud; then
        ensure_search_session
    fi

    while IFS= read -r idx; do
        [[ -n "${idx}" ]] || continue
        index_type="$(index_type_for_name "${idx}")"
        if platform_check_index "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null; then
            log "Index '${idx}' already exists."
            warn_if_wrong_metrics_datatype "${idx}"
            continue
        fi
        log "Creating index '${idx}'..."
        if ! platform_create_index "${SK}" "${SPLUNK_URI}" "${idx}" "512000" "${index_type}" 2>/dev/null; then
            log "ERROR: Failed to create index '${idx}'."
            exit 1
        fi
        warn_if_wrong_metrics_datatype "${idx}"
        INDEXES_CREATED=$((INDEXES_CREATED + 1))
    done < <(build_index_list)

    if [[ "${INDEXES_CREATED}" -gt 0 ]]; then
        log "$(log_platform_restart_guidance "new index changes")"
    fi
}

run_splunk_prep() {
    local hec_base event_url

    hec_base="$(detect_hec_base_url)"
    event_url="$(hec_event_url_from_base "${hec_base}")"
    log "Detected SC4S HEC base URL: ${hec_base}"
    log "Detected SC4S HEC event URL: ${event_url}"

    if [[ "${HEC_ONLY}" != "true" ]]; then
        ensure_indexes
    fi
    if [[ "${INDEXES_ONLY}" != "true" ]]; then
        ensure_hec_token
    fi
}

copy_named_files() {
    local target_dir="$1"; shift
    local spec name src
    mkdir -p "${target_dir}"
    for spec in "$@"; do
        [[ -n "${spec}" ]] || continue
        name="${spec%%=*}"
        src="${spec#*=}"
        cp "${src}" "${target_dir}/${name}"
    done
}

render_template_to_file() {
    local template_path="$1" output_path="$2"
    python3 - "$template_path" "$output_path" <<'PY'
from pathlib import Path
import os
import sys

template = Path(sys.argv[1]).read_text(encoding="utf-8")
for key, value in os.environ.items():
    if key.startswith("TPL_"):
        template = template.replace("{{" + key[4:] + "}}", value)
Path(sys.argv[2]).write_text(template, encoding="utf-8")
PY
}

compose_ports_block() {
    local enable_tls="$1"; shift
    python3 - "$enable_tls" "$@" <<'PY'
import sys

enable_tls = sys.argv[1].lower() in {"yes", "true", "1", "on"}
entries = [("tcp", 514), ("udp", 514), ("tcp", 601)]
if enable_tls:
    entries.append(("tcp", 6514))

for spec in sys.argv[2:]:
    name, proto, port_text = spec.split(":", 2)
    port = int(port_text)
    if proto == "tls":
        entries.append(("tcp", port))
    elif proto in ("tcp", "udp"):
        entries.append((proto, port))

seen = set()
lines = []
for proto, port in entries:
    key = (proto, port)
    if key in seen:
        continue
    seen.add(key)
    lines.append(f"      - target: {port}")
    lines.append(f"        published: {port}")
    lines.append(f"        protocol: {proto}")

print("\n".join(lines), end="")
PY
}

host_vendor_env_block() {
    python3 - "$@" <<'PY'
import sys

lines = []
for spec in sys.argv[1:]:
    name, proto, port = spec.split(":", 2)
    lines.append(f"SC4S_LISTEN_{name.upper()}_{proto.upper()}_PORT={port}")

if lines:
    print("\n" + "\n".join(lines), end="")
else:
    print("", end="")
PY
}

k8s_vendor_product_block() {
    python3 - "$@" <<'PY'
import sys

vendors = {}
for spec in sys.argv[1:]:
    name, proto, port = spec.split(":", 2)
    vendors.setdefault(name, {}).setdefault(proto, []).append(int(port))

if not vendors:
    print("", end="")
    raise SystemExit(0)

lines = ["  vendor_product:"]
for name in sorted(vendors):
    lines.append(f"    - name: {name}")
    lines.append("      ports:")
    for proto in sorted(vendors[name]):
        values = ", ".join(str(item) for item in sorted(set(vendors[name][proto])))
        lines.append(f"        {proto}: [{values}]")

print("\n".join(lines) + "\n", end="")
PY
}

yaml_file_block() {
    local block_name="$1"; shift
    python3 - "$block_name" "$@" <<'PY'
from pathlib import Path
import sys

block_name = sys.argv[1]
specs = sys.argv[2:]
if not specs:
    print("", end="")
    raise SystemExit(0)

lines = [f"  {block_name}:"]
for spec in specs:
    name, path = spec.split("=", 1)
    text = Path(path).read_text(encoding="utf-8")
    lines.append(f"    {name}: |-")
    for line in text.splitlines():
        lines.append(f"      {line}")
    if text.endswith("\n") and not text.endswith("\n\n"):
        pass
    if not text:
        lines.append("      ")

print("\n".join(lines) + "\n", end="")
PY
}

render_host_readme() {
    local host_dir="$1" hec_base_url="$2" env_file_name="$3" deployment_file="$4"
    cat > "${host_dir}/README.md" <<EOF
# Rendered SC4S Host Deployment

This directory contains rendered SC4S host assets.

## Files

- \`${env_file_name}\`
- \`${deployment_file}\`
- \`local/context/\`
- \`local/config/\`
- \`archive/\`
- \`tls/\`

## Target runtime path

- \`${SC4S_ROOT}\`

## HEC target

- \`${hec_base_url}\`

## Next steps

1. For compose mode, the rendered host directory is self-contained and can be installed or upgraded in place with the helper script.
2. For systemd mode, run \`systemd-install.sh\` or \`--apply-host\` to sync the rendered files into \`${SC4S_ROOT}\` and restart SC4S.
3. Ensure the target host has the required directories and enough storage for the syslog-ng persistent volume.
4. Review the rendered env file and confirm the HEC token, TLS, archive, and vendor listener settings.
5. Re-run the same apply workflow whenever you need to roll out config or image updates.

## Notes

- The rendered \`${env_file_name}\` is local-only and should not be committed.
- If you enabled inbound TLS, place \`server.pem\`, \`server.key\`, and optional \`trusted.pem\` under the rendered \`tls/\` directory before deployment.
- Kernel receive buffers should be sized for SC4S defaults to avoid UDP warning messages.
EOF
}

render_compose_helpers() {
    local host_dir="$1" runtime_name="$2"
    cat > "${host_dir}/compose-up.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
${runtime_name} compose -f docker-compose.yml pull
${runtime_name} compose -f docker-compose.yml up -d
EOF
    cat > "${host_dir}/compose-down.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
${runtime_name} compose -f docker-compose.yml down
EOF
    make_executable "${host_dir}/compose-up.sh"
    make_executable "${host_dir}/compose-down.sh"
}

render_systemd_helper() {
    local host_dir="$1"
    cat > "${host_dir}/systemd-install.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
target_root="${SC4S_ROOT}"
unit_dir="\${SC4S_SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
use_sudo="\${SC4S_SYSTEMD_USE_SUDO:-auto}"
systemctl_bin="\${SC4S_SYSTEMCTL_BIN:-systemctl}"

run_root() {
    if [[ "\${use_sudo}" == "never" || "\${EUID}" -eq 0 ]]; then
        "\$@"
    else
        sudo "\$@"
    fi
}

sync_dir() {
    local src="\$1" dest="\$2"
    [[ -d "\${src}" ]] || return 0
    run_root install -d -m 0755 "\${dest}"
    run_root cp -R "\${src}/." "\${dest}/"
}

run_root install -d -m 0755 \
    "\${target_root}" \
    "\${target_root}/local" \
    "\${target_root}/local/context" \
    "\${target_root}/local/config" \
    "\${target_root}/archive" \
    "\${target_root}/tls" \
    "\${unit_dir}"
run_root install -m 0600 env_file "\${target_root}/env_file"
sync_dir local "\${target_root}/local"
sync_dir archive "\${target_root}/archive"
sync_dir tls "\${target_root}/tls"
run_root install -m 0644 sc4s.service "\${unit_dir}/sc4s.service"
run_root "\${systemctl_bin}" daemon-reload
run_root "\${systemctl_bin}" enable sc4s
run_root "\${systemctl_bin}" restart sc4s
EOF
    make_executable "${host_dir}/systemd-install.sh"
}

render_host_assets() {
    local host_dir template_dir hec_base_url hec_token_value env_file_path compose_ports
    local archive_block source_tls_block tls_verify_block container_host_block vendor_env_block
    local archive_volume_block tls_volume_block archive_env_line tls_env_line archive_run_line tls_run_line
    local deployment_file runtime_bin

    host_dir="${OUTPUT_DIR}/host"
    template_dir="${SCRIPT_DIR}/../templates/host"
    hec_base_url="$(detect_hec_base_url)"
    if [[ -n "${HEC_TOKEN_FILE}" ]]; then
        assert_secret_output_dir_is_safe "${host_dir}"
        hec_token_value="$(read_secret_file "${HEC_TOKEN_FILE}")"
    else
        hec_token_value="<replace-with-hec-token>"
        log "WARN: No --hec-token-file provided. Rendering a placeholder token value."
    fi

    mkdir -p "${host_dir}/local/context" "${host_dir}/local/config" "${host_dir}/archive" "${host_dir}/tls"
    if (( ${#CONTEXT_FILE_SPECS[@]} > 0 )); then
        copy_named_files "${host_dir}/local/context" "${CONTEXT_FILE_SPECS[@]}"
    fi
    if (( ${#CONFIG_FILE_SPECS[@]} > 0 )); then
        copy_named_files "${host_dir}/local/config" "${CONFIG_FILE_SPECS[@]}"
    fi

    if [[ "${HEC_TLS_VERIFY}" == "no" ]]; then
        tls_verify_block=$'SC4S_DEST_SPLUNK_HEC_DEFAULT_TLS_VERIFY=no\n'
    else
        tls_verify_block=""
    fi

    if [[ "${ENABLE_GLOBAL_ARCHIVE}" == "true" ]]; then
        archive_block="SC4S_ARCHIVE_GLOBAL=yes"$'\n'"SC4S_GLOBAL_ARCHIVE_MODE=${ARCHIVE_MODE}"$'\n'
        archive_volume_block="      - ./archive:/var/lib/syslog-ng/archive:z"$'\n'
        archive_env_line="Environment=\"SC4S_ARCHIVE_MOUNT=${SC4S_ROOT}/archive:/var/lib/syslog-ng/archive:z\""$'\n'
        archive_run_line="        -v \"\$SC4S_ARCHIVE_MOUNT\" \\"$'\n'
    else
        archive_block=""
        archive_volume_block=""
        archive_env_line=""
        archive_run_line=""
    fi

    if [[ "${ENABLE_SOURCE_TLS}" == "true" ]]; then
        source_tls_block=$'SC4S_SOURCE_TLS_ENABLE=yes\nSC4S_LISTEN_DEFAULT_TLS_PORT=6514\n'
        tls_volume_block="      - ./tls:/etc/syslog-ng/tls:z"$'\n'
        tls_env_line="Environment=\"SC4S_TLS_MOUNT=${SC4S_ROOT}/tls:/etc/syslog-ng/tls:z\""$'\n'
        tls_run_line="        -v \"\$SC4S_TLS_MOUNT\" \\"$'\n'
    else
        source_tls_block=""
        tls_volume_block=""
        tls_env_line=""
        tls_run_line=""
    fi

    if [[ -n "${CONTAINER_HOST_NAME}" ]]; then
        container_host_block="SC4S_CONTAINER_HOST=${CONTAINER_HOST_NAME}"$'\n'
    else
        container_host_block=""
    fi

    if (( ${#VENDOR_PORT_SPECS[@]} > 0 )); then
        vendor_env_block="$(host_vendor_env_block "${VENDOR_PORT_SPECS[@]}")"
    else
        vendor_env_block=""
    fi
    env_file_path="${host_dir}/env_file"

    export TPL_HEC_BASE_URL="${hec_base_url}"
    export TPL_HEC_TOKEN="${hec_token_value}"
    export TPL_HEC_TLS_VERIFY_BLOCK="${tls_verify_block}"
    export TPL_ARCHIVE_BLOCK="${archive_block}"
    export TPL_SOURCE_TLS_BLOCK="${source_tls_block}"
    export TPL_CONTAINER_HOST_BLOCK="${container_host_block}"
    export TPL_VENDOR_PORT_BLOCK="${vendor_env_block}"
    render_template_to_file "${template_dir}/env_file.example" "${env_file_path}"
    chmod 600 "${env_file_path}"

    if [[ "${HOST_MODE}" == "compose" ]]; then
        if (( ${#VENDOR_PORT_SPECS[@]} > 0 )); then
            compose_ports="$(compose_ports_block "${ENABLE_SOURCE_TLS}" "${VENDOR_PORT_SPECS[@]}")"
        else
            compose_ports="$(compose_ports_block "${ENABLE_SOURCE_TLS}")"
        fi
        export TPL_SC4S_IMAGE="${SC4S_IMAGE}"
        export TPL_SC4S_ROOT="${SC4S_ROOT}"
        export TPL_SC4S_PERSIST_VOLUME="${SC4S_PERSIST_VOLUME}"
        export TPL_PORTS_BLOCK="${compose_ports}"
        export TPL_ARCHIVE_VOLUME_BLOCK="${archive_volume_block}"
        export TPL_TLS_VOLUME_BLOCK="${tls_volume_block}"
        deployment_file="docker-compose.yml"
        render_template_to_file "${template_dir}/docker-compose.yml" "${host_dir}/${deployment_file}"
        render_compose_helpers "${host_dir}" "${RUNTIME}"
    else
        runtime_bin="/usr/bin/${RUNTIME}"
        export TPL_SC4S_IMAGE="${SC4S_IMAGE}"
        export TPL_SC4S_PERSIST_VOLUME="${SC4S_PERSIST_VOLUME}"
        export TPL_SC4S_ROOT="${SC4S_ROOT}"
        export TPL_RUNTIME_BIN="${runtime_bin}"
        export TPL_ARCHIVE_ENV_LINE="${archive_env_line}"
        export TPL_TLS_ENV_LINE="${tls_env_line}"
        export TPL_ARCHIVE_RUN_LINE="${archive_run_line}"
        export TPL_TLS_RUN_LINE="${tls_run_line}"
        deployment_file="sc4s.service"
        render_template_to_file "${template_dir}/sc4s.service" "${host_dir}/${deployment_file}"
        render_systemd_helper "${host_dir}"
    fi

    render_host_readme "${host_dir}" "${hec_base_url}" "env_file" "${deployment_file}"
    cp "${template_dir}/README.md" "${host_dir}/README.template.md"
    log "Rendered host assets to ${host_dir}"
}

render_k8s_readme() {
    local k8s_dir="$1" hec_event_url="$2"
    cat > "${k8s_dir}/README.md" <<EOF
# Rendered SC4S Kubernetes Deployment

This directory contains rendered SC4S Helm assets.

## Files

- \`namespace.yaml\`
- \`values.yaml\`
- \`values.secret.yaml\` (optional, local-only)
- \`helm-install.sh\`

## Release settings

- namespace: \`${NAMESPACE}\`
- release: \`${RELEASE_NAME}\`
- HEC target: \`${hec_event_url}\`

## Next steps

1. Review \`values.yaml\` and confirm the replica count, TLS setting, vendor ports, and embedded context/config blocks.
2. Keep \`values.secret.yaml\` local-only if it contains a HEC token.
3. Run \`helm-install.sh\` to install or upgrade the release, or apply the files through your standard deployment workflow.
4. Validate pod readiness and SC4S startup events after deployment.
EOF
}

render_helm_helper() {
    local k8s_dir="$1"
    cat > "${k8s_dir}/helm-install.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
if ! helm repo add splunk-connect-for-syslog https://splunk.github.io/splunk-connect-for-syslog 2>/dev/null; then
  echo "WARN: helm repo add returned non-zero (repo may already exist); continuing." >&2
fi
helm repo update
cmd=(helm upgrade --install "${RELEASE_NAME}" splunk-connect-for-syslog/splunk-connect-for-syslog --namespace "${NAMESPACE}" --create-namespace -f values.yaml)
if [[ -f values.secret.yaml ]]; then
  cmd+=(-f values.secret.yaml)
fi
"\${cmd[@]}"
EOF
    make_executable "${k8s_dir}/helm-install.sh"
}

render_k8s_assets() {
    local k8s_dir template_dir hec_event_url existing_cert_block vendor_block context_block config_block token_value

    k8s_dir="${OUTPUT_DIR}/k8s"
    template_dir="${SCRIPT_DIR}/../templates/kubernetes"
    hec_event_url="$(hec_event_url_from_base "$(detect_hec_base_url)")"
    mkdir -p "${k8s_dir}"

    if [[ -n "${EXISTING_CERT}" ]]; then
        existing_cert_block="  existingCert: ${EXISTING_CERT}"$'\n'
    else
        existing_cert_block=""
    fi
    if (( ${#VENDOR_PORT_SPECS[@]} > 0 )); then
        vendor_block="$(k8s_vendor_product_block "${VENDOR_PORT_SPECS[@]}")"
    else
        vendor_block=""
    fi
    if (( ${#CONTEXT_FILE_SPECS[@]} > 0 )); then
        context_block="$(yaml_file_block "context_files" "${CONTEXT_FILE_SPECS[@]}")"
    else
        context_block=""
    fi
    if (( ${#CONFIG_FILE_SPECS[@]} > 0 )); then
        config_block="$(yaml_file_block "config_files" "${CONFIG_FILE_SPECS[@]}")"
    else
        config_block=""
    fi

    if [[ -z "${existing_cert_block}${vendor_block}${context_block}${config_block}" ]]; then
        existing_cert_block="  {}"$'\n'
    fi

    export TPL_REPLICA_COUNT="${REPLICA_COUNT}"
    export TPL_HEC_EVENT_URL="${hec_event_url}"
    export TPL_HEC_VERIFY_TLS="${HEC_TLS_VERIFY}"
    export TPL_EXISTING_CERT_BLOCK="${existing_cert_block}"
    export TPL_VENDOR_PRODUCT_BLOCK="${vendor_block}"
    export TPL_CONTEXT_FILES_BLOCK="${context_block}"
    export TPL_CONFIG_FILES_BLOCK="${config_block}"
    export TPL_NAMESPACE="${NAMESPACE}"
    render_template_to_file "${template_dir}/values.yaml" "${k8s_dir}/values.yaml"
    render_template_to_file "${template_dir}/namespace.yaml" "${k8s_dir}/namespace.yaml"
    cp "${template_dir}/README.md" "${k8s_dir}/README.template.md"

    if [[ -n "${HEC_TOKEN_FILE}" ]]; then
        assert_secret_output_dir_is_safe "${k8s_dir}"
        local _raw_token _escaped_token
        _raw_token="$(read_secret_file "${HEC_TOKEN_FILE}")"
        _escaped_token="$(printf '%s' "${_raw_token}" | python3 -c '
import sys
v = sys.stdin.read()
v = v.replace("\\", "\\\\").replace("\"", "\\\"")
print(v, end="")
')"
        write_secret_file "${k8s_dir}/values.secret.yaml" "$(cat <<EOF
splunk:
  hec_token: "${_escaped_token}"
EOF
)"
    else
        log "WARN: No --hec-token-file provided. Skipping values.secret.yaml."
    fi

    render_helm_helper "${k8s_dir}"
    render_k8s_readme "${k8s_dir}" "${hec_event_url}"
    log "Rendered Kubernetes assets to ${k8s_dir}"
}

run_compose_command() {
    local compose_dir="$1"
    shift
    if [[ "${RUNTIME}" == "docker" ]]; then
        command_exists docker || { log "ERROR: docker is required for --apply-host."; exit 1; }
        (cd "${compose_dir}" && docker compose -f docker-compose.yml "$@")
        return 0
    fi

    command_exists podman || { log "ERROR: podman is required for --apply-host."; exit 1; }
    if podman compose version >/dev/null 2>&1; then
        (cd "${compose_dir}" && podman compose -f docker-compose.yml "$@")
        return 0
    fi
    if command_exists podman-compose; then
        (cd "${compose_dir}" && podman-compose -f docker-compose.yml "$@")
        return 0
    fi
    log "ERROR: Podman compose support was not found. Install 'podman compose' or 'podman-compose'."
    exit 1
}

apply_host_assets() {
    local host_dir="${OUTPUT_DIR}/host"
    if [[ "${HOST_MODE}" == "compose" ]]; then
        if [[ ! -f "${host_dir}/docker-compose.yml" ]]; then
            log "ERROR: Missing rendered compose file at ${host_dir}/docker-compose.yml"
            exit 1
        fi
        run_compose_command "${host_dir}" pull
        run_compose_command "${host_dir}" up -d
        log "Applied SC4S compose deployment from ${host_dir}"
        return 0
    fi

    if [[ ! -x "${host_dir}/systemd-install.sh" ]]; then
        log "ERROR: Missing rendered systemd helper at ${host_dir}/systemd-install.sh"
        exit 1
    fi
    (cd "${host_dir}" && ./systemd-install.sh)
    log "Applied SC4S systemd deployment from ${host_dir}"
}

apply_k8s_assets() {
    local k8s_dir="${OUTPUT_DIR}/k8s"
    command_exists helm || { log "ERROR: helm is required for --apply-k8s."; exit 1; }
    (cd "${k8s_dir}" && ./helm-install.sh)
    log "Applied SC4S Helm deployment from ${k8s_dir}"
}

main() {
    warn_if_current_skill_role_unsupported

    validate_args

    if [[ "${DO_SPLUNK_PREP}" == "true" ]]; then
        run_splunk_prep
    fi

    if [[ "${RENDER_HOST}" == "true" ]]; then
        render_host_assets
    fi

    if [[ "${RENDER_K8S}" == "true" ]]; then
        render_k8s_assets
    fi

    if [[ "${APPLY_HOST}" == "true" ]]; then
        apply_host_assets
    fi

    if [[ "${APPLY_K8S}" == "true" ]]; then
        apply_k8s_assets
    fi
}

main
