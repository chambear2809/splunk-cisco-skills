#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

EVENT_INDEXES=(
    em_logs
    netops
)
METRIC_INDEXES=(
    em_metrics
    netmetrics
)

DO_SPLUNK_PREP=false
RENDER_COMPOSE=false
RENDER_K8S=false
APPLY_COMPOSE=false
APPLY_K8S=false
INDEXES_ONLY=false
HEC_ONLY=false

COMPOSE_RUNTIME="docker"
OUTPUT_DIR=""
DEFAULT_RENDER_DIR_NAME="sc4snmp-rendered"
SC4SNMP_IMAGE="ghcr.io/splunk/splunk-connect-for-snmp/container:latest"
HEC_TOKEN_NAME="sc4snmp"
HEC_URL=""
HEC_TLS_VERIFY="yes"
HEC_TOKEN_FILE=""
WRITE_HEC_TOKEN_FILE=""
DNS_SERVER=""
TRAP_LISTENER_IP=""
TRAP_PORT="162"
POLLER_REPLICAS="2"
SENDER_REPLICAS="1"
TRAP_REPLICAS="2"
NAMESPACE="sc4snmp"
RELEASE_NAME="sc4snmp"
INVENTORY_FILE=""
SCHEDULER_FILE=""
TRAPS_FILE=""
SNMPV3_SECRETS_FILE=""

SK=""
SESSION_READY=false
INGEST_SK=""
INGEST_SESSION_READY=false
INDEXES_CREATED=0
_ACS_HEC_CMD_GROUP=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
SC4SNMP Setup Automation

Usage: $(basename "$0") [OPTIONS]

Modes:
  --splunk-prep                  Verify/create default SC4SNMP indexes and HEC token
  --indexes-only                 With --splunk-prep, manage indexes only
  --hec-only                     With --splunk-prep, manage HEC token only
  --render-compose               Render Docker Compose assets
  --render-k8s                   Render Kubernetes/Helm assets
  --apply-compose                After --render-compose, install or upgrade the compose deployment
  --apply-k8s                    After --render-k8s, install or upgrade with helm

Common options:
  --output-dir PATH              Render output directory (default: repo-root ./sc4snmp-rendered)
  --hec-url URL                  HEC URL override; may include /services/collector/event
  --hec-token-name NAME          HEC token name (default: sc4snmp)
  --hec-token-file PATH          Local-only file containing the HEC token value
  --write-hec-token-file PATH    Write the created HEC token value to PATH when visible via REST
  --hec-tls-verify yes|no        Render HEC TLS verification setting (default: yes)
  --container-image IMAGE        SC4SNMP image (default: ghcr.io/.../container:latest)
  --dns-server IP                DNS server used to resolve the HEC endpoint
  --trap-listener-ip IP          Shared trap listener IP for Kubernetes LoadBalancer service
  --trap-port PORT               Trap listener port (default: 162)
  --inventory-file PATH          CSV inventory file override
  --scheduler-file PATH          Scheduler YAML file override
  --traps-file PATH              Traps YAML file override
  --snmpv3-secrets-file PATH     Local-only secrets.json for SNMPv3 credentials

Compose options:
  --compose-runtime docker|podman

Kubernetes options:
  --namespace NAME               Helm namespace (default: sc4snmp)
  --release-name NAME            Helm release name (default: sc4snmp)
  --poller-replicas N            Poller worker replicas (default: 2)
  --sender-replicas N            Sender worker replicas (default: 1)
  --trap-replicas N              Trap worker and trap listener replicas (default: 2)

Examples:
  $(basename "$0") --splunk-prep
  $(basename "$0") --render-compose --hec-token-file /tmp/sc4snmp_hec_token
  $(basename "$0") --render-k8s --trap-listener-ip 10.10.10.50 --hec-token-file /tmp/sc4snmp_hec_token

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --splunk-prep) DO_SPLUNK_PREP=true; shift ;;
        --indexes-only) INDEXES_ONLY=true; shift ;;
        --hec-only) HEC_ONLY=true; shift ;;
        --render-compose) RENDER_COMPOSE=true; shift ;;
        --render-k8s) RENDER_K8S=true; shift ;;
        --apply-compose) APPLY_COMPOSE=true; shift ;;
        --apply-k8s) APPLY_K8S=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --hec-url) require_arg "$1" $# || exit 1; HEC_URL="$2"; shift 2 ;;
        --hec-token-name) require_arg "$1" $# || exit 1; HEC_TOKEN_NAME="$2"; shift 2 ;;
        --hec-token-file) require_arg "$1" $# || exit 1; HEC_TOKEN_FILE="$2"; shift 2 ;;
        --write-hec-token-file) require_arg "$1" $# || exit 1; WRITE_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --hec-tls-verify) require_arg "$1" $# || exit 1; HEC_TLS_VERIFY="$2"; shift 2 ;;
        --container-image) require_arg "$1" $# || exit 1; SC4SNMP_IMAGE="$2"; shift 2 ;;
        --dns-server) require_arg "$1" $# || exit 1; DNS_SERVER="$2"; shift 2 ;;
        --trap-listener-ip) require_arg "$1" $# || exit 1; TRAP_LISTENER_IP="$2"; shift 2 ;;
        --trap-port) require_arg "$1" $# || exit 1; TRAP_PORT="$2"; shift 2 ;;
        --inventory-file) require_arg "$1" $# || exit 1; INVENTORY_FILE="$2"; shift 2 ;;
        --scheduler-file) require_arg "$1" $# || exit 1; SCHEDULER_FILE="$2"; shift 2 ;;
        --traps-file) require_arg "$1" $# || exit 1; TRAPS_FILE="$2"; shift 2 ;;
        --snmpv3-secrets-file) require_arg "$1" $# || exit 1; SNMPV3_SECRETS_FILE="$2"; shift 2 ;;
        --compose-runtime) require_arg "$1" $# || exit 1; COMPOSE_RUNTIME="$2"; shift 2 ;;
        --namespace) require_arg "$1" $# || exit 1; NAMESPACE="$2"; shift 2 ;;
        --release-name) require_arg "$1" $# || exit 1; RELEASE_NAME="$2"; shift 2 ;;
        --poller-replicas) require_arg "$1" $# || exit 1; POLLER_REPLICAS="$2"; shift 2 ;;
        --sender-replicas) require_arg "$1" $# || exit 1; SENDER_REPLICAS="$2"; shift 2 ;;
        --trap-replicas) require_arg "$1" $# || exit 1; TRAP_REPLICAS="$2"; shift 2 ;;
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
    mkdir -p "$(dirname "${target}")"
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

write_compose_bind_secret_file() {
    local path="$1" content="$2"
    # SC4SNMP Compose mounts these files into non-root containers, so owner-only
    # permissions from the render host can make them unreadable at runtime.
    write_secret_file "${path}" "${content}"
    chmod 644 "${path}"
}

make_executable() {
    chmod 755 "$1"
}

validate_args() {
    local has_mode=false

    HEC_TLS_VERIFY="$(normalize_yes_no "${HEC_TLS_VERIFY}")"

    if $DO_SPLUNK_PREP || $RENDER_COMPOSE || $RENDER_K8S; then
        has_mode=true
    fi
    if ! $has_mode; then
        log "ERROR: Select at least one mode: --splunk-prep, --render-compose, or --render-k8s."
        usage 1
    fi

    if $INDEXES_ONLY && $HEC_ONLY; then
        log "ERROR: --indexes-only and --hec-only cannot be used together."
        exit 1
    fi

    if $APPLY_COMPOSE && ! $RENDER_COMPOSE; then
        log "ERROR: --apply-compose requires --render-compose."
        exit 1
    fi

    if $APPLY_K8S && ! $RENDER_K8S; then
        log "ERROR: --apply-k8s requires --render-k8s."
        exit 1
    fi

    validate_choice "${COMPOSE_RUNTIME}" docker podman

    if [[ ! "${TRAP_PORT}" =~ ^[0-9]+$ ]] || (( TRAP_PORT < 1 || TRAP_PORT > 65535 )); then
        log "ERROR: --trap-port must be between 1 and 65535."
        exit 1
    fi

    if [[ ! "${POLLER_REPLICAS}" =~ ^[0-9]+$ ]] || (( POLLER_REPLICAS < 1 )); then
        log "ERROR: --poller-replicas must be a positive integer."
        exit 1
    fi
    if [[ ! "${SENDER_REPLICAS}" =~ ^[0-9]+$ ]] || (( SENDER_REPLICAS < 1 )); then
        log "ERROR: --sender-replicas must be a positive integer."
        exit 1
    fi
    if [[ ! "${TRAP_REPLICAS}" =~ ^[0-9]+$ ]] || (( TRAP_REPLICAS < 1 )); then
        log "ERROR: --trap-replicas must be a positive integer."
        exit 1
    fi

    if [[ -n "${HEC_TOKEN_FILE}" && ! -f "${HEC_TOKEN_FILE}" ]]; then
        log "ERROR: HEC token file not found: ${HEC_TOKEN_FILE}"
        exit 1
    fi
    if [[ -n "${INVENTORY_FILE}" && ! -f "${INVENTORY_FILE}" ]]; then
        log "ERROR: Inventory file not found: ${INVENTORY_FILE}"
        exit 1
    fi
    if [[ -n "${SCHEDULER_FILE}" && ! -f "${SCHEDULER_FILE}" ]]; then
        log "ERROR: Scheduler file not found: ${SCHEDULER_FILE}"
        exit 1
    fi
    if [[ -n "${TRAPS_FILE}" && ! -f "${TRAPS_FILE}" ]]; then
        log "ERROR: Traps file not found: ${TRAPS_FILE}"
        exit 1
    fi
    if [[ -n "${SNMPV3_SECRETS_FILE}" && ! -f "${SNMPV3_SECRETS_FILE}" ]]; then
        log "ERROR: SNMPv3 secrets file not found: ${SNMPV3_SECRETS_FILE}"
        exit 1
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

ensure_ingest_context() {
    ensure_splunk_context
    load_ingest_connection_settings
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

ensure_ingest_session() {
    local saved_user saved_pass

    ensure_ingest_context
    if [[ "${INGEST_SESSION_READY}" == "true" ]]; then
        return 0
    fi

    saved_user="${SPLUNK_USER:-}"
    saved_pass="${SPLUNK_PASS:-}"
    SPLUNK_USER="${INGEST_SPLUNK_USER:-${SPLUNK_USER:-}}"
    SPLUNK_PASS="${INGEST_SPLUNK_PASS:-${SPLUNK_PASS:-}}"
    INGEST_SK="$(get_session_key "${INGEST_SPLUNK_URI}")" || {
        SPLUNK_USER="${saved_user}"
        SPLUNK_PASS="${saved_pass}"
        log "ERROR: Could not authenticate to the ingest-tier Splunk REST API."
        exit 1
    }
    SPLUNK_USER="${saved_user}"
    SPLUNK_PASS="${saved_pass}"
    INGEST_SESSION_READY=true
}

maybe_start_ingest_session() {
    local saved_user saved_pass

    ensure_ingest_context
    if [[ "${INGEST_SESSION_READY}" == "true" ]]; then
        return 0
    fi

    saved_user="${SPLUNK_USER:-}"
    saved_pass="${SPLUNK_PASS:-}"
    SPLUNK_USER="${INGEST_SPLUNK_USER:-${SPLUNK_USER:-}}"
    SPLUNK_PASS="${INGEST_SPLUNK_PASS:-${SPLUNK_PASS:-}}"
    if INGEST_SK="$(get_session_key "${INGEST_SPLUNK_URI}" 2>/dev/null)"; then
        INGEST_SESSION_READY=true
        SPLUNK_USER="${saved_user}"
        SPLUNK_PASS="${saved_pass}"
        return 0
    fi
    SPLUNK_USER="${saved_user}"
    SPLUNK_PASS="${saved_pass}"
    return 1
}

build_index_list() {
    local idx
    for idx in "${EVENT_INDEXES[@]}"; do
        printf '%s\n' "${idx}"
    done
    for idx in "${METRIC_INDEXES[@]}"; do
        printf '%s\n' "${idx}"
    done
}

index_type_for_name() {
    local idx="$1"
    case "${idx}" in
        em_metrics|netmetrics) printf '%s' "metric" ;;
        *) printf '%s' "event" ;;
    esac
}

warn_if_wrong_index_datatype() {
    local idx="$1" expected="$2" datatype

    datatype="$(platform_get_index_datatype "${SK}" "${SPLUNK_URI}" "${idx}" 2>/dev/null || echo "")"
    case "${datatype}" in
        "${expected}"|"")
            ;;
        *)
            log "WARN: '${idx}' exists with datatype '${datatype}', expected '${expected}'."
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

    if [[ "${output_path}" == "${default_safe_dir}" || "${output_path}" == "${default_safe_dir}/compose" || "${output_path}" == "${default_safe_dir}/k8s" ]]; then
        log "Rendering secret-bearing files under the gitignored default output path: ${default_safe_dir}"
        return 0
    fi

    log "ERROR: Refusing to render secret-bearing SC4SNMP outputs inside the repo at ${output_path}."
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

parse_url_field() {
    python3 - "$1" "$2" <<'PY'
from urllib.parse import urlparse
import sys

parsed = urlparse(sys.argv[1])
field = sys.argv[2]
if field == "scheme":
    print(parsed.scheme or "https", end="")
elif field == "host":
    print(parsed.hostname or "", end="")
elif field == "port":
    default = "443" if parsed.scheme == "https" else "80"
    print(parsed.port or default, end="")
elif field == "path":
    print(parsed.path or "/services/collector/event", end="")
PY
}

image_repository() {
    printf '%s' "${SC4SNMP_IMAGE%:*}"
}

image_tag() {
    if [[ "${SC4SNMP_IMAGE}" == *:* ]]; then
        printf '%s' "${SC4SNMP_IMAGE##*:}"
    else
        printf '%s' "latest"
    fi
}

detect_hec_base_url() {
    local stack host ingest_role

    if [[ -n "${HEC_URL}" ]]; then
        normalize_hec_base_url "${HEC_URL}"
        return 0
    fi

    ensure_ingest_context
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

    if [[ -n "${INGEST_SPLUNK_HEC_URL:-}" ]]; then
        normalize_hec_base_url "${INGEST_SPLUNK_HEC_URL}"
        return 0
    fi

    ingest_role="$(resolve_ingest_target_role 2>/dev/null || true)"
    if [[ "${ingest_role}" == "indexer" ]] && deployment_index_bundle_profile >/dev/null 2>&1; then
        log "ERROR: Clustered indexer-tier ingest requires an explicit HEC URL."
        log "ERROR: Set --hec-url or configure SPLUNK_HEC_URL on the ingest profile."
        exit 1
    fi

    host="$(splunk_host_from_uri "${INGEST_SPLUNK_URI}")"
    if [[ -z "${host}" ]]; then
        host="${INGEST_SPLUNK_HOST:-${SPLUNK_HOST:-}}"
    fi
    if [[ -z "${host}" ]]; then
        log "ERROR: Could not determine the Enterprise ingest HEC host. Pass --hec-url or configure SPLUNK_INGEST_PROFILE."
        exit 1
    fi
    printf 'https://%s:8088' "${host}"
}

enterprise_hec_uses_bundle() {
    if is_splunk_cloud; then
        return 1
    fi
    type deployment_should_manage_ingest_hec_via_bundle >/dev/null 2>&1 \
        && deployment_should_manage_ingest_hec_via_bundle
}

enterprise_hec_token_state() {
    local token_name="$1"

    if enterprise_hec_uses_bundle; then
        deployment_get_bundle_hec_token_state "${token_name}" 2>/dev/null || echo "unknown"
        return 0
    fi
    if ! maybe_start_ingest_session; then
        return 1
    fi
    rest_get_hec_token_state "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "unknown"
}

enterprise_hec_token_record() {
    local token_name="$1"

    if enterprise_hec_uses_bundle; then
        deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null || echo "{}"
        return 0
    fi
    if ! maybe_start_ingest_session; then
        return 1
    fi
    rest_get_hec_token_record "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}"
}

rest_create_hec_token() {
    local token_name="$1" body resp http_code
    body=$(form_urlencode_pairs \
        name "${token_name}" \
        index "netops" \
        disabled "false" \
        useACK "0") || return 1
    resp=$(splunk_curl_post "${INGEST_SK}" "${body}" \
        "${INGEST_SPLUNK_URI}/services/data/inputs/http?output_mode=json" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(_extract_http_code "${resp}")
    case "${http_code}" in
        201|200|409) return 0 ;;
        *) return 1 ;;
    esac
}

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
        acs_command hec-token create --name "${token_name}" --default-index "netops" --disabled=false >/dev/null 2>&1
    else
        acs_command http-event-collectors create \
            --name "${token_name}" \
            --default-index "netops" \
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
    resp=$(splunk_curl_post "${INGEST_SK}" "" \
        "${INGEST_SPLUNK_URI}/services/data/inputs/http/${encoded_name}/enable" \
        -w '\n%{http_code}' 2>/dev/null)
    http_code=$(_extract_http_code "${resp}")
    case "${http_code}" in
        200|201|409) return 0 ;;
        *) return 1 ;;
    esac
}

rest_update_hec_token_default_index() {
    local token_name="$1" target_index="$2" encoded_name body resp http_code
    encoded_name="$(_urlencode "http://${token_name}")"
    body="$(form_urlencode_pairs index "${target_index}")" || return 1
    resp="$(splunk_curl_post "${INGEST_SK}" "${body}" \
        "${INGEST_SPLUNK_URI}/services/data/inputs/http/${encoded_name}?output_mode=json" \
        -w '\n%{http_code}' 2>/dev/null)"
    http_code="$(_extract_http_code "${resp}")"
    case "${http_code}" in
        200|201|409) return 0 ;;
        *) return 1 ;;
    esac
}

cloud_update_hec_token_default_index_via_acs() {
    local token_name="$1" target_index="$2" cmd_group
    cmd_group="$(acs_hec_command_group)"
    if [[ "${cmd_group}" == "hec-token" ]]; then
        acs_command hec-token update "${token_name}" --default-index "${target_index}" >/dev/null 2>&1
        return $?
    fi
    return 1
}

ensure_expected_hec_default_index() {
    local token_name="$1" expected_index="$2" token_record default_index

    if is_splunk_cloud; then
        if ! maybe_start_search_session; then
            log "WARN: Could not inspect the default index for HEC token '${token_name}' over Splunk REST."
            return 0
        fi
        token_record="$(rest_get_hec_token_record "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}")"
    else
        if ! token_record="$(enterprise_hec_token_record "${token_name}")"; then
            log "ERROR: Could not inspect the default index for HEC token '${token_name}' on the ingest tier."
            exit 1
        fi
    fi

    default_index="$(rest_json_field "${token_record}" "default_index")"
    if [[ -z "${default_index}" ]]; then
        default_index="$(rest_json_field "${token_record}" "index")"
    fi

    if [[ "${default_index}" == "${expected_index}" ]]; then
        return 0
    fi

    if is_splunk_cloud; then
        log "HEC token '${token_name}' default index is '${default_index:-unknown}'. Updating it to '${expected_index}' via ACS..."
        if ! cloud_update_hec_token_default_index_via_acs "${token_name}" "${expected_index}"; then
            log "ERROR: Failed to update HEC token '${token_name}' default index to '${expected_index}' via ACS."
            exit 1
        fi
        return 0
    fi

    if enterprise_hec_uses_bundle; then
        log "HEC token '${token_name}' default index is '${default_index:-unknown}'. Updating it to '${expected_index}' via cluster-manager bundle..."
        if ! deployment_update_cluster_bundle_hec_token_default_index "${token_name}" "${expected_index}"; then
            log "ERROR: Failed to update HEC token '${token_name}' default index to '${expected_index}' via cluster-manager bundle."
            exit 1
        fi
        token_record="$(deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null || echo "{}")"
    else
        log "HEC token '${token_name}' default index is '${default_index:-unknown}'. Updating it to '${expected_index}' via Splunk REST..."
        if ! rest_update_hec_token_default_index "${token_name}" "${expected_index}"; then
            log "ERROR: Failed to update HEC token '${token_name}' default index to '${expected_index}' via Splunk REST."
            exit 1
        fi
        token_record="$(enterprise_hec_token_record "${token_name}" 2>/dev/null || echo "{}")"
    fi

    default_index="$(rest_json_field "${token_record}" "default_index")"
    if [[ -z "${default_index}" ]]; then
        default_index="$(rest_json_field "${token_record}" "index")"
    fi
    if [[ "${default_index}" != "${expected_index}" ]]; then
        log "ERROR: HEC token '${token_name}' default index remained '${default_index:-unknown}', expected '${expected_index}'."
        exit 1
    fi
}

write_hec_token_file_if_requested() {
    local token_name="$1" token_record token_value
    [[ -n "${WRITE_HEC_TOKEN_FILE}" ]] || return 0

    if is_splunk_cloud; then
        if ! maybe_start_search_session; then
            log "WARN: Could not open a Splunk REST session to retrieve the HEC token value."
            return 0
        fi
        token_record="$(rest_get_hec_token_record "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}")"
    else
        if ! token_record="$(enterprise_hec_token_record "${token_name}")"; then
            log "WARN: Could not inspect the ingest-tier HEC token value."
            return 0
        fi
    fi

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

    if is_splunk_cloud; then
        if ! maybe_start_search_session; then
            log "WARN: Could not inspect detailed HEC token settings over Splunk REST."
            return 0
        fi
        token_record="$(rest_get_hec_token_record "${SK}" "${SPLUNK_URI}" "${token_name}" 2>/dev/null || echo "{}")"
    else
        if ! token_record="$(enterprise_hec_token_record "${token_name}")"; then
            log "WARN: Could not inspect detailed ingest-tier HEC token settings."
            return 0
        fi
    fi

    ack_state="$(rest_json_field "${token_record}" "useACK")"
    indexes_value="$(rest_json_field "${token_record}" "indexes")"
    default_index="$(rest_json_field "${token_record}" "default_index")"
    if [[ -z "${default_index}" ]]; then
        default_index="$(rest_json_field "${token_record}" "index")"
    fi

    case "${ack_state}" in
        1|true|True)
            log "WARN: HEC token '${token_name}' has acknowledgement enabled."
            ;;
    esac

    if [[ -n "${indexes_value}" ]]; then
        log "WARN: HEC token '${token_name}' has restricted Selected Indexes (${indexes_value})."
        log "WARN: Make sure it can write to em_logs, em_metrics, netops, and netmetrics."
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
        state="$(enterprise_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
        case "${state}" in
            enabled)
                log "HEC token '${HEC_TOKEN_NAME}' already exists."
                ;;
            disabled)
                if enterprise_hec_uses_bundle; then
                    log "HEC token '${HEC_TOKEN_NAME}' exists but is disabled. Enabling it via cluster-manager bundle..."
                    if ! deployment_enable_cluster_bundle_hec_token "${HEC_TOKEN_NAME}"; then
                        log "ERROR: Failed to enable disabled HEC token '${HEC_TOKEN_NAME}' via cluster-manager bundle."
                        exit 1
                    fi
                else
                    ensure_ingest_session
                    log "HEC token '${HEC_TOKEN_NAME}' exists but is disabled. Enabling it via Splunk REST..."
                    if ! rest_enable_hec_token "${HEC_TOKEN_NAME}"; then
                        log "ERROR: Failed to enable disabled HEC token '${HEC_TOKEN_NAME}' via Splunk REST."
                        exit 1
                    fi
                fi
                state="$(enterprise_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${HEC_TOKEN_NAME}' is still not enabled after the update."
                    exit 1
                fi
                log "Enabled HEC token '${HEC_TOKEN_NAME}'."
                ;;
            *)
                if enterprise_hec_uses_bundle; then
                    log "Creating HEC token '${HEC_TOKEN_NAME}' via cluster-manager bundle..."
                    if ! deployment_create_cluster_bundle_hec_token "${HEC_TOKEN_NAME}" "netops" "" "0"; then
                        log "ERROR: Failed to create HEC token '${HEC_TOKEN_NAME}' via cluster-manager bundle."
                        exit 1
                    fi
                    state="$(enterprise_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null || echo "unknown")"
                    if [[ "${state}" != "enabled" ]]; then
                        log "ERROR: HEC token '${HEC_TOKEN_NAME}' could not be verified after the cluster-manager bundle update."
                        exit 1
                    fi
                    log "Created HEC token '${HEC_TOKEN_NAME}' via cluster-manager bundle."
                else
                    ensure_ingest_session
                    log "Creating HEC token '${HEC_TOKEN_NAME}' via Splunk REST..."
                    if ! rest_create_hec_token "${HEC_TOKEN_NAME}"; then
                        log "ERROR: Failed to create HEC token '${HEC_TOKEN_NAME}' via Splunk REST."
                        exit 1
                    fi
                    log "Created HEC token '${HEC_TOKEN_NAME}'."
                fi
                ;;
        esac
    fi

    ensure_expected_hec_default_index "${HEC_TOKEN_NAME}" "netops"
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
            warn_if_wrong_index_datatype "${idx}" "${index_type}"
            continue
        fi
        log "Creating index '${idx}'..."
        if ! platform_create_index "${SK}" "${SPLUNK_URI}" "${idx}" "512000" "${index_type}" 2>/dev/null; then
            log "ERROR: Failed to create index '${idx}'."
            exit 1
        fi
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
    log "Detected SC4SNMP HEC base URL: ${hec_base}"
    log "Detected SC4SNMP HEC event URL: ${event_url}"

    if [[ "${HEC_ONLY}" != "true" ]]; then
        ensure_indexes
    fi
    if [[ "${INDEXES_ONLY}" != "true" ]]; then
        ensure_hec_token
    fi
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

default_inventory_content() {
    cat <<'EOF'
address,port,version,community,secret,security_engine,walk_interval,profiles,smart_profiles,delete
192.0.2.10,161,2c,public,,,300,if_mib,,false
EOF
}

default_scheduler_content() {
    cat <<'EOF'
groups:
  campus_switches:
    - address: 192.0.2.10
      port: 161
profiles:
  if_mib:
    frequency: 300
    varBinds:
      - ['IF-MIB', 'ifDescr']
      - ['IF-MIB', 'ifOperStatus']
EOF
}

default_traps_content() {
    cat <<'EOF'
communities:
  2c:
    - public
  1:
    - public
EOF
}

load_config_content() {
    local fpath="$1" kind="$2"
    if [[ -n "${fpath}" ]]; then
        cat "${fpath}"
        return 0
    fi
    case "${kind}" in
        inventory) default_inventory_content ;;
        scheduler) default_scheduler_content ;;
        traps) default_traps_content ;;
    esac
}

indent_block() {
    local spaces="$1" text="$2"
    python3 - "$spaces" "$text" <<'PY'
import sys

spaces = int(sys.argv[1])
text = sys.argv[2]
prefix = " " * spaces
for line in text.splitlines():
    print(prefix + line)
if not text.strip():
    print(prefix)
PY
}

render_compose_readme() {
    local compose_dir="$1" hec_event_url="$2"
    write_text_file "${compose_dir}/README.md" "$(cat <<EOF
# Rendered SC4SNMP Compose Deployment

This directory contains rendered SC4SNMP Docker Compose assets.

## Files

- \`.env\`
- \`docker-compose.yml\`
- \`config/inventory.csv\`
- \`config/scheduler-config.yaml\`
- \`config/traps-config.yaml\`
- \`secrets/\`
- \`compose-up.sh\`
- \`compose-down.sh\`

## HEC target

- \`${hec_event_url}\`

## Next steps

1. Review the rendered config files and confirm the device inventory, profiles, and trap communities.
2. Keep \`secrets/\` local-only.
3. Run \`compose-up.sh\` to install or upgrade the stack, or use your standard compose workflow.
4. Validate indexed data after the stack is running.
EOF
)"
}

render_compose_helpers() {
    local compose_dir="$1" runtime_name="$2"
    write_text_file "${compose_dir}/compose-up.sh" "$(cat <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
${runtime_name} compose -f docker-compose.yml pull
${runtime_name} compose -f docker-compose.yml up -d
EOF
)"
    write_text_file "${compose_dir}/compose-down.sh" "$(cat <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
${runtime_name} compose -f docker-compose.yml down
EOF
)"
    make_executable "${compose_dir}/compose-up.sh"
    make_executable "${compose_dir}/compose-down.sh"
}

render_compose_assets() {
    local compose_dir template_dir inventory_content scheduler_content traps_content
    local hec_base hec_event_url hec_protocol hec_host hec_port hec_path insecure_ssl

    compose_dir="${OUTPUT_DIR}/compose"
    template_dir="${SCRIPT_DIR}/../templates/compose"
    hec_base="$(detect_hec_base_url)"
    hec_event_url="$(hec_event_url_from_base "${hec_base}")"
    hec_protocol="$(parse_url_field "${hec_base}" "scheme")"
    hec_host="$(parse_url_field "${hec_base}" "host")"
    hec_port="$(parse_url_field "${hec_base}" "port")"
    hec_path="$(parse_url_field "${hec_event_url}" "path")"
    if [[ "${HEC_TLS_VERIFY}" == "yes" ]]; then
        insecure_ssl="false"
    else
        insecure_ssl="true"
    fi

    mkdir -p "${compose_dir}/config" "${compose_dir}/secrets" "${compose_dir}/mibs"
    if [[ -n "${HEC_TOKEN_FILE}" ]]; then
        assert_secret_output_dir_is_safe "${compose_dir}"
        write_compose_bind_secret_file "${compose_dir}/secrets/hec_token" "$(read_secret_file "${HEC_TOKEN_FILE}")"$'\n'
    else
        write_compose_bind_secret_file "${compose_dir}/secrets/hec_token.example" "<replace-with-hec-token>"$'\n'
        log "WARN: No --hec-token-file provided. Rendering a placeholder token file."
    fi
    if [[ -n "${SNMPV3_SECRETS_FILE}" ]]; then
        cp "${SNMPV3_SECRETS_FILE}" "${compose_dir}/secrets/secrets.json"
        chmod 644 "${compose_dir}/secrets/secrets.json"
    else
        write_compose_bind_secret_file "${compose_dir}/secrets/secrets.json.example" $'{\n  "example": {\n    "username": "snmp-user",\n    "authprotocol": "SHA",\n    "authkey": "replace-me"\n  }\n}\n'
    fi

    inventory_content="$(load_config_content "${INVENTORY_FILE}" "inventory")"
    scheduler_content="$(load_config_content "${SCHEDULER_FILE}" "scheduler")"
    traps_content="$(load_config_content "${TRAPS_FILE}" "traps")"
    write_text_file "${compose_dir}/config/inventory.csv" "${inventory_content}"$'\n'
    write_text_file "${compose_dir}/config/scheduler-config.yaml" "${scheduler_content}"$'\n'
    write_text_file "${compose_dir}/config/traps-config.yaml" "${traps_content}"$'\n'

    export TPL_SC4SNMP_IMAGE="${SC4SNMP_IMAGE}"
    export TPL_SPLUNK_HEC_PROTOCOL="${hec_protocol}"
    export TPL_SPLUNK_HEC_HOST="${hec_host}"
    export TPL_SPLUNK_HEC_PORT="${hec_port}"
    export TPL_SPLUNK_HEC_PATH="${hec_path}"
    export TPL_SPLUNK_HEC_INSECURESSL="${insecure_ssl}"
    export TPL_TRAPS_PORT="${TRAP_PORT}"
    export TPL_DNS_SERVER="${DNS_SERVER}"
    render_template_to_file "${template_dir}/env.example" "${compose_dir}/.env"
    chmod 600 "${compose_dir}/.env"

    export TPL_SC4SNMP_IMAGE="${SC4SNMP_IMAGE}"
    export TPL_TRAPS_PORT="${TRAP_PORT}"
    render_template_to_file "${template_dir}/docker-compose.yml" "${compose_dir}/docker-compose.yml"

    render_compose_helpers "${compose_dir}" "${COMPOSE_RUNTIME}"
    render_compose_readme "${compose_dir}" "${hec_event_url}"
    cp "${template_dir}/README.md" "${compose_dir}/README.template.md"
    log "Rendered Docker Compose assets to ${compose_dir}"
}

render_k8s_readme() {
    local k8s_dir="$1" hec_event_url="$2"
    write_text_file "${k8s_dir}/README.md" "$(cat <<EOF
# Rendered SC4SNMP Kubernetes Deployment

This directory contains rendered SC4SNMP Helm assets.

## Files

- \`namespace.yaml\`
- \`values.yaml\`
- \`values.secret.yaml\`
- \`helm-install.sh\`

## Release settings

- namespace: \`${NAMESPACE}\`
- release: \`${RELEASE_NAME}\`
- HEC target: \`${hec_event_url}\`

## Next steps

1. Review \`values.yaml\` and confirm the inventory, scheduler, trap communities, and replica counts.
2. Keep \`values.secret.yaml\` local-only.
3. Create any Kubernetes secrets needed for SNMPv3 usernames before deployment.
4. Run \`helm-install.sh\` to install or upgrade the release, or apply the files through your standard workflow.
EOF
)"
}

render_helm_helper() {
    local k8s_dir="$1"
    write_text_file "${k8s_dir}/helm-install.sh" "$(cat <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
if ! helm repo add splunk-connect-for-snmp https://splunk.github.io/splunk-connect-for-snmp 2>&1; then
  echo "WARN: helm repo add failed (may already exist). Continuing." >&2
fi
helm repo update
cmd=(helm upgrade --install "${RELEASE_NAME}" splunk-connect-for-snmp/splunk-connect-for-snmp --namespace "${NAMESPACE}" --create-namespace -f values.yaml)
if [[ -f values.secret.yaml ]]; then
  cmd+=(-f values.secret.yaml)
fi
"\${cmd[@]}"
EOF
)"
    make_executable "${k8s_dir}/helm-install.sh"
}

render_k8s_assets() {
    local k8s_dir template_dir inventory_content scheduler_content traps_content
    local hec_base hec_event_url hec_protocol hec_host hec_port insecure_ssl
    local inventory_block scheduler_block traps_block trap_service_type

    k8s_dir="${OUTPUT_DIR}/k8s"
    template_dir="${SCRIPT_DIR}/../templates/kubernetes"
    mkdir -p "${k8s_dir}"

    hec_base="$(detect_hec_base_url)"
    hec_event_url="$(hec_event_url_from_base "${hec_base}")"
    hec_protocol="$(parse_url_field "${hec_base}" "scheme")"
    hec_host="$(parse_url_field "${hec_base}" "host")"
    hec_port="$(parse_url_field "${hec_base}" "port")"
    if [[ "${HEC_TLS_VERIFY}" == "yes" ]]; then
        insecure_ssl="false"
    else
        insecure_ssl="true"
    fi

    inventory_content="$(load_config_content "${INVENTORY_FILE}" "inventory")"
    scheduler_content="$(load_config_content "${SCHEDULER_FILE}" "scheduler")"
    traps_content="$(load_config_content "${TRAPS_FILE}" "traps")"
    inventory_block="$(indent_block 4 "${inventory_content}")"
    scheduler_block="$(indent_block 2 "${scheduler_content}")"
    traps_block="$(indent_block 2 "${traps_content}")"
    local load_balancer_ip_line
    if [[ -n "${TRAP_LISTENER_IP}" ]]; then
        trap_service_type="LoadBalancer"
        load_balancer_ip_line="    loadBalancerIP: \"${TRAP_LISTENER_IP}\""$'\n'
    else
        trap_service_type="NodePort"
        load_balancer_ip_line=""
    fi

    TPL_SC4SNMP_IMAGE_REPOSITORY="$(image_repository)"
    export TPL_SC4SNMP_IMAGE_REPOSITORY
    TPL_SC4SNMP_IMAGE_TAG="$(image_tag)"
    export TPL_SC4SNMP_IMAGE_TAG
    export TPL_SPLUNK_HEC_PROTOCOL="${hec_protocol}"
    export TPL_SPLUNK_HEC_HOST="${hec_host}"
    export TPL_SPLUNK_HEC_PORT="${hec_port}"
    export TPL_SPLUNK_HEC_INSECURESSL="${insecure_ssl}"
    export TPL_INVENTORY_BLOCK="${inventory_block}"
    export TPL_SCHEDULER_BLOCK="${scheduler_block}"$'\n'
    export TPL_POLLER_REPLICAS="${POLLER_REPLICAS}"
    export TPL_SENDER_REPLICAS="${SENDER_REPLICAS}"
    export TPL_TRAP_REPLICAS="${TRAP_REPLICAS}"
    export TPL_TRAPS_BLOCK="${traps_block}"
    export TPL_TRAP_SERVICE_TYPE="${trap_service_type}"
    export TPL_TRAPS_PORT="${TRAP_PORT}"
    export TPL_LOAD_BALANCER_IP_LINE="${load_balancer_ip_line}"
    export TPL_DNS_SERVER="${DNS_SERVER}"
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
  token: "${_escaped_token}"
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
    if [[ "${COMPOSE_RUNTIME}" == "docker" ]]; then
        command_exists docker || { log "ERROR: docker is required for --apply-compose."; exit 1; }
        (cd "${compose_dir}" && docker compose -f docker-compose.yml "$@")
        return 0
    fi

    command_exists podman || { log "ERROR: podman is required for --apply-compose."; exit 1; }
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

apply_compose_assets() {
    local compose_dir="${OUTPUT_DIR}/compose"
    if [[ ! -f "${compose_dir}/docker-compose.yml" ]]; then
        log "ERROR: Missing rendered compose file at ${compose_dir}/docker-compose.yml"
        exit 1
    fi
    run_compose_command "${compose_dir}" pull
    run_compose_command "${compose_dir}" up -d
    log "Applied SC4SNMP compose deployment from ${compose_dir}"
}

apply_k8s_assets() {
    local k8s_dir="${OUTPUT_DIR}/k8s"
    command_exists helm || { log "ERROR: helm is required for --apply-k8s."; exit 1; }
    (cd "${k8s_dir}" && ./helm-install.sh)
    log "Applied SC4SNMP Helm deployment from ${k8s_dir}"
}

main() {
    warn_if_current_skill_role_unsupported
    validate_args

    if [[ "${DO_SPLUNK_PREP}" == "true" ]]; then
        run_splunk_prep
    fi
    if [[ "${RENDER_COMPOSE}" == "true" ]]; then
        render_compose_assets
    fi
    if [[ "${RENDER_K8S}" == "true" ]]; then
        render_k8s_assets
    fi
    if [[ "${APPLY_COMPOSE}" == "true" ]]; then
        apply_compose_assets
    fi
    if [[ "${APPLY_K8S}" == "true" ]]; then
        apply_k8s_assets
    fi
}

main
