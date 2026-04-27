#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="cisco-cloud-security"
BASE_URL=""
ORG_ID=""
TIMEZONE_VALUE=""
STORAGE_REGION=""
API_KEY_FILE=""
API_SECRET_FILE=""
INVESTIGATE_INDEX=""
PRIVATEAPP_INDEX=""
APPDISCOVERY_INDEX=""
DISCOVER_ORG_ID=false
CREATE_INDEX=true
SK=""

usage() {
    cat <<EOF
Cisco Secure Access Account Configuration

Usage: $(basename "$0") [OPTIONS]

Options:
  --org-id ID                    Organization ID
  --discover-org-id             Discover org ID from credentials before configuring
  --base-url URL                Secure Access API base URL
  --timezone TZ                 Timezone value
  --storage-region REGION       Storage region value
  --api-key-file PATH           File containing apiKey
  --api-secret-file PATH        File containing apiSecret
  --investigate-index INDEX     Optional investigate index
  --privateapp-index INDEX      Optional private apps index
  --appdiscovery-index INDEX    Optional app discovery index
  --no-create-index             Do not auto-create supplied indexes
  --help                        Show this help

Examples:
  $(basename "$0") \\
    --org-id example-org-id \\
    --base-url https://api.us.security.cisco.com \\
    --timezone UTC \\
    --storage-region us \\
    --api-key-file /tmp/secure_access_api_key \\
    --api-secret-file /tmp/secure_access_api_secret \\
    --investigate-index cisco_secure_access_investigate

  $(basename "$0") \\
    --discover-org-id \\
    --base-url https://api.us.security.cisco.com \\
    --api-key-file /tmp/secure_access_api_key \\
    --api-secret-file /tmp/secure_access_api_secret
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --org-id) require_arg "$1" $# || exit 1; ORG_ID="$2"; shift 2 ;;
        --discover-org-id) DISCOVER_ORG_ID=true; shift ;;
        --base-url) require_arg "$1" $# || exit 1; BASE_URL="$2"; shift 2 ;;
        --timezone) require_arg "$1" $# || exit 1; TIMEZONE_VALUE="$2"; shift 2 ;;
        --storage-region) require_arg "$1" $# || exit 1; STORAGE_REGION="$2"; shift 2 ;;
        --api-key-file) require_arg "$1" $# || exit 1; API_KEY_FILE="$2"; shift 2 ;;
        --api-secret-file) require_arg "$1" $# || exit 1; API_SECRET_FILE="$2"; shift 2 ;;
        --investigate-index) require_arg "$1" $# || exit 1; INVESTIGATE_INDEX="$2"; shift 2 ;;
        --privateapp-index) require_arg "$1" $# || exit 1; PRIVATEAPP_INDEX="$2"; shift 2 ;;
        --appdiscovery-index) require_arg "$1" $# || exit 1; APPDISCOVERY_INDEX="$2"; shift 2 ;;
        --no-create-index) CREATE_INDEX=false; shift ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

ensure_session() {
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
}

json_payload_from_pairs() {
    local args_file output rc restore_errexit=false

    args_file="$(mktemp)"
    chmod 600 "${args_file}"
    for arg in "$@"; do
        printf '%s\0' "${arg}"
    done > "${args_file}"

    case $- in
        *e*)
            restore_errexit=true
            set +e
            ;;
    esac
    output=$(python3 - "${args_file}" <<'PY'
import json
import sys
from pathlib import Path

raw = Path(sys.argv[1]).read_bytes()
args = raw.split(b"\0")
if args and args[-1] == b"":
    args.pop()
args = [value.decode("utf-8") for value in args]
payload = {}
for i in range(0, len(args), 2):
    key = args[i]
    value = args[i + 1]
    if value != "":
        payload[key] = value

print(json.dumps(payload), end="")
PY
)
    rc=$?
    if [[ "${restore_errexit}" == "true" ]]; then
        set -e
    fi
    rm -f "${args_file}"
    [[ "${rc}" -eq 0 ]] || return "${rc}"
    printf '%s' "${output}"
}

org_accounts_request() {
    local method="$1" query="${2:-}" payload="${3:-}"
    local url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/org_accounts"
    if [[ -n "${query}" ]]; then
        url="${url}?${query}"
    fi

    if [[ -n "${payload}" ]]; then
        splunk_curl "${SK}" \
            -X "${method}" \
            -H "Content-Type: application/json" \
            -d "${payload}" \
            "${url}" -w '\n%{http_code}' 2>/dev/null || true
    else
        splunk_curl "${SK}" \
            -X "${method}" \
            -H "Content-Type: application/json" \
            "${url}" -w '\n%{http_code}' 2>/dev/null || true
    fi
}

discover_org_id() {
    local api_key api_secret payload response http_code body discovered
    [[ -n "${BASE_URL}" ]] || { log "ERROR: --base-url is required for --discover-org-id."; exit 1; }
    [[ -n "${API_KEY_FILE}" ]] || { log "ERROR: --api-key-file is required for --discover-org-id."; exit 1; }
    [[ -n "${API_SECRET_FILE}" ]] || { log "ERROR: --api-secret-file is required for --discover-org-id."; exit 1; }

    api_key="$(read_secret_file "${API_KEY_FILE}")"
    api_secret="$(read_secret_file "${API_SECRET_FILE}")"
    payload="$(json_payload_from_pairs apiKey "${api_key}" apiSecret "${api_secret}" baseURL "${BASE_URL}")"

    response="$(org_accounts_request POST "action=get_orgId" "${payload}")"
    http_code="$(echo "${response}" | sed -n '$p')"
    body="$(echo "${response}" | sed '$d')"
    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Failed to discover org ID (HTTP ${http_code})."
        sanitize_response "${body}" 5 >&2 || true
        exit 1
    fi

    discovered="$(printf '%s' "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    payload = data.get('payload', {})
    if isinstance(payload, dict):
        print(payload.get('orgId', ''), end='')
except Exception:
    pass
")"

    if [[ -z "${discovered}" ]]; then
        log "ERROR: Could not parse orgId from the discovery response."
        exit 1
    fi
    printf '%s' "${discovered}"
}

account_exists() {
    local query response http_code encoded_org_id
    encoded_org_id="$(_urlencode "${ORG_ID}")"
    query="orgId=${encoded_org_id}&fields=all"
    response="$(org_accounts_request GET "${query}")"
    http_code="$(echo "${response}" | sed -n '$p')"
    case "${http_code}" in
        200) return 0 ;;
        404) return 1 ;;
        *)
            log "ERROR: Failed to query org account '${ORG_ID}' (HTTP ${http_code})."
            sanitize_response "$(echo "${response}" | sed '$d')" 5 >&2 || true
            exit 1
            ;;
    esac
}

ensure_indexes() {
    local idx
    for idx in "${INVESTIGATE_INDEX}" "${PRIVATEAPP_INDEX}" "${APPDISCOVERY_INDEX}"; do
        [[ -n "${idx}" ]] || continue
        if platform_create_index "${SK}" "${SPLUNK_URI}" "${idx}" "512000"; then
            log "Index '${idx}' created or already exists."
        else
            log "ERROR: Failed to create index '${idx}'."
            exit 1
        fi
    done
}

main() {
    local discovered_org_id="" api_key="" api_secret="" response http_code body payload
    local has_creds=false has_indexes=false has_updates=false

    ensure_session
    if ! rest_check_app "$SK" "$SPLUNK_URI" "$APP_NAME" 2>/dev/null; then
        log "ERROR: ${APP_NAME} is not installed. Install Cisco Secure Access first."
        exit 1
    fi

    if $DISCOVER_ORG_ID; then
        discovered_org_id="$(discover_org_id)"
        if [[ -z "${ORG_ID}" ]]; then
            ORG_ID="${discovered_org_id}"
            log "Discovered org ID: ${ORG_ID}"
        fi
    fi

    if [[ -z "${ORG_ID}" ]]; then
        log "ERROR: --org-id is required unless --discover-org-id is used."
        exit 1
    fi

    if [[ -n "${API_KEY_FILE}" || -n "${API_SECRET_FILE}" || -n "${BASE_URL}" ]]; then
        has_creds=true
    fi
    if [[ -n "${INVESTIGATE_INDEX}" || -n "${PRIVATEAPP_INDEX}" || -n "${APPDISCOVERY_INDEX}" ]]; then
        has_indexes=true
    fi

    if ${CREATE_INDEX}; then
        ensure_indexes
    fi

    if account_exists; then
        if ${has_creds}; then
            [[ -n "${API_KEY_FILE}" && -n "${API_SECRET_FILE}" && -n "${BASE_URL}" ]] || {
                log "ERROR: Updating credentials requires --base-url, --api-key-file, and --api-secret-file together."
                exit 1
            }
            api_key="$(read_secret_file "${API_KEY_FILE}")"
            api_secret="$(read_secret_file "${API_SECRET_FILE}")"
        fi

        if [[ -n "${TIMEZONE_VALUE}" || -n "${STORAGE_REGION}" || "${has_creds}" == "true" || "${has_indexes}" == "true" ]]; then
            has_updates=true
        fi
        if [[ "${has_updates}" != "true" ]]; then
            log "ERROR: Account '${ORG_ID}' already exists; provide fields to update."
            exit 1
        fi

        payload="$(json_payload_from_pairs \
            orgId "${ORG_ID}" \
            apiKey "${api_key}" \
            apiSecret "${api_secret}" \
            baseURL "${BASE_URL}" \
            timezone "${TIMEZONE_VALUE}" \
            storageRegion "${STORAGE_REGION}" \
            investigate_index "${INVESTIGATE_INDEX}" \
            privateapp_index "${PRIVATEAPP_INDEX}" \
            appdiscovery_index "${APPDISCOVERY_INDEX}")"

        response="$(org_accounts_request PUT "orgId=$(_urlencode "${ORG_ID}")" "${payload}")"
        http_code="$(echo "${response}" | sed -n '$p')"
        body="$(echo "${response}" | sed '$d')"
        if [[ "${http_code}" != "200" ]]; then
            log "ERROR: Failed to update org account '${ORG_ID}' (HTTP ${http_code})."
            sanitize_response "${body}" 5 >&2 || true
            exit 1
        fi
        log "Updated Cisco Secure Access org account '${ORG_ID}'."
        exit 0
    fi

    [[ -n "${BASE_URL}" ]] || { log "ERROR: --base-url is required for account creation."; exit 1; }
    [[ -n "${TIMEZONE_VALUE}" ]] || { log "ERROR: --timezone is required for account creation."; exit 1; }
    [[ -n "${STORAGE_REGION}" ]] || { log "ERROR: --storage-region is required for account creation."; exit 1; }
    [[ -n "${API_KEY_FILE}" ]] || { log "ERROR: --api-key-file is required for account creation."; exit 1; }
    [[ -n "${API_SECRET_FILE}" ]] || { log "ERROR: --api-secret-file is required for account creation."; exit 1; }

    api_key="$(read_secret_file "${API_KEY_FILE}")"
    api_secret="$(read_secret_file "${API_SECRET_FILE}")"

    payload="$(json_payload_from_pairs \
        orgId "${ORG_ID}" \
        apiKey "${api_key}" \
        apiSecret "${api_secret}" \
        baseURL "${BASE_URL}" \
        timezone "${TIMEZONE_VALUE}" \
        storageRegion "${STORAGE_REGION}" \
        investigate_index "${INVESTIGATE_INDEX}" \
        privateapp_index "${PRIVATEAPP_INDEX}" \
        appdiscovery_index "${APPDISCOVERY_INDEX}")"

    response="$(org_accounts_request POST "" "${payload}")"
    http_code="$(echo "${response}" | sed -n '$p')"
    body="$(echo "${response}" | sed '$d')"
    if [[ "${http_code}" != "201" && "${http_code}" != "200" ]]; then
        log "ERROR: Failed to create org account '${ORG_ID}' (HTTP ${http_code})."
        sanitize_response "${body}" 5 >&2 || true
        exit 1
    fi

    log "Created Cisco Secure Access org account '${ORG_ID}'."
}

main
