#!/usr/bin/env bash
# License manager helpers for Splunk Enterprise.
# Sourced by setup/validate scripts in splunk-license-manager-setup; safe to
# source elsewhere.
#
# Contract:
#   - Sourced into scripts that use 'set -euo pipefail'.
#   - Functions that check state return non-zero on "not found"; callers MUST
#     use 'if', '||', or '&&' to handle the exit status.
#   - Functions that perform actions return non-zero on failure and print an
#     error message to stderr.
#
# Security contract:
#   - All callers pass a Splunk session key (sk) obtained via
#     `get_session_key_from_password_file` (file-based, no argv exposure).
#   - All REST calls go through `splunk_curl` / `splunk_curl_post` so the
#     session key is fed via curl `-K <(...)` and never lands on argv.
#   - No helper here uses `splunk` CLI `-auth` or `curl -u` against a Splunk
#     management endpoint.

[[ -n "${_LICENSE_HELPERS_LOADED:-}" ]] && return 0
_LICENSE_HELPERS_LOADED=true

# log() and require_arg() come from rest_helpers.sh which is sourced through
# credential_helpers.sh. Source the parent module if not already loaded.
if [[ -z "${_CRED_HELPERS_LOADED:-}" ]]; then
    _LIC_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck disable=SC1091
    source "${_LIC_LIB_DIR}/credential_helpers.sh"
fi

# _lic_curl <manager_uri> <sk> <method> <path_relative_to_/services/licenser> [extra curl args...]
# Internal: thin wrapper around splunk_curl that scopes to the licenser
# REST namespace and adds output_mode=json.
_lic_curl() {
    local manager_uri="$1" sk="$2" method="$3" path="$4"
    shift 4
    splunk_curl "${sk}" -X "${method}" \
        "${manager_uri}/services/licenser/${path}?output_mode=json" \
        "$@"
}

# license_install_files <manager_uri> <sk> <file...>
#
# Installs one or more .lic files via the REST endpoint
# POST /services/licenser/licenses (multipart upload). This avoids
# `splunk add licenses ... -auth admin:pw` which would put the admin
# password on argv.
license_install_files() {
    local manager_uri="$1" sk="$2"
    shift 2
    if [[ $# -eq 0 ]]; then
        log "ERROR: license_install_files: at least one license file is required."
        return 1
    fi
    local file
    for file in "$@"; do
        if [[ ! -s "${file}" ]]; then
            log "ERROR: License file missing or empty: ${file}"
            return 1
        fi
        # POST with multipart/form-data; the file path stays in curl argv (a
        # path is not a secret) but the .lic content is read by curl itself
        # rather than expanded by the shell.
        splunk_curl "${sk}" -X POST \
            -F "license=@${file}" \
            "${manager_uri}/services/licenser/licenses?output_mode=json" >/dev/null \
            || { log "ERROR: License install failed for ${file}"; return 1; }
    done
}

# license_activate_group <manager_uri> <sk> <group>
# Group must be one of Enterprise|Forwarder|Free|Trial|Download-Trial.
license_activate_group() {
    local manager_uri="$1" sk="$2" group="$3"
    case "${group}" in
        Enterprise|Forwarder|Free|Trial|Download-Trial) ;;
        *)
            log "ERROR: license_activate_group: unsupported group '${group}'"
            return 1
            ;;
    esac
    splunk_curl_post "${sk}" "is_active=1" \
        "${manager_uri}/services/licenser/groups/${group}?output_mode=json" \
        >/dev/null
}

# license_localpeer_set_manager_uri <peer_uri> <sk> <manager_uri>
#
# Calls the localpeer REST endpoint on the *peer* (peer_uri is the peer's
# management URI, not the manager's). Splunk 9.x+ accepts `manager_uri`;
# older 8.x peers only accept `master_uri`. We try the modern form first
# and fall back if the response indicates the field is unknown.
#
# This entirely replaces the prior SSH + `splunk edit licenser-localpeer`
# pattern, which exposed the admin password on argv on both the local and
# remote hosts.
license_localpeer_set_manager_uri() {
    local peer_uri="$1" sk="$2" manager_uri="$3"
    local response http_code

    # Try modern manager_uri.
    http_code=$(splunk_curl "${sk}" -o /dev/null -w '%{http_code}' \
        -X POST --data-urlencode "manager_uri=${manager_uri}" \
        "${peer_uri}/services/licenser/localpeer?output_mode=json")
    if [[ "${http_code}" == "200" ]]; then
        printf '%s' "OK_MANAGER_URI"
        return 0
    fi

    # Fall back to legacy master_uri (Splunk 8.x peers).
    http_code=$(splunk_curl "${sk}" -o /dev/null -w '%{http_code}' \
        -X POST --data-urlencode "master_uri=${manager_uri}" \
        "${peer_uri}/services/licenser/localpeer?output_mode=json")
    if [[ "${http_code}" == "200" ]]; then
        printf '%s' "OK_MASTER_URI"
        return 0
    fi

    log "ERROR: localpeer update failed on ${peer_uri} (HTTP ${http_code})"
    return 1
}

# license_pool_apply <manager_uri> <sk> <pool_json_path>
#
# Creates the pool if missing; updates if it exists. Existence check uses
# HTTP status:
#   200 -> exists, update via POST /pools/<name>
#   404 -> does not exist, create via POST /pools
#   anything else -> fail loudly (auth / network / server error). Earlier
#       versions silently mapped any non-200 to "create", which mishandled
#       401/403/5xx and made debugging hard.
license_pool_apply() {
    local manager_uri="$1" sk="$2" pool_json="$3"
    if [[ ! -s "${pool_json}" ]]; then
        log "ERROR: pool JSON missing or empty: ${pool_json}"
        return 1
    fi

    local name stack_id quota slaves description
    # `slaves` is documented as a comma-separated peer GUID list (or "*").
    # The pool JSON spec stores it as either a string or a list; normalize
    # arrays to the comma-separated form Splunk expects, since printing a
    # Python list literal would send "['guid1', 'guid2']" to the REST API.
    name=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['name'])" "${pool_json}")
    stack_id=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['stack_id'])" "${pool_json}")
    quota=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['quota'])" "${pool_json}")
    slaves=$(python3 -c "
import json, sys
v = json.load(open(sys.argv[1]))['slaves']
if isinstance(v, list):
    print(','.join(str(item) for item in v))
else:
    print(v)
" "${pool_json}")
    description=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('description',''))" "${pool_json}")

    local -a body_args=(
        --data-urlencode "name=${name}"
        --data-urlencode "stack_id=${stack_id}"
        --data-urlencode "quota=${quota}"
        --data-urlencode "slaves=${slaves}"
    )
    if [[ -n "${description}" ]]; then
        body_args+=(--data-urlencode "description=${description}")
    fi

    local http_code
    http_code=$(splunk_curl "${sk}" -o /dev/null -w '%{http_code}' \
        "${manager_uri}/services/licenser/pools/${name}?output_mode=json")
    case "${http_code}" in
        200)
            splunk_curl "${sk}" -X POST "${body_args[@]}" \
                "${manager_uri}/services/licenser/pools/${name}?output_mode=json" \
                >/dev/null
            ;;
        404)
            splunk_curl "${sk}" -X POST "${body_args[@]}" \
                "${manager_uri}/services/licenser/pools?output_mode=json" \
                >/dev/null
            ;;
        401|403)
            log "ERROR: license_pool_apply: ${name}: HTTP ${http_code} on existence check (auth/permission). Refusing to POST blindly."
            return 1
            ;;
        *)
            log "ERROR: license_pool_apply: ${name}: unexpected HTTP ${http_code} on existence check. Refusing to POST blindly."
            return 1
            ;;
    esac
}

# license_messages_check <manager_uri> <sk>
# Echoes two integers to stdout: <error_count> <warn_count>.
# Returns non-zero when error_count > 0.
license_messages_check() {
    local manager_uri="$1" sk="$2"
    local payload
    payload=$(_lic_curl "${manager_uri}" "${sk}" GET "messages" 2>/dev/null || echo '{}')
    python3 - "${payload}" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1]) if sys.argv[1].strip() else {}
except Exception:
    data = {}
items = data.get("entry", []) if isinstance(data, dict) else []
errors = sum(1 for i in items if (i.get("content", {}) or {}).get("severity") == "ERROR")
warns = sum(1 for i in items if (i.get("content", {}) or {}).get("severity") == "WARN")
print(f"{errors} {warns}")
sys.exit(1 if errors > 0 else 0)
PY
}

# license_usage_snapshot <manager_uri> <sk> <output_dir>
# Snapshots all read-only license REST endpoints into <output_dir>/<endpoint>.json.
# Output files are written with mode 0600 because they may include stack
# IDs, peer GUIDs, and license metadata.
license_usage_snapshot() {
    local manager_uri="$1" sk="$2" output_dir="$3"
    mkdir -p "${output_dir}"
    chmod 0700 "${output_dir}" 2>/dev/null || true
    local endpoint out
    for endpoint in groups stacks pools licenses messages localpeer peers usage; do
        out="${output_dir}/${endpoint}.json"
        ( umask 077 && _lic_curl "${manager_uri}" "${sk}" GET "${endpoint}" \
            > "${out}" 2>/dev/null ) \
            || ( umask 077 && echo '{}' > "${out}" )
    done
}
