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

read_hec_token_value() {
    local token_path="$1" token_value
    if ! token_value="$(read_secret_file "${token_path}")"; then
        log "ERROR: Could not securely read HEC token file '${token_path}'. Use a nonempty, single-link regular file with mode 0400 or 0600." >&2
        return 1
    fi
    printf '%s' "${token_value}"
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
            log "ERROR: Expected yes or no, got '${1:-}'." >&2
            return 1
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

validate_hec_base_url() {
    python3 - "${1:-}" <<'PY'
import ipaddress
import re
import sys
from urllib.parse import urlsplit

raw = sys.argv[1]
try:
    parsed = urlsplit(raw)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if (
    parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
    or any(character.isspace() or ord(character) < 0x20 for character in raw)
    or parsed.path
    not in {
        "",
        "/",
        "/services/collector/event",
        "/services/collector/event/",
        "/services/collector/raw",
        "/services/collector/raw/",
    }
    or (port is not None and not 1 <= port <= 65535)
):
    raise SystemExit(1)
host = parsed.hostname
try:
    ipaddress.ip_address(host)
except ValueError:
    labels = host.split(".")
    if any(
        not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in labels
    ):
        raise SystemExit(1)
PY
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
    local previous_umask tmp
    ensure_parent_dir "${path}"
    if [[ -L "${path}" ]]; then
        log "ERROR: Refusing symbolic-link secret output path: ${path}"
        return 1
    fi
    previous_umask="$(umask)"
    umask 077
    tmp="$(mktemp "${path}.tmp.XXXXXX")" || { umask "${previous_umask}"; return 1; }
    if ! printf '%s' "${content}" > "${tmp}" || ! chmod 600 "${tmp}" || ! mv -f -- "${tmp}" "${path}"; then
        rm -f -- "${tmp}"
        umask "${previous_umask}"
        return 1
    fi
    umask "${previous_umask}"
}

write_compose_bind_secret_file() {
    local path="$1" content="$2"
    # Default to owner-only readable secrets. If your container runtime
    # needs group access (e.g. a non-root container UID mapped to a host
    # group that is intentionally on the file), `chmod 640` and `chgrp
    # <runtime-group>` the file after rendering, ideally as a documented
    # post-step rather than in this generic helper.
    write_secret_file "${path}" "${content}"
    chmod 600 "${path}"
}

make_executable() {
    chmod 755 "$1"
}

validate_args() {
    local has_mode=false applying=false future_token=false

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

    if $APPLY_COMPOSE || $APPLY_K8S; then
        applying=true
    fi
    if $DO_SPLUNK_PREP && [[ -n "${WRITE_HEC_TOKEN_FILE}" ]]; then
        future_token=true
    fi
    if $applying && [[ -z "${HEC_TOKEN_FILE}" ]] && ! $future_token; then
        log "ERROR: Live apply requires --hec-token-file, or --splunk-prep with --write-hec-token-file."
        exit 1
    fi

    validate_choice "${COMPOSE_RUNTIME}" docker podman

    if (( ${#NAMESPACE} > 63 )) || [[ ! "${NAMESPACE}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
        log "ERROR: --namespace must be a lowercase Kubernetes DNS label of at most 63 characters."
        exit 1
    fi
    if (( ${#RELEASE_NAME} > 53 )) || [[ ! "${RELEASE_NAME}" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]]; then
        log "ERROR: --release-name must be a lowercase Helm release name of at most 53 characters."
        exit 1
    fi
    if [[ ! "${SC4SNMP_IMAGE}" =~ ^[A-Za-z0-9][A-Za-z0-9._/:-]*$ ]]; then
        log "ERROR: --container-image contains unsupported container-reference characters."
        exit 1
    fi
    if [[ -n "${HEC_URL}" ]] && ! validate_hec_base_url "${HEC_URL}"; then
        log "ERROR: --hec-url must be a credential-free HTTPS HEC base, /event, or /raw URL."
        exit 1
    fi
    if [[ -n "${DNS_SERVER}" ]] && ! python3 - "${DNS_SERVER}" <<'PY'
import ipaddress, sys
ipaddress.ip_address(sys.argv[1])
PY
    then
        log "ERROR: --dns-server must be an IPv4 or IPv6 address."
        exit 1
    fi
    if [[ -n "${TRAP_LISTENER_IP}" ]] && ! python3 - "${TRAP_LISTENER_IP}" <<'PY'
import ipaddress, sys
ipaddress.ip_address(sys.argv[1])
PY
    then
        log "ERROR: --trap-listener-ip must be an IPv4 or IPv6 address."
        exit 1
    fi

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

    if [[ -n "${HEC_TOKEN_FILE}" && ! -f "${HEC_TOKEN_FILE}" ]] && ! $future_token; then
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

ensure_apply_token_ready() {
    local token_value=""
    if $APPLY_COMPOSE || $APPLY_K8S; then
        if [[ -n "${HEC_TOKEN_FILE}" && -L "${HEC_TOKEN_FILE}" ]]; then
            log "ERROR: HEC token file must be a regular file, not a symbolic link: ${HEC_TOKEN_FILE}"
            exit 1
        fi
        if [[ -z "${HEC_TOKEN_FILE}" || ! -s "${HEC_TOKEN_FILE}" ]]; then
            log "ERROR: Live apply is blocked because no nonempty HEC token file is available."
            log "HANDOFF: Provide --hec-token-file PATH, or combine --splunk-prep with --write-hec-token-file PATH."
            exit 1
        fi
        if ! token_value="$(read_hec_token_value "${HEC_TOKEN_FILE}")"; then
            exit 1
        fi
        if [[ -z "${token_value}" ]]; then
            log "ERROR: Live apply is blocked because the HEC token file contains only whitespace."
            exit 1
        fi
        if ! python3 - "${HEC_TOKEN_FILE}" <<'PY'
import os
import sys
raise SystemExit(0 if os.stat(sys.argv[1]).st_mode & 0o077 == 0 else 1)
PY
        then
            log "ERROR: HEC token file must not be readable or writable by group/other users: ${HEC_TOKEN_FILE}"
            exit 1
        fi
    fi
}

ensure_splunk_context() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
}

ensure_ingest_context() {
    if ! ensure_splunk_context; then
        return 1
    fi
    if ! load_ingest_connection_settings; then
        log "ERROR: Could not load the selected Splunk ingest target settings."
        return 1
    fi
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

    if ! ensure_ingest_context; then
        return 1
    fi
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

    if ! ensure_ingest_context; then
        return 1
    fi
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
    local last_component="${SC4SNMP_IMAGE##*/}"
    if [[ "${last_component}" == *:* ]]; then
        printf '%s' "${SC4SNMP_IMAGE%:*}"
    else
        printf '%s' "${SC4SNMP_IMAGE}"
    fi
}

image_tag() {
    local last_component="${SC4SNMP_IMAGE##*/}"
    if [[ "${last_component}" == *:* ]]; then
        printf '%s' "${last_component##*:}"
    else
        printf '%s' "latest"
    fi
}

detect_hec_base_url() {
    local stack host ingest_role bundle_status=0

    if [[ -n "${HEC_URL}" ]]; then
        normalize_hec_base_url "${HEC_URL}"
        return 0
    fi

    if ! ensure_ingest_context; then
        return 1
    fi
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

    if ! ingest_role="$(resolve_ingest_target_role)"; then
        log "ERROR: Could not resolve the selected Splunk ingest target role."
        return 1
    fi
    if [[ "${ingest_role}" == "indexer" ]]; then
        if deployment_index_bundle_profile >/dev/null; then
            log "ERROR: Clustered indexer-tier ingest requires an explicit HEC URL."
            log "ERROR: Set --hec-url or configure SPLUNK_HEC_URL on the ingest profile."
            return 1
        else
            bundle_status=$?
            if (( bundle_status == 2 )); then
                log "ERROR: Could not resolve the configured index-tier deployment target."
                return 1
            fi
        fi
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
    local platform="" bundle_status=0

    _DEPLOYMENT_BUNDLE_CHECK_ERROR=false
    if ! platform="$(resolve_splunk_platform)"; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    case "${platform}" in
        cloud) return 1 ;;
        enterprise) ;;
        *)
            _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
            log "ERROR: Unsupported Splunk platform '${platform}'; refusing HEC delivery routing."
            return 2
            ;;
    esac
    if ! type deployment_should_manage_ingest_hec_via_bundle >/dev/null 2>&1; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if deployment_should_manage_ingest_hec_via_bundle; then
        return 0
    else
        bundle_status=$?
    fi
    if (( bundle_status == 2 )) \
        || [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    return 1
}

enterprise_hec_token_state() {
    local token_name="$1" state=""

    if enterprise_hec_uses_bundle; then
        deployment_get_bundle_hec_token_state "${token_name}" 2>/dev/null
        return $?
    fi
    if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
        log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
        return 1
    fi
    if ! maybe_start_ingest_session; then
        return 1
    fi
    if ! state="$(rest_get_hec_token_state \
        "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null)"; then
        return 1
    fi
    case "${state}" in
        enabled|disabled|missing) printf '%s' "${state}" ;;
        *) return 1 ;;
    esac
}

enterprise_hec_token_record() {
    local token_name="$1"

    if enterprise_hec_uses_bundle; then
        deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null
        return $?
    fi
    if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
        log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
        return 1
    fi
    if ! maybe_start_ingest_session; then
        return 1
    fi
    rest_get_hec_token_record "${INGEST_SK}" "${INGEST_SPLUNK_URI}" "${token_name}" 2>/dev/null
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
    http_code=$(echo "${resp}" | tail -1)
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
    # Detect only the local CLI surface; a remote/auth failure must not select a fallback.
    if command acs hec-token list --help >/dev/null 2>&1; then
        _ACS_HEC_CMD_GROUP="hec-token"
    elif command acs http-event-collectors describe --help >/dev/null 2>&1; then
        _ACS_HEC_CMD_GROUP="http-event-collectors"
    else
        return 1
    fi
    printf '%s' "${_ACS_HEC_CMD_GROUP}"
}

cloud_describe_hec_token_state() {
    local token_name="$1" cmd_group="$2" output command_succeeded=false

    if output="$(acs_command "${cmd_group}" describe "${token_name}" 2>&1)"; then
        command_succeeded=true
    fi
    printf '%s' "${output}" | python3 -c '
import json
import re
import sys

requested = sys.argv[1]
command_succeeded = sys.argv[2] == "true"
raw = sys.stdin.read()
if not raw.strip() or len(raw.encode("utf-8")) > 1024 * 1024:
    raise SystemExit(1)
try:
    parsed = json.loads(raw)
except Exception:
    parsed = None

def walk(value, depth=0):
    if depth > 8:
        return
    yield value
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "response" and isinstance(child, str):
                try:
                    child = json.loads(child)
                except Exception:
                    continue
            yield from walk(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child, depth + 1)

def state_from_disabled(value):
    if isinstance(value, bool):
        return "disabled" if value else "enabled"
    normalized = str(value).strip().lower()
    if normalized in ("1", "true"):
        return "disabled"
    if normalized in ("0", "false"):
        return "enabled"
    raise ValueError("invalid disabled value")

if command_succeeded:
    if parsed is None:
        raise SystemExit(1)
    if isinstance(parsed, list):
        http_items = [
            item for item in parsed
            if isinstance(item, dict) and item.get("type") == "http"
        ]
        if len(http_items) != 1:
            raise SystemExit(1)
        status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")
        statuses = [http_items[0][key] for key in status_keys if key in http_items[0]]
        if statuses:
            if any(not str(value).isdigit() for value in statuses):
                raise SystemExit(1)
            normalized_statuses = {int(value) for value in statuses}
            if len(normalized_statuses) != 1 or not 200 <= next(iter(normalized_statuses)) <= 299:
                raise SystemExit(1)
    observations = []
    for node in walk(parsed):
        if not isinstance(node, dict):
            continue
        spec = node.get("spec")
        if isinstance(spec, dict) and isinstance(spec.get("name"), str) and spec["name"]:
            if "disabled" in spec:
                disabled = spec["disabled"]
            elif "disabled" in node:
                disabled = node["disabled"]
            else:
                raise SystemExit(1)
            observations.append((spec["name"], state_from_disabled(disabled)))
        direct_name = node.get("name") or node.get("tokenName")
        if isinstance(direct_name, str) and direct_name and "disabled" in node:
            observations.append((direct_name, state_from_disabled(node["disabled"])))
    names = {name for name, _state in observations}
    states = {state for name, state in observations if name == requested}
    if names != {requested} or len(states) != 1:
        raise SystemExit(1)
    print(states.pop(), end="")
    raise SystemExit(0)

status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")

def has_404(value):
    if not isinstance(value, dict):
        return False
    values = [str(value[key]).strip() for key in status_keys if key in value]
    return bool(values) and all(item == "404" for item in values)

def exact_http_404(value):
    if isinstance(value, dict):
        return has_404(value)
    if not isinstance(value, list):
        return False
    http_items = [
        item for item in value
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    return len(http_items) == 1 and has_404(http_items[0])

if parsed is not None and exact_http_404(parsed):
    print("missing", end="")
    raise SystemExit(0)

plain = " ".join(raw.split())
plain = re.sub(r"^error:\s*", "", plain, flags=re.IGNORECASE).rstrip(".")
for marker in (chr(34), chr(39), "[", "]"):
    plain = plain.replace(marker, "")
escaped = re.escape(requested)
patterns = (
    rf"^(?:hec[ -]?token|http event collector|token|resource)\s+{escaped}\s+(?:is\s+|was\s+)?not[ -]?found$",
    rf"^no such (?:hec[ -]?token|http event collector|token|resource)\s*:?\s*{escaped}$",
    rf"^(?:hec[ -]?token|http event collector|token|resource)\s+{escaped}\s+does not exist$",
)
if any(re.fullmatch(pattern, plain, flags=re.IGNORECASE) for pattern in patterns):
    print("missing", end="")
    raise SystemExit(0)
raise SystemExit(1)
' "${token_name}" "${command_succeeded}" 2>/dev/null
}

cloud_get_hec_token_state() {
    local token_name="$1" cmd_group raw page_result page_count page_state
    local count=100 offset=0 page_number=0 max_pages=100
    if ! cmd_group="$(acs_hec_command_group)"; then
        return 1
    fi

    if [[ "${cmd_group}" == "http-event-collectors" ]]; then
        cloud_describe_hec_token_state "${token_name}" "${cmd_group}"
        return $?
    fi

    while (( page_number < max_pages )); do
        if ! raw="$(acs_command hec-token list --count "${count}" --offset "${offset}" 2>/dev/null)"; then
            return 1
        fi

        if ! page_result="$(printf '%s' "${raw}" | python3 -c '
import json, sys

target = sys.argv[1]
page_limit = int(sys.argv[2])
try:
    text = sys.stdin.read()
    if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("empty or oversized ACS HEC inventory page")
    structured = json.loads(text)
except Exception:
    raise SystemExit(1)

payload = structured
if isinstance(structured, list):
    http_items = [
        item for item in structured
        if isinstance(item, dict) and item.get("type") == "http"
    ]
    if len(http_items) != 1:
        raise SystemExit(1)
    item = http_items[0]
    status_keys = ("code", "status", "statusCode", "status_code", "httpStatus", "http_status")
    statuses = [item[key] for key in status_keys if key in item]
    if statuses:
        if any(not str(value).isdigit() for value in statuses):
            raise SystemExit(1)
        normalized_statuses = {int(value) for value in statuses}
        if len(normalized_statuses) != 1 or not 200 <= next(iter(normalized_statuses)) <= 299:
            raise SystemExit(1)
    response = item.get("response")
    if not isinstance(response, str) or not response.strip():
        raise SystemExit(1)
    try:
        payload = json.loads(response)
    except Exception:
        raise SystemExit(1)
if not isinstance(payload, dict):
    raise SystemExit(1)
keys = ("http-event-collectors", "http_event_collectors", "tokens")
present = [key for key in keys if key in payload]
if len(present) != 1 or not isinstance(payload[present[0]], list):
    raise SystemExit(1)
collectors = payload[present[0]]
if len(collectors) > page_limit:
    raise SystemExit(1)
matches = []
for collector in collectors:
    if not isinstance(collector, dict) or not isinstance(collector.get("spec", {}), dict):
        raise SystemExit(1)
    spec = collector.get("spec", {})
    name = spec.get("name") or collector.get("name", "")
    if not isinstance(name, str) or not name:
        raise SystemExit(1)
    if name != target:
        continue
    if "disabled" in spec:
        disabled_value = spec["disabled"]
    elif "disabled" in collector:
        disabled_value = collector["disabled"]
    else:
        raise SystemExit(1)
    disabled = str(disabled_value).strip().lower()
    if disabled in ("1", "true"):
        matches.append("disabled")
    elif disabled in ("0", "false"):
        matches.append("enabled")
    else:
        raise SystemExit(1)
if len(matches) > 1:
    raise SystemExit(1)
state = matches[0] if matches else "absent"
print(f"{len(collectors)}:{state}", end="")
' "${token_name}" "${count}" 2>/dev/null)"; then
            return 1
        fi
        page_count="${page_result%%:*}"
        page_state="${page_result#*:}"
        [[ "${page_count}" =~ ^[0-9]+$ ]] || return 1
        case "${page_state}" in
            enabled|disabled)
                printf '%s' "${page_state}"
                return 0
                ;;
            absent) ;;
            *) return 1 ;;
        esac
        if (( page_count < count )); then
            printf 'missing'
            return 0
        fi
        offset=$((offset + count))
        page_number=$((page_number + 1))
    done
    return 1
}

cloud_rest_get_hec_token_record() {
    local token_name="$1" raw response http_code
    if ! maybe_start_search_session; then
        return 1
    fi
    if ! response="$(splunk_curl "${SK}" \
        "${SPLUNK_URI}/services/data/inputs/http?output_mode=json&count=0" \
        -w '\n%{http_code}' 2>/dev/null)"; then
        return 1
    fi
    http_code="${response##*$'\n'}"
    [[ "${http_code}" == "200" ]] || return 1
    raw="${response%$'\n'*}"

    printf '%s' "${raw}" | python3 -c '
import json, sys

target = sys.argv[1]
aliases = {target, f"http://{target}"}
try:
    text = sys.stdin.read()
    if not text.strip() or len(text.encode("utf-8")) > 1024 * 1024:
        raise ValueError("empty or oversized HEC inventory")
    data = json.loads(text)
except Exception:
    raise SystemExit(1)
if not isinstance(data, dict) or not isinstance(data.get("entry"), list):
    raise SystemExit(1)
matches = []
for entry in data["entry"]:
    if not isinstance(entry, dict):
        raise SystemExit(1)
    name = entry.get("name", "")
    content = entry.get("content", {})
    if not isinstance(name, str) or not isinstance(content, dict):
        raise SystemExit(1)
    if name not in aliases:
        continue
    matches.append((name, content))
if not matches:
    raise SystemExit(2)
if len(matches) != 1:
    raise SystemExit(1)
name, content = matches[0]
default_index = content.get("index")
if not isinstance(default_index, str) or not default_index:
    raise SystemExit(1)
indexes = content.get("indexes", "")
if isinstance(indexes, list):
    indexes = ",".join(str(item) for item in indexes)
elif not isinstance(indexes, str):
    raise SystemExit(1)
record = {
    "name": name,
    "disabled": str(content.get("disabled", "")),
    "useACK": str(content.get("useACK", content.get("useAck", ""))),
    "indexes": str(indexes),
    "default_index": default_index,
    "token": str(content.get("token", "")),
}
json.dump(record, sys.stdout, separators=(",", ":"))
' "${token_name}" 2>/dev/null
}

cloud_create_hec_token_via_acs() {
    local token_name="$1" cmd_group
    if ! cmd_group="$(acs_hec_command_group)"; then
        return 1
    fi
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
    if ! cmd_group="$(acs_hec_command_group)"; then
        return 1
    fi
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
    http_code=$(echo "${resp}" | tail -1)
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
    http_code="$(echo "${resp}" | tail -1)"
    case "${http_code}" in
        200|201|409) return 0 ;;
        *) return 1 ;;
    esac
}

cloud_update_hec_token_default_index_via_acs() {
    local token_name="$1" target_index="$2" cmd_group
    if ! cmd_group="$(acs_hec_command_group)"; then
        return 1
    fi
    if [[ "${cmd_group}" == "hec-token" ]]; then
        acs_command hec-token update "${token_name}" --default-index "${target_index}" >/dev/null 2>&1
        return $?
    fi
    return 1
}

ensure_expected_hec_default_index() {
    local token_name="$1" expected_index="$2" token_record default_index

    if is_splunk_cloud; then
        if ! token_record="$(cloud_rest_get_hec_token_record "${token_name}")"; then
            log "ERROR: Could not inspect the default index for HEC token '${token_name}' over Splunk REST; refusing mutation."
            return 1
        fi
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
            return 1
        fi
        if ! token_record="$(cloud_rest_get_hec_token_record "${token_name}")"; then
            log "ERROR: Could not read back HEC token '${token_name}' after the ACS default-index update."
            return 1
        fi
        default_index="$(rest_json_field "${token_record}" "default_index")"
        if [[ "${default_index}" != "${expected_index}" ]]; then
            log "ERROR: HEC token '${token_name}' default index remained '${default_index:-unknown}', expected '${expected_index}'."
            return 1
        fi
        return 0
    fi

    if enterprise_hec_uses_bundle; then
        log "HEC token '${token_name}' default index is '${default_index:-unknown}'. Updating it to '${expected_index}' via cluster-manager bundle..."
        if ! deployment_update_cluster_bundle_hec_token_default_index "${token_name}" "${expected_index}"; then
            log "ERROR: Failed to update HEC token '${token_name}' default index to '${expected_index}' via cluster-manager bundle."
            exit 1
        fi
        if ! token_record="$(deployment_get_bundle_hec_token_record \
            "${token_name}" 2>/dev/null)"; then
            log "ERROR: Could not read back HEC token '${token_name}' after the cluster-manager bundle update."
            return 1
        fi
    else
        if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
            log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
            return 1
        fi
        ensure_ingest_session || return 1
        log "HEC token '${token_name}' default index is '${default_index:-unknown}'. Updating it to '${expected_index}' via Splunk REST..."
        if ! rest_update_hec_token_default_index "${token_name}" "${expected_index}"; then
            log "ERROR: Failed to update HEC token '${token_name}' default index to '${expected_index}' via Splunk REST."
            exit 1
        fi
        if ! token_record="$(enterprise_hec_token_record \
            "${token_name}" 2>/dev/null)"; then
            log "ERROR: Could not read back HEC token '${token_name}' after the REST update."
            return 1
        fi
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
        if ! token_record="$(cloud_rest_get_hec_token_record "${token_name}")"; then
            log "ERROR: Could not inspect the requested Cloud HEC token value over Splunk REST."
            log "HANDOFF: Rotate/create the token through the supported Cloud HEC surface and store the one-time value in ${WRITE_HEC_TOKEN_FILE}."
            return 1
        fi
    else
        if ! token_record="$(enterprise_hec_token_record "${token_name}")"; then
            log "ERROR: Could not inspect the requested ingest-tier HEC token value."
            return 1
        fi
    fi

    token_value="$(rest_json_field "${token_record}" "token")"
    if [[ -z "${token_value}" ]]; then
        log "ERROR: Splunk did not return the requested HEC token value for '${token_name}'."
        log "HANDOFF: Rotate/create the token and store its one-time value in ${WRITE_HEC_TOKEN_FILE}, then rerun validation."
        return 1
    fi

    write_secret_file "${WRITE_HEC_TOKEN_FILE}" "${token_value}"$'\n' || return 1
    HEC_TOKEN_FILE="${WRITE_HEC_TOKEN_FILE}"
    log "Wrote HEC token value to ${WRITE_HEC_TOKEN_FILE}"
}

warn_about_hec_token_details() {
    local token_name="$1" token_record ack_state indexes_value default_index missing_indexes

    if is_splunk_cloud; then
        if ! token_record="$(cloud_rest_get_hec_token_record "${token_name}")"; then
            log "ERROR: Could not inspect detailed Cloud HEC token settings over Splunk REST."
            return 1
        fi
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
        missing_indexes="$(python3 - "${indexes_value}" "${EVENT_INDEXES[@]}" "${METRIC_INDEXES[@]}" <<'PY'
import sys
allowed = {item.strip() for item in sys.argv[1].split(",") if item.strip()}
required = sys.argv[2:]
print(",".join(item for item in required if "*" not in allowed and item not in allowed), end="")
PY
)"
        if [[ -n "${missing_indexes}" ]]; then
            log "ERROR: HEC token '${token_name}' Selected Indexes omit required SC4SNMP indexes: ${missing_indexes}."
            log "HANDOFF: Clear the Selected Indexes restriction or add every required event/metrics index, then rerun preparation."
            return 1
        fi
        log "HEC token '${token_name}' Selected Indexes include all required SC4SNMP indexes."
    fi

    if [[ -n "${default_index}" ]]; then
        log "HEC token '${token_name}' default index: ${default_index}"
    fi
}

ensure_hec_token() {
    local state
    log "Checking HEC token '${HEC_TOKEN_NAME}'..."

    ensure_splunk_context || return 1
    if is_splunk_cloud; then
        acs_prepare_context || { log "ERROR: ACS context is required for Splunk Cloud HEC management."; exit 1; }
        if ! state="$(cloud_get_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null)"; then
            log "ERROR: Could not inspect HEC token '${HEC_TOKEN_NAME}' through ACS; refusing mutation."
            return 1
        fi
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
                if ! state="$(cloud_get_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${HEC_TOKEN_NAME}' after the ACS enable operation."
                    return 1
                fi
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${HEC_TOKEN_NAME}' is still not enabled after the ACS update."
                    return 1
                fi
                log "Enabled HEC token '${HEC_TOKEN_NAME}' in Splunk Cloud."
                ;;
            missing)
                log "Creating HEC token '${HEC_TOKEN_NAME}' via ACS..."
                if ! cloud_create_hec_token_via_acs "${HEC_TOKEN_NAME}"; then
                    log "ERROR: Failed to create HEC token '${HEC_TOKEN_NAME}' via ACS."
                    return 1
                fi
                if ! state="$(cloud_get_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${HEC_TOKEN_NAME}' after the ACS create."
                    return 1
                fi
                if [[ "${state}" != "enabled" ]]; then
                    log "ERROR: HEC token '${HEC_TOKEN_NAME}' could not be verified as enabled after the ACS create."
                    return 1
                fi
                log "Created HEC token '${HEC_TOKEN_NAME}' via ACS."
                ;;
            *)
                log "ERROR: ACS returned an invalid HEC token observation for '${HEC_TOKEN_NAME}'; refusing mutation."
                return 1
                ;;
        esac
    else
        if ! state="$(enterprise_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null)"; then
            log "ERROR: Could not inspect HEC token '${HEC_TOKEN_NAME}' on the configured ingest target."
            return 1
        fi
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
                    if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
                        log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
                        return 1
                    fi
                    ensure_ingest_session || return 1
                    log "HEC token '${HEC_TOKEN_NAME}' exists but is disabled. Enabling it via Splunk REST..."
                    if ! rest_enable_hec_token "${HEC_TOKEN_NAME}"; then
                        log "ERROR: Failed to enable disabled HEC token '${HEC_TOKEN_NAME}' via Splunk REST."
                        exit 1
                    fi
                fi
                if ! state="$(enterprise_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null)"; then
                    log "ERROR: Could not read back HEC token '${HEC_TOKEN_NAME}' after the enable operation."
                    return 1
                fi
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
                    if ! state="$(enterprise_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null)"; then
                        log "ERROR: Could not read back HEC token '${HEC_TOKEN_NAME}' after the cluster-manager bundle update."
                        return 1
                    fi
                    if [[ "${state}" != "enabled" ]]; then
                        log "ERROR: HEC token '${HEC_TOKEN_NAME}' could not be verified after the cluster-manager bundle update."
                        exit 1
                    fi
                    log "Created HEC token '${HEC_TOKEN_NAME}' via cluster-manager bundle."
                else
                    if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
                        log "ERROR: Could not resolve the configured ingest deployment target; refusing REST fallback."
                        return 1
                    fi
                    ensure_ingest_session || return 1
                    log "Creating HEC token '${HEC_TOKEN_NAME}' via Splunk REST..."
                    if ! rest_create_hec_token "${HEC_TOKEN_NAME}"; then
                        log "ERROR: Failed to create HEC token '${HEC_TOKEN_NAME}' via Splunk REST."
                        exit 1
                    fi
                    if ! state="$(enterprise_hec_token_state "${HEC_TOKEN_NAME}" 2>/dev/null)"; then
                        log "ERROR: Could not read back HEC token '${HEC_TOKEN_NAME}' after the Splunk REST create."
                        return 1
                    fi
                    if [[ "${state}" != "enabled" ]]; then
                        log "ERROR: HEC token '${HEC_TOKEN_NAME}' could not be verified as enabled after the Splunk REST create."
                        return 1
                    fi
                    log "Created HEC token '${HEC_TOKEN_NAME}'."
                fi
                ;;
        esac
    fi

    ensure_expected_hec_default_index "${HEC_TOKEN_NAME}" "netops" || return 1
    warn_about_hec_token_details "${HEC_TOKEN_NAME}" || return 1
    write_hec_token_file_if_requested "${HEC_TOKEN_NAME}" || return 1
}

ensure_indexes() {
    local idx index_type
    ensure_splunk_context || return 1
    if ! is_splunk_cloud; then
        ensure_search_session || return 1
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

    if ! hec_base="$(detect_hec_base_url)"; then
        log "ERROR: Could not resolve the selected Splunk HEC target."
        return 1
    fi
    event_url="$(hec_event_url_from_base "${hec_base}")"
    log "Detected SC4SNMP HEC base URL: ${hec_base}"
    log "Detected SC4SNMP HEC event URL: ${event_url}"

    if [[ "${HEC_ONLY}" != "true" ]]; then
        ensure_indexes || return 1
    fi
    if [[ "${INDEXES_ONLY}" != "true" ]]; then
        ensure_hec_token || return 1
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
2. Keep \`secrets/\` local-only; secret files render as group-readable but not world-readable.
3. If your container runtime uses a non-owner group, run \`chgrp\` on \`secrets/\` before startup.
4. Run \`compose-up.sh\` to install or upgrade the stack, or use your standard compose workflow.
5. Validate indexed data after the stack is running.
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
    local hec_token_value

    compose_dir="${OUTPUT_DIR}/compose"
    template_dir="${SCRIPT_DIR}/../templates/compose"
    if ! hec_base="$(detect_hec_base_url)"; then
        log "ERROR: Could not resolve the selected Splunk HEC target."
        return 1
    fi
    if ! validate_hec_base_url "${hec_base}"; then
        log "ERROR: Resolved HEC URL is not a credential-free HTTPS HEC base, /event, or /raw URL: ${hec_base}"
        return 1
    fi
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
        if ! hec_token_value="$(read_hec_token_value "${HEC_TOKEN_FILE}")"; then
            return 1
        fi
        write_compose_bind_secret_file "${compose_dir}/secrets/hec_token" "${hec_token_value}"$'\n'
    else
        write_compose_bind_secret_file "${compose_dir}/secrets/hec_token.example" "<replace-with-hec-token>"$'\n'
        log "WARN: No --hec-token-file provided. Rendering a placeholder token file."
    fi
    if [[ -n "${SNMPV3_SECRETS_FILE}" ]]; then
        cp "${SNMPV3_SECRETS_FILE}" "${compose_dir}/secrets/secrets.json"
        chmod 600 "${compose_dir}/secrets/secrets.json"
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
    local k8s_dir="$1" release_name_q namespace_q
    printf -v release_name_q '%q' "${RELEASE_NAME}"
    printf -v namespace_q '%q' "${NAMESPACE}"
    write_text_file "${k8s_dir}/helm-install.sh" "$(cat <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\${BASH_SOURCE[0]}")"
if ! helm repo add splunk-connect-for-snmp https://splunk.github.io/splunk-connect-for-snmp 2>&1; then
  echo "WARN: helm repo add failed (may already exist). Continuing." >&2
fi
helm repo update
cmd=(helm upgrade --install ${release_name_q} splunk-connect-for-snmp/splunk-connect-for-snmp --namespace ${namespace_q} --create-namespace -f values.yaml)
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

    if ! hec_base="$(detect_hec_base_url)"; then
        log "ERROR: Could not resolve the selected Splunk HEC target."
        return 1
    fi
    if ! validate_hec_base_url "${hec_base}"; then
        log "ERROR: Resolved HEC URL is not a credential-free HTTPS HEC base, /event, or /raw URL: ${hec_base}"
        return 1
    fi
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
        if ! _raw_token="$(read_hec_token_value "${HEC_TOKEN_FILE}")"; then
            return 1
        fi
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
        run_splunk_prep || return 1
    fi
    ensure_apply_token_ready
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
