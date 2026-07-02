#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
APP_NAME="Splunk_MCP_Server"
PACKAGE_MANIFEST="${SCRIPT_DIR}/../package-manifest.json"
PACKAGE_METADATA="$(python3 - "${PACKAGE_MANIFEST}" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    manifest = json.load(handle)
if manifest.get("app_id") != 7931 or manifest.get("app_name") != "Splunk_MCP_Server":
    raise SystemExit("ERROR: invalid Splunk MCP Server package manifest identity")
if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("sha256", ""))):
    raise SystemExit("ERROR: invalid Splunk MCP Server package manifest SHA-256")
approved = manifest.get("production_approved")
if not isinstance(approved, bool):
    raise SystemExit("ERROR: package manifest production_approved must be boolean")
print(
    manifest["version"],
    manifest["filename"],
    manifest["sha256"],
    str(approved).lower(),
    manifest.get("review_status", "unknown"),
    sep="\t",
)
PY
)" || exit 1
IFS=$'\t' read -r EXPECTED_APP_VERSION DEFAULT_PACKAGE_NAME DEFAULT_PACKAGE_SHA256 PACKAGE_PRODUCTION_APPROVED PACKAGE_REVIEW_STATUS <<< "${PACKAGE_METADATA}"
DEFAULT_PACKAGE_FILE="${PROJECT_ROOT}/splunk-ta/${DEFAULT_PACKAGE_NAME}"
DEFAULT_OUTPUT_DIR_NAME="splunk-mcp-rendered"

DO_INSTALL=false
ACCEPT_NONPRODUCTION_PACKAGE=false
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
GATEWAY_MODE="platform"
GATEWAY_URL="${SPLUNK_MCP_GATEWAY_URL:-}"
SCS_REGION="${SPLUNK_MCP_SCS_REGION:-}"
GATEWAY_URL_SET=false
SCS_REGION_SET=false
O11Y_REALM="${SPLUNK_O11Y_REALM:-}"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
SPLUNK_TENANT="${SPLUNK_MCP_SPLUNK_TENANT:-}"
SPLUNK_JWT_FILE="${SPLUNK_MCP_SPLUNK_JWT_FILE:-}"
CURSOR_WORKSPACE=""
REGISTER_CODEX=true
CONFIGURE_CURSOR=true
CONFIGURE_CLAUDE=true

TOKEN_USER=""
TOKEN_EXPIRES_ON="+12h"
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
  --accept-nonproduction-package         Permit review-blocked package workflows for isolated evaluation only
  --uninstall                            Uninstall ${APP_NAME} using the shared app uninstaller (standalone)
  --rotate-keys                          Rotate the MCP RSA keys through /mcp_token
  --rotate-key-size 2048|4096            Key size used with --rotate-keys (default: 2048)
  --token-user USER                      Username to mint the encrypted bearer token for
  --token-expires-on VALUE               Token lifetime expression for /mcp_token (default: +12h)
  --token-not-before VALUE               Optional not_before value for /mcp_token
  --write-token-file PATH                Write the encrypted bearer token to PATH (0600)
  --bearer-token-file PATH               Existing encrypted bearer token file to use when rendering clients
  --render-clients                       Render a shared Cursor/Codex/Claude Code bridge bundle
  --output-dir PATH                      Client bundle output directory (default: repo-root ./splunk-mcp-rendered)
  --client-name NAME                     Client registration name for Codex (default: splunk-mcp)
  --cursor-workspace PATH                Cursor workspace to update (default: current working directory)
  --client-insecure-tls                  Render SPLUNK_MCP_INSECURE_TLS=1 in the client env file
  --no-register-codex                    Render the bundle but skip codex mcp registration
  --no-configure-cursor                  Render the bundle but skip updating Cursor workspace config
  --no-configure-claude                  Render the bundle but skip writing Claude Code .mcp.json
  --mcp-url URL                          Explicit Splunk Platform /services/mcp endpoint override
  --gateway-mode platform|o11y|combined  Client endpoint mode (default: platform)
  --gateway-url URL                      Explicit hosted SCS MCP Gateway URL for o11y or combined mode
  --scs-region REGION                    SCS region used to derive https://region-REGION.api.scs.splunk.com/system/mcp-gateway/v1/
  --o11y-realm REALM                     Splunk Observability realm (default: SPLUNK_O11Y_REALM)
  --o11y-token-file PATH                 Splunk Observability token file (default: SPLUNK_O11Y_TOKEN_FILE)
  --splunk-tenant NAME                   Splunk tenant header value for combined mode
  --splunk-jwt-file PATH                 Splunk Platform authorization token file for combined mode
  --package-file PATH                    Override the local package path used with --install

Server settings:
  --base-url URL                         Optional mcp.conf [server] base_url
  --timeout SECONDS                      mcp.conf [server] timeout
  --max-row-limit N                      mcp.conf [server] max_row_limit
  --default-row-limit N                  mcp.conf [server] default_row_limit
  --ssl-verify VALUE                     Store mcp.conf [server] ssl_verify (not enforced by vendor 1.2.1)
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
  $(basename "$0") --render-clients --gateway-mode o11y --scs-region pdx10 --o11y-realm us1 --o11y-token-file /tmp/splunk_o11y_api_token
  $(basename "$0") --render-clients --gateway-mode combined --scs-region pdx10 --o11y-realm us1 --o11y-token-file /tmp/splunk_o11y_api_token --splunk-tenant mytenant --splunk-jwt-file /tmp/splunk_mcp.token

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

validate_uint_option() {
    local label="$1" value="$2" minimum="$3" maximum="$4"
    [[ -z "${value}" ]] && return 0
    if [[ ! "${value}" =~ ^[0-9]+$ ]] || (( 10#${value} < minimum || 10#${value} > maximum )); then
        log "ERROR: ${label} must be an integer between ${minimum} and ${maximum}; got '${value}'."
        exit 1
    fi
}

shell_quote() {
    printf '%q' "${1:-}"
}

validate_header_value() {
    local value="$1" label="$2"
    if [[ "${value}" == *$'\n'* || "${value}" == *$'\r'* || ${#value} -gt 65536 ]]; then
        log "ERROR: ${label} contains a forbidden line break or exceeds 65536 characters."
        exit 1
    fi
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

atomic_write_from_stdin() {
    local path="$1" mode="$2"
    ensure_parent_dir "${path}"
    python3 /dev/fd/3 "${path}" "${mode}" 3<<'PY'
import os
import stat
import sys
import tempfile
from pathlib import Path

target = Path(sys.argv[1])
mode = int(sys.argv[2], 8)
try:
    existing = target.lstat()
except FileNotFoundError:
    existing = None
if existing is not None and (stat.S_ISLNK(existing.st_mode) or not stat.S_ISREG(existing.st_mode)):
    raise SystemExit(f"ERROR: refusing to replace non-regular or symlink target: {target}")

payload = sys.stdin.buffer.read()
fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
try:
    os.fchmod(fd, mode)
    with os.fdopen(fd, "wb", closefd=True) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_name, target)
    dir_fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
except BaseException:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(temp_name)
    except OSError:
        pass
    raise
PY
}

write_text_file() {
    local path="$1" content="$2"
    printf '%s' "${content}" | atomic_write_from_stdin "${path}" 644
}

write_secret_file() {
    local path="$1" content="$2"
    printf '%s' "${content}" | atomic_write_from_stdin "${path}" 600
}

assert_secret_source_file() {
    local path="$1" label="$2" mode owner size
    [[ ! -L "${path}" && -f "${path}" && -r "${path}" && -s "${path}" ]] || { log "ERROR: ${label} must be a readable, non-empty, non-symlink regular file: ${path}"; exit 1; }
    mode="$(stat -c '%a' "${path}" 2>/dev/null || stat -f '%Lp' "${path}" 2>/dev/null)"
    [[ "${mode}" == "600" ]] || { log "ERROR: ${label} must be chmod 600 (found ${mode:-unknown}): ${path}"; exit 1; }
    owner="$(stat -c '%u' "${path}" 2>/dev/null || stat -f '%u' "${path}" 2>/dev/null)"
    [[ "${owner}" == "$(id -u)" ]] || { log "ERROR: ${label} must be owned by the current user: ${path}"; exit 1; }
    size="$(stat -c '%s' "${path}" 2>/dev/null || stat -f '%z' "${path}" 2>/dev/null)"
    if [[ ! "${size}" =~ ^[0-9]+$ ]] || (( 10#${size} > 65536 )); then
        log "ERROR: ${label} size is unknown or exceeds the 65536-byte limit: ${path}"
        exit 1
    fi
}

copy_file_with_mode() {
    local source_path="$1" dest_path="$2" mode="$3"
    [[ ! -L "${source_path}" && -f "${source_path}" ]] || { log "ERROR: Refusing unsafe copy source: ${source_path}"; exit 1; }
    atomic_write_from_stdin "${dest_path}" "${mode}" < "${source_path}"
}

derive_mcp_url() {
    python3 - "${1:-}" <<'PY'
from urllib.parse import urlsplit
import sys

uri = (sys.argv[1] or "").strip()
if not uri:
    raise SystemExit(1)
if "://" not in uri:
    uri = "https://" + uri

parts = urlsplit(uri)
scheme = parts.scheme.lower()
netloc = parts.netloc
if scheme not in {"http", "https"} or not netloc or parts.username or parts.password:
    raise SystemExit(1)

print(f"{scheme}://{netloc}/services/mcp", end="")
PY
}

normalize_gateway_mode() {
    case "${1:-platform}" in
        platform|o11y|combined) printf '%s' "${1:-platform}" ;;
        *)
            log "ERROR: --gateway-mode must be platform, o11y, or combined." >&2
            exit 1
            ;;
    esac
}

validate_client_url() {
    local url="$1" allow_loopback_http="$2" insecure_tls="$3"
    python3 - "${url}" "${allow_loopback_http}" "${insecure_tls}" <<'PY'
import ipaddress
import sys
from urllib.parse import urlsplit

url, allow_loopback_http, insecure_tls = sys.argv[1:]
parts = urlsplit(url)
if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
    raise SystemExit("ERROR: MCP URL contains control characters")
if not parts.hostname or parts.username or parts.password or parts.fragment:
    raise SystemExit("ERROR: MCP URL must include a host and must not contain userinfo")

host = parts.hostname.lower()
loopback = host == "localhost"
try:
    loopback = loopback or ipaddress.ip_address(host).is_loopback
except ValueError:
    pass

if parts.scheme != "https" and not (parts.scheme == "http" and loopback and allow_loopback_http == "true"):
    raise SystemExit("ERROR: MCP URL must use HTTPS (HTTP is allowed only for an explicit loopback target)")
if insecure_tls == "true" and not loopback:
    raise SystemExit("ERROR: --client-insecure-tls is restricted to loopback targets; install a trusted CA for remote endpoints")
PY
}

normalize_o11y_realm() {
    printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]'
}

validate_o11y_realm_for_gateway() {
    local realm
    realm="$(normalize_o11y_realm "${1:-}")"
    case "${realm}" in
        us2|*gcp*|*gov*)
            log "ERROR: Splunk MCP Gateway does not support Google Cloud Platform realms or GovCloud realms. Realm '${realm}' is not supported." >&2
            exit 1
            ;;
    esac
}

scs_region_for_o11y_realm() {
    case "$(normalize_o11y_realm "${1:-}")" in
        eu0) printf '%s' "dub10" ;;
        eu1) printf '%s' "fra10" ;;
        eu2) printf '%s' "lon10" ;;
        us0) printf '%s' "iad10" ;;
        us1|us3) printf '%s' "pdx10" ;;
        jp0) printf '%s' "tyo10" ;;
        au0) printf '%s' "syd10" ;;
        sg0) printf '%s' "sin10" ;;
        *) return 1 ;;
    esac
}

normalize_scs_region() {
    local value
    value="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
    value="${value#region-}"
    if [[ ! "${value}" =~ ^[a-z]{3}[0-9]{2}$ ]]; then
        log "ERROR: --scs-region must be an SCS region value such as pdx10, dub10, or fra10." >&2
        exit 1
    fi
    printf '%s' "${value}"
}

derive_scs_gateway_url() {
    local region
    region="$(normalize_scs_region "${1:-}")"
    printf 'https://region-%s.api.scs.splunk.com/system/mcp-gateway/v1/' "${region}"
}

resolve_scs_gateway_url() {
    local realm="${1:-}" region="${2:-}" expected_region=""

    if [[ -n "${realm}" ]]; then
        realm="$(normalize_o11y_realm "${realm}")"
        validate_o11y_realm_for_gateway "${realm}"
        if expected_region="$(scs_region_for_o11y_realm "${realm}")"; then
            :
        else
            expected_region=""
        fi
    fi

    if [[ -n "${GATEWAY_URL}" ]]; then
        printf '%s' "${GATEWAY_URL}"
        return 0
    fi

    if [[ -n "${region}" ]]; then
        region="$(normalize_scs_region "${region}")"
        if [[ -n "${expected_region}" && "${region}" != "${expected_region}" ]]; then
            log "ERROR: --scs-region ${region} does not match o11y realm ${realm}; expected ${expected_region}." >&2
            exit 1
        fi
    elif [[ -n "${expected_region}" ]]; then
        region="${expected_region}"
    fi

    if [[ -z "${region}" ]]; then
        log "ERROR: --gateway-mode ${GATEWAY_MODE} requires --scs-region or --gateway-url." >&2
        exit 1
    fi

    SCS_REGION="${region}"
    derive_scs_gateway_url "${region}"
}

apply_gateway_defaults_from_env() {
    O11Y_REALM="${O11Y_REALM:-${SPLUNK_O11Y_REALM:-}}"
    O11Y_TOKEN_FILE="${O11Y_TOKEN_FILE:-${SPLUNK_O11Y_TOKEN_FILE:-}}"
    SCS_REGION="${SCS_REGION:-${SPLUNK_MCP_SCS_REGION:-}}"
    GATEWAY_URL="${GATEWAY_URL:-${SPLUNK_MCP_GATEWAY_URL:-}}"
    SPLUNK_TENANT="${SPLUNK_TENANT:-${SPLUNK_MCP_SPLUNK_TENANT:-}}"
    SPLUNK_JWT_FILE="${SPLUNK_JWT_FILE:-${SPLUNK_MCP_SPLUNK_JWT_FILE:-}}"
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

ensure_expected_installed_app_version() {
    local installed_version expected_mcp_url
    [[ -n "${SK}" ]] || ensure_session
    ensure_app_installed
    installed_version="$(rest_get_app_version "${SK}" "${SPLUNK_URI}" "${APP_NAME}")"
    if [[ "${installed_version}" != "${EXPECTED_APP_VERSION}" ]]; then
        log "ERROR: Installed ${APP_NAME} version ${installed_version:-unknown} does not match the reviewed version ${EXPECTED_APP_VERSION}."
        log "       Install the reviewed package first, or use --accept-nonproduction-package only for isolated evaluation."
        exit 1
    fi

    if [[ "${RENDER_CLIENTS}" == "true" && "${GATEWAY_MODE}" == "platform" && -n "${MCP_URL}" ]]; then
        expected_mcp_url="$(derive_mcp_url "${SPLUNK_URI}")" || {
            log "ERROR: Could not derive the reviewed MCP endpoint from ${SPLUNK_URI}."
            exit 1
        }
        python3 - "${MCP_URL}" "${expected_mcp_url}" <<'PY' || {
from urllib.parse import urlsplit
import sys

def endpoint(value):
    parts = urlsplit(value)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return (
        parts.scheme.lower(),
        (parts.hostname or "").lower(),
        port,
        parts.path.rstrip("/"),
        parts.query,
    )

if endpoint(sys.argv[1]) != endpoint(sys.argv[2]):
    raise SystemExit(1)
PY
            log "ERROR: --mcp-url does not identify the same reviewed Splunk endpoint as SPLUNK_URI."
            log "       Use matching Splunk credentials or --accept-nonproduction-package only for isolated evaluation."
            exit 1
        }
    fi
}

install_or_update_app() {
    local update_flag="--no-update" actual_sha package_version

    if [[ -L "${PACKAGE_FILE}" || ! -f "${PACKAGE_FILE}" ]]; then
        log "ERROR: Package file not found: ${PACKAGE_FILE}"
        exit 1
    fi

    if [[ "${PACKAGE_PRODUCTION_APPROVED}" != "true" ]]; then
        if [[ "${ACCEPT_NONPRODUCTION_PACKAGE}" != "true" ]]; then
            log "ERROR: ${APP_NAME} ${EXPECTED_APP_VERSION} is not production-approved by this repository review."
            log "       review_status=${PACKAGE_REVIEW_STATUS}"
            log "       Wait for a reviewed vendor fix. For isolated evaluation only, pass --accept-nonproduction-package."
            exit 1
        fi
    fi

    actual_sha="$(python3 - "${PACKAGE_FILE}" <<'PY'
import hashlib
import sys

digest = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest(), end="")
PY
)"
    if [[ "${actual_sha}" != "${DEFAULT_PACKAGE_SHA256}" ]]; then
        log "ERROR: Package checksum mismatch for ${PACKAGE_FILE}."
        log "       expected=${DEFAULT_PACKAGE_SHA256}"
        log "       actual=${actual_sha}"
        exit 1
    fi
    package_version="$(python3 - "${PACKAGE_FILE}" <<'PY'
import configparser
import io
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:*") as archive:
    member = archive.getmember("Splunk_MCP_Server/default/app.conf")
    handle = archive.extractfile(member)
    if handle is None:
        raise SystemExit("ERROR: package does not contain default/app.conf")
    parser = configparser.ConfigParser()
    parser.read_file(io.TextIOWrapper(handle, encoding="utf-8"))
id_version = parser.get("id", "version")
launcher_version = parser.get("launcher", "version")
if id_version != launcher_version:
    raise SystemExit(
        f"ERROR: package version metadata disagrees: id={id_version}, launcher={launcher_version}"
    )
print(launcher_version, end="")
PY
)" || exit 1
    if [[ "${package_version}" != "${EXPECTED_APP_VERSION}" ]]; then
        log "ERROR: Expected ${APP_NAME} ${EXPECTED_APP_VERSION}, found ${package_version:-unknown}."
        exit 1
    fi
    log "Verified ${APP_NAME} ${package_version} package (sha256=${actual_sha})."

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
        deployment_set_app_visible "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "true" >/dev/null 2>&1 || {
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
    local url body_form resp http_code body token

    if [[ -z "${TOKEN_USER}" ]]; then
        log "ERROR: --token-user is required with --write-token-file."
        exit 1
    fi

    # Send the username/expiry/not_before fields in the POST body (form-urlencoded)
    # rather than as URL query parameters so they do not appear in proxy/web/access
    # logs that record full request URLs.
    url="${SPLUNK_URI}/servicesNS/nobody/${APP_NAME}/mcp_token?output_mode=json"
    if [[ -n "${TOKEN_NOT_BEFORE}" ]]; then
        body_form="$(form_urlencode_pairs username "${TOKEN_USER}" expires_on "${TOKEN_EXPIRES_ON}" not_before "${TOKEN_NOT_BEFORE}")" || {
            log "ERROR: Failed to encode token mint payload."
            exit 1
        }
    else
        body_form="$(form_urlencode_pairs username "${TOKEN_USER}" expires_on "${TOKEN_EXPIRES_ON}")" || {
            log "ERROR: Failed to encode token mint payload."
            exit 1
        }
    fi

    resp="$(splunk_curl_post "${SK}" "${body_form}" "${url}" -X POST -w '\n%{http_code}' 2>/dev/null || true)"
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
    local token_source token_value token_value_quoted mcp_url mcp_url_quoted env_example env_live cursor_json wrapper_script js_wrapper_script codex_script output_abs cursor_name default_server_name_quoted
    local gateway_mode gateway_mode_quoted o11y_realm o11y_realm_quoted o11y_token_source o11y_token_value o11y_token_value_quoted
    local splunk_jwt_source splunk_jwt_value splunk_auth_header splunk_auth_header_quoted splunk_tenant_quoted has_secret_source

    if [[ -z "${OUTPUT_DIR}" ]]; then
        OUTPUT_DIR="${PROJECT_ROOT}/${DEFAULT_OUTPUT_DIR_NAME}"
    fi

    apply_gateway_defaults_from_env
    gateway_mode="$(normalize_gateway_mode "${GATEWAY_MODE}")"
    GATEWAY_MODE="${gateway_mode}"

    if [[ -n "${WRITE_TOKEN_FILE}" && -z "${BEARER_TOKEN_FILE}" && "${gateway_mode}" == "platform" ]]; then
        BEARER_TOKEN_FILE="${WRITE_TOKEN_FILE}"
    fi

    if [[ -n "${WRITE_TOKEN_FILE}" && -z "${SPLUNK_JWT_FILE}" && "${gateway_mode}" == "combined" ]]; then
        SPLUNK_JWT_FILE="${WRITE_TOKEN_FILE}"
    fi

    token_source=""
    o11y_realm=""
    o11y_token_source=""
    splunk_jwt_source=""
    has_secret_source=false

    case "${gateway_mode}" in
        platform)
            if [[ "${GATEWAY_URL_SET}" == "true" || "${SCS_REGION_SET}" == "true" ]]; then
                log "ERROR: --gateway-url and --scs-region are only valid with --gateway-mode o11y or combined."
                exit 1
            fi
            token_source="${BEARER_TOKEN_FILE}"
            [[ -z "${token_source}" ]] || assert_secret_source_file "${token_source}" "Bearer token file"
            if [[ -n "${MCP_URL}" ]]; then
                mcp_url="${MCP_URL}"
            else
                mcp_url="$(derive_mcp_url "${SPLUNK_URI}")" || {
                    log "ERROR: Could not derive the MCP URL from ${SPLUNK_URI}."
                    exit 1
                }
            fi
            ;;
        o11y)
            if [[ -n "${MCP_URL}" ]]; then
                log "ERROR: --mcp-url is for platform mode. Use --gateway-url or --scs-region with --gateway-mode o11y."
                exit 1
            fi
            o11y_realm="$(normalize_o11y_realm "${O11Y_REALM}")"
            if [[ -z "${o11y_realm}" ]]; then
                log "ERROR: --gateway-mode o11y requires --o11y-realm or SPLUNK_O11Y_REALM."
                exit 1
            fi
            if [[ -z "${O11Y_TOKEN_FILE}" ]]; then
                log "ERROR: --gateway-mode o11y requires --o11y-token-file or SPLUNK_O11Y_TOKEN_FILE."
                exit 1
            fi
            o11y_token_source="${O11Y_TOKEN_FILE}"
            assert_secret_source_file "${o11y_token_source}" "Observability token file"
            mcp_url="$(resolve_scs_gateway_url "${o11y_realm}" "${SCS_REGION}")"
            ;;
        combined)
            if [[ -n "${MCP_URL}" ]]; then
                log "ERROR: --mcp-url is for platform mode. Use --gateway-url or --scs-region with --gateway-mode combined."
                exit 1
            fi
            o11y_realm="$(normalize_o11y_realm "${O11Y_REALM}")"
            if [[ -z "${o11y_realm}" ]]; then
                log "ERROR: --gateway-mode combined requires --o11y-realm or SPLUNK_O11Y_REALM."
                exit 1
            fi
            if [[ -z "${O11Y_TOKEN_FILE}" ]]; then
                log "ERROR: --gateway-mode combined requires --o11y-token-file or SPLUNK_O11Y_TOKEN_FILE."
                exit 1
            fi
            if [[ -z "${SPLUNK_TENANT}" ]]; then
                log "ERROR: --gateway-mode combined requires --splunk-tenant or SPLUNK_MCP_SPLUNK_TENANT."
                exit 1
            fi
            if [[ -z "${SPLUNK_JWT_FILE}" ]]; then
                log "ERROR: --gateway-mode combined requires --splunk-jwt-file or SPLUNK_MCP_SPLUNK_JWT_FILE."
                exit 1
            fi
            o11y_token_source="${O11Y_TOKEN_FILE}"
            splunk_jwt_source="${SPLUNK_JWT_FILE}"
            assert_secret_source_file "${o11y_token_source}" "Observability token file"
            assert_secret_source_file "${splunk_jwt_source}" "Splunk Platform authorization token file"
            mcp_url="$(resolve_scs_gateway_url "${o11y_realm}" "${SCS_REGION}")"
            ;;
    esac

    [[ -z "${o11y_realm}" ]] || validate_header_value "${o11y_realm}" "Observability realm"
    [[ -z "${SPLUNK_TENANT}" ]] || validate_header_value "${SPLUNK_TENANT}" "Splunk tenant"
    validate_client_url "${mcp_url}" "true" "${CLIENT_INSECURE_TLS}" || exit 1

    if [[ -n "${token_source}" || -n "${o11y_token_source}" || -n "${splunk_jwt_source}" ]]; then
        has_secret_source=true
    fi
    if [[ "${has_secret_source}" == "true" ]]; then
        validate_secret_render_target "secrets"
    fi

    mkdir -p "${OUTPUT_DIR}/.cursor"
    output_abs="$(resolve_abs_path "${OUTPUT_DIR}")"
    cursor_name="${CLIENT_NAME}"
    mcp_url_quoted="$(shell_quote "${mcp_url}")"
    gateway_mode_quoted="$(shell_quote "${gateway_mode}")"
    default_server_name_quoted="$(shell_quote "${CLIENT_NAME}")"

    cursor_json="$(
        python3 - "${cursor_name}" <<'PY'
import json
import sys

payload = {
    "mcpServers": {
        sys.argv[1]: {
            "type": "stdio",
            "command": "node",
            "args": ["${workspaceFolder}/run-splunk-mcp.js"],
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

if [[ -f "${ENV_FILE}" ]]; then
  while IFS= read -r -d '' env_key && IFS= read -r -d '' env_value; do
    case "${env_key}" in
      SPLUNK_MCP_URL|SPLUNK_MCP_GATEWAY_MODE|SPLUNK_MCP_INSECURE_TLS|SPLUNK_MCP_TOKEN|SPLUNK_MCP_HEADER_AUTHORIZATION|SPLUNK_MCP_HEADER_SPLUNK_TENANT|SPLUNK_MCP_HEADER_X_SF_TOKEN|SPLUNK_MCP_HEADER_X_SF_REALM) ;;
      __SPLUNK_MCP_ENV_ERROR__)
        echo "splunk-mcp: invalid ${ENV_FILE}: ${env_value}" >&2
        exit 1
        ;;
      *)
        echo "splunk-mcp: unsupported key in ${ENV_FILE}: ${env_key}" >&2
        exit 1
        ;;
    esac
    if [[ -z "${!env_key+x}" ]]; then
      printf -v "${env_key}" '%s' "${env_value}"
      export "${env_key}"
    fi
  done < <(node - "${ENV_FILE}" <<'ENVNODE'
const fs = require("fs");

function emit(key, value) {
  process.stdout.write(key + "\0" + value + "\0");
}

function parseShellWord(value) {
  let result = "";
  let state = "normal";
  for (let i = 0; i < value.length; i++) {
    const ch = value[i];
    if (state === "single") {
      if (ch === "'") state = "normal";
      else result += ch;
      continue;
    }
    if (state === "double") {
      if (ch === '"') state = "normal";
      else if (ch === "\\") {
        i += 1;
        if (i < value.length) result += value[i];
      } else result += ch;
      continue;
    }
    if (state === "ansi") {
      if (ch === "'") state = "normal";
      else if (ch === "\\") {
        i += 1;
        const next = value[i];
        if (next === "n") result += "\n";
        else if (next === "r") result += "\r";
        else if (next === "t") result += "\t";
        else if (next !== undefined) result += next;
      } else result += ch;
      continue;
    }
    if (ch === "'") state = "single";
    else if (ch === '"') state = "double";
    else if (ch === "$" && value[i + 1] === "'") { state = "ansi"; i += 1; }
    else if (ch === "\\") { i += 1; if (i < value.length) result += value[i]; }
    else result += ch;
  }
  if (state !== "normal") throw new Error("unterminated quoted value");
  return result;
}

try {
  const lines = fs.readFileSync(process.argv[2], "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq < 1) throw new Error("expected KEY=VALUE");
    emit(trimmed.slice(0, eq).trim(), parseShellWord(trimmed.slice(eq + 1).trim()));
  }
} catch (error) {
  emit("__SPLUNK_MCP_ENV_ERROR__", error.message);
}
ENVNODE
  )
fi

if [[ -z "${SPLUNK_MCP_URL:-}" ]]; then
  echo "splunk-mcp: set SPLUNK_MCP_URL in ${ENV_FILE}" >&2
  exit 1
fi

node - "${SPLUNK_MCP_URL}" "${SPLUNK_MCP_INSECURE_TLS:-}" <<'NODE'
const raw = process.argv[2];
const insecure = process.argv[3] === "1";
const net = require("net");
let parsed;
if (/[\u0000-\u001F\u007F]/.test(raw)) {
  process.stderr.write("splunk-mcp: SPLUNK_MCP_URL contains control characters\n");
  process.exit(1);
}
try { parsed = new URL(raw); } catch (_) {
  process.stderr.write("splunk-mcp: SPLUNK_MCP_URL must be an absolute HTTPS URL\n");
  process.exit(1);
}
const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
const loopback = host === "localhost" ||
  (net.isIP(host) === 4 && host.startsWith("127.")) ||
  host === "::1" || host === "0:0:0:0:0:0:0:1";
if (parsed.username || parsed.password || !parsed.hostname || parsed.hash) {
  process.stderr.write("splunk-mcp: SPLUNK_MCP_URL must include a host and must not contain userinfo\n");
  process.exit(1);
}
if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) {
  process.stderr.write("splunk-mcp: SPLUNK_MCP_URL must use HTTPS; HTTP is allowed only for loopback\n");
  process.exit(1);
}
if (insecure && !loopback) {
  process.stderr.write("splunk-mcp: SPLUNK_MCP_INSECURE_TLS=1 is restricted to loopback\n");
  process.exit(1);
}
NODE

SPLUNK_MCP_GATEWAY_MODE="${SPLUNK_MCP_GATEWAY_MODE:-platform}"
case "${SPLUNK_MCP_GATEWAY_MODE}" in
  platform|o11y|combined) ;;
  *)
    echo "splunk-mcp: SPLUNK_MCP_GATEWAY_MODE must be platform, o11y, or combined" >&2
    exit 1
    ;;
esac

case "${SPLUNK_MCP_GATEWAY_MODE}" in
  platform)
    if [[ -z "${SPLUNK_MCP_TOKEN:-}" && -z "${SPLUNK_MCP_HEADER_AUTHORIZATION:-}" ]]; then
      echo "splunk-mcp: set SPLUNK_MCP_TOKEN or SPLUNK_MCP_HEADER_AUTHORIZATION in ${ENV_FILE}" >&2
      exit 1
    fi
    ;;
  o11y)
    if [[ -z "${SPLUNK_MCP_HEADER_X_SF_TOKEN:-}" || -z "${SPLUNK_MCP_HEADER_X_SF_REALM:-}" ]]; then
      echo "splunk-mcp: set SPLUNK_MCP_HEADER_X_SF_TOKEN and SPLUNK_MCP_HEADER_X_SF_REALM in ${ENV_FILE}" >&2
      exit 1
    fi
    ;;
  combined)
    if [[ -z "${SPLUNK_MCP_TOKEN:-}" && -z "${SPLUNK_MCP_HEADER_AUTHORIZATION:-}" ]]; then
      echo "splunk-mcp: set SPLUNK_MCP_HEADER_AUTHORIZATION or SPLUNK_MCP_TOKEN in ${ENV_FILE}" >&2
      exit 1
    fi
    if [[ -z "${SPLUNK_MCP_HEADER_SPLUNK_TENANT:-}" || -z "${SPLUNK_MCP_HEADER_X_SF_TOKEN:-}" || -z "${SPLUNK_MCP_HEADER_X_SF_REALM:-}" ]]; then
      echo "splunk-mcp: set SPLUNK_MCP_HEADER_SPLUNK_TENANT, SPLUNK_MCP_HEADER_X_SF_TOKEN, and SPLUNK_MCP_HEADER_X_SF_REALM in ${ENV_FILE}" >&2
      exit 1
    fi
    ;;
esac

for header_name in SPLUNK_MCP_TOKEN SPLUNK_MCP_HEADER_AUTHORIZATION SPLUNK_MCP_HEADER_SPLUNK_TENANT SPLUNK_MCP_HEADER_X_SF_TOKEN SPLUNK_MCP_HEADER_X_SF_REALM; do
  header_value="${!header_name-}"
  if [[ "${header_value}" == *$'\n'* || "${header_value}" == *$'\r'* || ${#header_value} -gt 65536 ]]; then
    echo "splunk-mcp: ${header_name} contains a forbidden line break or exceeds 65536 characters" >&2
    exit 1
  fi
done

if [[ "${SPLUNK_MCP_INSECURE_TLS:-}" == "1" ]]; then
  export NODE_TLS_REJECT_UNAUTHORIZED=0
fi

if ! command -v mcp-remote >/dev/null 2>&1; then
  echo "splunk-mcp: install the vetted bridge: npm install -g mcp-remote@0.1.38" >&2
  exit 1
fi

if ! node - "$(command -v mcp-remote)" <<'NODE'
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
let current = path.dirname(fs.realpathSync(process.argv[2]));
let metadata = null;
while (true) {
  const candidate = path.join(current, "package.json");
  if (fs.existsSync(candidate)) {
    try {
      const value = JSON.parse(fs.readFileSync(candidate, "utf8"));
      if (value.name === "mcp-remote") { metadata = value; break; }
    } catch (_) {}
  }
  const parent = path.dirname(current);
  if (parent === current) break;
  current = parent;
}
if (!metadata && process.platform === "win32") {
  try {
    const npmRoot = execFileSync("npm.cmd", ["root", "-g"], {
      encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    const expectedShimDir = path.dirname(npmRoot).toLowerCase();
    if (path.dirname(path.resolve(process.argv[2])).toLowerCase() === expectedShimDir) {
      metadata = JSON.parse(fs.readFileSync(path.join(npmRoot, "mcp-remote", "package.json"), "utf8"));
    }
  } catch (_) {}
}
if (!metadata || metadata.name !== "mcp-remote" || metadata.version !== "0.1.38") process.exit(1);
NODE
then
  echo "splunk-mcp: mcp-remote 0.1.38 is required; install it with: npm install -g mcp-remote@0.1.38" >&2
  exit 1
fi

# Single-quote the header placeholders so bash does NOT expand secrets here.
# mcp-remote performs ${VAR} substitution on --header values at runtime
# using the inherited environment, which keeps token values out of argv.
remote_args=("${SPLUNK_MCP_URL}")
if [[ "${SPLUNK_MCP_GATEWAY_MODE}" != "platform" ]]; then
  remote_args+=(--transport http-only --allow-http)
fi
header_args=()
if [[ -n "${SPLUNK_MCP_HEADER_AUTHORIZATION:-}" ]]; then
  header_args+=(--header 'Authorization: ${SPLUNK_MCP_HEADER_AUTHORIZATION}')
elif [[ -n "${SPLUNK_MCP_TOKEN:-}" ]]; then
  header_args+=(--header 'Authorization: Bearer ${SPLUNK_MCP_TOKEN}')
fi
if [[ -n "${SPLUNK_MCP_HEADER_SPLUNK_TENANT:-}" ]]; then
  header_args+=(--header 'splunk_tenant: ${SPLUNK_MCP_HEADER_SPLUNK_TENANT}')
fi
if [[ -n "${SPLUNK_MCP_HEADER_X_SF_TOKEN:-}" ]]; then
  header_args+=(--header 'X-SF-TOKEN: ${SPLUNK_MCP_HEADER_X_SF_TOKEN}')
fi
if [[ -n "${SPLUNK_MCP_HEADER_X_SF_REALM:-}" ]]; then
  header_args+=(--header 'X-SF-REALM: ${SPLUNK_MCP_HEADER_X_SF_REALM}')
fi

exec mcp-remote "${remote_args[@]}" "${header_args[@]}"
EOF
)"

    js_wrapper_script="$(cat <<'JSEOF'
#!/usr/bin/env node
"use strict";

// Cross-platform MCP bridge for Splunk MCP Server.
// Works on macOS, Linux, and Windows (Git Bash, native cmd/PowerShell).
// Requires: Node.js and a preinstalled, operator-vetted mcp-remote 0.1.38.

const fs = require("fs");
const net = require("net");
const path = require("path");
const { execFileSync, spawn } = require("child_process");

const scriptDir = __dirname;
const envFile = path.join(scriptDir, ".env.splunk-mcp");
const allowedEnvKeys = new Set([
  "SPLUNK_MCP_URL",
  "SPLUNK_MCP_GATEWAY_MODE",
  "SPLUNK_MCP_INSECURE_TLS",
  "SPLUNK_MCP_TOKEN",
  "SPLUNK_MCP_HEADER_AUTHORIZATION",
  "SPLUNK_MCP_HEADER_SPLUNK_TENANT",
  "SPLUNK_MCP_HEADER_X_SF_TOKEN",
  "SPLUNK_MCP_HEADER_X_SF_REALM",
]);

// Load .env.splunk-mcp if present (KEY=VALUE lines, no export, no quoting needed).
function parseShellWord(value) {
  let result = "";
  let state = "normal";
  for (let i = 0; i < value.length; i++) {
    const ch = value[i];
    if (state === "single") {
      if (ch === "'") {
        state = "normal";
      } else {
        result += ch;
      }
      continue;
    }
    if (state === "double") {
      if (ch === '"') {
        state = "normal";
      } else if (ch === "\\") {
        i += 1;
        if (i < value.length) result += value[i];
      } else {
        result += ch;
      }
      continue;
    }
    if (state === "ansi") {
      if (ch === "'") {
        state = "normal";
      } else if (ch === "\\") {
        i += 1;
        const next = value[i];
        if (next === "n") result += "\n";
        else if (next === "r") result += "\r";
        else if (next === "t") result += "\t";
        else if (next !== undefined) result += next;
      } else {
        result += ch;
      }
      continue;
    }
    if (ch === "'") {
      state = "single";
    } else if (ch === '"') {
      state = "double";
    } else if (ch === "$" && value[i + 1] === "'") {
      state = "ansi";
      i += 1;
    } else if (ch === "\\") {
      i += 1;
      if (i < value.length) result += value[i];
    } else {
      result += ch;
    }
  }
  if (state !== "normal") throw new Error("unterminated quoted value");
  return result;
}

function loadEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    if (!allowedEnvKeys.has(key)) {
      process.stderr.write("splunk-mcp: unsupported key in " + filePath + ": " + key + "\n");
      process.exit(1);
    }
    let val;
    try {
      val = parseShellWord(trimmed.slice(eq + 1).trim());
    } catch (error) {
      process.stderr.write("splunk-mcp: invalid value in " + filePath + " for " + key + ": " + error.message + "\n");
      process.exit(1);
    }
    // Pre-existing env vars take precedence.
    if (!(key in process.env)) {
      process.env[key] = val;
    }
  }
}

loadEnvFile(envFile);

const mcpUrl = process.env.SPLUNK_MCP_URL;
const gatewayMode = process.env.SPLUNK_MCP_GATEWAY_MODE || "platform";

if (!mcpUrl) {
  process.stderr.write("splunk-mcp: set SPLUNK_MCP_URL in " + envFile + "\n");
  process.exit(1);
}

function hasEnv(name) {
  return Boolean(process.env[name]);
}

function fail(message) {
  process.stderr.write("splunk-mcp: " + message + "\n");
  process.exit(1);
}

function validateRuntimeUrl(rawUrl) {
  let parsed;
  if (/[\u0000-\u001F\u007F]/.test(rawUrl)) {
    fail("SPLUNK_MCP_URL contains control characters");
  }
  try {
    parsed = new URL(rawUrl);
  } catch (_) {
    fail("SPLUNK_MCP_URL must be an absolute HTTPS URL");
  }
  if (parsed.username || parsed.password || !parsed.hostname || parsed.hash) {
    fail("SPLUNK_MCP_URL must include a host and must not contain userinfo");
  }
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  const loopback = host === "localhost" ||
    (net.isIP(host) === 4 && host.startsWith("127.")) ||
    host === "::1" || host === "0:0:0:0:0:0:0:1";
  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && loopback)) {
    fail("SPLUNK_MCP_URL must use HTTPS; HTTP is allowed only for loopback");
  }
  if (process.env.SPLUNK_MCP_INSECURE_TLS === "1" && !loopback) {
    fail("SPLUNK_MCP_INSECURE_TLS=1 is restricted to loopback; configure a trusted CA for remote endpoints");
  }
}

validateRuntimeUrl(mcpUrl);

for (const name of [
  "SPLUNK_MCP_TOKEN",
  "SPLUNK_MCP_HEADER_AUTHORIZATION",
  "SPLUNK_MCP_HEADER_SPLUNK_TENANT",
  "SPLUNK_MCP_HEADER_X_SF_TOKEN",
  "SPLUNK_MCP_HEADER_X_SF_REALM",
]) {
  const value = process.env[name];
  if (value && (/\r|\n/.test(value) || value.length > 65536)) {
    fail(name + " contains a forbidden line break or exceeds 65536 characters");
  }
}

if (!["platform", "o11y", "combined"].includes(gatewayMode)) {
  fail("SPLUNK_MCP_GATEWAY_MODE must be platform, o11y, or combined");
}

if (gatewayMode === "platform") {
  if (!hasEnv("SPLUNK_MCP_TOKEN") && !hasEnv("SPLUNK_MCP_HEADER_AUTHORIZATION")) {
    fail("set SPLUNK_MCP_TOKEN or SPLUNK_MCP_HEADER_AUTHORIZATION in " + envFile);
  }
} else if (gatewayMode === "o11y") {
  if (!hasEnv("SPLUNK_MCP_HEADER_X_SF_TOKEN") || !hasEnv("SPLUNK_MCP_HEADER_X_SF_REALM")) {
    fail("set SPLUNK_MCP_HEADER_X_SF_TOKEN and SPLUNK_MCP_HEADER_X_SF_REALM in " + envFile);
  }
} else if (gatewayMode === "combined") {
  if (!hasEnv("SPLUNK_MCP_HEADER_AUTHORIZATION") && !hasEnv("SPLUNK_MCP_TOKEN")) {
    fail("set SPLUNK_MCP_HEADER_AUTHORIZATION or SPLUNK_MCP_TOKEN in " + envFile);
  }
  if (!hasEnv("SPLUNK_MCP_HEADER_SPLUNK_TENANT") || !hasEnv("SPLUNK_MCP_HEADER_X_SF_TOKEN") || !hasEnv("SPLUNK_MCP_HEADER_X_SF_REALM")) {
    fail("set SPLUNK_MCP_HEADER_SPLUNK_TENANT, SPLUNK_MCP_HEADER_X_SF_TOKEN, and SPLUNK_MCP_HEADER_X_SF_REALM in " + envFile);
  }
}

if (process.env.SPLUNK_MCP_INSECURE_TLS === "1") {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
}

// Resolve a preinstalled, operator-vetted mcp-remote. Never download and
// execute a mutable npm package during MCP startup.
function findMcpRemote() {
  try {
    // On Windows `where`, on Unix `which` -- execFileSync with a
    // try/catch is cross-platform without requiring a shell.
    const result = execFileSync(
      process.platform === "win32" ? "where" : "which",
      ["mcp-remote"],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }
    ).trim().split(/\r?\n/)[0].trim();
    if (result) return { cmd: result, args: [] };
  } catch (_) {
    // not found on PATH
  }
  fail("mcp-remote not found on PATH; install the vetted version with: npm install -g mcp-remote@0.1.38");
}

function readPackageMetadata(filePath) {
  let current = path.dirname(fs.realpathSync(filePath));
  while (true) {
    const candidate = path.join(current, "package.json");
    if (fs.existsSync(candidate)) {
      try {
        const metadata = JSON.parse(fs.readFileSync(candidate, "utf8"));
        if (metadata.name === "mcp-remote") return metadata;
      } catch (_) {
        // Keep walking; a parent package.json may be the package root.
      }
    }
    const parent = path.dirname(current);
    if (parent === current) break;
    current = parent;
  }
  if (process.platform !== "win32") return null;
  try {
    const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
    const npmRoot = execFileSync(npmCommand, ["root", "-g"], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    const expectedShimDir = path.dirname(npmRoot).toLowerCase();
    if (path.dirname(path.resolve(filePath)).toLowerCase() !== expectedShimDir) return null;
    return JSON.parse(fs.readFileSync(path.join(npmRoot, "mcp-remote", "package.json"), "utf8"));
  } catch (_) {
    return null;
  }
}

const { cmd, args: prefixArgs } = findMcpRemote();
const mcpRemotePackage = readPackageMetadata(cmd);
if (!mcpRemotePackage || mcpRemotePackage.name !== "mcp-remote" || mcpRemotePackage.version !== "0.1.38") {
  fail("mcp-remote 0.1.38 is required; install it with: npm install -g mcp-remote@0.1.38");
}
// Pass literal placeholders so mcp-remote performs ${VAR} substitution
// at runtime against the inherited env. This keeps secret header values out
// of argv (visible to process listings).
const headerArgs = [];
const remoteArgs = [mcpUrl];
if (gatewayMode !== "platform") {
  remoteArgs.push("--transport", "http-only", "--allow-http");
}
function addHeader(name, placeholder) {
  headerArgs.push("--header", name + ": " + placeholder);
}
if (hasEnv("SPLUNK_MCP_HEADER_AUTHORIZATION")) {
  addHeader("Authorization", "${SPLUNK_MCP_HEADER_AUTHORIZATION}");
} else if (hasEnv("SPLUNK_MCP_TOKEN")) {
  addHeader("Authorization", "Bearer ${SPLUNK_MCP_TOKEN}");
}
if (hasEnv("SPLUNK_MCP_HEADER_SPLUNK_TENANT")) {
  addHeader("splunk_tenant", "${SPLUNK_MCP_HEADER_SPLUNK_TENANT}");
}
if (hasEnv("SPLUNK_MCP_HEADER_X_SF_TOKEN")) {
  addHeader("X-SF-TOKEN", "${SPLUNK_MCP_HEADER_X_SF_TOKEN}");
}
if (hasEnv("SPLUNK_MCP_HEADER_X_SF_REALM")) {
  addHeader("X-SF-REALM", "${SPLUNK_MCP_HEADER_X_SF_REALM}");
}

const child = spawn(
  cmd,
  [...prefixArgs, ...remoteArgs, ...headerArgs],
  { stdio: "inherit" }
);

child.on("error", function(err) {
  process.stderr.write(
    "splunk-mcp: failed to start mcp-remote: " + err.message + "\n" +
    "  Install it with: npm install -g mcp-remote@0.1.38\n"
  );
  process.exit(1);
});

child.on("exit", function(code, signal) {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code !== null ? code : 0);
  }
});
JSEOF
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
cp "\${SCRIPT_DIR}/run-splunk-mcp.js" "\${CODEX_BUNDLE_DIR}/run-splunk-mcp.js"
chmod 755 "\${CODEX_BUNDLE_DIR}/run-splunk-mcp.js"

if [[ -f "\${SCRIPT_DIR}/.env.splunk-mcp" ]]; then
  cp "\${SCRIPT_DIR}/.env.splunk-mcp" "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp"
  chmod 600 "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp"
fi

if [[ -f "\${SCRIPT_DIR}/.env.splunk-mcp.example" ]]; then
  cp "\${SCRIPT_DIR}/.env.splunk-mcp.example" "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp.example"
  chmod 644 "\${CODEX_BUNDLE_DIR}/.env.splunk-mcp.example"
fi

exec codex mcp add "\${SERVER_NAME}" -- node "\${CODEX_BUNDLE_DIR}/run-splunk-mcp.js"
EOF
)"

    case "${gateway_mode}" in
        platform)
            env_example="$(cat <<EOF
# Copy to .env.splunk-mcp and keep the populated file local only.
SPLUNK_MCP_GATEWAY_MODE=${gateway_mode_quoted}
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_TOKEN=''
EOF
)"
            ;;
        o11y)
            o11y_realm_quoted="$(shell_quote "${o11y_realm}")"
            env_example="$(cat <<EOF
# Copy to .env.splunk-mcp and keep the populated file local only.
SPLUNK_MCP_GATEWAY_MODE=${gateway_mode_quoted}
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_HEADER_X_SF_TOKEN=''
SPLUNK_MCP_HEADER_X_SF_REALM=${o11y_realm_quoted}
EOF
)"
            ;;
        combined)
            o11y_realm_quoted="$(shell_quote "${o11y_realm}")"
            splunk_tenant_quoted="$(shell_quote "${SPLUNK_TENANT}")"
            env_example="$(cat <<EOF
# Copy to .env.splunk-mcp and keep the populated file local only.
SPLUNK_MCP_GATEWAY_MODE=${gateway_mode_quoted}
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_HEADER_AUTHORIZATION=''
SPLUNK_MCP_HEADER_SPLUNK_TENANT=${splunk_tenant_quoted}
SPLUNK_MCP_HEADER_X_SF_TOKEN=''
SPLUNK_MCP_HEADER_X_SF_REALM=${o11y_realm_quoted}
EOF
)"
            ;;
    esac
    if [[ "${CLIENT_INSECURE_TLS}" == "true" ]]; then
        env_example="${env_example}"$'\n''SPLUNK_MCP_INSECURE_TLS=1'
    else
        env_example="${env_example}"$'\n''# SPLUNK_MCP_INSECURE_TLS=1'
    fi

    write_text_file "${OUTPUT_DIR}/.cursor/mcp.json" "${cursor_json}"
    write_text_file "${OUTPUT_DIR}/run-splunk-mcp.sh" "${wrapper_script}"
    chmod 755 "${OUTPUT_DIR}/run-splunk-mcp.sh"
    write_text_file "${OUTPUT_DIR}/run-splunk-mcp.js" "${js_wrapper_script}"$'\n'
    chmod 755 "${OUTPUT_DIR}/run-splunk-mcp.js"
    write_text_file "${OUTPUT_DIR}/register-codex-mcp.sh" "${codex_script}"
    chmod 755 "${OUTPUT_DIR}/register-codex-mcp.sh"
    write_text_file "${OUTPUT_DIR}/.env.splunk-mcp.example" "${env_example}"

    case "${gateway_mode}" in
        platform)
            if [[ -n "${token_source}" ]]; then
                token_value="$(read_secret_file "${token_source}")" || exit 1
                validate_header_value "${token_value}" "Bearer token"
                token_value_quoted="$(shell_quote "${token_value}")"
                env_live="$(cat <<EOF
SPLUNK_MCP_GATEWAY_MODE=${gateway_mode_quoted}
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_TOKEN=${token_value_quoted}
EOF
)"
            fi
            ;;
        o11y)
            o11y_token_value="$(read_secret_file "${o11y_token_source}")" || exit 1
            validate_header_value "${o11y_token_value}" "Observability token"
            o11y_token_value_quoted="$(shell_quote "${o11y_token_value}")"
            o11y_realm_quoted="$(shell_quote "${o11y_realm}")"
            env_live="$(cat <<EOF
SPLUNK_MCP_GATEWAY_MODE=${gateway_mode_quoted}
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_HEADER_X_SF_TOKEN=${o11y_token_value_quoted}
SPLUNK_MCP_HEADER_X_SF_REALM=${o11y_realm_quoted}
EOF
)"
            ;;
        combined)
            o11y_token_value="$(read_secret_file "${o11y_token_source}")" || exit 1
            splunk_jwt_value="$(read_secret_file "${splunk_jwt_source}")" || exit 1
            validate_header_value "${o11y_token_value}" "Observability token"
            validate_header_value "${splunk_jwt_value}" "Splunk authorization token"
            splunk_auth_header="Bearer ${splunk_jwt_value}"
            splunk_auth_header_quoted="$(shell_quote "${splunk_auth_header}")"
            splunk_tenant_quoted="$(shell_quote "${SPLUNK_TENANT}")"
            o11y_token_value_quoted="$(shell_quote "${o11y_token_value}")"
            o11y_realm_quoted="$(shell_quote "${o11y_realm}")"
            env_live="$(cat <<EOF
SPLUNK_MCP_GATEWAY_MODE=${gateway_mode_quoted}
SPLUNK_MCP_URL=${mcp_url_quoted}
SPLUNK_MCP_HEADER_AUTHORIZATION=${splunk_auth_header_quoted}
SPLUNK_MCP_HEADER_SPLUNK_TENANT=${splunk_tenant_quoted}
SPLUNK_MCP_HEADER_X_SF_TOKEN=${o11y_token_value_quoted}
SPLUNK_MCP_HEADER_X_SF_REALM=${o11y_realm_quoted}
EOF
)"
            ;;
    esac

    if [[ -n "${env_live:-}" ]]; then
        if [[ "${CLIENT_INSECURE_TLS}" == "true" ]]; then
            env_live="${env_live}"$'\n''SPLUNK_MCP_INSECURE_TLS=1'
        fi
        write_secret_file "${OUTPUT_DIR}/.env.splunk-mcp" "${env_live}"
    elif [[ -e "${OUTPUT_DIR}/.env.splunk-mcp" || -L "${OUTPUT_DIR}/.env.splunk-mcp" ]]; then
        rm -f -- "${OUTPUT_DIR}/.env.splunk-mcp"
        log "Removed stale live client environment because no credential source was supplied."
    fi

    log "Rendered shared Cursor/Codex/Claude Code MCP bridge bundle at ${output_abs}."
    log "Open that directory as a Cursor workspace, run ${output_abs}/register-codex-mcp.sh for Codex, or use --render-clients to auto-write Claude Code .mcp.json."
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
    # Args: config_path server_name wrapper_command [wrapper_arg]
    # When wrapper_arg is provided, wrapper_command becomes the executable (e.g. "node")
    # and wrapper_arg becomes the first element of "args" (e.g. the .js path).
    local config_path="$1" server_name="$2" wrapper_command="$3" wrapper_arg="${4:-}"
    python3 - "${config_path}" "${server_name}" "${wrapper_command}" "${wrapper_arg}" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
server_name = sys.argv[2]
wrapper_command = sys.argv[3]
wrapper_arg = sys.argv[4] if len(sys.argv) > 4 else ""

entry = {
    "type": "stdio",
    "command": wrapper_command,
    "args": [wrapper_arg] if wrapper_arg else [],
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
    local codex_bundle_dir stable_wrapper stable_js stable_env stable_env_example source_dir

    ensure_command_available "codex" "Install the Codex CLI or rerun with --no-register-codex."
    source_dir="$(dirname "${wrapper_abs}")"
    codex_bundle_dir="$(resolve_codex_bundle_dir "${CLIENT_NAME}")"
    stable_wrapper="${codex_bundle_dir}/run-splunk-mcp.sh"
    stable_js="${codex_bundle_dir}/run-splunk-mcp.js"
    stable_env="${codex_bundle_dir}/.env.splunk-mcp"
    stable_env_example="${codex_bundle_dir}/.env.splunk-mcp.example"

    mkdir -p "${codex_bundle_dir}"
    copy_file_with_mode "${wrapper_abs}" "${stable_wrapper}" 755
    copy_file_with_mode "${source_dir}/run-splunk-mcp.js" "${stable_js}" 755

    if [[ -f "${source_dir}/.env.splunk-mcp" ]]; then
        copy_file_with_mode "${source_dir}/.env.splunk-mcp" "${stable_env}" 600
    elif [[ -e "${stable_env}" || -L "${stable_env}" ]]; then
        rm -f -- "${stable_env}"
    fi
    if [[ -f "${source_dir}/.env.splunk-mcp.example" ]]; then
        copy_file_with_mode "${source_dir}/.env.splunk-mcp.example" "${stable_env_example}" 644
    fi

    set +e
    codex_output="$(codex mcp add "${CLIENT_NAME}" -- node "${stable_js}" 2>&1)"
    codex_rc=$?
    set -e

    if (( codex_rc != 0 )); then
        [[ -n "${codex_output}" ]] && printf '%s\n' "${codex_output}" >&2
        log "ERROR: Failed to register Codex MCP server '${CLIENT_NAME}'."
        exit 1
    fi

    log "Registered Codex MCP server '${CLIENT_NAME}' using portable bundle ${stable_js}."
}

write_cursor_workspace_config() {
    local workspace_dir="$1" js_arg="$2"
    local cursor_config_path="${workspace_dir}/.cursor/mcp.json"
    local cursor_json

    cursor_json="$(build_cursor_workspace_json "${cursor_config_path}" "${CLIENT_NAME}" "node" "${js_arg}")" || exit 1
    write_text_file "${cursor_config_path}" "${cursor_json}"
    log "Configured Cursor MCP server '${CLIENT_NAME}' in ${workspace_dir}."
}

write_claude_workspace_config() {
    local workspace_dir="$1" js_arg="$2"
    local claude_config_path="${workspace_dir}/.mcp.json"
    local claude_json

    claude_json="$(build_cursor_workspace_json "${claude_config_path}" "${CLIENT_NAME}" "node" "${js_arg}")" || exit 1
    write_text_file "${claude_config_path}" "${claude_json}"
    log "Configured Claude Code MCP server '${CLIENT_NAME}' in ${workspace_dir}."
}

apply_client_setup() {
    local wrapper_abs js_abs workspace_dir="" js_arg=""

    if [[ "${REGISTER_CODEX}" != "true" && "${CONFIGURE_CURSOR}" != "true" && "${CONFIGURE_CLAUDE}" != "true" ]]; then
        log "Skipped Codex, Cursor, and Claude Code auto-apply; rendered bundle only."
        return 0
    fi

    if ! command -v mcp-remote >/dev/null 2>&1; then
        log "WARNING: mcp-remote not found on PATH. Install the vetted version with: npm install -g mcp-remote@0.1.38"
        log "         The rendered bridge requires mcp-remote at runtime."
    fi
    wrapper_abs="$(resolve_abs_path "${OUTPUT_DIR}/run-splunk-mcp.sh")"
    js_abs="$(resolve_abs_path "${OUTPUT_DIR}/run-splunk-mcp.js")"

    if [[ "${CONFIGURE_CURSOR}" == "true" || "${CONFIGURE_CLAUDE}" == "true" ]]; then
        workspace_dir="$(resolve_cursor_workspace_dir)"
        js_arg="$(build_cursor_wrapper_command "${workspace_dir}" "${js_abs}")"
    fi

    if [[ "${CONFIGURE_CURSOR}" == "true" ]]; then
        # Validate and prepare any existing Cursor config before mutating Codex registration.
        build_cursor_workspace_json "${workspace_dir}/.cursor/mcp.json" "${CLIENT_NAME}" "node" "${js_arg}" >/dev/null || exit 1
    fi

    if [[ "${REGISTER_CODEX}" == "true" ]]; then
        register_codex_client "${wrapper_abs}"
    fi

    if [[ "${CONFIGURE_CURSOR}" == "true" ]]; then
        write_cursor_workspace_config "${workspace_dir}" "${js_arg}"
    fi

    if [[ "${CONFIGURE_CLAUDE}" == "true" ]]; then
        write_claude_workspace_config "${workspace_dir}" "${js_arg}"
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) DO_INSTALL=true; shift ;;
        --accept-nonproduction-package) HAS_UNINSTALL_CONFLICT=true; ACCEPT_NONPRODUCTION_PACKAGE=true; shift ;;
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
        --no-configure-claude) HAS_UNINSTALL_CONFLICT=true; CONFIGURE_CLAUDE=false; shift ;;
        --mcp-url) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; MCP_URL="$2"; shift 2 ;;
        --gateway-mode) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; GATEWAY_MODE="$2"; shift 2 ;;
        --gateway-url) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; GATEWAY_URL="$2"; GATEWAY_URL_SET=true; shift 2 ;;
        --scs-region) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; SCS_REGION="$2"; SCS_REGION_SET=true; shift 2 ;;
        --o11y-realm) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; O11Y_REALM="$2"; shift 2 ;;
        --o11y-token-file) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --splunk-tenant) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; SPLUNK_TENANT="$2"; shift 2 ;;
        --splunk-jwt-file) HAS_UNINSTALL_CONFLICT=true; require_arg "$1" $# || exit 1; SPLUNK_JWT_FILE="$2"; shift 2 ;;
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

GATEWAY_MODE="$(normalize_gateway_mode "${GATEWAY_MODE}")"

if [[ "${DO_INSTALL}" == "true" && "${DO_UNINSTALL}" == "true" ]]; then
    log "ERROR: --install and --uninstall cannot be used together."
    exit 1
fi

if [[ "${DO_UNINSTALL}" == "true" && "${HAS_UNINSTALL_CONFLICT}" == "true" ]]; then
    log "ERROR: --uninstall must be run by itself without any other action or configuration flags."
    exit 1
fi

# A deliberately accepted evaluation install should still avoid the vendor's
# permissive token and admission defaults. Explicit CLI values win.
if [[ "${DO_INSTALL}" == "true" ]]; then
    TIMEOUT="${TIMEOUT:-90}"
    MAX_ROW_LIMIT="${MAX_ROW_LIMIT:-2000}"
    DEFAULT_ROW_LIMIT="${DEFAULT_ROW_LIMIT:-250}"
    SSL_VERIFY="${SSL_VERIFY:-true}"
    REQUIRE_ENCRYPTED_TOKEN="${REQUIRE_ENCRYPTED_TOKEN:-true}"
    LEGACY_TOKEN_GRACE_DAYS="${LEGACY_TOKEN_GRACE_DAYS:-0}"
    TOKEN_DEFAULT_LIFETIME_SECONDS="${TOKEN_DEFAULT_LIFETIME_SECONDS:-43200}"
    TOKEN_MAX_LIFETIME_SECONDS="${TOKEN_MAX_LIFETIME_SECONDS:-86400}"
    TOKEN_KEY_RELOAD_INTERVAL_SECONDS="${TOKEN_KEY_RELOAD_INTERVAL_SECONDS:-300}"
    GLOBAL_RATE_LIMIT="${GLOBAL_RATE_LIMIT:-600}"
    ADMISSION_GLOBAL="${ADMISSION_GLOBAL:-60}"
    TENANT_AUTHENTICATED="${TENANT_AUTHENTICATED:-240}"
    TENANT_UNAUTHENTICATED="${TENANT_UNAUTHENTICATED:-10}"
    CIRCUIT_BREAKER_FAILURE_THRESHOLD="${CIRCUIT_BREAKER_FAILURE_THRESHOLD:-5}"
    CIRCUIT_BREAKER_COOLDOWN_SECONDS="${CIRCUIT_BREAKER_COOLDOWN_SECONDS:-60}"
fi

validate_uint_option "--timeout" "${TIMEOUT}" 1 3600
validate_uint_option "--max-row-limit" "${MAX_ROW_LIMIT}" 1 100000
validate_uint_option "--default-row-limit" "${DEFAULT_ROW_LIMIT}" 1 100000
validate_uint_option "--legacy-token-grace-days" "${LEGACY_TOKEN_GRACE_DAYS}" 0 365
validate_uint_option "--token-default-lifetime-seconds" "${TOKEN_DEFAULT_LIFETIME_SECONDS}" 1 31536000
validate_uint_option "--token-max-lifetime-seconds" "${TOKEN_MAX_LIFETIME_SECONDS}" 1 31536000
validate_uint_option "--token-key-reload-interval-seconds" "${TOKEN_KEY_RELOAD_INTERVAL_SECONDS}" 1 86400
validate_uint_option "--global-rate-limit" "${GLOBAL_RATE_LIMIT}" 0 1000000
validate_uint_option "--admission-global" "${ADMISSION_GLOBAL}" 0 1000000
validate_uint_option "--tenant-authenticated" "${TENANT_AUTHENTICATED}" 0 1000000
validate_uint_option "--tenant-unauthenticated" "${TENANT_UNAUTHENTICATED}" 0 1000000
validate_uint_option "--circuit-breaker-failure-threshold" "${CIRCUIT_BREAKER_FAILURE_THRESHOLD}" 1 1000000
validate_uint_option "--circuit-breaker-cooldown-seconds" "${CIRCUIT_BREAKER_COOLDOWN_SECONDS}" 1 86400

if [[ -n "${DEFAULT_ROW_LIMIT}" && -n "${MAX_ROW_LIMIT}" ]] \
   && (( 10#${DEFAULT_ROW_LIMIT} > 10#${MAX_ROW_LIMIT} )); then
    log "ERROR: --default-row-limit cannot exceed --max-row-limit."
    exit 1
fi
if [[ -n "${TOKEN_DEFAULT_LIFETIME_SECONDS}" && -n "${TOKEN_MAX_LIFETIME_SECONDS}" ]] \
   && (( 10#${TOKEN_DEFAULT_LIFETIME_SECONDS} > 10#${TOKEN_MAX_LIFETIME_SECONDS} )); then
    log "ERROR: --token-default-lifetime-seconds cannot exceed --token-max-lifetime-seconds."
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

if [[ "${LIVE_SPLUNK_ACTIONS}" == "false" \
   && "${RENDER_CLIENTS}" != "true" \
   && "${DO_UNINSTALL}" != "true" ]]; then
    LIVE_SPLUNK_ACTIONS=true
fi

VENDOR_PACKAGE_ACTION=false
if [[ "${DO_UNINSTALL}" != "true" \
   && ( "${LIVE_SPLUNK_ACTIONS}" == "true" \
        || ( "${RENDER_CLIENTS}" == "true" \
             && "${GATEWAY_MODE}" == "platform" \
             && ( "${REGISTER_CODEX}" == "true" \
                  || "${CONFIGURE_CURSOR}" == "true" \
                  || "${CONFIGURE_CLAUDE}" == "true" ) ) ) ]]; then
    VENDOR_PACKAGE_ACTION=true
fi

if [[ "${VENDOR_PACKAGE_ACTION}" == "true" && "${PACKAGE_PRODUCTION_APPROVED}" != "true" ]]; then
    if [[ "${ACCEPT_NONPRODUCTION_PACKAGE}" != "true" ]]; then
        log "ERROR: ${APP_NAME} ${EXPECTED_APP_VERSION} workflows are blocked by this repository's production review."
        log "       review_status=${PACKAGE_REVIEW_STATUS}"
        log "       Wait for a reviewed vendor fix. For isolated evaluation only, pass --accept-nonproduction-package."
        exit 1
    fi
    log "WARNING: Continuing a non-production-approved vendor workflow for isolated evaluation only."
elif [[ "${ACCEPT_NONPRODUCTION_PACKAGE}" == "true" && "${VENDOR_PACKAGE_ACTION}" != "true" ]]; then
    log "ERROR: --accept-nonproduction-package is valid only for local Splunk Platform package workflows."
    exit 1
fi

if [[ "${VENDOR_PACKAGE_ACTION}" == "true" \
   && "${PACKAGE_PRODUCTION_APPROVED}" == "true" \
   && "${DO_INSTALL}" != "true" \
   && "${ACCEPT_NONPRODUCTION_PACKAGE}" != "true" ]]; then
    ensure_expected_installed_app_version
fi

if [[ "${DO_UNINSTALL}" == "true" || "${LIVE_SPLUNK_ACTIONS}" == "true" ]]; then
    require_current_skill_role_supported
fi

if [[ "${DO_INSTALL}" == "true" ]]; then
    install_or_update_app
    if [[ "${PACKAGE_PRODUCTION_APPROVED}" == "true" \
       && "${ACCEPT_NONPRODUCTION_PACKAGE}" != "true" ]]; then
        # Verify what the installer actually exposed, and bind any platform
        # client activation to that same reviewed Splunk endpoint.
        ensure_expected_installed_app_version
    fi
fi

if [[ "${DO_UNINSTALL}" == "true" ]]; then
    uninstall_app
    exit 0
fi

if [[ "${LIVE_SPLUNK_ACTIONS}" == "true" ]]; then
    [[ -n "${SK}" ]] || ensure_session
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
elif [[ "${RENDER_CLIENTS}" == "true" && "${GATEWAY_MODE}" == "platform" && -z "${MCP_URL}" ]]; then
    load_splunk_credentials || {
        log "ERROR: --render-clients without --mcp-url requires Splunk credentials so the MCP URL can be derived."
        exit 1
    }
fi

if [[ "${RENDER_CLIENTS}" == "true" ]]; then
    if [[ "${GATEWAY_MODE}" != "platform" ]]; then
        NEED_O11Y_DEFAULTS=false
        if [[ -z "${O11Y_REALM}" || -z "${O11Y_TOKEN_FILE}" || ( -z "${SCS_REGION}" && -z "${GATEWAY_URL}" ) ]]; then
            NEED_O11Y_DEFAULTS=true
        fi
        if [[ "${GATEWAY_MODE}" == "combined" && ( -z "${SPLUNK_TENANT}" || -z "${SPLUNK_JWT_FILE}" ) ]]; then
            NEED_O11Y_DEFAULTS=true
        fi
        if [[ "${NEED_O11Y_DEFAULTS}" == "true" ]]; then
            load_observability_cloud_settings
            apply_gateway_defaults_from_env
        fi
    fi
    render_client_bundle
    if [[ -f "${OUTPUT_DIR}/.env.splunk-mcp" ]]; then
        apply_client_setup
    elif [[ "${REGISTER_CODEX}" == "true" || "${CONFIGURE_CURSOR}" == "true" || "${CONFIGURE_CLAUDE}" == "true" ]]; then
        log "ERROR: Refusing to register an unusable MCP bridge without a live credential environment."
        log "       Supply the required token file(s), or pass all three --no-* client flags for render-only output."
        exit 1
    fi
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
