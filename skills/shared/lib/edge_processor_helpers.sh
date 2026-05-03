#!/usr/bin/env bash
# Splunk Edge Processor helpers (Cloud + Enterprise control planes).
# Sourced by setup/validate scripts in splunk-edge-processor-setup.
#
# Security contract:
#   - The EP API Bearer token is read from a chmod 600 file (token_file)
#     and fed to curl via `-K <(printf 'header = "Authorization: Bearer %s"' "${tok}")`
#     so the token never lands on argv (visible in `ps`).
#   - TLS verification is enabled by default. Operators on a private CA
#     should set EP_API_CA_CERT=/path/to/ca.pem; setting EP_API_INSECURE=true
#     keeps the legacy "skip verification" behavior but emits a one-time
#     warning so it cannot silently re-introduce MITM exposure.

[[ -n "${_EDGE_PROCESSOR_HELPERS_LOADED:-}" ]] && return 0
_EDGE_PROCESSOR_HELPERS_LOADED=true

if [[ -z "${_CRED_HELPERS_LOADED:-}" ]]; then
    _EP_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
        if [[ ! -s "${ca_cert}" ]]; then
            echo "ERROR: EP_API_CA_CERT not found or empty: ${ca_cert}" >&2
            return 1
        fi
        printf -- '--cacert\n%s\n' "${ca_cert}"
        return 0
    fi
    case "${insecure,,}" in
        1|true|yes)
            if [[ -z "${_WARNED_EP_API_INSECURE:-}" ]]; then
                echo "WARNING: TLS verification is disabled for Edge Processor API calls (EP_API_INSECURE=true). Use EP_API_CA_CERT=/path/to/ca.pem for private CAs in production." >&2
                _WARNED_EP_API_INSECURE=1
            fi
            printf -- '-k\n'
            ;;
        *) ;;
    esac
}

# ep_api_call <tenant_url> <token_file> <method> <path> [extra curl args...]
# Calls the Edge Processor management API using a Bearer token loaded from
# `token_file`. The token is fed to curl via -K <(...) so it never appears
# in `ps` / /proc/*/cmdline. The tenant URL and method are not secrets.
ep_api_call() {
    local tenant_url="$1" token_file="$2" method="$3" path="$4"
    shift 4
    if [[ ! -s "${token_file}" ]]; then
        log "ERROR: EP API token missing or empty: ${token_file}"
        return 1
    fi
    # Read TLS args into a bash array. mapfile is simpler but less portable;
    # use a here-string to keep behavior deterministic on macOS bash 3.x.
    # _ep_curl_tls_args returns 1 when EP_API_CA_CERT is misconfigured; we
    # must propagate that error rather than silently falling back to default
    # curl verification (which could mask MITM-relevant misconfiguration).
    local tls_args=() tls_status=0
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_ep_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]] && [[ "${tls_args[-1]}" == STATUS=* ]]; then
        tls_status="${tls_args[-1]#STATUS=}"
        unset 'tls_args[-1]'
    fi
    if (( tls_status != 0 )); then
        log "ERROR: Edge Processor TLS configuration invalid (EP_API_CA_CERT/EP_API_INSECURE)."
        return 1
    fi
    local token
    token="$(cat "${token_file}")"
    # printf is a bash builtin, so the token does not appear in any separate
    # process argv. The FIFO that backs the curl `-K` config is briefly
    # readable to the same UID via /proc; on multi-tenant hosts where the
    # caller's UID is shared with untrusted code, the EP token should be
    # treated as compromised — same trade-off documented in rest_helpers.sh.
    curl -sS \
        ${tls_args[@]+"${tls_args[@]}"} \
        -X "${method}" \
        -K <(printf 'header = "Content-Type: application/json"\nheader = "Authorization: Bearer %s"\n' "${token}") \
        "$@" \
        "${tenant_url}${path}"
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
    ep_api_call "${tenant_url}" "${token_file}" PUT \
        "/api/v1/edge-processor/source-types/${name}" \
        --data-binary @"${json_path}" >/dev/null
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
    ep_api_call "${tenant_url}" "${token_file}" PUT \
        "/api/v1/edge-processor/destinations/${name}" \
        --data-binary @"${json_path}" >/dev/null
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
    ep_api_call "${tenant_url}" "${token_file}" PUT \
        "/api/v1/edge-processor/pipelines/${name}" \
        --data-binary @"${json_path}" >/dev/null
}

# ep_attach_pipeline_to_ep <tenant_url> <token_file> <ep_name> <pipeline_name>
ep_attach_pipeline_to_ep() {
    local tenant_url="$1" token_file="$2" ep_name="$3" pipeline_name="$4"
    ep_api_call "${tenant_url}" "${token_file}" POST \
        "/api/v1/edge-processor/edge-processors/${ep_name}/pipelines/${pipeline_name}/attach" >/dev/null
}

# ep_instance_status <tenant_url> <token_file> <ep_name>
# Echoes <healthy_count> <total_count> on stdout.
ep_instance_status() {
    local tenant_url="$1" token_file="$2" ep_name="$3"
    local body
    body=$(ep_api_call "${tenant_url}" "${token_file}" GET \
        "/api/v1/edge-processor/edge-processors/${ep_name}/instances" 2>/dev/null || echo '{}')
    python3 - "${body}" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1]) if sys.argv[1].strip() else {}
except Exception:
    data = {}
instances = data.get("instances", []) if isinstance(data, dict) else []
healthy = sum(1 for i in instances if i.get("status") == "Healthy")
total = len(instances)
print(f"{healthy} {total}")
PY
}
