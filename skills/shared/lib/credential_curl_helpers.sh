#!/usr/bin/env bash
# Fail-closed transport policy for curl calls carrying credentials.

[[ -n "${_CREDENTIAL_CURL_HELPERS_LOADED:-}" ]] && return 0
_CREDENTIAL_CURL_HELPERS_LOADED=true

CREDENTIAL_CURL_TRANSPORT_ARGS=()

credential_curl_trap_body() {
    local signal="${1:-}" trap_output
    trap_output="$(trap -p "${signal}" || true)"
    [[ -n "${trap_output}" ]] || return 0
    python3 -c '
import shlex
import sys

expected = sys.argv[1].upper()
base_signal = expected[3:] if expected.startswith("SIG") else expected
raw = sys.stdin.read()
if raw.endswith("\n"):
    raw = raw[:-1]
try:
    fields = shlex.split(raw, posix=True)
except ValueError:
    raise SystemExit(1)
actual = fields[3].upper() if len(fields) == 4 else ""
valid_signals = {expected, base_signal, f"SIG{base_signal}"}
if fields[:2] != ["trap", "--"] or actual not in valid_signals:
    raise SystemExit(1)
sys.stdout.write(fields[2])
' "${signal}" <<< "${trap_output}"
}

credential_curl_append_cleanup_trap() {
    local cleanup_cmd="${1:-}" signal existing
    shift || true
    [[ -n "${cleanup_cmd}" ]] || return 0
    for signal in "$@"; do
        existing="$(credential_curl_trap_body "${signal}")" || {
            echo "ERROR: Failed to parse the existing ${signal} trap safely." >&2
            return 1
        }
        if [[ -n "${existing}" ]]; then
            # shellcheck disable=SC2064  # capture the cleanup path now.
            trap "${existing}; ${cleanup_cmd}" "${signal}"
        else
            # shellcheck disable=SC2064  # capture the cleanup path now.
            trap "${cleanup_cmd}" "${signal}"
        fi
    done
}

credential_curl_prepare_transport() {
    local allow_http="${1:-false}"
    # shellcheck disable=SC2034  # consumed by authenticated caller libraries.
    CREDENTIAL_CURL_TRANSPORT_ARGS=(
        --proto '=https' --proto-redir '=https' --max-redirs 0 --globoff
    )
    case "${allow_http,,}" in
        1|true|yes|on)
            # shellcheck disable=SC2034  # consumed by authenticated caller libraries.
            CREDENTIAL_CURL_TRANSPORT_ARGS=(
                --proto '=http,https' --proto-redir '=http,https' --max-redirs 0 --globoff
            )
            ;;
    esac
}

credential_curl_validate_url() {
    local url="${1:-}" allow_http="${2:-false}"
    python3 - "${url}" "${allow_http}" <<'PY'
import sys
from urllib.parse import urlsplit

value = sys.argv[1]
allow_http = sys.argv[2].strip().lower() in {"1", "true", "yes", "on"}
if not value or any(ch.isspace() for ch in value):
    raise SystemExit(1)
try:
    parsed = urlsplit(value)
    port = parsed.port
except ValueError:
    raise SystemExit(1)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit(1)
if parsed.scheme == "http" and not allow_http:
    raise SystemExit(1)
if parsed.username is not None or parsed.password is not None or parsed.fragment:
    raise SystemExit(1)
if port is not None and not 1 <= port <= 65535:
    raise SystemExit(1)
PY
}

# credential_curl_validate_request_args <allow_http> <curl args...>
# The accepted grammar is intentionally limited to options used by the shared
# authenticated helpers. Authentication config, protocol, redirect, TLS, URL
# expansion, and transfer-boundary options are always wrapper-owned.
credential_curl_validate_request_args() {
    local allow_http="${1:-false}" argument="" option_name=""
    local expect_value=false url_count=0
    shift || true

    for argument in "$@"; do
        if [[ "${expect_value}" == "true" ]]; then
            if [[ "${option_name}" == "-H" || "${option_name}" == "--header" ]]; then
                if [[ "${argument}" == @* || "${argument}" == *$'\r'* || "${argument}" == *$'\n'* || "${argument}" != *:* ]]; then
                    echo "ERROR: credential-bearing curl request rejects file-backed or malformed caller headers." >&2
                    return 1
                fi
                local header_name="${argument%%:*}"
                if [[ ! "${header_name}" =~ ^[A-Za-z0-9-]+$ ]]; then
                    echo "ERROR: credential-bearing curl request rejects malformed caller header names." >&2
                    return 1
                fi
                case "${header_name,,}" in
                    authorization|proxy-authorization|host|cookie|ph-auth-token|x-auth-token|\
                    x-cisco-meraki-api-key|x-events-api-accountname|x-events-api-key|x-sf-token|\
                    content-length|transfer-encoding|connection)
                        echo "ERROR: credential-bearing curl request owns authentication, authority, and framing headers." >&2
                        return 1
                        ;;
                esac
            fi
            case "${option_name}" in
                -d|--data|--data-ascii|--data-binary|--data-raw)
                    if [[ "${argument}" == @* && "${argument}" != "@-" ]]; then
                        echo "ERROR: credential-bearing curl request rejects file-backed body arguments; stream a descriptor-validated file on stdin with @-." >&2
                        return 1
                    fi
                    ;;
                --data-urlencode)
                    if [[ "${argument}" == @* && "${argument}" != "@-" ]] || \
                       [[ "${argument}" != *=* && "${argument}" == *@* && "${argument}" != *@- ]]; then
                        echo "ERROR: credential-bearing curl request rejects file-backed URL-encoded body arguments; stream a descriptor-validated file on stdin." >&2
                        return 1
                    fi
                    ;;
                -F|--form)
                    local form_value="${argument#*=}"
                    if [[ "${argument}" != *=* || "${argument}" == *$'\r'* || "${argument}" == *$'\n'* || \
                          "${argument}" == *';'[Hh][Ee][Aa][Dd][Ee][Rr][Ss]=* ]] || \
                       { [[ "${form_value}" == @* || "${form_value}" == \<* ]] && [[ "${form_value}" != "@-" ]]; }; then
                        echo "ERROR: credential-bearing curl request rejects file-backed or malformed form arguments." >&2
                        return 1
                    fi
                    ;;
            esac
            expect_value=false
            option_name=""
            continue
        fi
        if [[ "${argument}" =~ ^-[fGsS]+$ ]]; then
            continue
        fi
        case "${argument}" in
            --|--next|--config|--config=*|-K*|-[^-]*K*|-:*|-[^-]*:*)
                echo "ERROR: credential-bearing curl request rejects config and transfer-boundary options." >&2
                return 1
                ;;
            --url|--url=*|--variable|--variable=*|--expand-*)
                echo "ERROR: credential-bearing curl request rejects caller URL and expansion options." >&2
                return 1
                ;;
            --location|--location-trusted|--max-redirs|--max-redirs=*|-L*|-[^-]*L*)
                echo "ERROR: credential-bearing curl request rejects caller redirect controls." >&2
                return 1
                ;;
            --proto|--proto=*|--proto-default|--proto-default=*|--proto-redir|--proto-redir=*|\
            --globoff|--no-globoff|-g)
                echo "ERROR: credential-bearing curl request owns protocol and URL-globbing policy." >&2
                return 1
                ;;
            --insecure|--no-insecure|--cacert|--cacert=*|--capath|--capath=*|\
            --ca-native|--no-ca-native|--proxy-insecure|--no-proxy-insecure|\
            --proxy-cacert|--proxy-cacert=*|--proxy-capath|--proxy-capath=*|\
            --doh-insecure|--no-doh-insecure|--ssl-no-revoke|\
            --ssl-revoke-best-effort|-k*|-[^-]*k*)
                echo "ERROR: credential-bearing curl request owns TLS verification policy." >&2
                return 1
                ;;
            -X|--request|-o|--output|-w|--write-out|-H|--header|-d|--data|\
            --data-ascii|--data-binary|--data-raw|--data-urlencode|-F|--form|\
            --connect-timeout|--max-time)
                expect_value=true
                option_name="${argument}"
                ;;
            --fail|--fail-with-body|--show-error|--silent)
                ;;
            [Hh][Tt][Tt][Pp]://*|[Hh][Tt][Tt][Pp][Ss]://*)
                if ! credential_curl_validate_url "${argument}" "${allow_http}"; then
                    echo "ERROR: credential-bearing curl request requires a credential-free HTTPS URL." >&2
                    return 1
                fi
                url_count=$((url_count + 1))
                ;;
            -*)
                echo "ERROR: credential-bearing curl request rejects unsupported curl option: ${argument}" >&2
                return 1
                ;;
            *)
                echo "ERROR: credential-bearing curl request rejects an ambiguous or non-HTTP(S) URL token." >&2
                return 1
                ;;
        esac
    done

    if [[ "${expect_value}" == "true" ]]; then
        echo "ERROR: credential-bearing curl request received ${option_name} without a value." >&2
        return 1
    fi
    if ((url_count != 1)); then
        echo "ERROR: credential-bearing curl request requires exactly one explicit URL; found ${url_count}." >&2
        return 1
    fi
    credential_curl_prepare_transport "${allow_http}"
}

# Stream a bounded regular file only after descriptor-bound validation. Callers
# use this with a wrapper-owned `@-` curl body; raw caller-supplied @PATH curl
# arguments remain forbidden by credential_curl_validate_request_args.
credential_curl_stream_file() {
    local path="${1:-}" max_bytes="${2:-67108864}"
    python3 - "${path}" "${max_bytes}" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
try:
    max_bytes = int(sys.argv[2])
except ValueError:
    raise SystemExit(1)
if not path or max_bytes < 1 or max_bytes > 1024 * 1024 * 1024 or not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
try:
    descriptor = os.open(path, flags)
except OSError:
    raise SystemExit(1)
try:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size < 1
        or before.st_size > max_bytes
    ):
        raise SystemExit(1)
    chunks = []
    remaining = max_bytes + 1
    while remaining > 0:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    if remaining == 0:
        raise SystemExit(1)
    after = os.fstat(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(descriptor)
payload = b"".join(chunks)
view = memoryview(payload)
while view:
    written = os.write(sys.stdout.fileno(), view)
    if written <= 0:
        raise SystemExit(1)
    view = view[written:]
PY
}

credential_curl_validate_auth_config() {
    local path="${1:-}"
    if ! python3 - "${path}" <<'PY'
import os
import re
import stat
import sys

allowed = re.compile(r'^(header|user) = "((?:[^"\\]|\\.)*)"$')
allowed_auth_headers = {
    "authorization",
    "content-type",
    "cookie",
    "ph-auth-token",
    "x-auth-token",
    "x-cisco-meraki-api-key",
    "x-events-api-accountname",
    "x-events-api-key",
    "x-sf-token",
}
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)
flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
try:
    descriptor = os.open(sys.argv[1], flags)
except OSError:
    raise SystemExit(1)
try:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
        or metadata.st_size < 1
        or metadata.st_size > 65536
    ):
        raise SystemExit(1)
    chunks = []
    remaining = 65537
    while True:
        chunk = os.read(descriptor, min(65536, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
        if remaining == 0:
            raise SystemExit(1)
    after = os.fstat(descriptor)
    if (
        (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)
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
if not text or "\r" in text or re.search(r"\\[rn]", text):
    raise SystemExit(1)
for raw_line in text.splitlines():
    match = allowed.fullmatch(raw_line)
    if not raw_line or match is None:
        raise SystemExit(1)
    if match.group(1) == "header":
        value = match.group(2)
        if value.startswith("@") or ":" not in value:
            raise SystemExit(1)
        header_name = value.split(":", 1)[0].strip().lower()
        if header_name not in allowed_auth_headers:
            raise SystemExit(1)
PY
    then
        echo "ERROR: credential curl auth config must be a private single-link file containing only safe auth directives." >&2
        return 1
    fi
}

_credential_curl_write_config() {
    local secret_file="${1:-}" directive="${2:-}" config_name="${3:-}"
    local output_file="${4:-}" value_prefix="${5:-}"
    if ! python3 - "${secret_file}" "${directive}" "${config_name}" "${output_file}" "${value_prefix}" <<'PY'
import os
import re
import stat
import sys

secret_path, directive, config_name, output_path, value_prefix = sys.argv[1:]
allowed_headers = {
    "authorization",
    "cookie",
    "ph-auth-token",
    "x-auth-token",
    "x-cisco-meraki-api-key",
    "x-events-api-accountname",
    "x-events-api-key",
    "x-sf-token",
}
if directive == "header":
    if config_name.lower() not in allowed_headers or not re.fullmatch(
        r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", config_name
    ):
        raise SystemExit(1)
    if value_prefix not in {"", "Bearer ", "Splunk "}:
        raise SystemExit(1)
elif directive == "user":
    if not re.fullmatch(r"[A-Za-z0-9._@-]+", config_name) or value_prefix:
        raise SystemExit(1)
else:
    raise SystemExit(1)
if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)

read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
try:
    source_fd = os.open(secret_path, read_flags)
except OSError:
    raise SystemExit(1)
try:
    before = os.fstat(source_fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
        or before.st_size < 1
        or before.st_size > 65536
    ):
        raise SystemExit(1)
    chunks = []
    while True:
        chunk = os.read(source_fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    after = os.fstat(source_fd)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(source_fd)

raw = b"".join(chunks)
try:
    text = raw.decode("utf-8")
except UnicodeDecodeError:
    raise SystemExit(1)
lines = text.splitlines()
if (
    len(lines) != 1
    or not lines[0]
    or "\r" in text
    or "\x00" in text
):
    raise SystemExit(1)
if directive == "header":
    if '"' in lines[0] or "\\" in lines[0]:
        raise SystemExit(1)
    payload = f'header = "{config_name}: {value_prefix}{lines[0]}"\n'.encode("utf-8")
else:
    escaped = lines[0].replace("\\", "\\\\").replace('"', '\\"')
    payload = f'user = "{config_name}:{escaped}"\n'.encode("utf-8")

parent_path = os.path.dirname(os.path.abspath(output_path))
output_name = os.path.basename(output_path)
directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
try:
    parent_fd = os.open(parent_path, directory_flags)
except OSError:
    raise SystemExit(1)
try:
    try:
        existing_fd = os.open(output_name, read_flags, dir_fd=parent_fd)
    except OSError:
        raise SystemExit(1)
    try:
        existing = os.fstat(existing_fd)
        if (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_nlink != 1
            or stat.S_IMODE(existing.st_mode) != 0o600
        ):
            raise SystemExit(1)
    finally:
        os.close(existing_fd)

    temporary = f".{output_name}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
    write_flags = (
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | os.O_NOFOLLOW
    )
    output_fd = os.open(temporary, write_flags, 0o600, dir_fd=parent_fd)
    try:
        metadata = os.fstat(output_fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise SystemExit(1)
        view = memoryview(payload)
        while view:
            written = os.write(output_fd, view)
            if written <= 0:
                raise SystemExit(1)
            view = view[written:]
        os.fsync(output_fd)
    finally:
        os.close(output_fd)
    current_fd = os.open(output_name, read_flags, dir_fd=parent_fd)
    try:
        current = os.fstat(current_fd)
        if (current.st_dev, current.st_ino, current.st_nlink) != (
            existing.st_dev,
            existing.st_ino,
            1,
        ):
            raise SystemExit(1)
    finally:
        os.close(current_fd)
    os.replace(temporary, output_name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    os.fsync(parent_fd)
finally:
    try:
        os.unlink(temporary, dir_fd=parent_fd)
    except (FileNotFoundError, UnboundLocalError):
        pass
    os.close(parent_fd)
PY
    then
        echo "ERROR: credential curl secret input/output files failed descriptor-bound validation." >&2
        return 1
    fi
    credential_curl_validate_auth_config "${output_file}"
}

# Opens both files with O_NOFOLLOW, validates their inodes with fstat, reads the
# secret from the validated descriptor, and atomically writes one auth
# directive to an already-created private output file. The secret never appears
# on argv.
credential_curl_write_header_config() {
    _credential_curl_write_config "${1:-}" header "${2:-}" "${3:-}" "${4:-}"
}

credential_curl_write_user_config() {
    _credential_curl_write_config "${1:-}" user "${2:-}" "${3:-}" ""
}
