#!/usr/bin/env bash
# Shared guardrails and small helpers for Splunk AppDynamics skills.
#
# These helpers intentionally prefer file-backed credentials. They should be
# sourced by AppDynamics setup scripts before argument parsing completes.

if [[ "$-" == *x* ]]; then
    echo "ERROR: shell xtrace is enabled; refusing to load AppDynamics credential helpers because expanded access tokens could be logged." >&2
    return 1 2>/dev/null || exit 1
fi

set -euo pipefail

_APPD_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${_APPD_LIB_DIR}/credential_curl_helpers.sh"

appd_reject_direct_secret_args() {
    local arg
    for arg in "$@"; do
        case "${arg}" in
            --password|--password=*|--pass|--pass=*|--secret|--secret=*|--client-secret|--client-secret=*|--api-key|--api-key=*|--token|--token=*|--access-token|--access-token=*|--events-api-key|--events-api-key=*|--controller-password|--controller-password=*)
                cat >&2 <<'EOF'
Refusing direct-secret CLI input. Use a chmod-600 secret file instead:
  --token-file PATH
  --password-file PATH
  --client-secret-file PATH
  --events-api-key-file PATH

Create local-only secret files with:
  bash skills/shared/scripts/write_secret_file.sh PATH
EOF
                return 2
                ;;
        esac
    done
}

appd_file_mode_octal() {
    local path="$1"
    python3 - "${path}" <<'PY'
import os
import stat
import sys

print(format(stat.S_IMODE(os.stat(sys.argv[1]).st_mode), "03o"))
PY
}

appd_assert_secret_file() {
    local path="$1"
    local label="${2:-secret file}"
    if [[ -z "${path}" ]]; then
        return 0
    fi
    if ! python3 - "${path}" <<'PY'
import os
import stat
import sys

if not hasattr(os, "O_NOFOLLOW"):
    raise SystemExit(1)
try:
    descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
except OSError:
    raise SystemExit(1)
try:
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) not in {0o400, 0o600}
        or before.st_size < 1
        or before.st_size > 65536
    ):
        raise SystemExit(1)
    raw = os.read(descriptor, 65537)
    after = os.fstat(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(descriptor)
value = raw.rstrip(b"\n")
if not value or b"\x00" in raw or b"\r" in raw or value.find(b"\n") >= 0:
    raise SystemExit(1)
PY
    then
        echo "FAIL: ${label} must be a private single-link, non-symlink one-line file: ${path}" >&2
        return 2
    fi
}

appd_controller_api_url() {
    local controller_url="$1"
    local path="$2"
    printf "%s/%s\n" "${controller_url%/}" "${path#/}"
}

appd_json_result() {
    local status="$1"
    local message="$2"
    python3 - "${status}" "${message}" <<'PY'
import json
import sys

print(json.dumps({"status": sys.argv[1], "message": sys.argv[2]}, sort_keys=True))
PY
}

APPD_CURL_TLS_ARGS=()
_APPD_WARNED_INSECURE_TLS=0

appd_prepare_curl_tls_args() {
    APPD_CURL_TLS_ARGS=()

    if [[ -n "${APPD_CA_CERT:-}" ]]; then
        if [[ "${APPD_CA_CERT}" == *$'\r'* || "${APPD_CA_CERT}" == *$'\n'* || ! -f "${APPD_CA_CERT}" ]]; then
            echo "FAIL: APPD_CA_CERT does not exist: ${APPD_CA_CERT}" >&2
            return 2
        fi
        APPD_CURL_TLS_ARGS=(--cacert "${APPD_CA_CERT}")
        return 0
    fi

    case "${APPD_VERIFY_SSL:-true}" in
        false|False|FALSE|0|no|No|NO|off|Off|OFF)
            if [[ "${_APPD_WARNED_INSECURE_TLS}" != "1" ]]; then
                echo "WARN: TLS verification is disabled for AppDynamics API calls (APPD_VERIFY_SSL=false). Prefer APPD_CA_CERT=/path/to/ca.pem for self-signed lab controllers." >&2
                _APPD_WARNED_INSECURE_TLS=1
            fi
            APPD_CURL_TLS_ARGS=(-k)
            ;;
        true|True|TRUE|1|yes|Yes|YES|on|On|ON|"")
            ;;
        *)
            echo "FAIL: APPD_VERIFY_SSL must be true or false; got '${APPD_VERIFY_SSL}'" >&2
            return 2
            ;;
    esac
}

appd_curl() {
    local auth_config=""
    local -a request_args=()
    while (($#)); do
        case "$1" in
            -K)
                if [[ $# -lt 2 || -n "${auth_config}" ]]; then
                    echo "FAIL: appd_curl requires exactly one separated -K auth config." >&2
                    return 2
                fi
                auth_config="$2"
                shift 2
                ;;
            -K*)
                echo "FAIL: appd_curl rejects attached or clustered curl config options." >&2
                return 2
                ;;
            *)
                request_args+=("$1")
                shift
                ;;
        esac
    done
    if [[ -z "${auth_config}" ]]; then
        echo "FAIL: appd_curl requires a validated -K auth config." >&2
        return 2
    fi
    credential_curl_validate_auth_config "${auth_config}" || return 2
    credential_curl_validate_request_args false "${request_args[@]}" || return 2
    appd_prepare_curl_tls_args || return $?
    if ((${#APPD_CURL_TLS_ARGS[@]})); then
        curl -q "${APPD_CURL_TLS_ARGS[@]}" "${request_args[@]}" \
            -K "${auth_config}" "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"
    else
        curl -q "${request_args[@]}" \
            -K "${auth_config}" "${CREDENTIAL_CURL_TRANSPORT_ARGS[@]}"
    fi
}

appd_controller_oauth_token() {
    local controller_url="$1"
    local account_name="$2"
    local client_name="$3"
    local client_secret_file="$4"
    appd_assert_secret_file "${client_secret_file}" "AppDynamics OAuth client secret file"

    local auth_config body_file rc restore_errexit=false
    auth_config="$(mktemp)" || return 1
    body_file="$(mktemp)" || {
        rm -f "${auth_config}"
        return 1
    }
    chmod 600 "${auth_config}" "${body_file}"
    credential_curl_append_cleanup_trap "rm -f $(printf '%q' "${auth_config}") $(printf '%q' "${body_file}") 2>/dev/null || true" HUP INT TERM

    if ! python3 - "${client_name}" "${account_name}" "${client_secret_file}" "${auth_config}" "${body_file}" <<'PY'
import os
import re
import stat
import sys
from urllib.parse import urlencode

client_name, account_name, secret_file, auth_config, body_file = sys.argv[1:]
flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
source_fd = os.open(secret_file, flags)
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
    raw = os.read(source_fd, 65537)
    after = os.fstat(source_fd)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(source_fd)
if b"\x00" in raw or b"\r" in raw or raw.rstrip(b"\n").find(b"\n") >= 0:
    raise SystemExit(1)
secret = raw.decode("utf-8").rstrip("\n")
if not secret:
    raise SystemExit(1)
client_id = client_name if "@" in client_name else f"{client_name}@{account_name}"
basic_user = client_name.split("@", 1)[0]
if not re.fullmatch(r"[A-Za-z0-9._-]+", basic_user):
    raise SystemExit(1)

escaped_user = basic_user.replace("\\", "\\\\").replace('"', '\\"')
escaped_secret = secret.replace("\\", "\\\\").replace('"', '\\"')
payloads = {
    auth_config: f'user = "{escaped_user}:{escaped_secret}"\n'.encode("utf-8"),
    body_file: urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret,
    }).encode("utf-8"),
}
for path, payload in payloads.items():
    descriptor = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise SystemExit(1)
        os.ftruncate(descriptor, 0)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SystemExit(1)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
PY
    then
        rm -f "${auth_config}" "${body_file}"
        return 1
    fi

    case $- in
        *e*)
            restore_errexit=true
            set +e
            ;;
    esac
    credential_curl_stream_file "${body_file}" | appd_curl -fsS \
        -X POST "$(appd_controller_api_url "${controller_url}" "/controller/api/oauth/access_token")" \
        -K "${auth_config}" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        --data-binary @-
    rc=$?
    if [[ "${restore_errexit}" == "true" ]]; then
        set -e
    fi
    rm -f "${auth_config}" "${body_file}"
    return "${rc}"
}

appd_events_api_headers_file() {
    local account_name="$1"
    local events_api_key_file="$2"
    local output_file="$3"
    python3 - "${account_name}" "${events_api_key_file}" "${output_file}" <<'PY'
import os
import stat
import sys
from pathlib import Path

account_name, secret_path, output_path = sys.argv[1:]
if not account_name or any(char in account_name for char in "\r\n\x00\"\\"):
    raise SystemExit(1)
read_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
source_fd = os.open(secret_path, read_flags)
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
    raw = os.read(source_fd, 65537)
    after = os.fstat(source_fd)
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        or after.st_nlink != 1
    ):
        raise SystemExit(1)
finally:
    os.close(source_fd)
if (
    b"\x00" in raw
    or b"\r" in raw
    or b'"' in raw
    or b"\\" in raw
    or raw.rstrip(b"\n").find(b"\n") >= 0
):
    raise SystemExit(1)
key = raw.decode("utf-8").rstrip("\n")
if not key:
    raise SystemExit(1)
payload = (
    f'header = "X-Events-API-AccountName: {account_name}"\n'
    f'header = "X-Events-API-Key: {key}"\n'
    'header = "Content-Type: application/vnd.appd.events+json;v=2"\n'
).encode("utf-8")
if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
    raise SystemExit(1)
destination = Path(os.path.abspath(output_path))
name = destination.name
if not name or name in {".", ".."}:
    raise SystemExit(1)
parent = destination.parent
if sys.platform == "darwin" and parent.is_absolute() and len(parent.parts) > 1:
    first = parent.parts[1]
    if first in {"tmp", "var"}:
        alias = Path("/") / first
        try:
            alias_info = alias.lstat()
            target = alias.resolve(strict=True)
        except OSError:
            pass
        else:
            if (
                stat.S_ISLNK(alias_info.st_mode)
                and alias_info.st_uid == 0
                and target.is_dir()
                and target.parts[:2] == ("/", "private")
            ):
                parent = target.joinpath(*parent.parts[2:])
directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
parent_fd = os.open("/", directory_flags)
temporary = f".{name}.{os.getpid()}.{os.urandom(16).hex()}.tmp"
created = False
try:
    for component in parent.parts[1:]:
        if component in {"", ".", ".."}:
            raise SystemExit(1)
        child_fd = os.open(component, directory_flags, dir_fd=parent_fd)
        os.close(parent_fd)
        parent_fd = child_fd
    try:
        existing = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None and (
        not stat.S_ISREG(existing.st_mode)
        or existing.st_nlink != 1
        or stat.S_IMODE(existing.st_mode) != 0o600
    ):
        raise SystemExit(1)
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=parent_fd,
    )
    created = True
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise SystemExit(1)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        current = None
    if existing is None:
        if current is not None:
            raise SystemExit(1)
    elif current is None or (
        current.st_dev,
        current.st_ino,
        current.st_nlink,
    ) != (existing.st_dev, existing.st_ino, 1):
        raise SystemExit(1)
    os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
    created = False
    os.fsync(parent_fd)
finally:
    if created:
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
    os.close(parent_fd)
PY
}

appd_validate_json_file() {
    local path="$1"
    python3 -m json.tool "${path}" >/dev/null
}
