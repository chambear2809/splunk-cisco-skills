#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
APP_NAME="Splunk_MCP_Server"
DEFAULT_PACKAGE_FILE="${PROJECT_ROOT}/splunk-ta/splunk-mcp-server_110.tgz"
DEFAULT_OUTPUT_DIR_NAME="splunk-mcp-rendered"

DO_INSTALL=false
DO_UNINSTALL=false
HAS_UNINSTALL_CONFLICT=false
PACKAGE_FILE="${DEFAULT_PACKAGE_FILE}"
ROTATE_KEYS=false
ROTATE_KEY_SIZE="2048"
RENDER_CLIENTS=false
OUTPUT_DIR=""
CLIENT_NAME="splunk-mcp"
CLIENT_INSECURE_TLS=false
MCP_URL=""
CURSOR_WORKSPACE=""
REGISTER_CODEX=true
CONFIGURE_CURSOR=true

TOKEN_USER=""
TOKEN_EXPIRES_ON="+30d"
TOKEN_NOT_BEFORE=""
WRITE_TOKEN_FILE=""
BEARER_TOKEN_FILE=""

BASE_URL=""
TIMEOUT=""
MAX_ROW_LIMIT=""
DEFAULT_ROW_LIMIT=""
SSL_VERIFY=""
REQUIRE_ENCRYPTED_TOKEN=""
LEGACY_TOKEN_GRACE_DAYS=""
TOKEN_MAX_LIFETIME_SECONDS=""
TOKEN_DEFAULT_LIFETIME_SECONDS=""
TOKEN_KEY_RELOAD_INTERVAL_SECONDS=""

GLOBAL_RATE_LIMIT=""
ADMISSION_GLOBAL=""
TENANT_AUTHENTICATED=""
TENANT_UNAUTHENTICATED=""
CIRCUIT_BREAKER_FAILURE_THRESHOLD=""
CIRCUIT_BREAKER_COOLDOWN_SECONDS=""

SK=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk MCP Server Setup

Usage: $(basename "$0") [OPTIONS]

Primary actions:
  --install                              Install or update ${APP_NAME} from the repo-local package
  --uninstall                            Uninstall ${APP_NAME} using the shared app uninstaller (standalone)
  --rotate-keys                          Rotate the MCP RSA keys through /mcp_token
  --rotate-key-size 2048|4096            Key size used with --rotate-keys (default: 2048)
  --token-user USER                      Username to mint the encrypted bearer token for
  --token-expires-on VALUE               Token lifetime expression for /mcp_token (default: +30d)
  --token-not-before VALUE               Optional not_before value for /mcp_token
  --write-token-file PATH                Write the encrypted bearer token to PATH (0600)
  --bearer-token-file PATH               Existing encrypted bearer token file to use when rendering clients
  --render-clients                       Render a shared Cursor/Codex bridge bundle
  --output-dir PATH                      Client bundle output directory (default: repo-root ./splunk-mcp-rendered)
  --client-name NAME                     Client registration name for Codex (default: splunk-mcp)
  --cursor-workspace PATH                Cursor workspace to update (default: current working directory)
  --client-insecure-tls                  Render SPLUNK_MCP_INSECURE_TLS=1 in the client env file
  --no-register-codex                    Render the bundle but skip codex mcp registration
  --no-configure-cursor                  Render the bundle but skip updating Cursor workspace config
  --mcp-url URL                          Explicit MCP endpoint override for the client bundle
  --package-file PATH                    Override the local package path used with --install

Server settings:
  --base-url URL                         Optional mcp.conf [server] base_url
  --timeout SECONDS                      mcp.conf [server] timeout
  --max-row-limit N                      mcp.conf [server] max_row_limit
  --default-row-limit N                  mcp.conf [server] default_row_limit
  --ssl-verify VALUE                     mcp.conf [server] ssl_verify (true|false|none|/path/to/ca.pem)
  --require-encrypted-token true|false   mcp.conf [server] require_encrypted_token
  --legacy-token-grace-days N            mcp.conf [server] legacy_token_grace_days
  --token-max-lifetime-seconds N         mcp.conf [server] mcp_token_max_lifetime_seconds
  --token-default-lifetime-seconds N     mcp.conf [server] mcp_token_default_lifetime_seconds
  --token-key-reload-interval-seconds N  mcp.conf [server] token_key_reload_interval_seconds

Rate limits:
  --global-rate-limit N                  mcp.conf [rate_limits] global
  --admission-global N                   mcp.conf [rate_limits] admission_global
  --tenant-authenticated N               mcp.conf [rate_limits] tenant_authenticated
  --tenant-unauthenticated N             mcp.conf [rate_limits] tenant_unauthenticated
  --circuit-breaker-failure-threshold N  mcp.conf [rate_limits] circuit_breaker_failure_threshold
  --circuit-breaker-cooldown-seconds N   mcp.conf [rate_limits] circuit_breaker_cooldown_seconds

Examples:
  $(basename "$0") --install
  $(basename "$0") --uninstall
  $(basename "$0") --timeout 90 --max-row-limit 2000 --default-row-limit 250
  $(basename "$0") --token-user existing-user --write-token-file /tmp/splunk_mcp.token
  $(basename "$0") --render-clients --bearer-token-file /tmp/splunk_mcp.token
  $(basename "$0") --render-clients --cursor-workspace ~/Projects/my-cursor-workspace

EOF
    exit "${exit_code}"
}

normalize_boolean() {
    case "${1:-}" in
        true|TRUE|True|1|yes|YES|on|ON) printf '%s' "true" ;;
        false|FALSE|False|0|no|NO|off|OFF) printf '%s' "false" ;;
        *)
            log "ERROR: Expected a boolean value, got '${1:-}'. Use true or false."
            exit 1
            ;;
    esac
}

shell_quote() {
    printf '%q' "${1:-}"
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

sanitize_path_component() {
    python3 - "${1:-}" <<'PY'
import re
import sys

value = (sys.argv[1] or "").strip() or "splunk-mcp"
value = re.sub(r"[\\/]+", "-", value)
value = re.sub(r"\s+", "-", value)
value = re.sub(r"[^A-Za-z0-9._-]", "-", value)
value = re.sub(r"-{2,}", "-", value).strip("-.") or "splunk-mcp"
print(value, end="")
PY
}

resolve_codex_bundle_dir() {
    local client_name="$1"
    local codex_home safe_name

    codex_home="${CODEX_HOME:-${HOME}/.codex}"
    safe_name="$(sanitize_path_component "${client_name}")"
    printf '%s' "${codex_home}/mcp-bridges/${safe_name}"
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

relative_path_within_dir() {
    python3 - "$1" "$2" <<'PY'
from pathlib import Path
import sys

target = Path(sys.argv[1]).resolve()
base = Path(sys.argv[2]).resolve()
print(target.relative_to(base).as_posix(), end="")
PY
}

ensure_parent_dir() {
    mkdir -p "$(dirname "$1")"
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

copy_file_with_mode() {
    local source_path="$1" dest_path="$2" mode="$3"

    ensure_parent_dir "${dest_path}"
    cp "${source_path}" "${dest_path}"
    chmod "${mode}" "${dest_path}"
}

derive_mcp_url() {
    python3 - "${1:-}" <<'PY'
from urllib.parse import urlsplit
import sys

uri = (sys.argv[1] or "").strip()
if not uri:
    raise SystemExit(1)

parts = urlsplit(uri)
scheme = parts.scheme or "https"
netloc = parts.netloc or parts.path
if not netloc:
    raise SystemExit(1)

print(f"{scheme}://{netloc}/services/mcp", end="")
PY
}

ensure_session() {
    load_splunk_credentials || {
        log "ERROR: Splunk credentials are required."
        exit 1
    }
    SK="$(get_session_key "${SPLUNK_URI}")" || {
        log "ERROR: Could not authenticate to Splunk."
        exit 1
    }
}

ensure_app_installed() {
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: ${APP_NAME} is not installed. Use --install or run the shared app installer first."
        exit 1
    fi
}

install_or_update_app() {
    local update_flag="--no-update"

    if [[ ! -f "${PACKAGE_FILE}" ]]; then
        log "ERROR: Package file not found: ${PACKAGE_FILE}"
        exit 1
    fi

    ensure_session
    if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        update_flag="--update"
        log "Installing update for ${APP_NAME} from ${PACKAGE_FILE}..."
    else
        log "Installing ${APP_NAME} from ${PACKAGE_FILE}..."
    fi

    bash "${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh" \
        --source local \
        --file "${PACKAGE_FILE}" \
        "${update_flag}"
}

uninstall_app() {
    log "Uninstalling ${APP_NAME}..."
    printf 'yes\n' | bash "${PROJECT_ROOT}/skills/splunk-app-install/scripts/uninstall_app.sh" \
        --app-name "${APP_NAME}"
}

ensure_app_visible() {
    local visible
    visible="$(
        splunk_curl "${SK}" \
            "${SPLUNK_URI}/services/apps/local/${APP_NAME}?output_mode=json" 2>/dev/null \
            | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["entry"][0]["content"].get("visible", True), end="")
except Exception:
    print("True", end="")
' 2>/dev/null || echo "True"
    )"

    if [[ "${visible}" == "False" ]]; then
        log "Setting ${APP_NAME} visible=true..."
        splunk_curl "${SK}" -X POST \
            "${SPLUNK_URI}/services/apps/local/${APP_NAME}" \
            -d "visible=true" -d "output_mode=json" >/dev/null 2>&1 || {
            log "ERROR: Failed to set ${APP_NAME} visible=true."
            exit 1
        }
    fi
}

set_conf_field() {
    local conf="$1" stanza="$2" key="$3" value="$4"
    local body
    body="$(form_urlencode_pairs "${key}" "${value}")" || return 1
    rest_set_conf "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "${conf}" "${stanza}" "${body}"
}

configure_server_settings() {
    local mutated=false

    if [[ -n "${BASE_URL}" ]]; then
        set_conf_field "mcp" "server" "base_url" "${BASE_URL}" || exit 1
        mutated=true
    fi
    if [[ -n "${TIMEOUT}" ]]; then
        set_conf_field "mcp" "server" "timeout" "${TIMEOUT}" || exit 1
        mutated=true
    fi
    if [[ -n "${MAX_ROW_LIMIT}" ]]; then
        set_conf_field "mcp" "server" "max_row_limit" "${MAX_ROW_LIMIT}" || exit 1
        mutated=true
    fi
    if [[ -n "${DEFAULT_ROW_LIMIT}" ]]; then
        set_conf_field "mcp" "server" "default_row_limit" "${DEFAULT_ROW_LIMIT}" || exit 1
        mutated=true
    fi
    if [[ -n "${SSL_VERIFY}" ]]; then
        set_conf_field "mcp" "server" "ssl_verify" "${SSL_VERIFY}" || exit 1
        mutated=true
    fi
    if [[ -n "${REQUIRE_ENCRYPTED_TOKEN}" ]]; then
        set_conf_field "mcp" "server" "require_encrypted_token" "${REQUIRE_ENCRYPTED_TOKEN}" || exit 1
        mutated=true
    fi
    if [[ -n "${LEGACY_TOKEN_GRACE_DAYS}" ]]; then
        set_conf_field "mcp" "server" "legacy_token_grace_days" "${LEGACY_TOKEN_GRACE_DAYS}" || exit 1
        mutated=true
    fi
    if [[ -n "${TOKEN_MAX_LIFETIME_SECONDS}" ]]; then
        set_conf_field "mcp" "server" "mcp_token_max_lifetime_seconds" "${TOKEN_MAX_LIFETIME_SECONDS}" || exit 1
        mutated=true
    fi
    if [[ -n "${TOKEN_DEFAULT_LIFETIME_SECONDS}" ]]; then
        set_conf_field "mcp" "server" "mcp_token_default_lifetime_seconds" "${TOKEN_DEFAULT_LIFETIME_SECONDS}" || exit 1
        mutated=true
    fi
    if [[ -n "${TOKEN_KEY_RELOAD_INTERVAL_SECONDS}" ]]; then
        set_conf_field "mcp" "server" "token_key_reload_interval_seconds" "${TOKEN_KEY_RELOAD_INTERVAL_SECONDS}" || exit 1
        mutated=true
    fi

    if [[ "${mutated}" == "true" ]]; then
        log "Updated supported mcp.conf [server] settings."
    fi
}

configure_rate_limits() {
    local mutated=false

    if [[ -n "${GLOBAL_RATE_LIMIT}" ]]; then
        set_conf_field "mcp" "rate_limits" "global" "${GLOBAL_RATE_LIMIT}" || exit 1
        mutated=true
    fi
    if [[ -n "${ADMISSION_GLOBAL}" ]]; then
        set_conf_field "mcp" "rate_limits" "admission_global" "${ADMISSION_GLOBAL}" || exit 1
        mutated=true
    fi
    if [[ -n "${TENANT_AUTHENTICATED}" ]]; then
        set_conf_field "mcp" "rate_limits" "tenant_authenticated" "${TENANT_AUTHENTICATED}" || exit 1
        mutated=true
    fi
    if [[ -n "${TENANT_UNAUTHENTICATED}" ]]; then
        set_conf_field "mcp" "rate_limits" "tenant_unauthenticated" "${TENANT_UNAUTHENTICATED}" || exit 1
        mutated=true
    fi
    if [[ -n "${CIRCUIT_BREAKER_FAILURE_THRESHOLD}" ]]; then
        set_conf_field "mcp" "rate_limits" "circuit_breaker_failure_threshold" "${CIRCUIT_BREAKER_FAILURE_THRESHOLD}" || exit 1
        mutated=true
    fi
    if [[ -n "${CIRCUIT_BREAKER_COOLDOWN_SECONDS}" ]]; then
        set_conf_field "mcp" "rate_limits" "circuit_breaker_cooldown_seconds" "${CIRCUIT_BREAKER_COOLDOWN_SECONDS}" || exit 1
        mutated=true
    fi

    if [[ "${mutated}" == "true" ]]; then
        log "Updated mcp.conf [rate_limits] settings."
    fi
}

rotate_keys() {
    local url resp http_code body fingerprint

    url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_token?action=rotate&key_size=${ROTATE_KEY_SIZE}&output_mode=json"
    resp="$(splunk_curl "${SK}" -X POST "${url}" -w '\n%{http_code}' 2>/dev/null || true)"
    http_code="$(printf '%s\n' "${resp}" | tail -1)"
    body="$(printf '%s\n' "${resp}" | sed '$d')"

    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Key rotation failed (HTTP ${http_code})."
        sanitize_response "${body}" 10 >&2
        exit 1
    fi

    fingerprint="$(
        printf '%s' "${body}" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("public_key_fingerprint", ""), end="")
except Exception:
    print("", end="")
' 2>/dev/null || true
    )"
    log "Rotated MCP RSA keys (key_size=${ROTATE_KEY_SIZE}${fingerprint:+, fingerprint=${fingerprint}})."
}

mint_token_to_file() {
    local target_file="$1"
    local encoded_user encoded_exp encoded_not_before url resp http_code body token

    if [[ -z "${TOKEN_USER}" ]]; then
        log "ERROR: --token-user is required with --write-token-file."
        exit 1
    fi

    encoded_user="$(_urlencode "${TOKEN_USER}")"
    encoded_exp="$(_urlencode "${TOKEN_EXPIRES_ON}")"
    url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_token?output_mode=json&username=${encoded_user}&expires_on=${encoded_exp}"

    if [[ -n "${TOKEN_NOT_BEFORE}" ]]; then
        encoded_not_before="$(_urlencode "${TOKEN_NOT_BEFORE}")"
        url="${url}&not_before=${encoded_not_before}"
    fi

    resp="$(splunk_curl "${SK}" "${url}" -w '\n%{http_code}' 2>/dev/null || true)"
    http_code="$(printf '%s\n' "${resp}" | tail -1)"
    body="$(printf '%s\n' "${resp}" | sed '$d')"

    if [[ "${http_code}" != "200" ]]; then
        log "ERROR: Token creation failed (HTTP ${http_code})."
        sanitize_response "${body}" 10 >&2
        exit 1
    fi

    token="$(
        printf '%s' "${body}" | python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("token", ""), end="")
except Exception:
    print("", end="")
' 2>/dev/null || true
    )"

    if [[ -z "${token}" ]]; then
        log "ERROR: MCP token response did not include a token."
        exit 1
    fi

    write_secret_file "${target_file}" "${token}"
    log "Encrypted MCP bearer token written to ${target_file}."
}

validate_secret_render_target() {
    local token_source="$1"
    local output_abs repo_abs default_abs

    [[ -n "${token_source}" ]] || return 0

    output_abs="$(resolve_abs_path "${OUTPUT_DIR}")"
    repo_abs="$(resolve_abs_path "${PROJECT_ROOT}")"
    default_abs="$(resolve_abs_path "${PROJECT_ROOT}/${DEFAULT_OUTPUT_DIR_NAME}")"

    if [[ "${output_abs}" == "${default_abs}" ]]; then
        return 0
    fi

    if [[ "$(path_is_within_dir "${output_abs}" "${repo_abs}")" == "yes" ]]; then
        log "ERROR: Refusing to render token-backed client files into a repo directory that is not the default ./${DEFAULT_OUTPUT_DIR_NAME} path."
        log "       Use the default gitignored path or an output directory outside the repo."
        exit 1
    fi
}

render_client_bundle() {
    local token_source token_value token_value_quoted mcp_url mcp_url_quoted env_example env_live cursor_json wrapper_script codex_script output_abs cursor_name default_server_name_quoted

    if [[ -z "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="${PROJECT_ROOT}/${DEFAULT_OUTPUT_DIR_NAME}"
    fi

    if [[ -n "${WRITE_TOKEN_FILE}" && -z "${BEARER_TOKEN_FILE}" ]]; then
        BEARER_TOKEN_FILE="${WRITE_TOKEN_FILE}"
    fi

    token_source="${BEARER_TOKEN_FILE}"
    if [[ -n "${token_source}" && ! -f "${token_source}" ]]; then
        log "ERROR: Bearer token file not found: ${token_source}"
        exit 1
    fi

    validate_secret_render_target "${token_source}"

    if [[ -n "${MCP_URL}" ]]; then
        mcp_url="${MCP_URL}"
    else
        mcp_url="$(derive_mcp_url "${SPLUNK_URI}")" || {
            log "ERROR: Could not derive the MCP URL from ${SPLUNK_URI}."
            exit 1
        }
    fi

    mkdir -p "${OUTPUT_DIR}/.cursor"
    output_abs="$(resolve_abs_path "${OUTPUT_DIR}")"
    cursor_name="${CLIENT_NAME}"
    mcp_url_quoted="$(shell_quote "${mcp_url}")"
    default_server_name_quoted="$(shell_quote "${CLIENT_NAME}")"

    cursor_json="$(
        python3 - "${cursor_name}" <<'PY'
import json
import sys

payload = {
    "mcpServers": {
        sys.argv[1]: {
            "type": "stdio",
            "command": "${workspaceFolder}/run-splunk-mcp.sh",
            "args": [],
        }
    }
}
print(json.dumps(payload, indent=2), end="\n")
PY
    )"

    wrapper_script="$(cat <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env.splunk-mcp"

_PRE_SPLUNK_MCP_URL="${SPLUNK_MCP_URL-}"
_PRE_SPLUNK_MCP_TOKEN="${SPLUNK_MCP_TOKEN-}"
_PRE_SPLUNK_MCP_INSECURE_TLS="${SPLUNK_MCP_INSECURE_TLS-}"

set -a
# shellcheck source=/dev/null
[[ -f "${ENV_FILE}" ]] && source "${ENV_FILE}"
set +a

[[ -n "${_PRE_SPLUNK_MCP_URL}" ]] && SPLUNK_MCP_URL="${_PRE_SPLUNK_MCP_URL}"
[[ -n "${_PRE_SPLUNK_MCP_TOKEN}" ]] && SPLUNK_MCP_TOKEN="${_PRE_SPLUNK_MCP_TOKEN}"
[[ -n "${_PRE_SPLUNK_MCP_INSECURE_TLS}" ]] && SPLUNK_MCP_INSECURE_TLS="${_PRE_SPLUNK_MCP_INSECURE_TLS}"

if [[ -z "${SPLUNK_MCP_URL:-}" ]]; then
  echo "splunk-mcp: set SPLUNK_MCP_URL in ${ENV_FILE}" >&2
  exit 1
fi

if [[ -z "${SPLUNK_MCP_TOKEN:-}" ]]; then
  echo "splunk-mcp: set SPLUNK_MCP_TOKEN in ${ENV_FILE}" >&2
  exit 1
fi

if [[ "${SPLUNK_MCP_INSECURE_TLS:-}" == "1" ]]; then
  export NODE_TLS_REJECT_UNAUTHORIZED=0
fi

if ! command -v mcp-remote >/dev/null 2>&1; then
  echo "splunk-mcp: install mcp-remote (for example: npm install -g mcp-remote)" >&2
  exit 1
fi

exec mcp-remote "${SPLUNK_MCP_URL}" --header "Authorization: Bearer ${SPLUNK_MCP_TOKEN}"
EOF
)"

    codex_script="$(cat <<EOF
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="\$(cd "\$(dirname "\$0")" && pwd)"
DEFAULT_SERVER_NAME=${default_server_name_quoted}
SERVER_NAME="\${1:-\${DEFAULT_SERVER_NAME}}"
CODEX_HOME_DIR="\${CODEX_HOME:-\${HOME}/.codex}"
SAFE_SERVER_NAME="\$(
python3 - "\${SERVER_NAME}" <<'PY'
import re
import sys

value = (sys.argv[1] or "").strip() or "splunk-mcp"
value = re.sub(r"[\\\\/]+", "-", value)
value = re.sub(r"\\s+", "-", value)
value = re.sub(r"[^A-Za-z0-9._-]", "-", value)
value = re.sub(r"-{2,}", "-", value).strip("-.") or "splunk-mcp"
print(value, end="")
PY
)"
CODEX_BUNDLE_DIR="\${CODEX_HOME_DIR}/mcp-bridges/\${SAFE_SERVER_NAME}"

mkdir -p "\${CODEX_BUNDLE_DIR}"
cp "\${SCRIPT_DIR}/run-splunk-mcp.sh" "\${CODEX_BUNDLE_DIR}/run-splunk-mcp.sh"
chmod 755 "\${CODEX_BUNDLE_DIR}/run-splunk-mcp.sh"

if [[ -f "\${SCRIPT_DIR}/.env.splunk-mcp" ]]; then
  cp "\${SCRIPT_DIR}/.env.splunk-mcp" "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp"
  chmod 600 "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp"
fi

if [[ -f "\${SCRIPT_DIR}/.env.splunk-mcp.example" ]]; then
  cp "\${SCRIPT_DIR}/.env.splunk-mcp.example" "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp.example"
  chmod 644 "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp.example"
fi

exec codex mcp add "\${SERVER_NAME}" -- "\${CODEX_BUNDLE_DIR}/run-splunk-mcp.sh"
EOF
)"

    env_example="$(cat <<EOF
# Copy to .env.splunk-mcp and keep the populated file local only.
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_TOKEN=''
EOF
)"
    if [[ "${CLIENT_INSECURE_TLS}" == "true" ]]; then
        env_example="${env_example}"$'\n''SPLUNK_MCP_INSECURE_TLS=1'
    else
        env_example="${env_example}"$'\n''# SPLUNK_MCP_INSECURE_TLS=1'
    fi

    write_text_file "${OUTPUT_DIR}/.cursor/mcp.json" "${cursor_json}"
    write_text_file "${OUTPUT_DIR}/run-splunk-mcp.sh" "${wrapper_script}"
    chmod 755 "${OUTPUT_DIR}/run-splunk-mcp.sh"
    write_text_file "${OUTPUT_DIR}/register-codex-mcp.sh" "${codex_script}"
    chmod 755 "${OUTPUT_DIR}/register-codex-mcp.sh"
    write_text_file "${OUTPUT_DIR}/.env.splunk-mcp.example" "${env_example}"

    if [[ -n "${token_source}" ]]; then
        token_value="$(read_secret_file "${token_source}")" || exit 1
        token_value_quoted="$(shell_quote "${token_value}")"
        env_live="$(cat <<EOF
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_TOKEN=${token_value_quoted}
EOF
)"
        if [[ "${CLIENT_INSECURE_TLS}" == "true" ]]; then
            env_live="${env_live}"$'\n''SPLUNK_MCP_INSECURE_TLS=1'
        fi
        write_secret_file "${OUTPUT_DIR}/.env.splunk-mcp" "${env_live}"
    fi

    log "Rendered shared Cursor/Codex MCP bridge bundle at ${output_abs}."
    log "Open that directory as a Cursor workspace, or run ${output_abs}/register-codex-mcp.sh to sync a portable Codex bundle and register it."
}

ensure_command_available() {
    local command_name="$1" hint="${2:-}"

    if command -v "${command_name}" >/dev/null 2>&1; then
        return 0
    fi

    log "ERROR: Required command not found on PATH: ${command_name}"
    if [[ -n "${hint}" ]]; then
        log "       ${hint}"
    fi
    exit 1
}

resolve_cursor_workspace_dir() {
    local workspace_input="${CURSOR_WORKSPACE:-${PWD}}"
    local workspace_abs

    workspace_abs="$(resolve_abs_path "${workspace_input}")"
    if [[ ! -d "${workspace_abs}" ]]; then
        log "ERROR: Cursor workspace directory not found: ${workspace_input}"
        exit 1
    fi

    printf '%s' "${workspace_abs}"
}

build_cursor_wrapper_command() {
    local workspace_dir="$1" wrapper_abs="$2"
    local wrapper_command relative_wrapper_path

    if [[ "$(path_is_within_dir "${wrapper_abs}" "${workspace_dir}")" == "yes" ]]; then
        relative_wrapper_path="$(relative_path_within_dir "${wrapper_abs}" "${workspace_dir}")"
        wrapper_command="\${workspaceFolder}/${relative_wrapper_path}"
    else
        wrapper_command="${wrapper_abs}"
    fi

    printf '%s' "${wrapper_command}"
}

build_cursor_workspace_json() {
    local config_path="$1" server_name="$2" wrapper_command="$3"
    python3 - "${config_path}" "${server_name}" "${wrapper_command}" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
server_name = sys.argv[2]
wrapper_command = sys.argv[3]

entry = {
    "type": "stdio",
    "command": wrapper_command,
    "args": [],
}

data = {}
if config_path.exists():
    try:
        raw = config_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"ERROR: Existing Cursor MCP config is not valid JSON: {config_path}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"ERROR: Could not read existing Cursor MCP config {config_path}: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if not isinstance(data, dict):
        print(f"ERROR: Existing Cursor MCP config must contain a top-level JSON object: {config_path}", file=sys.stderr)
        raise SystemExit(1)

mcp_servers = data.get("mcpServers")
if mcp_servers is None:
    mcp_servers = {}
    data["mcpServers"] = mcp_servers
elif not isinstance(mcp_servers, dict):
    print(f"ERROR: Existing Cursor MCP config has a non-object mcpServers field: {config_path}", file=sys.stderr)
    raise SystemExit(1)

mcp_servers[server_name] = entry

json.dump(data, sys.stdout, indent=2)
sys.stdout.write("\n")
PY
}

register_codex_client() {
    local wrapper_abs="$1"
    local codex_output codex_rc
    local codex_bundle_dir stable_wrapper stable_env stable_env_example source_dir

    ensure_command_available "codex" "Install the Codex CLI or rerun with --no-register-codex."
    source_dir="$(dirname "${wrapper_abs}")"
    codex_bundle_dir="$(resolve_codex_bundle_dir "${CLIENT_NAME}")"
    stable_wrapper="${codex_bundle_dir}/run-splunk-mcp.sh"
    stable_env="${codex_bundle_dir}/.env.splunk-mcp"
    stable_env_example="${codex_bundle_dir}/.env.splunk-mcp.example"

    mkdir -p "${codex_bundle_dir}"
    copy_file_with_mode "${wrapper_abs}" "${stable_wrapper}" 755

    if [[ -f "${source_dir}/.env.splunk-mcp" ]]; then
        copy_file_with_mode "${source_dir}/.env.splunk-mcp" "${stable_env}" 600
    fi
    if [[ -f "${source_dir}/.env.splunk-mcp.example" ]]; then
        copy_file_with_mode "${source_dir}/.env.splunk-mcp.example" "${stable_env_example}" 644
    fi

    set +e
    codex_output="$(codex mcp add "${CLIENT_NAME}" -- "${stable_wrapper}" 2>&1)"
    codex_rc=$?
    set -e

    if (( codex_rc != 0 )); then
        [[ -n "${codex_output}" ]] && printf '%s\n' "${codex_output}" >&2
        log "ERROR: Failed to register Codex MCP server '${CLIENT_NAME}'."
        exit 1
    fi

    log "Registered Codex MCP server '${CLIENT_NAME}' using portable bundle ${stable_wrapper}."
}

write_cursor_workspace_config() {
    local workspace_dir="$1" wrapper_command="$2"
    local cursor_config_path="${workspace_dir}/.cursor/mcp.json"
    local cursor_json

    cursor_json="$(build_cursor_workspace_json "${cursor_config_path}" "${CLIENT_NAME}" "${wrapper_command}")" || exit 1
    write_text_file "${cursor_config_path}" "${cursor_json}"
    log "Configured Cursor MCP server '${CLIENT_NAME}' in ${workspace_dir}."
}

apply_client_setup() {
    local wrapper_abs workspace_dir="" wrapper_command=""

    if [[ "${REGISTER_CODEX}" != "true" && "${CONFIGURE_CURSOR}" != "true" ]]; then
        log "Skipped Codex and Cursor auto-apply; rendered bundle only."
        return 0
    fi

    ensure_command_available "mcp-remote" "Install it with: npm install -g mcp-remote"
    wrapper_abs="$(resolve_abs_path "${OUTPUT_DIR}/run-splunk-mcp.sh")"

    if [[ "${CONFIGURE_CURSOR}" == "true" ]]; then
        workspace_dir="$(resolve_cursor_workspace_dir)"
        wrapper_command="$(build_cursor_wrapper_command "${workspace_dir}" "${wrapper_abs}")"
        # Validate and prepare any existing Cursor config before mutating Codex registration.
        build_cursor_workspace_json "${workspace_dir}/.cursor/mcp.json" "${CLIENT_NAME}" "${wrapper_command}" >/dev/null || exit 1
    fi

    if [[ "${REGISTER_CODEX}" == "true" ]]; then
        register_codex_client "${wrapper_abs}"
    fi

    if [[ "${CONFIGURE_CURSOR}" == "true" ]]; then
        write_cursor_workspace_config "${workspace_dir}" "${wrapper_command}"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) DO_INSTALL=true; shift ;;
        --uninstall) DO_UNINSTALL=true; shift ;;
        --package-file) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; PACKAGE_FILE="$2"; shift 2 ;;
        --rotate-keys) HAS_UNINSTALL_CONFLICT=true; ROTATE_KEYS=true; shift ;;
        --rotate-key-size) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; ROTATE_KEY_SIZE="$2"; shift 2 ;;
        --render-clients) HAS_UNINSTALL_CONFLICT=true; RENDER_CLIENTS=true; shift ;;
        --output-dir) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --client-name) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; CLIENT_NAME="$2"; shift 2 ;;
        --cursor-workspace) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; CURSOR_WORKSPACE="$2"; shift 2 ;;
        --client-insecure-tls) HAS_UNINSTALL_CONFLICT=true; CLIENT_INSECURE_TLS=true; shift ;;
        --no-register-codex) HAS_UNINSTALL_CONFLICT=true; REGISTER_CODEX=false; shift ;;
        --no-configure-cursor) HAS_UNINSTALL_CONFLICT=true; CONFIGURE_CURSOR=false; shift ;;
        --mcp-url) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; MCP_URL="$2"; shift 2 ;;
        --token-user) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TOKEN_USER="$2"; shift 2 ;;
        --token-expires-on) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TOKEN_EXPIRES_ON="$2"; shift 2 ;;
        --token-not-before) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TOKEN_NOT_BEFORE="$2"; shift 2 ;;
        --write-token-file) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; WRITE_TOKEN_FILE="$2"; shift 2 ;;
        --bearer-token-file) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; BEARER_TOKEN_FILE="$2"; shift 2 ;;
        --base-url) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; BASE_URL="$2"; shift 2 ;;
        --timeout) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TIMEOUT="$2"; shift 2 ;;
        --max-row-limit) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; MAX_ROW_LIMIT="$2"; shift 2 ;;
        --default-row-limit) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; DEFAULT_ROW_LIMIT="$2"; shift 2 ;;
        --ssl-verify) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; SSL_VERIFY="$2"; shift 2 ;;
        --require-encrypted-token) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; REQUIRE_ENCRYPTED_TOKEN="$(normalize_boolean "$2")"; shift 2 ;;
        --legacy-token-grace-days) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; LEGACY_TOKEN_GRACE_DAYS="$2"; shift 2 ;;
        --token-max-lifetime-seconds) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TOKEN_MAX_LIFETIME_SECONDS="$2"; shift 2 ;;
        --token-default-lifetime-seconds) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TOKEN_DEFAULT_LIFETIME_SECONDS="$2"; shift 2 ;;
        --token-key-reload-interval-seconds) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TOKEN_KEY_RELOAD_INTERVAL_SECONDS="$2"; shift 2 ;;
        --global-rate-limit) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; GLOBAL_RATE_LIMIT="$2"; shift 2 ;;
        --admission-global) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; ADMISSION_GLOBAL="$2"; shift 2 ;;
        --tenant-authenticated) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TENANT_AUTHENTICATED="$2"; shift 2 ;;
        --tenant-unauthenticated) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; TENANT_UNAUTHENTICATED="$2"; shift 2 ;;
        --circuit-breaker-failure-threshold) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; CIRCUIT_BREAKER_FAILURE_THRESHOLD="$2"; shift 2 ;;
        --circuit-breaker-cooldown-seconds) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; CIRCUIT_BREAKER_COOLDOWN_SECONDS="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

case "${ROTATE_KEY_SIZE}" in
    2048|4096) ;;
    *)
        log "ERROR: --rotate-key-size must be 2048 or 4096."
        exit 1
        ;;
esac

if [[ "${DO_INSTALL}" == "true" && "${DO_UNINSTALL}" == "true" ]]; then
    log "ERROR: --install and --uninstall cannot be used together."
    exit 1
fi

if [[ "${DO_UNINSTALL}" == "true" && "${HAS_UNINSTALL_CONFLICT}" == "true" ]]; then
    log "ERROR: --uninstall must be run by itself without any other action or configuration flags."
    exit 1
fi

if [[ "${REQUIRE_ENCRYPTED_TOKEN}" == "false" && ( "${ROTATE_KEYS}" == "true" || -n "${WRITE_TOKEN_FILE}" ) ]]; then
    log "ERROR: /mcp_token minting and key rotation require require_encrypted_token=true."
    log "       Split this into separate runs or keep encrypted tokens enabled."
    exit 1
fi

warn_if_role_unsupported_for_skill "splunk-mcp-server-setup"

LIVE_SPLUNK_ACTIONS=false
if [[ "${DO_INSTALL}" == "true" \
   || "${ROTATE_KEYS}" == "true" \
   || -n "${WRITE_TOKEN_FILE}" \
   || -n "${BASE_URL}" \
   || -n "${TIMEOUT}" \
   || -n "${MAX_ROW_LIMIT}" \
   || -n "${DEFAULT_ROW_LIMIT}" \
   || -n "${SSL_VERIFY}" \
   || -n "${REQUIRE_ENCRYPTED_TOKEN}" \
   || -n "${LEGACY_TOKEN_GRACE_DAYS}" \
   || -n "${TOKEN_MAX_LIFETIME_SECONDS}" \
   || -n "${TOKEN_DEFAULT_LIFETIME_SECONDS}" \
   || -n "${TOKEN_KEY_RELOAD_INTERVAL_SECONDS}" \
   || -n "${GLOBAL_RATE_LIMIT}" \
   || -n "${ADMISSION_GLOBAL}" \
   || -n "${TENANT_AUTHENTICATED}" \
   || -n "${TENANT_UNAUTHENTICATED}" \
   || -n "${CIRCUIT_BREAKER_FAILURE_THRESHOLD}" \
   || -n "${CIRCUIT_BREAKER_COOLDOWN_SECONDS}" ]]; then
    LIVE_SPLUNK_ACTIONS=true
fi

if [[ "${LIVE_SPLUNK_ACTIONS}" == "false" && "${RENDER_CLIENTS}" != "true" ]]; then
    LIVE_SPLUNK_ACTIONS=true
fi

if [[ "${DO_INSTALL}" == "true" ]]; then
    install_or_update_app
fi

if [[ "${DO_UNINSTALL}" == "true" ]]; then
    uninstall_app
    exit 0
fi

if [[ "${LIVE_SPLUNK_ACTIONS}" == "true" ]]; then
    ensure_session
    ensure_app_installed
    ensure_app_visible
    configure_server_settings
    configure_rate_limits

    if [[ "${ROTATE_KEYS}" == "true" ]]; then
        rotate_keys
    fi

    if [[ -n "${WRITE_TOKEN_FILE}" ]]; then
        mint_token_to_file "${WRITE_TOKEN_FILE}"
    fi
elif [[ "${RENDER_CLIENTS}" == "true" && -z "${MCP_URL}" ]]; then
    load_splunk_credentials || {
        log "ERROR: --render-clients without --mcp-url requires Splunk credentials so the MCP URL can be derived."
        exit 1
    }
fi

if [[ "${RENDER_CLIENTS}" == "true" ]]; then
    render_client_bundle
    apply_client_setup
fi

if [[ "${DO_INSTALL}" != "true" \
   && -z "${WRITE_TOKEN_FILE}" \
   && "${ROTATE_KEYS}" != "true" \
   && "${RENDER_CLIENTS}" != "true" \
   && -z "${BASE_URL}" \
   && -z "${TIMEOUT}" \
   && -z "${MAX_ROW_LIMIT}" \
   && -z "${DEFAULT_ROW_LIMIT}" \
   && -z "${SSL_VERIFY}" \
   && -z "${REQUIRE_ENCRYPTED_TOKEN}" \
   && -z "${LEGACY_TOKEN_GRACE_DAYS}" \
   && -z "${TOKEN_MAX_LIFETIME_SECONDS}" \
   && -z "${TOKEN_DEFAULT_LIFETIME_SECONDS}" \
   && -z "${TOKEN_KEY_RELOAD_INTERVAL_SECONDS}" \
   && -z "${GLOBAL_RATE_LIMIT}" \
   && -z "${ADMISSION_GLOBAL}" \
   && -z "${TENANT_AUTHENTICATED}" \
   && -z "${TENANT_UNAUTHENTICATED}" \
   && -z "${CIRCUIT_BREAKER_FAILURE_THRESHOLD}" \
   && -z "${CIRCUIT_BREAKER_COOLDOWN_SECONDS}" ]]; then
    log "No explicit changes requested. Verified ${APP_NAME} is installed and visible."
fi
