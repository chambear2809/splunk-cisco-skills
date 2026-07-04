#!/usr/bin/env bash
# Splunk SOAR helpers (On-prem and Cloud).
# Sourced by setup/validate scripts in splunk-soar-setup.
#
# Security contract:
#   - SOAR REST tokens (`ph-auth-token`) and the admin password are read
#     through descriptor-bound private files and fed to curl via private
#     auth configs, never credential-bearing argv.
#   - Automation-token minting is acceptance-gated and journaled before POST;
#     ambiguous outcomes block retries until manual reconciliation/revocation.
#   - TLS verification is enabled by default. Operators on a private CA
#     should set SOAR_API_CA_CERT=/path/to/ca.pem; SOAR_API_INSECURE=true
#     keeps the legacy "skip verification" behavior with a one-time warning.

[[ -n "${_SOAR_HELPERS_LOADED:-}" ]] && return 0
_SOAR_HELPERS_LOADED=true

_SOAR_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${_SOAR_LIB_DIR}/credential_curl_helpers.sh"

if [[ -z "${_CRED_HELPERS_LOADED:-}" ]]; then
    # shellcheck disable=SC1091
    source "${_SOAR_LIB_DIR}/credential_helpers.sh"
fi

soar_validate_tenant_url() {
    local tenant_url="${1:-}" allow_http="${SOAR_API_ALLOW_HTTP:-false}"
    python3 - "${tenant_url}" "${allow_http}" <<'PY'
import sys
from urllib.parse import urlsplit

value = sys.argv[1].strip()
allow_http = sys.argv[2].strip().lower() in {"1", "true", "yes"}
if not value or any(ch.isspace() for ch in value):
    raise SystemExit(1)
try:
    parsed = urlsplit(value)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit(1)
host = parsed.hostname.lower()
if "<" in host or ">" in host or host == "example.com" or host.endswith(".example.com"):
    raise SystemExit(1)
if parsed.scheme == "http" and not allow_http:
    raise SystemExit(1)
if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
    raise SystemExit(1)
if port is not None and not 1 <= port <= 65535:
    raise SystemExit(1)
PY
}

soar_require_secret_file() {
    local path="${1:-}" label="${2:-SOAR secret file}" mode
    if [[ ! -f "${path}" || ! -r "${path}" || ! -s "${path}" ]]; then
        log "ERROR: ${label} must be a readable, non-empty regular file: ${path}"
        return 1
    fi
    mode="$(stat -c '%a' "${path}" 2>/dev/null || stat -f '%Lp' "${path}" 2>/dev/null || true)"
    if [[ "${mode}" != "600" ]]; then
        log "ERROR: ${label} must be chmod 600 (found ${mode:-unknown}): ${path}"
        return 1
    fi
}

_soar_curl_tls_args() {
    local insecure="${SOAR_API_INSECURE:-false}"
    local ca_cert="${SOAR_API_CA_CERT:-}"
    if [[ -n "${ca_cert}" ]]; then
        if [[ "${ca_cert}" == *$'\r'* || "${ca_cert}" == *$'\n'* || ! -s "${ca_cert}" ]]; then
            echo "ERROR: SOAR_API_CA_CERT not found or empty: ${ca_cert}" >&2
            return 1
        fi
        printf -- '--cacert\n%s\n' "${ca_cert}"
        return 0
    fi
    case "${insecure}" in
        1|true|TRUE|True|yes|YES|Yes|on|ON|On)
            if [[ -z "${_WARNED_SOAR_API_INSECURE:-}" ]]; then
                echo "WARNING: TLS verification is disabled for SOAR API calls (SOAR_API_INSECURE=true). Use SOAR_API_CA_CERT=/path/to/ca.pem for private CAs in production." >&2
                _WARNED_SOAR_API_INSECURE=1
            fi
            printf -- '-k\n'
            ;;
        *) ;;
    esac
}

# soar_rest_call <tenant_url> <token_file> <method> <path> [extra curl args...]
# Calls the SOAR REST API using a descriptor-validated private curl config so
# the ph-auth-token never appears in the curl process argv.
soar_rest_call() {
    local tenant_url="$1" token_file="$2" method="$3" path="$4"
    shift 4
    if ! soar_validate_tenant_url "${tenant_url}"; then
        log "ERROR: SOAR tenant URL must be a real credential-free HTTPS URL without whitespace, query, or fragment."
        log "       Set SOAR_API_ALLOW_HTTP=true only for an explicitly approved non-TLS lab endpoint."
        return 1
    fi
    if [[ ! "${method}" =~ ^(GET|POST|PUT|PATCH|DELETE)$ || "${path}" != /* || "${path}" == //* || \
          "${path}" == *'#'* || "${path}" == *$'\r'* || "${path}" == *$'\n'* || "${path}" == *' '* || "${path}" == *$'\t'* ]]; then
        log "ERROR: SOAR request method/path is unsafe or ambiguous."
        return 1
    fi
    local request_url="${tenant_url}${path}"
    if ! credential_curl_validate_request_args \
        "${SOAR_API_ALLOW_HTTP:-false}" "$@" "${request_url}"; then
        log "ERROR: SOAR request rejected by credential transport policy."
        return 1
    fi
    case "${tenant_url}" in
        http://*|HTTP://*|Http://*)
            if [[ -z "${_WARNED_SOAR_API_HTTP:-}" ]]; then
                log "WARNING: LAB ONLY: SOAR_API_ALLOW_HTTP=true sends SOAR credentials over plaintext HTTP."
                _WARNED_SOAR_API_HTTP=1
            fi
            ;;
    esac
    local tls_args=() tls_status=0 last_index=0
    # _soar_curl_tls_args may legitimately return 1 when SOAR_API_CA_CERT
    # points at a missing/empty file. We must NOT swallow that with `|| true`
    # because doing so would silently fall back to default curl verification
    # against a broken operator config. Capture status separately and abort.
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_soar_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]]; then
        last_index=$(( ${#tls_args[@]} - 1 ))
    fi
    if [[ "${#tls_args[@]}" -gt 0 && "${tls_args[${last_index}]}" == STATUS=* ]]; then
        tls_status="${tls_args[${last_index}]#STATUS=}"
        unset "tls_args[${last_index}]"
    fi
    if (( tls_status != 0 )); then
        log "ERROR: SOAR TLS configuration invalid (SOAR_API_CA_CERT/SOAR_API_INSECURE)."
        return 1
    fi
    local auth_config rc
    auth_config="$(mktemp)" || return 1
    chmod 600 "${auth_config}"
    credential_curl_append_cleanup_trap "rm -f $(printf '%q' "${auth_config}") 2>/dev/null || true" HUP INT TERM
    if ! credential_curl_write_header_config "${token_file}" "ph-auth-token" "${auth_config}"; then
        rm -f "${auth_config}"
        log "ERROR: SOAR API token must be a private single-link, non-symlink one-line file."
        return 1
    fi
    if curl -q -sS \
        ${tls_args[@]+"${tls_args[@]}"} \
        -X "${method}" \
        -K "${auth_config}" \
        -H "Content-Type: application/json" \
        "$@" \
        "${request_url}" \
        "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"; then
        rc=0
    else
        rc=$?
    fi
    rm -f "${auth_config}"
    return "${rc}"
}

# soar_validate_health <tenant_url> <token_file>
# Returns 0 if /rest/version returns a version string; non-zero otherwise.
soar_validate_health() {
    local tenant_url="$1" token_file="$2"
    local body
    body="$(soar_rest_call "${tenant_url}" "${token_file}" GET /rest/version 2>/dev/null || echo '{}')"
    python3 - "${body}" <<'PY'
import json, sys
try:
    data = json.loads(sys.argv[1]) if sys.argv[1].strip() else {}
except Exception:
    data = {}
ver = data.get("version", "")
if not ver:
    sys.exit(1)
print(ver)
sys.exit(0)
PY
}

# soar_install_splunk_side_apps <app_install_setup_sh> <splunkbase_id...>
# Wrapper around splunk-app-install for the Splunk-side SOAR apps.
soar_install_splunk_side_apps() {
    local app_install="$1"
    shift
    if [[ ! -x "${app_install}" ]]; then
        log "ERROR: splunk-app-install setup script missing or not executable: ${app_install}"
        return 1
    fi
    local id
    for id in "$@"; do
        bash "${app_install}" --source splunkbase --app-id "${id}" --no-update || return 1
    done
}

# _soar_admin_basic_auth_call <tenant_url> <admin_pw_file> <method> <path> [extra curl args...]
# Internal helper that POSTs/GETs against SOAR using HTTP Basic auth as the
# `soar_local_admin` user, with the password read through the shared
# descriptor-bound curl-config writer so it never lands on argv.
_soar_admin_basic_auth_call() {
    local tenant_url="$1" admin_pw_file="$2" method="$3" path="$4"
    shift 4
    if ! soar_validate_tenant_url "${tenant_url}"; then
        log "ERROR: SOAR tenant URL must be a real credential-free HTTPS URL without whitespace, query, or fragment."
        log "       Set SOAR_API_ALLOW_HTTP=true only for an explicitly approved non-TLS lab endpoint."
        return 1
    fi
    if [[ ! "${method}" =~ ^(GET|POST|PUT|PATCH|DELETE)$ || "${path}" != /* || "${path}" == //* || \
          "${path}" == *'#'* || "${path}" == *$'\r'* || "${path}" == *$'\n'* || "${path}" == *' '* || "${path}" == *$'\t'* ]]; then
        log "ERROR: SOAR admin request method/path is unsafe or ambiguous."
        return 1
    fi
    local request_url="${tenant_url}${path}"
    if ! credential_curl_validate_request_args \
        "${SOAR_API_ALLOW_HTTP:-false}" "$@" "${request_url}"; then
        log "ERROR: SOAR admin request rejected by credential transport policy."
        return 1
    fi
    case "${tenant_url}" in
        http://*|HTTP://*|Http://*)
            if [[ -z "${_WARNED_SOAR_API_HTTP:-}" ]]; then
                log "WARNING: LAB ONLY: SOAR_API_ALLOW_HTTP=true sends SOAR credentials over plaintext HTTP."
                _WARNED_SOAR_API_HTTP=1
            fi
            ;;
    esac
    local auth_config rc
    auth_config="$(mktemp)" || return 1
    chmod 600 "${auth_config}"
    credential_curl_append_cleanup_trap "rm -f $(printf '%q' "${auth_config}") 2>/dev/null || true" HUP INT TERM
    if ! credential_curl_write_user_config "${admin_pw_file}" "soar_local_admin" "${auth_config}"; then
        rm -f "${auth_config}"
        log "ERROR: SOAR admin password must be a private single-link, non-symlink one-line file."
        return 1
    fi
    local tls_args=() tls_status=0 last_index=0
    # See soar_rest_call: do not swallow _soar_curl_tls_args failures.
    {
        while IFS= read -r line; do
            [[ -n "${line}" ]] && tls_args+=("${line}")
        done
    } < <(_soar_curl_tls_args; printf 'STATUS=%d\n' "$?")
    if [[ "${#tls_args[@]}" -gt 0 ]]; then
        last_index=$(( ${#tls_args[@]} - 1 ))
    fi
    if [[ "${#tls_args[@]}" -gt 0 && "${tls_args[${last_index}]}" == STATUS=* ]]; then
        tls_status="${tls_args[${last_index}]#STATUS=}"
        unset "tls_args[${last_index}]"
    fi
    if (( tls_status != 0 )); then
        rm -f "${auth_config}"
        log "ERROR: SOAR TLS configuration invalid (SOAR_API_CA_CERT/SOAR_API_INSECURE)."
        return 1
    fi
    if curl -q -sS \
        ${tls_args[@]+"${tls_args[@]}"} \
        -X "${method}" \
        -K "${auth_config}" \
        "$@" \
        "${request_url}" \
        "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"; then
        rc=0
    else
        rc=$?
    fi
    rm -f "${auth_config}"
    return "${rc}"
}

_soar_private_token_file_valid() {
    local path="${1:-}"
    python3 - "${path}" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
if not path or not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)
try:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW)
except OSError:
    raise SystemExit(1)
try:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size < 1
        or before.st_size > 1024 * 1024
    ):
        raise SystemExit(1)
    chunks = []
    while True:
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(descriptor)
try:
    text = b"".join(chunks).decode("utf-8")
except UnicodeDecodeError:
    raise SystemExit(1)
lines = text.splitlines()
raise SystemExit(0 if len(lines) == 1 and bool(lines[0]) and "\x00" not in lines[0] else 1)
PY
}

_soar_token_journal_status() {
    local path="${1:-}"
    python3 - "${path}" <<'PY'
import json
import os
import stat
import sys

path = sys.argv[1]
if not os.path.lexists(path):
    print("absent")
    raise SystemExit(0)
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)
try:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW)
except OSError:
    raise SystemExit(1)
try:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_size < 1
        or before.st_size > 1024 * 1024
    ):
        raise SystemExit(1)
    raw = os.read(descriptor, 1024 * 1024 + 1)
    after = os.fstat(descriptor)
    if (
        len(raw) > 1024 * 1024
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(descriptor)
try:
    value = json.loads(raw.decode("utf-8"))
except (UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
status = value.get("status") if isinstance(value, dict) else None
if value.get("schema_version") != 1 or status not in {"in_progress", "ambiguous", "complete"}:
    raise SystemExit(1)
print(status)
PY
}

_soar_write_token_journal() {
    local path="$1" status="$2" username="${3:-}" user_id="${4:-}" reason="${5:-}"
    python3 - "${path}" "${status}" "${username}" "${user_id}" "${reason}" <<'PY'
import json
import os
import secrets
import stat
import sys

path, status, username, user_id, reason = sys.argv[1:]
if status not in {"in_progress", "ambiguous", "complete"} or not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)
parent = os.path.dirname(path) or "."
name = os.path.basename(path)
if not name or name in {".", ".."}:
    raise SystemExit(1)
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
directory_fd = os.open(parent, directory_flags)
temp_name = f".soar-mint-state-{secrets.token_hex(12)}"
temp_fd = None
try:
    previous = {}
    try:
        existing = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_nlink != 1
            or stat.S_IMODE(existing.st_mode) != 0o600
        ):
            raise SystemExit(1)
        existing_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
            dir_fd=directory_fd,
        )
        try:
            existing_raw = os.read(existing_fd, 1024 * 1024 + 1)
        finally:
            os.close(existing_fd)
        try:
            decoded = json.loads(existing_raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise SystemExit(1)
        if not isinstance(decoded, dict):
            raise SystemExit(1)
        previous = decoded
    value = {
        "schema_version": 1,
        "status": status,
        "username": username or str(previous.get("username", "")),
        "user_id": user_id or str(previous.get("user_id", "")),
        "reason": reason,
        "manual_reconcile": status == "ambiguous",
    }
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp_fd = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    view = memoryview(payload)
    while view:
        written = os.write(temp_fd, view)
        if written <= 0:
            raise SystemExit(1)
        view = view[written:]
    os.fchmod(temp_fd, 0o600)
    os.fsync(temp_fd)
    os.close(temp_fd)
    temp_fd = None
    os.replace(temp_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    os.fsync(directory_fd)
finally:
    if temp_fd is not None:
        os.close(temp_fd)
    try:
        os.unlink(temp_name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    os.close(directory_fd)
PY
}

_soar_mark_token_journal_ambiguous() {
    local journal="$1" reason="$2" status
    status="$(_soar_token_journal_status "${journal}" 2>/dev/null)" || return 1
    if [[ "${status}" == "in_progress" ]]; then
        _soar_write_token_journal "${journal}" ambiguous "" "" "${reason}"
    fi
}

_soar_install_token_from_response() {
    local response_file="$1" destination="$2"
    python3 - "${response_file}" "${destination}" <<'PY'
import json
import os
import secrets
import stat
import sys

response_path, destination = sys.argv[1:]
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)
read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
try:
    response_fd = os.open(response_path, read_flags)
except OSError:
    raise SystemExit(1)
try:
    before = os.fstat(response_fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) & 0o077
        or before.st_size < 1
        or before.st_size > 1024 * 1024
    ):
        raise SystemExit(1)
    raw = os.read(response_fd, 1024 * 1024 + 1)
    after = os.fstat(response_fd)
    if (
        len(raw) > 1024 * 1024
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(response_fd)
try:
    value = json.loads(raw.decode("utf-8"))
except (UnicodeError, json.JSONDecodeError):
    raise SystemExit(1)
token = value.get("key") if isinstance(value, dict) else None
if not isinstance(token, str) or not token or "\n" in token or "\r" in token or "\x00" in token:
    raise SystemExit(1)
payload = token.encode("utf-8")
parent = os.path.dirname(destination) or "."
name = os.path.basename(destination)
directory_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW)
temp_name = f".soar-token-{secrets.token_hex(12)}"
temp_fd = None
try:
    try:
        existing = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode)
        or existing.st_nlink != 1
        or stat.S_IMODE(existing.st_mode) != 0o600
    ):
        raise SystemExit(1)
    temp_fd = os.open(
        temp_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    view = memoryview(payload)
    while view:
        written = os.write(temp_fd, view)
        if written <= 0:
            raise SystemExit(1)
        view = view[written:]
    os.fchmod(temp_fd, 0o600)
    os.fsync(temp_fd)
    os.close(temp_fd)
    temp_fd = None
    os.replace(temp_name, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
    os.fsync(directory_fd)
finally:
    token = ""
    if temp_fd is not None:
        os.close(temp_fd)
    try:
        os.unlink(temp_name, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    os.close(directory_fd)
PY
}

# soar_create_automation_user <tenant_url> <admin_pw_file> <username> <new_token_file>
# Creates an `automation` user (idempotent) and, with explicit acceptance,
# mints a long-lived REST token under a durable pre-intent journal.
soar_create_automation_user() (
    local tenant_url="$1" admin_pw_file="$2" username="$3" new_token_file="$4"
    local journal_file="${SOAR_TOKEN_MINT_JOURNAL_FILE:-${new_token_file}.mint-state.json}"
    local accept_mint="${SOAR_ACCEPT_TOKEN_MINT_OR_ROTATION:-false}"
    local rotate_token="${SOAR_ROTATE_AUTOMATION_TOKEN:-false}"
    local work_dir="" lock_dir="${journal_file}.lock" user_id="" journal_status=""
    local lock_owned=false

    # shellcheck disable=SC2329  # invoked indirectly by signal/EXIT traps.
    _soar_mint_cleanup() {
        _soar_mark_token_journal_ambiguous "${journal_file}" \
            "automation-token mint was interrupted before durable completion; inspect and revoke any orphan token" \
            >/dev/null 2>&1 || true
        [[ -n "${work_dir}" ]] && rm -rf -- "${work_dir}"
        [[ "${lock_owned}" == "true" ]] && rm -rf -- "${lock_dir}"
    }
    trap '_soar_mint_cleanup' EXIT
    trap '_soar_mint_cleanup; exit 130' INT
    trap '_soar_mint_cleanup; exit 143' TERM
    trap '_soar_mint_cleanup; exit 129' HUP

    if ! soar_validate_tenant_url "${tenant_url}"; then
        log "ERROR: SOAR tenant URL must be a real credential-free HTTPS URL without whitespace, query, or fragment."
        log "       Set SOAR_API_ALLOW_HTTP=true only for an explicitly approved non-TLS lab endpoint."
        return 1
    fi
    if [[ -z "${username}" || "${username}" == *$'\r'* || "${username}" == *$'\n'* ]]; then
        log "ERROR: SOAR automation username must be a non-empty single line."
        return 1
    fi

    if ! journal_status="$(_soar_token_journal_status "${journal_file}" 2>/dev/null)"; then
        log "ERROR: SOAR token-mint journal is unsafe or corrupt: ${journal_file}"
        log "       Reconcile the automation user's live tokens manually before changing this file."
        return 1
    fi
    case "${journal_status}" in
        in_progress|ambiguous)
            log "ERROR: SOAR token-mint state is ${journal_status}; automatic retry is blocked."
            log "       Inspect the automation user in SOAR, revoke any orphan/unknown token, then archive"
            log "       ${journal_file} only after manual reconciliation."
            return 1
            ;;
    esac

    if _soar_private_token_file_valid "${new_token_file}"; then
        case "${rotate_token,,}" in
            1|true|yes|on) ;;
            *)
                log "OK: Existing private SOAR automation token is retained; no user or token POST was sent."
                return 0
                ;;
        esac
    elif [[ -e "${new_token_file}" || -L "${new_token_file}" ]]; then
        log "ERROR: Existing SOAR token destination is not a valid private single-link mode-600 token file."
        log "       Refusing to overwrite it: ${new_token_file}"
        return 1
    elif [[ "${journal_status}" == "complete" ]]; then
        log "ERROR: Token-mint journal is complete but the token file is missing or invalid."
        log "       Reconcile or revoke the live token before any new mint."
        return 1
    fi

    case "${accept_mint,,}" in
        1|true|yes|on) ;;
        *)
            log "ERROR: Token mint/rotation requires SOAR_ACCEPT_TOKEN_MINT_OR_ROTATION=true."
            log "       This acknowledges a new long-lived credential will be created."
            return 1
            ;;
    esac
    soar_require_secret_file "${admin_pw_file}" "SOAR admin password file" || return 1

    local token_dir previous_umask
    token_dir="$(dirname "${new_token_file}")"
    previous_umask="$(umask)"
    umask 077
    mkdir -p -- "${token_dir}"
    if [[ -L "${token_dir}" || ! -d "${token_dir}" ]]; then
        umask "${previous_umask}"
        log "ERROR: SOAR token parent must be a real directory: ${token_dir}"
        return 1
    fi
    if ! mkdir -m 700 -- "${lock_dir}" 2>/dev/null; then
        umask "${previous_umask}"
        log "ERROR: Another token mint may be active, or a stale mint lock requires reconciliation: ${lock_dir}"
        return 1
    fi
    lock_owned=true
    work_dir="$(mktemp -d "${token_dir}/.soar-mint-work.XXXXXX")"
    chmod 700 "${work_dir}"
    umask "${previous_umask}"

    # Recheck under the exclusive per-destination lock.
    journal_status="$(_soar_token_journal_status "${journal_file}" 2>/dev/null)" || {
        log "ERROR: SOAR token-mint journal became unsafe while acquiring the lock."
        return 1
    }
    case "${journal_status}" in
        in_progress|ambiguous)
            log "ERROR: SOAR token-mint state requires manual reconciliation; no POST was sent."
            return 1
            ;;
    esac
    if _soar_private_token_file_valid "${new_token_file}"; then
        case "${rotate_token,,}" in
            1|true|yes|on) ;;
            *)
                log "OK: Another run installed the private token; no duplicate POST was sent."
                return 0
                ;;
        esac
    fi

    # 1. Create the user (ignore 409 if already exists). All response files
    #    live under the private, signal-cleaned work directory.
    #    The username is built into JSON via python's json.dumps so any quote,
    #    backslash, or control character in the value cannot break out of the
    #    JSON string and modify the request structure.
    local create_body="${work_dir}/create-response.json" create_json create_code
    : > "${create_body}"
    chmod 600 "${create_body}"
    create_json="$(python3 -c '
import json, sys
print(json.dumps({"username": sys.argv[1], "type": "automation"}))
' "${username}")"
    create_code="$(_soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" POST /rest/ph_user \
        -H 'Content-Type: application/json' \
        --data "${create_json}" \
        -o "${create_body}" -w '%{http_code}' 2>/dev/null || echo 000)"
    case "${create_code}" in
        200|201|409) ;;
        *)
            log "ERROR: SOAR automation-user create returned HTTP ${create_code}."
            return 1
            ;;
    esac

    # 2. Look up the user id. The username is URL-encoded so that filter
    #    metacharacters (`"`, `&`, `=`, spaces, etc.) cannot alter the OData
    #    filter the SOAR `_filter_username` endpoint will parse.
    local lookup_body="${work_dir}/lookup-response.json" encoded_username
    encoded_username="$(python3 -c '
import sys, urllib.parse
print(urllib.parse.quote(sys.argv[1], safe=""))
' "${username}")"
    : > "${lookup_body}"
    chmod 600 "${lookup_body}"
    if ! _soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" GET \
        "/rest/ph_user?_filter_username=%22${encoded_username}%22&include_automation=1" \
        -o "${lookup_body}" --fail-with-body; then
        log "ERROR: SOAR automation-user lookup failed."
        return 1
    fi
    if ! user_id=$(python3 - "${lookup_body}" "${username}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    value = json.load(handle)
matches = [
    item
    for item in value.get("data", [])
    if isinstance(item, dict)
    and item.get("username") == sys.argv[2]
    and item.get("type") == "automation"
]
if len(matches) != 1 or not str(matches[0].get("id", "")).isdigit():
    raise SystemExit(1)
print(matches[0]["id"])
PY
    ); then
        log "ERROR: SOAR automation-user lookup response was invalid or empty."
        return 1
    fi
    if [[ ! "${user_id}" =~ ^[0-9]+$ ]]; then
        log "ERROR: SOAR automation-user lookup returned an invalid user id."
        return 1
    fi

    # 3. Persist intent before the token POST. Any surviving in_progress or
    #    ambiguous state blocks retries until the operator reconciles/revokes.
    if ! _soar_write_token_journal "${journal_file}" in_progress \
        "${username}" "${user_id}" "token POST has not reached durable completion"; then
        log "ERROR: Could not durably persist token-mint intent; no token POST was sent."
        return 1
    fi

    local token_body="${work_dir}/token-response.json"
    : > "${token_body}"
    chmod 600 "${token_body}"
    if ! _soar_admin_basic_auth_call "${tenant_url}" "${admin_pw_file}" POST \
        "/rest/ph_user/${user_id}/token" \
        -o "${token_body}" --fail-with-body; then
        _soar_write_token_journal "${journal_file}" ambiguous "${username}" "${user_id}" \
            "token POST failed or its outcome is uncertain" || true
        log "ERROR: SOAR automation-token mint outcome is ambiguous; automatic retry is blocked."
        log "       Inspect/revoke tokens for ${username} before reconciling ${journal_file}."
        return 1
    fi
    if ! _soar_install_token_from_response "${token_body}" "${new_token_file}"; then
        _soar_write_token_journal "${journal_file}" ambiguous "${username}" "${user_id}" \
            "token response was missing/invalid or destination installation was uncertain" || true
        log "ERROR: SOAR returned no safely installable token; state is ambiguous and retry is blocked."
        log "       Inspect/revoke tokens for ${username} before reconciling ${journal_file}."
        return 1
    fi
    if ! _soar_write_token_journal "${journal_file}" complete \
        "${username}" "${user_id}" "token installed atomically"; then
        _soar_write_token_journal "${journal_file}" ambiguous "${username}" "${user_id}" \
            "token file may be installed but completion journal was not durable" || true
        log "ERROR: Token file may have been installed, but completion state is uncertain."
        log "       Manual reconciliation is required before retry."
        return 1
    fi
    log "OK: Automation user ${username} (id=${user_id}) ready. Token at ${new_token_file}."
)
