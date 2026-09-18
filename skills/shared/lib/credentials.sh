#!/usr/bin/env bash
# Credential file loading, profile resolution, and Splunk connection settings.
# Sourced by credential_helpers.sh; not intended for direct use.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_CREDENTIALS_LOADED:-}" ]] && return 0
_CREDENTIALS_LOADED=true

_RESOLVED_CREDENTIAL_PROFILE=""
_RESOLVED_CREDENTIAL_PROFILE_REQUEST=""
_RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
_RESOLVED_SEARCH_CREDENTIAL_PROFILE_REQUEST=""
_RESOLVED_SPLUNK_TARGET_ROLE=""
_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE=""
_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE=""
_RESOLVED_SPLUNK_PLATFORM_CONTEXT=""
_RESOLVED_PRIMARY_SPLUNK_ENDPOINT=""
_RESOLVED_SEARCH_SPLUNK_ENDPOINT=""
_LOADED_CREDENTIAL_SELECTION_CONTEXT=""
_CREDENTIAL_FILE_WAS_USED=""
_CREDENTIAL_OPERATOR_CONNECTION_CAPTURED=false
_CREDENTIAL_OPERATOR_SEARCH_API_URI=""
_CREDENTIAL_OPERATOR_URI=""
_CREDENTIAL_OPERATOR_HOST=""
_CREDENTIAL_OPERATOR_MGMT_PORT=""
_CREDENTIAL_OPERATOR_SSH_HOST=""
_CREDENTIAL_FILE_SNAPSHOT_BOUND=false
_CREDENTIAL_FILE_BOUND_PATH=""
_CREDENTIAL_FILE_BOUND_SNAPSHOT=""
_CREDENTIAL_RUNTIME_ROUTE_BOUND=false
_CREDENTIAL_RUNTIME_ROUTE_SNAPSHOT=""

_credential_file_snapshot() {
    local file_path="${1:-}"

    [[ -n "${file_path}" ]] || return 1
    python3 - "${file_path}" <<'PY'
import hashlib
import os
import stat
import sys

path = sys.argv[1]


def stat_fields(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


try:
    route_before = os.lstat(path)
except FileNotFoundError:
    # Bind absence to the absolute selected route so a file appearing later in
    # the same process cannot silently become a new target source.
    route_digest = hashlib.sha256(
        os.path.abspath(path).encode("utf-8", "surrogateescape")
    ).hexdigest()
    print(f"absent:{route_digest}", end="")
    raise SystemExit(0)
except OSError:
    raise SystemExit(1)

flags = os.O_RDONLY
if hasattr(os, "O_CLOEXEC"):
    flags |= os.O_CLOEXEC

try:
    descriptor = os.open(path, flags)
except OSError:
    raise SystemExit(1)

try:
    target_before = os.fstat(descriptor)
    if not stat.S_ISREG(target_before.st_mode):
        raise SystemExit(1)

    content_digest = hashlib.sha256()
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            break
        content_digest.update(chunk)

    target_after = os.fstat(descriptor)
finally:
    os.close(descriptor)

try:
    route_after = os.lstat(path)
    selected_target = os.stat(path)
except OSError:
    raise SystemExit(1)

if stat_fields(route_before) != stat_fields(route_after):
    raise SystemExit(1)
if stat_fields(target_before) != stat_fields(target_after):
    raise SystemExit(1)
if (selected_target.st_dev, selected_target.st_ino) != (
    target_after.st_dev,
    target_after.st_ino,
):
    raise SystemExit(1)

snapshot = hashlib.sha256()
snapshot.update(os.path.abspath(path).encode("utf-8", "surrogateescape"))
snapshot.update(b"\0")
snapshot.update(os.path.realpath(path).encode("utf-8", "surrogateescape"))
snapshot.update(b"\0")
snapshot.update(repr(stat_fields(route_after)).encode("ascii"))
snapshot.update(b"\0")
snapshot.update(repr(stat_fields(target_after)).encode("ascii"))
snapshot.update(b"\0")
snapshot.update(content_digest.digest())
print(f"present:{snapshot.hexdigest()}", end="")
PY
}

_credential_current_runtime_route_snapshot() {
    {
        printf '%s\0' \
            "${SPLUNK_SEARCH_API_URI:-}" \
            "${SPLUNK_URI:-}" \
            "${SPLUNK_HOST:-}" \
            "${SPLUNK_MGMT_PORT:-}" \
            "${SPLUNK_SSH_HOST:-}" \
            "${SPLUNK_SSH_PORT:-}" \
            "${SPLUNK_RESOLVE:-}"
    } | python3 -c 'import hashlib, sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest(), end="")'
}

_credential_assert_bound_file_snapshot() {
    local current_snapshot=""

    [[ "${_CREDENTIAL_FILE_SNAPSHOT_BOUND:-false}" == "true" ]] || return 0
    if [[ "${_CREDENTIAL_FILE_BOUND_PATH:-}" != "${_CRED_FILE:-}" ]]; then
        echo "ERROR: The selected credential-file route changed after settings were loaded; start a fresh process for the new target." >&2
        return 1
    fi
    if ! current_snapshot="$(_credential_file_snapshot "${_CRED_FILE}")"; then
        echo "ERROR: Could not safely revalidate the selected credential file; refusing to reuse loaded target settings." >&2
        return 1
    fi
    if [[ "${current_snapshot}" != "${_CREDENTIAL_FILE_BOUND_SNAPSHOT}" ]]; then
        echo "ERROR: The selected credential file changed after settings were loaded; refusing to reuse the prior target." >&2
        return 1
    fi
}

_credential_assert_file_snapshot_matches() {
    local file_path="${1:-}"
    local expected_snapshot="${2:-}"
    local current_snapshot=""

    if ! current_snapshot="$(_credential_file_snapshot "${file_path}")"; then
        echo "ERROR: Could not safely snapshot the selected credential file; refusing target selection." >&2
        return 1
    fi
    if [[ "${current_snapshot}" != "${expected_snapshot}" ]]; then
        echo "ERROR: The selected credential file changed while settings were loading; refusing target selection." >&2
        return 1
    fi
}

_credential_bind_file_snapshot() {
    local file_path="${1:-}"
    local expected_snapshot="${2:-}"

    _credential_assert_file_snapshot_matches "${file_path}" "${expected_snapshot}" || return 1
    _CREDENTIAL_FILE_BOUND_PATH="${file_path}"
    _CREDENTIAL_FILE_BOUND_SNAPSHOT="${expected_snapshot}"
    _CREDENTIAL_FILE_SNAPSHOT_BOUND=true
}

_credential_assert_bound_runtime_route() {
    local current_snapshot=""

    [[ "${_CREDENTIAL_RUNTIME_ROUTE_BOUND:-false}" == "true" ]] || return 0
    if ! current_snapshot="$(_credential_current_runtime_route_snapshot)"; then
        echo "ERROR: Could not safely inspect the active Splunk route; refusing to reuse loaded target settings." >&2
        return 1
    fi
    if [[ "${current_snapshot}" != "${_CREDENTIAL_RUNTIME_ROUTE_SNAPSHOT}" ]]; then
        echo "ERROR: The active Splunk route changed outside a reviewed internal transition; refusing the target change." >&2
        return 1
    fi
}

_credential_bind_current_runtime_route() {
    local current_snapshot=""

    if ! current_snapshot="$(_credential_current_runtime_route_snapshot)"; then
        echo "ERROR: Could not safely bind the active Splunk route." >&2
        return 1
    fi
    _CREDENTIAL_RUNTIME_ROUTE_SNAPSHOT="${current_snapshot}"
    _CREDENTIAL_RUNTIME_ROUTE_BOUND=true
}

# Internal target-transition API. Callers must first load and bind the selected
# credential context. This is intentionally narrower than assigning the route
# globals directly: it verifies the old binding, changes the endpoint aliases
# as one unit, applies explicit SSH-host, SSH-port, and resolver policies, and
# binds the resulting route.
_credential_transition_runtime_route() {
    local endpoint_uri="${1:-}"
    local ssh_policy="${2:-preserve}"
    local ssh_host="${3:-}"
    local ssh_port_policy="${4:-preserve}"
    local ssh_port="${5:-}"
    local resolve_policy="${6:-preserve}"
    local resolve_value="${7:-}"

    [[ "${_CREDENTIAL_RUNTIME_ROUTE_BOUND:-false}" == "true" ]] || {
        echo "ERROR: Load and bind Splunk connection settings before changing the runtime route." >&2
        return 1
    }
    case "${ssh_policy}" in
        preserve|clear)
            ;;
        set)
            [[ -n "${ssh_host}" ]] || {
                echo "ERROR: A non-empty SSH host is required for a bound route transition." >&2
                return 1
            }
            ;;
        *)
            echo "ERROR: Invalid internal SSH route-transition policy." >&2
            return 1
            ;;
    esac
    case "${ssh_port_policy}" in
        preserve|clear)
            ;;
        set)
            if [[ ! "${ssh_port}" =~ ^[0-9]{1,5}$ ]] \
                || (( 10#${ssh_port} < 1 || 10#${ssh_port} > 65535 )); then
                echo "ERROR: A valid SSH port is required for a bound route transition." >&2
                return 1
            fi
            ;;
        *)
            echo "ERROR: Invalid internal SSH-port route-transition policy." >&2
            return 1
            ;;
    esac
    case "${resolve_policy}" in
        preserve|clear)
            ;;
        set)
            [[ -n "${resolve_value}" ]] || {
                echo "ERROR: A non-empty resolve mapping is required for a bound route transition." >&2
                return 1
            }
            ;;
        *)
            echo "ERROR: Invalid internal resolve route-transition policy." >&2
            return 1
            ;;
    esac

    _credential_assert_bound_file_snapshot || return 1
    _credential_assert_bound_runtime_route || return 1
    _apply_resolved_connection_endpoint "${endpoint_uri}" || return 1
    case "${ssh_policy}" in
        clear) unset SPLUNK_SSH_HOST ;;
        set) SPLUNK_SSH_HOST="${ssh_host}" ;;
    esac
    case "${ssh_port_policy}" in
        clear) unset SPLUNK_SSH_PORT ;;
        set) SPLUNK_SSH_PORT="${ssh_port}" ;;
    esac
    case "${resolve_policy}" in
        clear) unset SPLUNK_RESOLVE ;;
        set) SPLUNK_RESOLVE="${resolve_value}" ;;
    esac
    _credential_assert_bound_file_snapshot || return 1
    _credential_bind_current_runtime_route
}

_read_credential_file_entries_unchecked() {
    local file_path="$1"
    local selected_profile="${2:-}"
    local profile_only="${3:-false}"
    python3 - "$file_path" "$selected_profile" "$profile_only" <<'PY'
import ast
import os
import re
import sys

path = sys.argv[1]
selected_profile = sys.argv[2].strip()
profile_only = sys.argv[3].strip().lower() == "true"
allowed_keys = [
    "SPLUNK_PROFILE",
    "SPLUNK_SEARCH_PROFILE",
    "SPLUNK_INGEST_PROFILE",
    "SPLUNK_DEPLOYER_PROFILE",
    "SPLUNK_CLUSTER_MANAGER_PROFILE",
    "SPLUNK_PLATFORM",
    "SPLUNK_DELIVERY_PLANE",
    "SPLUNK_TARGET_ROLE",
    "SPLUNK_SEARCH_TARGET_ROLE",
    "SPLUNK_SEARCH_API_URI",
    "SPLUNK_HOST",
    "SPLUNK_MGMT_PORT",
    "SPLUNK_RESOLVE",
    "SPLUNK_URI",
    "SPLUNK_HEC_URL",
    "SPLUNK_SSH_HOST",
    "SPLUNK_SSH_PORT",
    "SPLUNK_SSH_USER",
    "SPLUNK_SSH_PASS",
    "SPLUNK_SSH_KNOWN_HOSTS_FILE",
    "SPLUNK_SSH_HOST_KEY_FINGERPRINT",
    "SPLUNK_SSH_ALLOW_TOFU",
    "SPLUNK_REMOTE_TMPDIR",
    "SPLUNK_REMOTE_SUDO",
    "SPLUNK_USER",
    "SPLUNK_PASS",
    "SPLUNK_HOME",
    "SPLUNK_CA_CERT",
    "SPLUNK_CLOUD_STACK",
    "SPLUNK_CLOUD_SEARCH_HEAD",
    "SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS",
    "SPLUNK_O11Y_REALM",
    "SPLUNK_O11Y_TOKEN_FILE",
    "SPLUNK_O11Y_ADMIN_TOKEN_FILE",
    "SPLUNK_O11Y_ORG_TOKEN_FILE",
    "SPLUNK_O11Y_RUM_TOKEN_FILE",
    "SPLUNK_ONCALL_API_ID",
    "SPLUNK_ONCALL_API_KEY_FILE",
    "SPLUNK_ONCALL_REST_INTEGRATION_KEY_FILE",
    "SPLUNK_ONCALL_DEFAULT_ROUTING_KEY",
    "APPD_CONTROLLER_URL",
    "APPD_ACCOUNT_NAME",
    "APPD_CLIENT_NAME",
    "APPD_CLIENT_SECRET_FILE",
    "APPD_VERIFY_SSL",
    "APPD_CA_CERT",
    "SPLUNK_MCP_GATEWAY_URL",
    "SPLUNK_MCP_SCS_REGION",
    "SPLUNK_MCP_SPLUNK_TENANT",
    "SPLUNK_MCP_SPLUNK_JWT_FILE",
    "ACS_SERVER",
    "STACK_USERNAME",
    "STACK_PASSWORD",
    "STACK_TOKEN",
    "STACK_TOKEN_USER",
    "SPLUNK_USERNAME",
    "SPLUNK_PASSWORD",
    "SB_USER",
    "SB_PASS",
    "SPLUNK_ALLOW_INSECURE_HTTP",
    "SPLUNK_VERIFY_SSL",
    "SPLUNKBASE_VERIFY_SSL",
    "SPLUNKBASE_CA_CERT",
    "APP_DOWNLOAD_VERIFY_SSL",
    "APP_DOWNLOAD_CA_CERT",
]
allowed = set(allowed_keys)
raw_values = {}
profile_values = {}
profile_pattern = re.compile(r"PROFILE_([A-Za-z0-9][A-Za-z0-9_-]*)__([A-Za-z_][A-Za-z0-9_]*)$")

with open(path, encoding="utf-8") as handle:
    for raw_line in handle:
        if "\0" in raw_line:
            print(
                "ERROR: Credential files must not contain NUL bytes; refusing to load any settings.",
                file=sys.stderr,
            )
            raise SystemExit(4)
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in raw_line:
            continue

        key, value = raw_line.split("=", 1)
        key = key.strip()

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            try:
                value = ast.literal_eval(value)
            except Exception:
                value = value[1:-1]
        if not isinstance(value, str) or "\0" in value:
            print(
                "ERROR: Credential values must not contain NUL bytes; refusing to load any settings.",
                file=sys.stderr,
            )
            raise SystemExit(4)

        profile_match = profile_pattern.fullmatch(key)
        if profile_match:
            profile_name, actual_key = profile_match.groups()
            if actual_key not in allowed:
                continue
            profile_values.setdefault(profile_name, {})[actual_key] = value
            continue

        if key not in allowed:
            continue

        raw_values[key] = value

if selected_profile and selected_profile not in profile_values:
    # Keep an explicitly unknown profile distinguishable from an omitted one.
    # Callers use this status to reject the target before applying flat values.
    raise SystemExit(3)

pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

def resolve_value(value, profile_name, stack):
    def repl(match):
        name = match.group(1)
        if name in stack:
            return match.group(0)
        if profile_name and name in profile_values.get(profile_name, {}):
            return resolve_value(profile_values[profile_name][name], profile_name, stack | {name})
        if name in raw_values:
            return resolve_value(raw_values[name], profile_name, stack | {name})
        return os.environ.get(name, match.group(0))
    return pattern.sub(repl, value)

emitted = set()
if selected_profile and selected_profile in profile_values:
    for key in allowed_keys:
        if key not in profile_values[selected_profile]:
            continue
        resolved = resolve_value(profile_values[selected_profile][key], selected_profile, {key})
        sys.stdout.buffer.write(key.encode("utf-8"))
        sys.stdout.buffer.write(b"\0")
        sys.stdout.buffer.write(resolved.encode("utf-8"))
        sys.stdout.buffer.write(b"\0")
        emitted.add(key)

for key in allowed_keys:
    if profile_only or key not in raw_values or key in emitted:
        continue
    resolved = resolve_value(raw_values[key], selected_profile or None, {key})
    sys.stdout.buffer.write(key.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
    sys.stdout.buffer.write(resolved.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
PY
}

_read_credential_file_entries() {
    local file_path="${1:-}"
    local output_file="" read_status=0

    if [[ "${file_path}" != "${_CRED_FILE:-}" \
        || "${_CREDENTIAL_FILE_SNAPSHOT_BOUND:-false}" != "true" ]]; then
        _read_credential_file_entries_unchecked "$@"
        return $?
    fi

    _credential_assert_bound_file_snapshot || return 1
    output_file="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-credential-read.XXXXXX")" \
        || return 1
    if _read_credential_file_entries_unchecked "$@" >"${output_file}"; then
        read_status=0
    else
        read_status=$?
        rm -f "${output_file}"
        return "${read_status}"
    fi
    if ! _credential_assert_bound_file_snapshot; then
        rm -f "${output_file}"
        return 1
    fi
    if ! command cat "${output_file}"; then
        rm -f "${output_file}"
        return 1
    fi
    rm -f "${output_file}"
}

_credential_temp_file() {
    local template="${1:-${TMPDIR:-/tmp}/splunk-credentials.XXXXXX}"
    local output_file=""

    output_file="$(mktemp "${template}")" || return 1
    if ! chmod 600 "${output_file}"; then
        rm -f "${output_file}"
        return 1
    fi
    printf '%s' "${output_file}"
}

_credential_profile_exists_in_file() {
    local file_path="${1:-}"
    local profile_name="${2:-}"
    local profile_output read_status=0

    [[ -n "${file_path}" && -f "${file_path}" ]] || return 1
    [[ "${profile_name}" =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || return 1
    profile_output="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-profile.XXXXXX")" || return 2
    if _read_credential_file_entries "${file_path}" "${profile_name}" true >"${profile_output}"; then
        read_status=0
    else
        read_status=$?
        rm -f "${profile_output}"
        if (( read_status == 3 )); then
            return 1
        fi
        return 2
    fi
    if [[ ! -s "${profile_output}" ]]; then
        rm -f "${profile_output}"
        return 1
    fi
    rm -f "${profile_output}"
    return 0
}

_validate_credential_profile() {
    local profile_name="${1:-}"
    local profile_kind="${2:-credential}"
    local validation_status=0

    [[ -n "${profile_name}" ]] || return 0
    if _credential_profile_exists_in_file "${_CRED_FILE}" "${profile_name}"; then
        return 0
    else
        validation_status=$?
    fi
    if (( validation_status == 1 )); then
        echo "ERROR: Selected ${profile_kind} profile is not defined in ${_CRED_FILE}." >&2
    else
        echo "ERROR: Could not safely inspect the selected ${profile_kind} profile in ${_CRED_FILE}." >&2
    fi
    return 1
}
_list_credential_profiles_from_file() {
    local file_path="$1"
    [[ -f "${file_path}" ]] || return 0
    python3 - "$file_path" <<'PY'
import sys

path = sys.argv[1]
profiles = set()

with open(path, encoding="utf-8") as handle:
    for raw_line in handle:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            continue
        key, _ = raw_line.split("=", 1)
        key = key.strip()
        if key.startswith("PROFILE_") and "__" in key:
            profiles.add(key[len("PROFILE_"):].split("__", 1)[0])

for name in sorted(profiles):
    sys.stdout.buffer.write(name.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
PY
}

_credential_file_has_flat_target_entries() {
    local file_path="$1"
    [[ -f "${file_path}" ]] || return 1
    python3 - "$file_path" <<'PY'
import sys

path = sys.argv[1]
flat_target_keys = {
    "SPLUNK_PLATFORM", "SPLUNK_DELIVERY_PLANE",
    "SPLUNK_TARGET_ROLE", "SPLUNK_SEARCH_TARGET_ROLE",
    "SPLUNK_INGEST_PROFILE", "SPLUNK_DEPLOYER_PROFILE", "SPLUNK_CLUSTER_MANAGER_PROFILE",
    "SPLUNK_SEARCH_API_URI", "SPLUNK_HOST",
    "SPLUNK_MGMT_PORT", "SPLUNK_URI", "SPLUNK_HEC_URL",
    "SPLUNK_SSH_HOST", "SPLUNK_SSH_PORT",
    "SPLUNK_SSH_USER", "SPLUNK_SSH_PASS", "SPLUNK_SSH_KNOWN_HOSTS_FILE",
    "SPLUNK_SSH_HOST_KEY_FINGERPRINT", "SPLUNK_SSH_ALLOW_TOFU",
    "SPLUNK_REMOTE_TMPDIR", "SPLUNK_REMOTE_SUDO",
    "SPLUNK_USER", "SPLUNK_PASS",
    "SPLUNK_CA_CERT",
    "SPLUNK_CLOUD_STACK", "SPLUNK_CLOUD_SEARCH_HEAD",
    "SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS", "SPLUNK_O11Y_REALM",
    "SPLUNK_O11Y_TOKEN_FILE", "SPLUNK_O11Y_ADMIN_TOKEN_FILE",
    "SPLUNK_O11Y_ORG_TOKEN_FILE", "SPLUNK_O11Y_RUM_TOKEN_FILE",
    "SPLUNK_ONCALL_API_ID", "SPLUNK_ONCALL_API_KEY_FILE",
    "SPLUNK_ONCALL_REST_INTEGRATION_KEY_FILE", "SPLUNK_ONCALL_DEFAULT_ROUTING_KEY",
    "APPD_CONTROLLER_URL", "APPD_ACCOUNT_NAME", "APPD_CLIENT_NAME",
    "APPD_CLIENT_SECRET_FILE", "APPD_VERIFY_SSL", "APPD_CA_CERT",
    "SPLUNK_MCP_GATEWAY_URL",
    "SPLUNK_MCP_SCS_REGION", "SPLUNK_MCP_SPLUNK_TENANT",
    "SPLUNK_MCP_SPLUNK_JWT_FILE", "ACS_SERVER",
    "STACK_USERNAME", "STACK_PASSWORD", "STACK_TOKEN", "STACK_TOKEN_USER",
    "SPLUNK_USERNAME", "SPLUNK_PASSWORD", "SB_USER", "SB_PASS",
    "SPLUNK_ALLOW_INSECURE_HTTP", "SPLUNK_VERIFY_SSL",
    "SPLUNKBASE_VERIFY_SSL", "SPLUNKBASE_CA_CERT",
    "APP_DOWNLOAD_VERIFY_SSL", "APP_DOWNLOAD_CA_CERT",
}

try:
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or "=" not in raw_line:
                continue
            key, _ = raw_line.split("=", 1)
            if key.strip() in flat_target_keys:
                sys.exit(0)
except (OSError, UnicodeError):
    sys.exit(2)
sys.exit(1)
PY
}

_default_credential_profile_from_file() {
    local file_path="$1"
    [[ -f "${file_path}" ]] || return 0
    python3 - "$file_path" <<'PY'
import ast
import sys

path = sys.argv[1]

with open(path, encoding="utf-8") as handle:
    for raw_line in handle:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        if key != "SPLUNK_PROFILE":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            try:
                value = ast.literal_eval(value)
            except Exception:
                value = value[1:-1]
        print(value, end="")
        break
PY
}

_prompt_for_credential_profile() {
    local -a profiles=("$@")
    local choice

    [[ -t 0 ]] || return 1

    echo ""
    echo "Multiple credential profiles detected."
    for i in "${!profiles[@]}"; do
        printf "  %d) %s\n" $((i + 1)) "${profiles[$i]}"
    done

    while true; do
        read -rp "Choose the profile for this run by number or name: " choice
        if [[ -z "${choice}" ]]; then
            continue
        fi
        if [[ "${choice}" =~ ^[0-9]+$ ]] && [[ "${choice}" -ge 1 ]] && [[ "${choice}" -le ${#profiles[@]} ]]; then
            _RESOLVED_CREDENTIAL_PROFILE="${profiles[$((choice - 1))]}"
            return 0
        fi
        for profile in "${profiles[@]}"; do
            if [[ "${choice}" == "${profile}" ]]; then
                _RESOLVED_CREDENTIAL_PROFILE="${profile}"
                return 0
            fi
        done
    done
}

resolve_credential_profile() {
    local default_profile
    local -a profiles=()
    local profile profiles_output="" requested_profile="${SPLUNK_PROFILE:-}"
    local flat_status=0

    if [[ -n "${_RESOLVED_CREDENTIAL_PROFILE:-}" ]]; then
        if [[ "${_RESOLVED_CREDENTIAL_PROFILE_REQUEST:-}" != "${requested_profile}" ]]; then
            _RESOLVED_CREDENTIAL_PROFILE=""
        else
            if [[ ! -f "${_CRED_FILE}" ]]; then
                if [[ -n "${requested_profile}" \
                    || "${_CREDENTIAL_FILE_WAS_USED:-}" == "${_CRED_FILE}" \
                    || -n "${_LOADED_CREDENTIAL_SELECTION_CONTEXT:-}" ]]; then
                    _validate_credential_profile "${requested_profile}" "primary credential"
                    _RESOLVED_CREDENTIAL_PROFILE=""
                    if [[ -z "${requested_profile}" ]]; then
                        echo "ERROR: The previously used credential file is no longer available; refusing to reuse loaded target settings." >&2
                    fi
                    return 1
                fi
                _RESOLVED_CREDENTIAL_PROFILE=""
                return 0
            fi
            if ! _validate_credential_profile "${_RESOLVED_CREDENTIAL_PROFILE}" "primary credential"; then
                _RESOLVED_CREDENTIAL_PROFILE=""
                return 1
            fi
            printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
            return 0
        fi
    fi

    if [[ -n "${requested_profile}" ]]; then
        _validate_credential_profile "${requested_profile}" "primary credential" || return 1
        _RESOLVED_CREDENTIAL_PROFILE="${requested_profile}"
        _RESOLVED_CREDENTIAL_PROFILE_REQUEST="${requested_profile}"
        printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
        return 0
    fi

    [[ -f "${_CRED_FILE}" ]] || {
        if [[ "${_CREDENTIAL_FILE_WAS_USED:-}" == "${_CRED_FILE}" \
            || -n "${_LOADED_CREDENTIAL_SELECTION_CONTEXT:-}" ]]; then
            echo "ERROR: The previously used credential file is no longer available; refusing to reuse loaded target settings." >&2
            return 1
        fi
        return 0
    }
    _CREDENTIAL_FILE_WAS_USED="${_CRED_FILE}"

    profiles_output="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-profile-list.XXXXXX")" || return 1
    if ! _list_credential_profiles_from_file "${_CRED_FILE}" >"${profiles_output}"; then
        rm -f "${profiles_output}"
        return 1
    fi
    while IFS= read -r -d '' profile; do
        profiles+=("${profile}")
    done <"${profiles_output}"
    rm -f "${profiles_output}"


    if ! default_profile="$(_default_credential_profile_from_file "${_CRED_FILE}")"; then
        echo "ERROR: Could not safely read the default credential profile from ${_CRED_FILE}." >&2
        return 1
    fi
    if [[ -n "${default_profile}" ]]; then
        _validate_credential_profile "${default_profile}" "primary credential" || return 1
        _RESOLVED_CREDENTIAL_PROFILE="${default_profile}"
        _RESOLVED_CREDENTIAL_PROFILE_REQUEST=""
        printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
        return 0
    fi

    if (( ${#profiles[@]} == 0 )); then
        return 0
    fi
    if _credential_file_has_flat_target_entries "${_CRED_FILE}"; then
        return 0
    else
        flat_status=$?
        if (( flat_status != 1 )); then
            echo "ERROR: Could not safely inspect flat target settings in ${_CRED_FILE}." >&2
            return 1
        fi
    fi

    if (( ${#profiles[@]} == 1 )); then
        _validate_credential_profile "${profiles[0]}" "primary credential" || return 1
        _RESOLVED_CREDENTIAL_PROFILE="${profiles[0]}"
        _RESOLVED_CREDENTIAL_PROFILE_REQUEST=""
        printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
        return 0
    fi

    if ! _prompt_for_credential_profile "${profiles[@]}"; then
        echo "ERROR: Multiple credential profiles are defined in ${_CRED_FILE}." >&2
        echo "Set SPLUNK_PROFILE to the desired profile for non-interactive runs." >&2
        return 1
    fi

    _validate_credential_profile "${_RESOLVED_CREDENTIAL_PROFILE}" "primary credential" || return 1
    _RESOLVED_CREDENTIAL_PROFILE_REQUEST=""
    printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
}

resolve_search_credential_profile() {
    local requested_profile=""

    if ! requested_profile="$(_effective_credential_profile_selector "SPLUNK_SEARCH_PROFILE")"; then
        return 1
    fi

    if [[ -n "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE:-}" ]]; then
        if [[ "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE_REQUEST:-}" != "${requested_profile}" ]]; then
            _RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
        else
            if [[ ! -f "${_CRED_FILE}" ]]; then
                if [[ -n "${requested_profile}" ]]; then
                    _validate_credential_profile "${requested_profile}" "search"
                    _RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
                    return 1
                fi
                _RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
                return 0
            fi
            if ! _validate_credential_profile "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE}" "search"; then
                _RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
                return 1
            fi
            printf '%s' "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE}"
            return 0
        fi
    fi

    if [[ -n "${requested_profile}" ]]; then
        _validate_credential_profile "${requested_profile}" "search" || return 1
        _RESOLVED_SEARCH_CREDENTIAL_PROFILE="${requested_profile}"
        _RESOLVED_SEARCH_CREDENTIAL_PROFILE_REQUEST="${requested_profile}"
        printf '%s' "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE}"
        return 0
    fi

    return 0
}

resolve_ingest_credential_profile() {
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi
    if [[ -n "${SPLUNK_INGEST_PROFILE:-}" ]]; then
        _validate_credential_profile "${SPLUNK_INGEST_PROFILE}" "ingest" || return 1
        printf '%s' "${SPLUNK_INGEST_PROFILE}"
    fi
}

resolve_deployer_credential_profile() {
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi
    if [[ -n "${SPLUNK_DEPLOYER_PROFILE:-}" ]]; then
        _validate_credential_profile "${SPLUNK_DEPLOYER_PROFILE}" "deployer" || return 1
        printf '%s' "${SPLUNK_DEPLOYER_PROFILE}"
    fi
}

resolve_cluster_manager_credential_profile() {
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi
    if [[ -n "${SPLUNK_CLUSTER_MANAGER_PROFILE:-}" ]]; then
        _validate_credential_profile "${SPLUNK_CLUSTER_MANAGER_PROFILE}" "cluster-manager" || return 1
        printf '%s' "${SPLUNK_CLUSTER_MANAGER_PROFILE}"
    fi
}

load_observability_cloud_settings() {
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi
}

# Load Splunk On-Call settings (SPLUNK_ONCALL_API_ID,
# SPLUNK_ONCALL_API_KEY_FILE, SPLUNK_ONCALL_REST_INTEGRATION_KEY_FILE,
# SPLUNK_ONCALL_DEFAULT_ROUTING_KEY) from the project credentials file.
# Used by the splunk-oncall-setup skill. The API key and REST endpoint
# integration key live in chmod-600 files and are never stored inline in
# the credentials file or environment.
load_oncall_settings() {
    _load_credential_values_from_file "${_CRED_FILE}"
}

_search_profile_overrides_key() {
    case "${1:-}" in
        SPLUNK_RESOLVE|SPLUNK_SSH_PORT|SPLUNK_SSH_USER|SPLUNK_SSH_PASS|SPLUNK_SSH_KNOWN_HOSTS_FILE|SPLUNK_SSH_HOST_KEY_FINGERPRINT|SPLUNK_SSH_ALLOW_TOFU|SPLUNK_REMOTE_TMPDIR|SPLUNK_REMOTE_SUDO|SPLUNK_USER|SPLUNK_PASS|SPLUNK_ALLOW_INSECURE_HTTP)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}
_credential_output_value() {
    local output_file="${1:-}"
    local target_key="${2:-}"
    local key value

    [[ -s "${output_file}" && -n "${target_key}" ]] || return 0
    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        if [[ "${key}" == "${target_key}" ]]; then
            printf '%s' "${value}"
            return 0
        fi
    done <"${output_file}"
}

_endpoint_uri_from_alias_values() {
    local search_api_uri="${1:-}"
    local legacy_uri="${2:-}"
    local host="${3:-}"
    local port="${4:-}"

    if [[ -n "${search_api_uri}" ]]; then
        printf '%s' "${search_api_uri}"
        return 0
    fi
    if [[ -n "${legacy_uri}" ]]; then
        printf '%s' "${legacy_uri}"
        return 0
    fi
    if [[ -n "${host}" ]]; then
        _format_splunk_https_endpoint "${host}" "${port:-8089}"
        return $?
    fi
    return 1
}

_endpoint_uri_from_credential_output() {
    local output_file="${1:-}"
    local search_api_uri="" legacy_uri="" host="" port=""

    search_api_uri="$(_credential_output_value "${output_file}" "SPLUNK_SEARCH_API_URI")"
    legacy_uri="$(_credential_output_value "${output_file}" "SPLUNK_URI")"
    host="$(_credential_output_value "${output_file}" "SPLUNK_HOST")"
    port="$(_credential_output_value "${output_file}" "SPLUNK_MGMT_PORT")"
    _endpoint_uri_from_alias_values "${search_api_uri}" "${legacy_uri}" "${host}" "${port}"
}

_apply_resolved_connection_endpoint() {
    local endpoint_uri="${1:-}"
    local endpoint_host="" endpoint_port=""

    [[ -n "${endpoint_uri}" ]] || return 1
    endpoint_host="$(splunk_host_from_uri "${endpoint_uri}")"
    [[ -n "${endpoint_host}" ]] || return 1
    endpoint_port="$(splunk_port_from_uri "${endpoint_uri}")"
    endpoint_port="${endpoint_port:-8089}"

    SPLUNK_SEARCH_API_URI="${endpoint_uri}"
    SPLUNK_URI="${endpoint_uri}"
    SPLUNK_HOST="${endpoint_host}"
    SPLUNK_MGMT_PORT="${endpoint_port}"
}

_effective_credential_profile_selector() {
    local selector_key="${1:-}"
    local selected_profile="" selector_output="" selector_value="" effective_primary_profile=""

    [[ -n "${selector_key}" ]] || return 1
    if [[ -n "${!selector_key-}" ]]; then
        printf '%s' "${!selector_key}"
        return 0
    fi
    if [[ ! -f "${_CRED_FILE}" ]]; then
        if [[ "${_CREDENTIAL_FILE_WAS_USED:-}" == "${_CRED_FILE}" \
            || -n "${_LOADED_CREDENTIAL_SELECTION_CONTEXT:-}" ]]; then
            echo "ERROR: The previously used credential file is no longer available; refusing to reuse loaded target settings." >&2
            return 1
        fi
        return 0
    fi

    if ! selected_profile="$(resolve_credential_profile)"; then
        return 1
    fi
    selector_output="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-profile-selector.XXXXXX")" || return 1
    if ! _read_credential_file_entries "${_CRED_FILE}" "${selected_profile}" >"${selector_output}"; then
        rm -f "${selector_output}"
        return 1
    fi
    effective_primary_profile="$(_credential_output_value "${selector_output}" "SPLUNK_PROFILE")"
    if [[ -z "${SPLUNK_PROFILE:-}" && -n "${effective_primary_profile}" \
        && "${effective_primary_profile}" != "${selected_profile}" ]]; then
        rm -f "${selector_output}"
        echo "ERROR: The selected credential profile attempts to redirect SPLUNK_PROFILE; refusing the target change." >&2
        return 1
    fi
    selector_value="$(_credential_output_value "${selector_output}" "${selector_key}")"
    rm -f "${selector_output}"
    printf '%s' "${selector_value}"
}

_load_credential_values_from_file() {
    local file_path="${1:-${_CRED_FILE}}"
    local selected_profile=""
    local search_profile=""
    local effective_primary_profile="" ingest_profile="" deployer_profile="" cluster_manager_profile=""
    local primary_output="" search_output="" primary_profile_output="" search_profile_output=""
    local key value current_value selected_value
    local selection_context=""
    local operator_endpoint="" primary_endpoint="" final_endpoint=""
    local primary_profile_endpoint="" search_profile_endpoint=""
    local primary_profile_ssh_host="" search_profile_ssh_host="" endpoint_host=""
    local endpoint_status=0 primary_profile_has_endpoint=false search_profile_has_endpoint=false
    local credential_snapshot=""

    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        _credential_assert_bound_runtime_route || return 1
        _credential_assert_bound_file_snapshot || return 1
        if ! credential_snapshot="$(_credential_file_snapshot "${file_path}")"; then
            echo "ERROR: Could not safely snapshot the selected credential file; refusing target selection." >&2
            return 1
        fi
        if [[ "${_CREDENTIAL_OPERATOR_CONNECTION_CAPTURED}" != "true" ]]; then
            _CREDENTIAL_OPERATOR_SEARCH_API_URI="${SPLUNK_SEARCH_API_URI:-}"
            _CREDENTIAL_OPERATOR_URI="${SPLUNK_URI:-}"
            _CREDENTIAL_OPERATOR_HOST="${SPLUNK_HOST:-}"
            _CREDENTIAL_OPERATOR_MGMT_PORT="${SPLUNK_MGMT_PORT:-}"
            _CREDENTIAL_OPERATOR_SSH_HOST="${SPLUNK_SSH_HOST:-}"
            _CREDENTIAL_OPERATOR_CONNECTION_CAPTURED=true
        fi
        if operator_endpoint="$(_endpoint_uri_from_alias_values \
            "${_CREDENTIAL_OPERATOR_SEARCH_API_URI}" \
            "${_CREDENTIAL_OPERATOR_URI}" \
            "${_CREDENTIAL_OPERATOR_HOST}" \
            "${_CREDENTIAL_OPERATOR_MGMT_PORT}")"; then
            :
        else
            endpoint_status=$?
            if (( endpoint_status != 1 )); then
                return 1
            fi
            operator_endpoint=""
        fi
    fi

    if [[ ! -f "${file_path}" ]]; then
        if [[ "${file_path}" == "${_CRED_FILE}" ]] \
            && [[ "${_CREDENTIAL_FILE_WAS_USED:-}" == "${file_path}" \
                || -n "${_LOADED_CREDENTIAL_SELECTION_CONTEXT:-}" \
                || -n "${SPLUNK_PROFILE:-}" \
                || -n "${SPLUNK_SEARCH_PROFILE:-}" \
                || -n "${SPLUNK_INGEST_PROFILE:-}" \
                || -n "${SPLUNK_DEPLOYER_PROFILE:-}" \
                || -n "${SPLUNK_CLUSTER_MANAGER_PROFILE:-}" ]]; then
            echo "ERROR: The selected or previously loaded credential target requires ${_CRED_FILE}; refusing to reuse stale settings." >&2
            return 1
        fi
        if [[ -n "${operator_endpoint}" ]]; then
            _apply_resolved_connection_endpoint "${operator_endpoint}" || return 1
            _RESOLVED_PRIMARY_SPLUNK_ENDPOINT="${operator_endpoint}"
            _RESOLVED_SEARCH_SPLUNK_ENDPOINT="${operator_endpoint}"
        fi
        if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
            _credential_bind_file_snapshot "${file_path}" "${credential_snapshot}" || return 1
            _credential_bind_current_runtime_route || return 1
        fi
        return 0
    fi
    primary_output="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-credentials.XXXXXX")" || return 1

    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        if ! selected_profile="$(resolve_credential_profile)"; then
            rm -f "${primary_output}"
            return 1
        fi
    fi
    if ! _read_credential_file_entries "${file_path}" "${selected_profile}" >"${primary_output}"; then
        rm -f "${primary_output}"
        return 1
    fi

    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        effective_primary_profile="$(_credential_output_value "${primary_output}" "SPLUNK_PROFILE")"
        if [[ -z "${SPLUNK_PROFILE:-}" && -n "${effective_primary_profile}" \
            && "${effective_primary_profile}" != "${selected_profile}" ]]; then
            rm -f "${primary_output}"
            echo "ERROR: The selected credential profile attempts to redirect SPLUNK_PROFILE; refusing the target change." >&2
            return 1
        fi
        if [[ -n "${SPLUNK_SEARCH_PROFILE:-}" ]]; then
            search_profile="${SPLUNK_SEARCH_PROFILE}"
        else
            search_profile="$(_credential_output_value "${primary_output}" "SPLUNK_SEARCH_PROFILE")"
        fi
        if [[ -n "${search_profile}" ]] && ! _validate_credential_profile "${search_profile}" "search"; then
            rm -f "${primary_output}"
            return 1
        fi
        ingest_profile="${SPLUNK_INGEST_PROFILE:-$(_credential_output_value "${primary_output}" "SPLUNK_INGEST_PROFILE")}"
        deployer_profile="${SPLUNK_DEPLOYER_PROFILE:-$(_credential_output_value "${primary_output}" "SPLUNK_DEPLOYER_PROFILE")}"
        cluster_manager_profile="${SPLUNK_CLUSTER_MANAGER_PROFILE:-$(_credential_output_value "${primary_output}" "SPLUNK_CLUSTER_MANAGER_PROFILE")}"
        if ! _validate_credential_profile "${ingest_profile}" "ingest" \
            || ! _validate_credential_profile "${deployer_profile}" "deployer" \
            || ! _validate_credential_profile "${cluster_manager_profile}" "cluster-manager"; then
            rm -f "${primary_output}"
            return 1
        fi
        selection_context="${selected_profile}"$'\t'"${search_profile}"$'\t'"${ingest_profile}"$'\t'"${deployer_profile}"$'\t'"${cluster_manager_profile}"
        if [[ -n "${_LOADED_CREDENTIAL_SELECTION_CONTEXT:-}" \
            && "${_LOADED_CREDENTIAL_SELECTION_CONTEXT}" != "${selection_context}" ]]; then
            rm -f "${primary_output}"
            echo "ERROR: Credential profile selection changed after settings were loaded; start a fresh process for the new target." >&2
            return 1
        fi
        if [[ -n "${search_profile}" && "${search_profile}" != "${selected_profile}" ]]; then
            search_output="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-search-credentials.XXXXXX")" || {
                rm -f "${primary_output}"
                return 1
            }
            if ! _read_credential_file_entries "${file_path}" "${search_profile}" >"${search_output}"; then
                rm -f "${primary_output}" "${search_output}"
                return 1
            fi
        fi

        if [[ -n "${selected_profile}" ]]; then
            primary_profile_output="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-primary-profile.XXXXXX")" || {
                rm -f "${primary_output}" "${search_output}"
                return 1
            }
            if ! _read_credential_file_entries \
                "${file_path}" "${selected_profile}" true >"${primary_profile_output}"; then
                rm -f "${primary_output}" "${search_output}" "${primary_profile_output}"
                return 1
            fi
            if primary_profile_endpoint="$(_endpoint_uri_from_credential_output \
                "${primary_profile_output}")"; then
                primary_profile_has_endpoint=true
            else
                endpoint_status=$?
                if (( endpoint_status != 1 )); then
                    rm -f "${primary_output}" "${search_output}" "${primary_profile_output}"
                    return 1
                fi
                primary_profile_endpoint=""
            fi
            primary_profile_ssh_host="$(_credential_output_value \
                "${primary_profile_output}" "SPLUNK_SSH_HOST")"
        fi

        if [[ -n "${search_profile}" && "${search_profile}" != "${selected_profile}" ]]; then
            search_profile_output="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-search-profile.XXXXXX")" || {
                rm -f "${primary_output}" "${search_output}" "${primary_profile_output}"
                return 1
            }
            if ! _read_credential_file_entries \
                "${file_path}" "${search_profile}" true >"${search_profile_output}"; then
                rm -f "${primary_output}" "${search_output}" \
                    "${primary_profile_output}" "${search_profile_output}"
                return 1
            fi
            if search_profile_endpoint="$(_endpoint_uri_from_credential_output \
                "${search_profile_output}")"; then
                search_profile_has_endpoint=true
            else
                endpoint_status=$?
                if (( endpoint_status != 1 )); then
                    rm -f "${primary_output}" "${search_output}" \
                        "${primary_profile_output}" "${search_profile_output}"
                    return 1
                fi
                search_profile_endpoint=""
            fi
            search_profile_ssh_host="$(_credential_output_value \
                "${search_profile_output}" "SPLUNK_SSH_HOST")"
        fi

        if ! _credential_assert_file_snapshot_matches \
            "${file_path}" "${credential_snapshot}"; then
            rm -f "${primary_output}" "${search_output}" \
                "${primary_profile_output}" "${search_profile_output}"
            return 1
        fi
    fi

    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        current_value="${!key-}"
        if [[ -z "${current_value}" ]]; then
            printf -v "${key}" '%s' "${value}"
        fi
    done <"${primary_output}"

    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        if [[ -n "${operator_endpoint}" ]]; then
            primary_endpoint="${operator_endpoint}"
        elif [[ "${primary_profile_has_endpoint}" == "true" ]]; then
            primary_endpoint="${primary_profile_endpoint}"
        elif primary_endpoint="$(_endpoint_uri_from_credential_output "${primary_output}")"; then
            :
        else
            endpoint_status=$?
            if (( endpoint_status != 1 )); then
                rm -f "${primary_output}" "${search_output}" \
                    "${primary_profile_output}" "${search_profile_output}"
                return 1
            fi
            primary_endpoint=""
        fi

        if [[ -n "${primary_endpoint}" ]]; then
            if ! _apply_resolved_connection_endpoint "${primary_endpoint}"; then
                rm -f "${primary_output}" "${search_output}" \
                    "${primary_profile_output}" "${search_profile_output}"
                return 1
            fi
        fi
        _RESOLVED_PRIMARY_SPLUNK_ENDPOINT="${primary_endpoint}"

        if [[ -n "${_CREDENTIAL_OPERATOR_SSH_HOST}" ]]; then
            SPLUNK_SSH_HOST="${_CREDENTIAL_OPERATOR_SSH_HOST}"
        elif [[ -n "${primary_profile_ssh_host}" ]]; then
            SPLUNK_SSH_HOST="${primary_profile_ssh_host}"
        elif [[ "${primary_profile_has_endpoint}" == "true" \
            && -n "${SPLUNK_SSH_HOST:-}" ]]; then
            endpoint_host="$(splunk_host_from_uri "${primary_endpoint}")"
            if [[ -n "${endpoint_host}" && "${SPLUNK_SSH_HOST}" != "${endpoint_host}" ]]; then
                unset SPLUNK_SSH_HOST
            fi
        fi
    fi

    if [[ -n "${search_output}" ]]; then
        while IFS= read -r -d '' key && IFS= read -r -d '' value; do
            if _search_profile_overrides_key "${key}"; then
                current_value="${!key-}"
                selected_value=""
                if [[ -n "${selected_profile}" ]]; then
                    selected_value="$(_credential_output_value "${primary_output}" "${key}")"
                fi
                if [[ -z "${current_value}" || "${current_value}" == "${selected_value}" ]]; then
                    printf -v "${key}" '%s' "${value}"
                fi
            fi
        done <"${search_output}"
    fi

    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        final_endpoint="${primary_endpoint}"
        if [[ -z "${operator_endpoint}" \
            && "${search_profile_has_endpoint}" == "true" ]]; then
            final_endpoint="${search_profile_endpoint}"
        fi
        if [[ -n "${final_endpoint}" ]] \
            && ! _apply_resolved_connection_endpoint "${final_endpoint}"; then
            rm -f "${primary_output}" "${search_output}" \
                "${primary_profile_output}" "${search_profile_output}"
            return 1
        fi

        if [[ -n "${_CREDENTIAL_OPERATOR_SSH_HOST}" ]]; then
            SPLUNK_SSH_HOST="${_CREDENTIAL_OPERATOR_SSH_HOST}"
        elif [[ -n "${operator_endpoint}" ]]; then
            endpoint_host="$(splunk_host_from_uri "${operator_endpoint}")"
            if [[ -n "${SPLUNK_SSH_HOST:-}" \
                && -n "${endpoint_host}" \
                && "${SPLUNK_SSH_HOST}" != "${endpoint_host}" ]]; then
                unset SPLUNK_SSH_HOST
            fi
        elif [[ -n "${search_profile_ssh_host}" ]]; then
            SPLUNK_SSH_HOST="${search_profile_ssh_host}"
        elif [[ "${search_profile_has_endpoint}" == "true" \
            && "${search_profile_endpoint}" != "${primary_endpoint}" ]]; then
            unset SPLUNK_SSH_HOST
        fi

        _RESOLVED_SEARCH_SPLUNK_ENDPOINT="${final_endpoint}"
        _LOADED_CREDENTIAL_SELECTION_CONTEXT="${selection_context}"
        _CREDENTIAL_FILE_WAS_USED="${file_path}"
    fi
    rm -f "${primary_output}" "${search_output}" \
        "${primary_profile_output}" "${search_profile_output}"
    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        _credential_bind_file_snapshot "${file_path}" "${credential_snapshot}" || return 1
        _credential_bind_current_runtime_route || return 1
    fi
}

_credential_value_for_profile_key() {
    local profile_name="${1:-}"
    local target_key="${2:-}"
    local file_path="${3:-${_CRED_FILE}}"
    local output_file="" key value result=""

    [[ -n "${target_key}" ]] || return 0
    if [[ ! -f "${file_path}" ]]; then
        [[ -z "${profile_name}" ]] && return 0
        return 1
    fi
    if [[ -n "${profile_name}" ]] && ! _credential_profile_exists_in_file "${file_path}" "${profile_name}"; then
        return 1
    fi
    output_file="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-credential-value.XXXXXX")" || return 1
    if ! _read_credential_file_entries "${file_path}" "${profile_name}" >"${output_file}"; then
        rm -f "${output_file}"
        return 1
    fi

    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        if [[ "${key}" == "${target_key}" ]]; then
            result="${value}"
            break
        fi
    done <"${output_file}"
    rm -f "${output_file}"
    printf '%s' "${result}"
}

_credential_profile_value_for_profile_key() {
    local profile_name="${1:-}"
    local target_key="${2:-}"
    local file_path="${3:-${_CRED_FILE}}"
    local output_file="" key value result=""

    [[ -n "${profile_name}" && -n "${target_key}" ]] || return 0
    [[ -f "${file_path}" ]] || return 1
    if ! _credential_profile_exists_in_file "${file_path}" "${profile_name}"; then
        return 1
    fi
    output_file="$(_credential_temp_file "${TMPDIR:-/tmp}/splunk-credential-profile-value.XXXXXX")" || return 1
    if ! _read_credential_file_entries "${file_path}" "${profile_name}" true >"${output_file}"; then
        rm -f "${output_file}"
        return 1
    fi
    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        if [[ "${key}" == "${target_key}" ]]; then
            result="${value}"
            break
        fi
    done <"${output_file}"
    rm -f "${output_file}"
    printf '%s' "${result}"
}

_selected_profile_credential_value() {
    local selected_profile=""

    if ! selected_profile="$(resolve_credential_profile)"; then
        return 1
    fi
    _credential_value_for_profile_key "${selected_profile}" "${1:-}" "${2:-${_CRED_FILE}}"
}

_search_profile_credential_value() {
    local search_profile=""

    if ! search_profile="$(resolve_search_credential_profile)"; then
        return 1
    fi
    [[ -n "${search_profile}" ]] || return 0

    _credential_value_for_profile_key "${search_profile}" "${1:-}" "${2:-${_CRED_FILE}}"
}

# Load only the plaintext-HTTP policy bit, without importing usernames,
# passwords, or tokens into a password-file-only caller's shell environment.
load_splunk_transport_policy() {
    local profile_name="" policy_value=""

    if [[ -n "${SPLUNK_ALLOW_INSECURE_HTTP:-}" ]]; then
        return 0
    fi
    [[ -f "${_CRED_FILE}" ]] || return 0

    if ! profile_name="$(resolve_search_credential_profile)"; then
        return 1
    fi
    if [[ -z "${profile_name}" ]]; then
        if ! profile_name="$(resolve_credential_profile)"; then
            return 1
        fi
    fi
    if ! policy_value="$(_credential_value_for_profile_key \
        "${profile_name}" "SPLUNK_ALLOW_INSECURE_HTTP" "${_CRED_FILE}")"; then
        return 1
    fi
    if [[ -n "${policy_value}" ]]; then
        printf -v SPLUNK_ALLOW_INSECURE_HTTP '%s' "${policy_value}"
    fi
}

_profile_value_or_current() {
    local profile_name="${1:-}"
    local target_key="${2:-}"
    local profile_value=""

    if [[ -n "${profile_name}" ]]; then
        if ! profile_value="$(_credential_value_for_profile_key "${profile_name}" "${target_key}")"; then
            return 1
        fi
        if [[ -n "${profile_value}" ]]; then
            printf '%s' "${profile_value}"
            return 0
        fi
    fi

    printf '%s' "${!target_key-}"
}
_profile_endpoint_uri() {
    local profile_name="${1:-}"
    local explicit_search_api_uri="" explicit_uri="" explicit_host="" explicit_port=""
    local fallback_search_api_uri="" fallback_uri="" fallback_host="" fallback_port=""

    if [[ -n "${profile_name}" ]]; then
        if ! explicit_search_api_uri="$(_credential_profile_value_for_profile_key "${profile_name}" "SPLUNK_SEARCH_API_URI")" \
            || ! explicit_uri="$(_credential_profile_value_for_profile_key "${profile_name}" "SPLUNK_URI")" \
            || ! explicit_host="$(_credential_profile_value_for_profile_key "${profile_name}" "SPLUNK_HOST")" \
            || ! explicit_port="$(_credential_profile_value_for_profile_key "${profile_name}" "SPLUNK_MGMT_PORT")"; then
            return 1
        fi
    fi

    if [[ -n "${explicit_search_api_uri}" ]]; then
        printf '%s' "${explicit_search_api_uri}"
        return 0
    fi
    if [[ -n "${explicit_uri}" ]]; then
        printf '%s' "${explicit_uri}"
        return 0
    fi
    if [[ -n "${explicit_host}" ]]; then
        # A profile-local host starts a new endpoint.  Pair it with the
        # profile-local port when present, otherwise the Splunk management
        # default; do not splice any current/flat endpoint component into it.
        fallback_port="8089"
        _format_splunk_https_endpoint "${explicit_host}" "${explicit_port:-${fallback_port}}"
        return 0
    fi

    fallback_search_api_uri="${SPLUNK_SEARCH_API_URI:-}"
    fallback_uri="${SPLUNK_URI:-}"
    fallback_host=""
    if [[ -n "${fallback_search_api_uri:-${fallback_uri}}" ]]; then
        fallback_host="$(splunk_host_from_uri "${fallback_search_api_uri:-${fallback_uri}}")"
    else
        fallback_host="${SPLUNK_HOST:-}"
    fi
    fallback_port="$(splunk_port_from_uri "${fallback_search_api_uri:-${fallback_uri}}")"
    fallback_port="${fallback_port:-${SPLUNK_MGMT_PORT:-8089}}"
    if [[ -n "${fallback_search_api_uri}" ]]; then
        printf '%s' "${fallback_search_api_uri}"
    elif [[ -n "${fallback_uri}" ]]; then
        printf '%s' "${fallback_uri}"
    elif [[ -n "${fallback_host}" ]]; then
        _format_splunk_https_endpoint "${fallback_host}" "${fallback_port}"
    fi
}

# shellcheck disable=SC2034
load_ingest_connection_settings() {
    local ingest_profile="" endpoint_uri="" endpoint_port=""

    if ! load_splunk_connection_settings; then
        return 1
    fi
    if ! ingest_profile="$(resolve_ingest_credential_profile)"; then
        return 1
    fi

    INGEST_SPLUNK_PROFILE="${ingest_profile}"
    if ! INGEST_SPLUNK_USER="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_USER")" \
        || ! INGEST_SPLUNK_PASS="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_PASS")" \
        || ! INGEST_SPLUNK_HEC_URL="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_HEC_URL")" \
        || ! INGEST_SPLUNK_TARGET_ROLE="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_TARGET_ROLE")"; then
        return 1
    fi

    if ! endpoint_uri="$(_profile_endpoint_uri "${ingest_profile}")"; then
        return 1
    fi

    if [[ -n "${endpoint_uri}" ]]; then
        INGEST_SPLUNK_SEARCH_API_URI="${endpoint_uri}"
        INGEST_SPLUNK_URI="${endpoint_uri}"
        INGEST_SPLUNK_HOST="$(splunk_host_from_uri "${endpoint_uri}")"
        endpoint_port="$(splunk_port_from_uri "${endpoint_uri}")"
        INGEST_SPLUNK_MGMT_PORT="${endpoint_port:-${SPLUNK_MGMT_PORT:-8089}}"
    else
        INGEST_SPLUNK_SEARCH_API_URI="${SPLUNK_SEARCH_API_URI:-}"
        INGEST_SPLUNK_URI="${SPLUNK_URI:-${INGEST_SPLUNK_SEARCH_API_URI}}"
        INGEST_SPLUNK_HOST="$(splunk_host_from_uri "${INGEST_SPLUNK_URI}")"
        endpoint_port="$(splunk_port_from_uri "${INGEST_SPLUNK_URI}")"
        INGEST_SPLUNK_MGMT_PORT="${endpoint_port:-${SPLUNK_MGMT_PORT:-8089}}"
    fi
}

resolve_delivery_plane() {
    case "${SPLUNK_DELIVERY_PLANE:-auto}" in
        auto|rest|bundle)
            printf '%s' "${SPLUNK_DELIVERY_PLANE:-auto}"
            ;;
        *)
            echo "ERROR: SPLUNK_DELIVERY_PLANE must be auto, rest, or bundle; refusing implicit routing." >&2
            return 1
            ;;
    esac
}

load_splunk_connection_settings() {
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi

    SPLUNK_MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"

    if [[ -n "${SPLUNK_SEARCH_API_URI:-}" ]]; then
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    elif [[ -n "${SPLUNK_URI:-}" ]]; then
        SPLUNK_SEARCH_API_URI="${SPLUNK_URI}"
    elif [[ -n "${SPLUNK_HOST:-}" ]]; then
        if ! SPLUNK_SEARCH_API_URI="$(_format_splunk_https_endpoint "${SPLUNK_HOST}" "${SPLUNK_MGMT_PORT}")"; then
            return 1
        fi
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    else
        SPLUNK_SEARCH_API_URI="https://localhost:8089"
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    fi

    _credential_assert_bound_file_snapshot || return 1
    _credential_bind_current_runtime_route
}

splunk_host_from_uri() {
    local uri="${1:-${SPLUNK_URI:-}}" authority="" host=""
    authority="${uri#http://}"
    authority="${authority#https://}"
    authority="${authority%%/*}"
    authority="${authority##*@}"
    if [[ "${authority}" == \[* ]]; then
        host="${authority#\[}"
        host="${host%%\]*}"
    else
        host="${authority%%:*}"
    fi
    printf '%s' "${host}"
}

splunk_port_from_uri() {
    local uri="${1:-${SPLUNK_URI:-}}" authority remainder port scheme=""
    case "${uri}" in
        http://*) scheme="http" ;;
        https://*) scheme="https" ;;
    esac
    authority="${uri#http://}"
    authority="${authority#https://}"
    authority="${authority%%/*}"
    authority="${authority##*@}"
    if [[ "${authority}" == \[*\]* ]]; then
        remainder="${authority#*\]}"
        if [[ "${remainder}" == :* ]]; then
            port="${remainder#:}"
            if [[ "${port}" =~ ^[0-9]+$ ]]; then
                printf '%s' "${port}"
                return 0
            fi
        fi
    elif [[ "${authority}" == *:* && "${authority%%:*}" != *:* && "${authority#*:}" != *:* ]]; then
        port="${authority##*:}"
        if [[ "${port}" =~ ^[0-9]+$ ]]; then
            printf '%s' "${port}"
            return 0
        fi
    fi
    if [[ "${authority}" != *:* || "${authority}" == \[*\] ]]; then
        case "${scheme}" in
            http) printf '%s' "80" ;;
            https) printf '%s' "443" ;;
        esac
    fi
}

_format_splunk_https_endpoint() {
    local host="${1:-}" port="${2:-8089}" uri_host=""

    [[ -n "${host}" ]] || return 1
    if [[ "${host}" == \[*\] ]]; then
        uri_host="${host}"
    elif [[ "${host}" == *:* ]]; then
        uri_host="[${host}]"
    else
        uri_host="${host}"
    fi
    printf 'https://%s:%s' "${uri_host}" "${port}"
}

_is_staging_splunk_cloud_host() {
    local value="${1:-}" host
    value="${value#http://}"
    value="${value#https://}"
    host="${value%%/*}"
    host="${host%%:*}"
    [[ "${host}" == *.stg.splunkcloud.com ]]
}

_is_splunk_cloud_host() {
    local value="${1:-}" host
    value="${value#http://}"
    value="${value#https://}"
    host="${value%%/*}"
    host="${host%%:*}"
    [[ "${host}" == *.splunkcloud.com ]]
}

_normalize_cloud_stack_name() {
    local value="${1:-}" host
    value="${value#http://}"
    value="${value#https://}"
    host="${value%%/*}"
    host="${host%%:*}"
    case "${host}" in
        *.stg.splunkcloud.com) printf '%s' "${host%.stg.splunkcloud.com}" ;;
        *.splunkcloud.com) printf '%s' "${host%.splunkcloud.com}" ;;
        *) printf '%s' "${host}" ;;
    esac
}

_extract_acs_search_head_prefix() {
    local value="${1:-}" host
    value="${value#http://}"
    value="${value#https://}"
    host="${value%%/*}"
    host="${host%%:*}"
    case "${host}" in
        sh-i-*.*|shc[0-9]*.*|sh[0-9]*.*) printf '%s' "${host%%.*}" ;;
        sh-i-*|shc[0-9]*|sh[0-9]*) printf '%s' "${host}" ;;
        *) printf '%s' "" ;;
    esac
}

_is_default_local_splunk_uri() {
    [[ "${SPLUNK_URI:-}" == "https://localhost:8089" && -z "${SPLUNK_HOST:-}" ]]
}

_has_cloud_target_config() {
    [[ -n "${SPLUNK_CLOUD_STACK:-}" || -n "${STACK_TOKEN:-}" || -n "${STACK_USERNAME:-}" || -n "${STACK_TOKEN_USER:-}" ]]
}

_is_hybrid_target_config() {
    _has_cloud_target_config && [[ -n "${SPLUNK_URI:-}" ]] && ! _is_default_local_splunk_uri && [[ "${SPLUNK_URI:-}" != *".splunkcloud.com"* ]]
}

_prompt_for_splunk_platform() {
    local choice

    [[ -t 0 ]] || return 1

    echo ""
    echo "Hybrid deployment configuration detected."
    echo "  1) Enterprise / forwarder target (${SPLUNK_URI})"
    echo "  2) Splunk Cloud stack (${SPLUNK_CLOUD_STACK})"
    while true; do
        read -rp "Choose the target for this run [1/2]: " choice
        case "${choice}" in
            1|enterprise|Enterprise)
                _RESOLVED_SPLUNK_PLATFORM="enterprise"
                return 0
                ;;
            2|cloud|Cloud)
                _RESOLVED_SPLUNK_PLATFORM="cloud"
                return 0
                ;;
        esac
    done
}

resolve_splunk_platform() {
    local platform_context=""

    if ! load_splunk_platform_settings; then
        return 1
    fi

    platform_context="${SPLUNK_PROFILE:-}"$'\t'"${SPLUNK_SEARCH_PROFILE:-}"$'\t'"${SPLUNK_PLATFORM:-}"$'\t'"${SPLUNK_URI:-}"$'\t'"${SPLUNK_CLOUD_STACK:-}"$'\t'"${SPLUNK_CLOUD_SEARCH_HEAD:-}"
    if [[ -n "${_RESOLVED_SPLUNK_PLATFORM:-}" \
        && "${_RESOLVED_SPLUNK_PLATFORM_CONTEXT:-}" == "${platform_context}" ]]; then
        printf '%s' "${_RESOLVED_SPLUNK_PLATFORM}"
        return 0
    fi
    _RESOLVED_SPLUNK_PLATFORM=""

    if [[ -n "${SPLUNK_PLATFORM:-}" ]]; then
        case "${SPLUNK_PLATFORM}" in
            cloud|enterprise)
                _RESOLVED_SPLUNK_PLATFORM="${SPLUNK_PLATFORM}"
                ;;
            *)
                echo "ERROR: SPLUNK_PLATFORM must be cloud or enterprise; refusing target selection." >&2
                return 1
                ;;
        esac
    elif [[ "${SPLUNK_URI:-}" == *".splunkcloud.com"* ]]; then
        _RESOLVED_SPLUNK_PLATFORM="cloud"
    elif _has_cloud_target_config && _is_default_local_splunk_uri; then
        _RESOLVED_SPLUNK_PLATFORM="cloud"
    elif _is_hybrid_target_config; then
        if ! _prompt_for_splunk_platform; then
            echo "ERROR: Hybrid deployment configuration is ambiguous in non-interactive mode." >&2
            echo "Set SPLUNK_PLATFORM=cloud or SPLUNK_PLATFORM=enterprise for this run." >&2
            return 1
        fi
    else
        _RESOLVED_SPLUNK_PLATFORM="enterprise"
    fi

    _RESOLVED_SPLUNK_PLATFORM_CONTEXT="${platform_context}"
    printf '%s' "${_RESOLVED_SPLUNK_PLATFORM}"
}

load_splunk_platform_settings() {
    local raw_stack raw_search_head default_acs_server normalized_search_head
    local primary_endpoint primary_endpoint_host
    if ! load_splunk_connection_settings; then
        return 1
    fi

    primary_endpoint="${_RESOLVED_PRIMARY_SPLUNK_ENDPOINT:-}"
    primary_endpoint_host=""
    if [[ -n "${primary_endpoint}" ]]; then
        primary_endpoint_host="$(splunk_host_from_uri "${primary_endpoint}")"
    fi
    raw_stack="${SPLUNK_CLOUD_STACK:-}"
    raw_search_head="${SPLUNK_CLOUD_SEARCH_HEAD:-}"

    default_acs_server="https://admin.splunk.com"
    if _is_staging_splunk_cloud_host "${primary_endpoint}" \
        || _is_staging_splunk_cloud_host "${primary_endpoint_host}" \
        || _is_staging_splunk_cloud_host "${raw_stack}" \
        || _is_staging_splunk_cloud_host "${raw_search_head}"; then
        default_acs_server="https://staging.admin.splunk.com"
    fi

    ACS_SERVER="${ACS_SERVER:-${default_acs_server}}"
    if [[ -n "${raw_stack}" ]]; then
        SPLUNK_CLOUD_STACK="$(_normalize_cloud_stack_name "${raw_stack}")"
    fi
    if [[ -n "${raw_search_head}" ]]; then
        normalized_search_head="$(_extract_acs_search_head_prefix "${raw_search_head}")"
        if [[ -n "${normalized_search_head}" ]]; then
            SPLUNK_CLOUD_SEARCH_HEAD="${normalized_search_head}"
        else
            echo "ERROR: SPLUNK_CLOUD_SEARCH_HEAD must identify a recognized ACS search-head prefix; refusing target selection." >&2
            return 1
        fi
    fi
    SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS="${SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS:-90}"
}

is_splunk_cloud() {
    resolve_splunk_platform >/dev/null || return 1
    [[ "${_RESOLVED_SPLUNK_PLATFORM:-}" == "cloud" ]]
}

_primary_cloud_search_api_uri() {
    local configured_uri configured_host stack suffix
    if ! load_splunk_platform_settings; then
        return 1
    fi

    configured_uri="${_RESOLVED_PRIMARY_SPLUNK_ENDPOINT:-}"
    configured_host=""
    if [[ -n "${configured_uri}" ]]; then
        configured_host="$(splunk_host_from_uri "${configured_uri}")"
    fi
    if _is_splunk_cloud_host "${configured_uri}"; then
        printf '%s' "${configured_uri}"
        return 0
    fi

    stack="${SPLUNK_CLOUD_STACK:-}"
    if [[ -z "${stack}" ]] && ! stack="$(_selected_profile_credential_value "SPLUNK_CLOUD_STACK")"; then
        return 1
    fi
    stack="$(_normalize_cloud_stack_name "${stack}")"
    [[ -n "${stack}" ]] || return 1

    if [[ "${ACS_SERVER:-}" == "https://staging.admin.splunk.com" ]] \
        || _is_staging_splunk_cloud_host "${configured_uri}" \
        || _is_staging_splunk_cloud_host "${configured_host}" \
        || _is_staging_splunk_cloud_host "${stack}" \
        || _is_staging_splunk_cloud_host "${SPLUNK_CLOUD_SEARCH_HEAD:-}"; then
        suffix=".stg.splunkcloud.com"
    else
        suffix=".splunkcloud.com"
    fi

    printf 'https://%s%s:8089' "${stack}" "${suffix}"
}

_normalize_target_role() {
    case "${1:-}" in
        search-tier|indexer|heavy-forwarder|universal-forwarder|external-collector)
            printf '%s' "${1}"
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

_search_profile_role_is_active() {
    local selected_profile search_profile

    if ! selected_profile="$(resolve_credential_profile)"; then
        return 2
    fi
    if ! search_profile="$(resolve_search_credential_profile)"; then
        return 2
    fi

    [[ -n "${search_profile}" && "${search_profile}" != "${selected_profile}" ]]
}

_warn_invalid_target_role_once() {
    local role_value="${1:-}"
    local role_key="${2:-SPLUNK_TARGET_ROLE}"

    _warn_once "_WARNED_INVALID_SPLUNK_TARGET_ROLE" \
        "ERROR: ${role_key} must be search-tier, indexer, heavy-forwarder, universal-forwarder, or external-collector; received '${role_value}'; refusing target selection."
}

_resolve_target_role_platform_hint() {
    if ! load_splunk_connection_settings; then
        return 1
    fi

    if [[ -n "${SPLUNK_PLATFORM:-}" ]]; then
        case "${SPLUNK_PLATFORM}" in
            cloud|enterprise)
                printf '%s' "${SPLUNK_PLATFORM}"
                return 0
                ;;
            *)
                echo "ERROR: SPLUNK_PLATFORM must be cloud or enterprise; refusing target selection." >&2
                return 1
                ;;
        esac
    fi

    if [[ "${SPLUNK_URI:-}" == *".splunkcloud.com"* ]]; then
        printf '%s' "cloud"
        return 0
    fi

    if _has_cloud_target_config && _is_default_local_splunk_uri; then
        printf '%s' "cloud"
        return 0
    fi

    if [[ -n "${SPLUNK_SEARCH_TARGET_ROLE:-}" ]] && _is_hybrid_target_config; then
        printf '%s' "enterprise"
        return 0
    fi

    if _is_hybrid_target_config; then
        return 0
    fi

    printf '%s' "enterprise"
}

resolve_primary_splunk_target_role() {
    local candidate=""
    local normalized=""
    local platform_hint=""

    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi
    candidate="${SPLUNK_TARGET_ROLE:-}"

    if [[ -n "${candidate}" ]]; then
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_TARGET_ROLE"
            return 1
        fi
        _RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE="${normalized}"
        printf '%s' "${_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    if ! platform_hint="$(_resolve_target_role_platform_hint)"; then
        return 1
    fi
    if [[ "${platform_hint}" == "cloud" ]]; then
        _RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE="search-tier"
        printf '%s' "${_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    return 0
}

resolve_search_splunk_target_role() {
    local candidate=""
    local normalized=""
    local search_profile_status=0

    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi

    if [[ -n "${SPLUNK_SEARCH_TARGET_ROLE:-}" ]]; then
        candidate="${SPLUNK_SEARCH_TARGET_ROLE}"
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_SEARCH_TARGET_ROLE"
            return 1
        fi
        _RESOLVED_SEARCH_SPLUNK_TARGET_ROLE="${normalized}"
        printf '%s' "${_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    if _search_profile_role_is_active; then
        :
    else
        search_profile_status=$?
        if (( search_profile_status == 2 )); then
            return 1
        fi
        return 0
    fi

    if ! candidate="$(_search_profile_credential_value "SPLUNK_TARGET_ROLE")"; then
        return 1
    fi

    if [[ -n "${candidate}" ]]; then
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_TARGET_ROLE"
            return 1
        fi
        _RESOLVED_SEARCH_SPLUNK_TARGET_ROLE="${normalized}"
        printf '%s' "${_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    return 0
}

resolve_ingest_target_role() {
    local candidate=""
    local normalized=""

    if ! load_ingest_connection_settings; then
        return 1
    fi

    candidate="${INGEST_SPLUNK_TARGET_ROLE:-}"
    if [[ -n "${candidate}" ]]; then
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_INGEST_PROFILE target role"
            return 1
        fi
        printf '%s' "${normalized}"
        return 0
    fi

    if ! candidate="$(resolve_search_splunk_target_role)"; then
        return 1
    fi
    if [[ -n "${candidate}" ]]; then
        printf '%s' "${candidate}"
        return 0
    fi

    resolve_splunk_target_role
}

resolve_splunk_target_role() {
    local active_role=""
    local platform_hint=""
    local search_profile_active=false search_profile_status=0

    if ! load_splunk_connection_settings; then
        return 1
    fi

    if ! platform_hint="$(_resolve_target_role_platform_hint)"; then
        return 1
    fi

    case "${platform_hint}" in
        cloud)
            if ! active_role="$(resolve_primary_splunk_target_role)"; then
                return 1
            fi
            ;;
        enterprise|"")
            if _search_profile_role_is_active; then
                search_profile_active=true
            else
                search_profile_status=$?
                if (( search_profile_status == 2 )); then
                    return 1
                fi
            fi
            if [[ "${search_profile_active}" == "true" ]] \
                || { [[ -n "${SPLUNK_SEARCH_TARGET_ROLE:-}" ]] && _is_hybrid_target_config; }; then
                if ! active_role="$(resolve_search_splunk_target_role)"; then
                    return 1
                fi
                if [[ -z "${active_role}" ]]; then
                    if ! active_role="$(resolve_primary_splunk_target_role)"; then
                        return 1
                    fi
                fi
            else
                if ! active_role="$(resolve_primary_splunk_target_role)"; then
                    return 1
                fi
            fi
            ;;
        *)
            if ! active_role="$(resolve_primary_splunk_target_role)"; then
                return 1
            fi
            ;;
    esac

    if [[ -n "${active_role}" ]]; then
        _RESOLVED_SPLUNK_TARGET_ROLE="${active_role}"
        printf '%s' "${_RESOLVED_SPLUNK_TARGET_ROLE}"
    fi

    return 0
}

load_splunk_credentials() {
    local platform=""

    if ! load_splunk_platform_settings; then
        return 1
    fi

    if ! platform="$(resolve_splunk_platform)"; then
        return 1
    fi
    if [[ "${platform}" == "cloud" ]]; then
        if [[ -z "${SPLUNK_USER:-}" && -n "${STACK_USERNAME:-}" ]]; then
            SPLUNK_USER="${STACK_USERNAME}"
        fi
        if [[ -z "${SPLUNK_PASS:-}" && -n "${STACK_PASSWORD:-}" ]]; then
            SPLUNK_PASS="${STACK_PASSWORD}"
        fi
    fi

    if [[ -z "${SPLUNK_USER:-}" && -n "${SPLUNK_USERNAME:-}" ]]; then
        SPLUNK_USER="${SPLUNK_USERNAME}"
    fi
    if [[ -z "${SPLUNK_PASS:-}" && -n "${SPLUNK_PASSWORD:-}" ]]; then
        SPLUNK_PASS="${SPLUNK_PASSWORD}"
    fi
    if [[ -n "${SPLUNK_SESSION_KEY:-}" ]]; then
        if type prefer_current_cloud_search_api_uri &>/dev/null; then
            if ! prefer_current_cloud_search_api_uri; then
                return 1
            fi
        fi
        _credential_assert_bound_runtime_route || return 1
        return 0
    fi

    if [[ -z "${SPLUNK_USER:-}" ]]; then
        read -rp "Splunk username: " SPLUNK_USER
    fi
    if [[ -z "${SPLUNK_PASS:-}" ]]; then
        read -rsp "Splunk password: " SPLUNK_PASS
        echo ""
    fi

    if [[ -z "${SPLUNK_USER:-}" || -z "${SPLUNK_PASS:-}" ]]; then
        echo "ERROR: Splunk credentials are required." >&2
        return 1
    fi

    if type prefer_current_cloud_search_api_uri &>/dev/null; then
        if ! prefer_current_cloud_search_api_uri; then
            return 1
        fi
    fi
    _credential_assert_bound_runtime_route
}

load_splunkbase_credentials() {
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi

    if [[ -z "${SB_USER:-}" ]]; then
        read -rp "Splunkbase (splunk.com) username: " SB_USER
    fi
    if [[ -z "${SB_PASS:-}" ]]; then
        read -rsp "Splunkbase (splunk.com) password: " SB_PASS
        echo ""
    fi

    if [[ -z "${SB_USER:-}" || -z "${SB_PASS:-}" ]]; then
        echo "ERROR: Splunkbase credentials are required." >&2
        return 1
    fi
}

_appd_infer_account_name_from_controller_url() {
    local controller_url="${1:-}"
    python3 - "${controller_url}" <<'PY'
import sys
from urllib.parse import urlparse

raw = (sys.argv[1] or "").strip()
if not raw:
    raise SystemExit(1)
if "://" not in raw:
    raw = f"https://{raw}"
host = urlparse(raw).hostname or ""
if host.endswith(".saas.appdynamics.com"):
    account = host[: -len(".saas.appdynamics.com")]
    if account:
        print(account, end="")
        raise SystemExit(0)
raise SystemExit(1)
PY
}

load_appd_credentials() {
    if ! _load_credential_values_from_file "${_CRED_FILE}"; then
        return 1
    fi

    if [[ -n "${APPD_CONTROLLER_URL:-}" && "${APPD_CONTROLLER_URL}" != http://* && "${APPD_CONTROLLER_URL}" != https://* ]]; then
        APPD_CONTROLLER_URL="https://${APPD_CONTROLLER_URL}"
    fi

    if [[ -z "${APPD_ACCOUNT_NAME:-}" && -n "${APPD_CONTROLLER_URL:-}" ]]; then
        APPD_ACCOUNT_NAME="$(_appd_infer_account_name_from_controller_url "${APPD_CONTROLLER_URL}" 2>/dev/null || true)"
    fi

    if [[ -n "${APPD_CLIENT_NAME:-}" && -z "${APPD_API_CLIENT_NAME:-}" ]]; then
        APPD_API_CLIENT_NAME="${APPD_CLIENT_NAME}"
    elif [[ -n "${APPD_API_CLIENT_NAME:-}" && -z "${APPD_CLIENT_NAME:-}" ]]; then
        APPD_CLIENT_NAME="${APPD_API_CLIENT_NAME}"
    fi

    if [[ -n "${APPD_CLIENT_SECRET_FILE:-}" && -z "${APPD_OAUTH_CLIENT_SECRET_FILE:-}" ]]; then
        APPD_OAUTH_CLIENT_SECRET_FILE="${APPD_CLIENT_SECRET_FILE}"
    elif [[ -n "${APPD_OAUTH_CLIENT_SECRET_FILE:-}" && -z "${APPD_CLIENT_SECRET_FILE:-}" ]]; then
        APPD_CLIENT_SECRET_FILE="${APPD_OAUTH_CLIENT_SECRET_FILE}"
    fi
}

load_splunk_ssh_credentials() {
    local resolved_ssh_host="" resolved_ssh_port="" runtime_endpoint=""

    if ! load_splunk_connection_settings; then
        return 1
    fi

    resolved_ssh_host="${SPLUNK_SSH_HOST:-${SPLUNK_HOST:-$(splunk_host_from_uri "${SPLUNK_URI}")}}"
    resolved_ssh_port="${SPLUNK_SSH_PORT:-22}"
    runtime_endpoint="${SPLUNK_SEARCH_API_URI:-${SPLUNK_URI:-}}"
    if ! _credential_transition_runtime_route \
        "${runtime_endpoint}" set "${resolved_ssh_host}" \
        set "${resolved_ssh_port}"; then
        return 1
    fi
    SPLUNK_SSH_USER="${SPLUNK_SSH_USER:-splunk}"

    if [[ -z "${SPLUNK_SSH_PASS:-}" ]]; then
        if [[ ! -t 0 ]]; then
            echo "ERROR: Splunk SSH password is required for SSH staging." >&2
            return 1
        fi
        read -rsp "Splunk SSH password: " SPLUNK_SSH_PASS
        echo ""
    fi

    if [[ -z "${SPLUNK_SSH_HOST:-}" || -z "${SPLUNK_SSH_USER:-}" || -z "${SPLUNK_SSH_PASS:-}" ]]; then
        echo "ERROR: Splunk SSH host, user, and password are required." >&2
        return 1
    fi
}
