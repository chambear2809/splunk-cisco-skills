#!/usr/bin/env bash
# Splunk Edge Processor helpers (Cloud + Enterprise control planes).
# Sourced by setup/validate scripts in splunk-edge-processor-setup.
#
# Security contract:
#   - The EP API Bearer token is read from a private single-link file and
#     written through descriptor validation to a private curl config supplied
#     with `-K`, so the token never lands on argv (visible in `ps`).
#   - TLS verification is enabled by default. Operators on a private CA
#     should set EP_API_CA_CERT=/path/to/ca.pem; setting EP_API_INSECURE=true
#     keeps the legacy "skip verification" behavior but emits a one-time
#     warning so it cannot silently re-introduce MITM exposure.

[[ -n "${_EDGE_PROCESSOR_HELPERS_LOADED:-}" ]] && return 0
_EDGE_PROCESSOR_HELPERS_LOADED=true

_EP_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${_EP_LIB_DIR}/credential_curl_helpers.sh"

if [[ -z "${_CRED_HELPERS_LOADED:-}" ]]; then
    # shellcheck disable=SC1091
    source "${_EP_LIB_DIR}/credential_helpers.sh"
fi

_ep_curl_tls_args() {
    # Mirror the rest_helpers TLS posture: verified by default, opt-in
    # CA bundle for private PKIs, explicit insecure escape hatch for
    # development.
    local insecure="${EP_API_INSECURE:-false}"
    local ca_cert="${EP_API_CA_CERT:-}"
    if [[ -n "${ca_cert}" ]]; then
        if [[ "${ca_cert}" == *$'\r'* || "${ca_cert}" == *$'\n'* || ! -s "${ca_cert}" ]]; then
            echo "ERROR: EP_API_CA_CERT not found or empty: ${ca_cert}" >&2
            return 1
        fi
        printf -- '--cacert\n%s\n' "${ca_cert}"
        return 0
    fi
    case "${insecure}" in
        1|true|TRUE|True|yes|YES|Yes|on|ON|On)
            if [[ -z "${_WARNED_EP_API_INSECURE:-}" ]]; then
                echo "WARNING: TLS verification is disabled for Edge Processor API calls (EP_API_INSECURE=true). Use EP_API_CA_CERT=/path/to/ca.pem for private CAs in production." >&2
                _WARNED_EP_API_INSECURE=1
            fi
            printf -- '-k\n'
            ;;
        *) ;;
    esac
}

_ep_validate_object_name() {
    local value="${1:-}" label="${2:-Edge Processor object name}"
    if [[ -z "${value}" || "${value}" == "." || "${value}" == ".." || ! "${value}" =~ ^[A-Za-z0-9._:-]+$ ]]; then
        log "ERROR: ${label} contains unsafe URL/path characters: ${value}"
        return 1
    fi
}

_ep_validate_request_target() {
    local tenant_url="${1:-}" method="${2:-}" path="${3:-}"
    python3 - "${tenant_url}" "${method}" "${path}" <<'PY'
import sys
from urllib.parse import urlsplit

base, method, path = sys.argv[1:]
try:
    parsed = urlsplit(base)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if (
    parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.path not in {"", "/"}
    or parsed.query
    or parsed.fragment
    or any(character.isspace() for character in base)
    or (port is not None and not 1 <= port <= 65535)
    or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    or not path.startswith("/")
    or path.startswith("//")
    or "#" in path
    or any(character.isspace() for character in path)
):
    raise SystemExit(1)
PY
}

# ep_api_call <tenant_url> <token_file> <method> <path> [extra curl args...]
# Calls the Edge Processor management API using a Bearer token loaded from
# `token_file`. The token is fed through a descriptor-validated private -K config so it never appears
# in `ps` / /proc/*/cmdline. The tenant URL and method are not secrets.
ep_api_call() {
    local tenant_url="$1" token_file="$2" method="$3" path="$4"
    shift 4
    if ! _ep_validate_request_target "${tenant_url}" "${method}" "${path}"; then
        log "ERROR: Edge Processor API target must use a credential-free HTTPS origin, a known method, and one relative API path."
        return 1
    fi
    local request_url="${tenant_url}${path}"
    if ! credential_curl_validate_request_args false "$@" "${request_url}"; then
        log "ERROR: Edge Processor request rejected by credential transport policy."
        return 1
    fi
    # Read TLS args into a bash array. mapfile is simpler but less portable;
    # use a here-string to keep behavior deterministic on macOS bash 3.x.
    # _ep_curl_tls_args returns 1 when EP_API_CA_CERT is misconfigured; we
    # must propagate that error rather than silently falling back to default
    # curl verification (which could mask MITM-relevant misconfiguration).
    local tls_args=() tls_status=0 last_index=0
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_ep_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]]; then
        last_index=$(( ${#tls_args[@]} - 1 ))
    fi
    if [[ "${#tls_args[@]}" -gt 0 ]] && [[ "${tls_args[${last_index}]}" == STATUS=* ]]; then
        tls_status="${tls_args[${last_index}]#STATUS=}"
        unset "tls_args[${last_index}]"
    fi
    if (( tls_status != 0 )); then
        log "ERROR: Edge Processor TLS configuration invalid (EP_API_CA_CERT/EP_API_INSECURE)."
        return 1
    fi
    local response_file http_code auth_config
    auth_config="$(mktemp)" || return 1
    chmod 600 "${auth_config}"
    credential_curl_append_cleanup_trap "rm -f $(printf '%q' "${auth_config}") 2>/dev/null || true" HUP INT TERM
    if ! credential_curl_write_header_config \
        "${token_file}" "Authorization" "${auth_config}" "Bearer "; then
        rm -f "${auth_config}"
        log "ERROR: EP API token must be a private single-link, non-symlink one-line file."
        return 1
    fi
    response_file="$(mktemp)" || {
        rm -f "${auth_config}"
        return 1
    }
    chmod 600 "${response_file}"
    credential_curl_append_cleanup_trap "rm -f $(printf '%q' "${response_file}") 2>/dev/null || true" HUP INT TERM
    if ! http_code="$(curl -q -sS -o "${response_file}" -w '%{http_code}' \
        ${tls_args[@]+"${tls_args[@]}"} \
        -X "${method}" \
        -K "${auth_config}" \
        -H "Content-Type: application/json" \
        "$@" \
        "${request_url}" \
        "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}")"; then
        rm -f "${auth_config}"
        rm -f "${response_file}"
        log "ERROR: Edge Processor API request failed at the transport layer: ${method} ${path}"
        return 1
    fi
    rm -f "${auth_config}"
    case "${http_code}" in
        2??)
            local response_rc=0
            cat "${response_file}" || response_rc=$?
            rm -f "${response_file}"
            return "${response_rc}"
            ;;
        *)
            log "ERROR: Edge Processor API request failed (HTTP ${http_code}): ${method} ${path}"
            rm -f "${response_file}"
            return 1
            ;;
    esac
}

# ep_apply_source_type <tenant_url> <token_file> <source_type_json>
ep_apply_source_type() {
    local tenant_url="$1" token_file="$2" json_path="$3"
    if [[ ! -s "${json_path}" ]]; then
        log "ERROR: source-type JSON missing or empty: ${json_path}"
        return 1
    fi
    local name
    name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "${json_path}")
    _ep_validate_object_name "${name}" "source-type name" || return 1
    credential_curl_stream_file "${json_path}" | ep_api_call "${tenant_url}" "${token_file}" PUT \
        "/api/v1/edge-processor/source-types/${name}" \
        --data-binary @- >/dev/null
}

# ep_apply_destination <tenant_url> <token_file> <destination_json>
ep_apply_destination() {
    local tenant_url="$1" token_file="$2" json_path="$3"
    if [[ ! -s "${json_path}" ]]; then
        log "ERROR: destination JSON missing or empty: ${json_path}"
        return 1
    fi
    local name
    name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "${json_path}")
    _ep_validate_object_name "${name}" "destination name" || return 1
    credential_curl_stream_file "${json_path}" | ep_api_call "${tenant_url}" "${token_file}" PUT \
        "/api/v1/edge-processor/destinations/${name}" \
        --data-binary @- >/dev/null
}

# ep_apply_pipeline <tenant_url> <token_file> <pipeline_json>
ep_apply_pipeline() {
    local tenant_url="$1" token_file="$2" json_path="$3"
    if [[ ! -s "${json_path}" ]]; then
        log "ERROR: pipeline JSON missing or empty: ${json_path}"
        return 1
    fi
    local name
    name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "${json_path}")
    _ep_validate_object_name "${name}" "pipeline name" || return 1
    credential_curl_stream_file "${json_path}" | ep_api_call "${tenant_url}" "${token_file}" PUT \
        "/api/v1/edge-processor/pipelines/${name}" \
        --data-binary @- >/dev/null
}

# ep_attach_pipeline_to_ep <tenant_url> <token_file> <ep_name> <pipeline_name>
ep_attach_pipeline_to_ep() {
    local tenant_url="$1" token_file="$2" ep_name="$3" pipeline_name="$4"
    _ep_validate_object_name "${ep_name}" "edge-processor name" || return 1
    _ep_validate_object_name "${pipeline_name}" "pipeline name" || return 1
    ep_api_call "${tenant_url}" "${token_file}" POST \
        "/api/v1/edge-processor/edge-processors/${ep_name}/pipelines/${pipeline_name}/attach" >/dev/null
}

# ep_instance_status <tenant_url> <token_file> <ep_name>
# Echoes <healthy_count> <total_count> on stdout.
ep_instance_status() {
    local tenant_url="$1" token_file="$2" ep_name="$3"
    local body
    _ep_validate_object_name "${ep_name}" "edge-processor name" || return 1
    if ! body=$(ep_api_call "${tenant_url}" "${token_file}" GET \
        "/api/v1/edge-processor/edge-processors/${ep_name}/instances" 2>/dev/null); then
        echo "ERROR: could not read Edge Processor instance status for ${ep_name}." >&2
        return 2
    fi
    python3 - "${body}" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
except Exception as exc:
    print(f"ERROR: invalid Edge Processor instance response: {exc}", file=sys.stderr)
    sys.exit(2)
if not isinstance(data, dict) or not isinstance(data.get("instances"), list):
    print("ERROR: Edge Processor instance response has an invalid schema", file=sys.stderr)
    sys.exit(2)
instances = data["instances"]
healthy = sum(1 for i in instances if i.get("status") == "Healthy")
total = len(instances)
print(f"{healthy} {total}")
PY
}
