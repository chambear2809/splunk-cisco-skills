#!/usr/bin/env bash
# Credential file loading, profile resolution, and Splunk connection settings.
# Sourced by credential_helpers.sh; not intended for direct use.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_CREDENTIALS_LOADED:-}" ]] && return 0
_CREDENTIALS_LOADED=true

_RESOLVED_CREDENTIAL_PROFILE=""
_RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
_RESOLVED_SPLUNK_TARGET_ROLE=""
_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE=""
_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE=""

_read_credential_file_entries() {
    local file_path="$1"
    local selected_profile="${2:-}"
    python3 - "$file_path" "$selected_profile" <<'PY'
import ast
import os
import re
import sys

path = sys.argv[1]
selected_profile = sys.argv[2].strip()
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
    "SPLUNK_URI",
    "SPLUNK_HEC_URL",
    "SPLUNK_SSH_HOST",
    "SPLUNK_SSH_PORT",
    "SPLUNK_SSH_USER",
    "SPLUNK_SSH_PASS",
    "SPLUNK_REMOTE_TMPDIR",
    "SPLUNK_REMOTE_SUDO",
    "SPLUNK_USER",
    "SPLUNK_PASS",
    "SPLUNK_CA_CERT",
    "SPLUNK_CLOUD_STACK",
    "SPLUNK_CLOUD_SEARCH_HEAD",
    "SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS",
    "ACS_SERVER",
    "STACK_USERNAME",
    "STACK_PASSWORD",
    "STACK_TOKEN",
    "STACK_TOKEN_USER",
    "SPLUNK_USERNAME",
    "SPLUNK_PASSWORD",
    "SB_USER",
    "SB_PASS",
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
    if key not in raw_values or key in emitted:
        continue
    resolved = resolve_value(raw_values[key], selected_profile or None, {key})
    sys.stdout.buffer.write(key.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
    sys.stdout.buffer.write(resolved.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
PY
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
    "SPLUNK_SSH_USER", "SPLUNK_SSH_PASS", "SPLUNK_REMOTE_TMPDIR", "SPLUNK_REMOTE_SUDO",
    "SPLUNK_USER", "SPLUNK_PASS",
    "SPLUNK_CA_CERT",
    "SPLUNK_CLOUD_STACK", "SPLUNK_CLOUD_SEARCH_HEAD",
    "SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS", "ACS_SERVER",
    "STACK_USERNAME", "STACK_PASSWORD", "STACK_TOKEN", "STACK_TOKEN_USER",
    "SPLUNK_USERNAME", "SPLUNK_PASSWORD", "SB_USER", "SB_PASS",
    "SPLUNK_VERIFY_SSL", "SPLUNKBASE_VERIFY_SSL", "SPLUNKBASE_CA_CERT",
    "APP_DOWNLOAD_VERIFY_SSL", "APP_DOWNLOAD_CA_CERT",
}

with open(path, encoding="utf-8") as handle:
    for raw_line in handle:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            continue
        key, _ = raw_line.split("=", 1)
        if key.strip() in flat_target_keys:
            sys.exit(0)
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
    local profile

    if [[ -n "${_RESOLVED_CREDENTIAL_PROFILE:-}" ]]; then
        printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
        return 0
    fi

    if [[ -n "${SPLUNK_PROFILE:-}" ]]; then
        _RESOLVED_CREDENTIAL_PROFILE="${SPLUNK_PROFILE}"
        printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
        return 0
    fi

    [[ -f "${_CRED_FILE}" ]] || return 0

    while IFS= read -r -d '' profile; do
        profiles+=("${profile}")
    done < <(_list_credential_profiles_from_file "${_CRED_FILE}")

    if (( ${#profiles[@]} == 0 )); then
        return 0
    fi

    default_profile="$(_default_credential_profile_from_file "${_CRED_FILE}")"
    if [[ -n "${default_profile}" ]]; then
        _RESOLVED_CREDENTIAL_PROFILE="${default_profile}"
        printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
        return 0
    fi

    if _credential_file_has_flat_target_entries "${_CRED_FILE}"; then
        return 0
    fi

    if (( ${#profiles[@]} == 1 )); then
        _RESOLVED_CREDENTIAL_PROFILE="${profiles[0]}"
        printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
        return 0
    fi

    if ! _prompt_for_credential_profile "${profiles[@]}"; then
        echo "ERROR: Multiple credential profiles are defined in ${_CRED_FILE}." >&2
        echo "Set SPLUNK_PROFILE to the desired profile for non-interactive runs." >&2
        return 1
    fi

    printf '%s' "${_RESOLVED_CREDENTIAL_PROFILE}"
}

resolve_search_credential_profile() {
    if [[ -n "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE:-}" ]]; then
        printf '%s' "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE}"
        return 0
    fi

    if [[ -n "${SPLUNK_SEARCH_PROFILE:-}" ]]; then
        _RESOLVED_SEARCH_CREDENTIAL_PROFILE="${SPLUNK_SEARCH_PROFILE}"
        printf '%s' "${_RESOLVED_SEARCH_CREDENTIAL_PROFILE}"
        return 0
    fi

    return 0
}

resolve_ingest_credential_profile() {
    _load_credential_values_from_file "${_CRED_FILE}"
    if [[ -n "${SPLUNK_INGEST_PROFILE:-}" ]]; then
        printf '%s' "${SPLUNK_INGEST_PROFILE}"
    fi
}

resolve_deployer_credential_profile() {
    _load_credential_values_from_file "${_CRED_FILE}"
    if [[ -n "${SPLUNK_DEPLOYER_PROFILE:-}" ]]; then
        printf '%s' "${SPLUNK_DEPLOYER_PROFILE}"
    fi
}

resolve_cluster_manager_credential_profile() {
    _load_credential_values_from_file "${_CRED_FILE}"
    if [[ -n "${SPLUNK_CLUSTER_MANAGER_PROFILE:-}" ]]; then
        printf '%s' "${SPLUNK_CLUSTER_MANAGER_PROFILE}"
    fi
}

_search_profile_overrides_key() {
    case "${1:-}" in
        SPLUNK_HOST|SPLUNK_MGMT_PORT|SPLUNK_SEARCH_API_URI|SPLUNK_URI|SPLUNK_SSH_HOST|SPLUNK_SSH_PORT|SPLUNK_SSH_USER|SPLUNK_SSH_PASS|SPLUNK_REMOTE_TMPDIR|SPLUNK_REMOTE_SUDO|SPLUNK_USER|SPLUNK_PASS)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

_load_credential_values_from_file() {
    local file_path="${1:-${_CRED_FILE}}"
    local selected_profile=""
    local search_profile=""
    local key value current_value selected_value

    [[ -f "${file_path}" ]] || return 0

    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        selected_profile="$(resolve_credential_profile)"
    fi

    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        current_value="${!key-}"
        if [[ -z "${current_value}" ]]; then
            printf -v "${key}" '%s' "${value}"
        fi
    done < <(_read_credential_file_entries "${file_path}" "${selected_profile}")

    if [[ "${file_path}" == "${_CRED_FILE}" ]]; then
        search_profile="$(resolve_search_credential_profile)"
        if [[ -n "${search_profile}" && "${search_profile}" != "${selected_profile}" ]]; then
            while IFS= read -r -d '' key && IFS= read -r -d '' value; do
                if _search_profile_overrides_key "${key}"; then
                    current_value="${!key-}"
                    selected_value=""
                    if [[ -n "${selected_profile}" ]]; then
                        selected_value="$(_credential_value_for_profile_key "${selected_profile}" "${key}" "${file_path}")"
                    fi
                    if [[ -z "${current_value}" || "${current_value}" == "${selected_value}" ]]; then
                        printf -v "${key}" '%s' "${value}"
                    fi
                fi
            done < <(_read_credential_file_entries "${file_path}" "${search_profile}")
        fi
    fi
}

_credential_value_for_profile_key() {
    local profile_name="${1:-}"
    local target_key="${2:-}"
    local file_path="${3:-${_CRED_FILE}}"
    local key value

    [[ -n "${target_key}" && -f "${file_path}" ]] || return 0

    while IFS= read -r -d '' key && IFS= read -r -d '' value; do
        if [[ "${key}" == "${target_key}" ]]; then
            printf '%s' "${value}"
            return 0
        fi
    done < <(_read_credential_file_entries "${file_path}" "${profile_name}")
}

_selected_profile_credential_value() {
    local selected_profile=""

    selected_profile="$(resolve_credential_profile 2>/dev/null || true)"
    _credential_value_for_profile_key "${selected_profile}" "${1:-}" "${2:-${_CRED_FILE}}"
}

_search_profile_credential_value() {
    local search_profile=""

    search_profile="$(resolve_search_credential_profile 2>/dev/null || true)"
    [[ -n "${search_profile}" ]] || return 0

    _credential_value_for_profile_key "${search_profile}" "${1:-}" "${2:-${_CRED_FILE}}"
}

_profile_value_or_current() {
    local profile_name="${1:-}"
    local target_key="${2:-}"
    local profile_value=""

    if [[ -n "${profile_name}" ]]; then
        profile_value="$(_credential_value_for_profile_key "${profile_name}" "${target_key}")"
        if [[ -n "${profile_value}" ]]; then
            printf '%s' "${profile_value}"
            return 0
        fi
    fi

    printf '%s' "${!target_key-}"
}

# shellcheck disable=SC2034
load_ingest_connection_settings() {
    local ingest_profile=""

    load_splunk_connection_settings
    ingest_profile="$(resolve_ingest_credential_profile 2>/dev/null || true)"

    INGEST_SPLUNK_PROFILE="${ingest_profile}"
    INGEST_SPLUNK_HOST="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_HOST")"
    INGEST_SPLUNK_MGMT_PORT="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_MGMT_PORT")"
    INGEST_SPLUNK_SEARCH_API_URI="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_SEARCH_API_URI")"
    INGEST_SPLUNK_URI="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_URI")"
    INGEST_SPLUNK_USER="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_USER")"
    INGEST_SPLUNK_PASS="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_PASS")"
    INGEST_SPLUNK_HEC_URL="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_HEC_URL")"
    INGEST_SPLUNK_TARGET_ROLE="$(_profile_value_or_current "${ingest_profile}" "SPLUNK_TARGET_ROLE")"

    if [[ -z "${INGEST_SPLUNK_MGMT_PORT:-}" ]]; then
        INGEST_SPLUNK_MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"
    fi

    if [[ -n "${INGEST_SPLUNK_SEARCH_API_URI:-}" ]]; then
        INGEST_SPLUNK_URI="${INGEST_SPLUNK_SEARCH_API_URI}"
    elif [[ -n "${INGEST_SPLUNK_URI:-}" ]]; then
        INGEST_SPLUNK_SEARCH_API_URI="${INGEST_SPLUNK_URI}"
    elif [[ -n "${INGEST_SPLUNK_HOST:-}" ]]; then
        INGEST_SPLUNK_SEARCH_API_URI="https://${INGEST_SPLUNK_HOST}:${INGEST_SPLUNK_MGMT_PORT}"
        INGEST_SPLUNK_URI="${INGEST_SPLUNK_SEARCH_API_URI}"
    else
        INGEST_SPLUNK_SEARCH_API_URI="${SPLUNK_SEARCH_API_URI:-}"
        INGEST_SPLUNK_URI="${SPLUNK_URI:-${INGEST_SPLUNK_SEARCH_API_URI}}"
    fi
}

resolve_delivery_plane() {
    case "${SPLUNK_DELIVERY_PLANE:-auto}" in
        auto|rest|bundle)
            printf '%s' "${SPLUNK_DELIVERY_PLANE:-auto}"
            ;;
        *)
            _warn_once "_WARNED_INVALID_SPLUNK_DELIVERY_PLANE" \
                "WARNING: Ignoring invalid SPLUNK_DELIVERY_PLANE value '${SPLUNK_DELIVERY_PLANE}'. Supported values: auto, rest, bundle."
            printf '%s' "auto"
            ;;
    esac
}

load_splunk_connection_settings() {
    _load_credential_values_from_file "${_CRED_FILE}"

    SPLUNK_MGMT_PORT="${SPLUNK_MGMT_PORT:-8089}"

    if [[ -n "${SPLUNK_SEARCH_API_URI:-}" ]]; then
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    elif [[ -n "${SPLUNK_URI:-}" ]]; then
        SPLUNK_SEARCH_API_URI="${SPLUNK_URI}"
    elif [[ -n "${SPLUNK_HOST:-}" ]]; then
        SPLUNK_SEARCH_API_URI="https://${SPLUNK_HOST}:${SPLUNK_MGMT_PORT}"
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    else
        SPLUNK_SEARCH_API_URI="https://localhost:8089"
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    fi
}

splunk_host_from_uri() {
    local uri="${1:-${SPLUNK_URI:-}}"
    uri="${uri#http://}"
    uri="${uri#https://}"
    uri="${uri%%/*}"
    printf '%s' "${uri%%:*}"
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
    load_splunk_platform_settings

    if [[ -n "${_RESOLVED_SPLUNK_PLATFORM:-}" ]]; then
        printf '%s' "${_RESOLVED_SPLUNK_PLATFORM}"
        return 0
    fi

    if [[ -n "${SPLUNK_PLATFORM:-}" ]]; then
        _RESOLVED_SPLUNK_PLATFORM="${SPLUNK_PLATFORM}"
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

    printf '%s' "${_RESOLVED_SPLUNK_PLATFORM}"
}

load_splunk_platform_settings() {
    local raw_stack raw_search_head default_acs_server normalized_search_head
    local selected_search_api_uri selected_uri selected_host
    load_splunk_connection_settings

    selected_search_api_uri="$(_selected_profile_credential_value "SPLUNK_SEARCH_API_URI")"
    selected_uri="$(_selected_profile_credential_value "SPLUNK_URI")"
    selected_host="$(_selected_profile_credential_value "SPLUNK_HOST")"
    raw_stack="${SPLUNK_CLOUD_STACK:-}"
    raw_search_head="${SPLUNK_CLOUD_SEARCH_HEAD:-}"

    default_acs_server="https://admin.splunk.com"
    if _is_staging_splunk_cloud_host "${selected_search_api_uri}" \
        || _is_staging_splunk_cloud_host "${selected_uri}" \
        || _is_staging_splunk_cloud_host "${selected_host}" \
        || _is_staging_splunk_cloud_host "${SPLUNK_URI:-}" \
        || _is_staging_splunk_cloud_host "${SPLUNK_HOST:-}" \
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
        elif [[ "${raw_search_head}" == *".splunkcloud.com"* ]]; then
            SPLUNK_CLOUD_SEARCH_HEAD=""
        fi
    fi
    SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS="${SPLUNK_CLOUD_INDEX_SEARCHABLE_DAYS:-90}"
}

is_splunk_cloud() {
    resolve_splunk_platform >/dev/null || return 1
    [[ "${_RESOLVED_SPLUNK_PLATFORM:-}" == "cloud" ]]
}

_primary_cloud_search_api_uri() {
    local configured_uri configured_host configured_port stack suffix host

    load_splunk_platform_settings

    configured_uri="$(_selected_profile_credential_value "SPLUNK_SEARCH_API_URI")"
    [[ -z "${configured_uri}" ]] && configured_uri="$(_selected_profile_credential_value "SPLUNK_URI")"
    if _is_splunk_cloud_host "${configured_uri}"; then
        printf '%s' "${configured_uri}"
        return 0
    fi

    configured_host="$(_selected_profile_credential_value "SPLUNK_HOST")"
    configured_port="$(_selected_profile_credential_value "SPLUNK_MGMT_PORT")"
    configured_port="${configured_port:-${SPLUNK_MGMT_PORT:-8089}}"
    if _is_splunk_cloud_host "${configured_host}"; then
        host="$(splunk_host_from_uri "${configured_host}")"
        printf 'https://%s:%s' "${host}" "${configured_port}"
        return 0
    fi

    stack="${SPLUNK_CLOUD_STACK:-$(_selected_profile_credential_value "SPLUNK_CLOUD_STACK")}"
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

    selected_profile="$(resolve_credential_profile 2>/dev/null || true)"
    search_profile="$(resolve_search_credential_profile 2>/dev/null || true)"

    [[ -n "${search_profile}" && "${search_profile}" != "${selected_profile}" ]]
}

_warn_invalid_target_role_once() {
    local role_value="${1:-}"
    local role_key="${2:-SPLUNK_TARGET_ROLE}"

    _warn_once "_WARNED_INVALID_SPLUNK_TARGET_ROLE" \
        "WARNING: Ignoring invalid ${role_key} value '${role_value}'. Supported roles: search-tier, indexer, heavy-forwarder, universal-forwarder, external-collector."
}

_resolve_target_role_platform_hint() {
    load_splunk_connection_settings

    if [[ -n "${SPLUNK_PLATFORM:-}" ]]; then
        printf '%s' "${SPLUNK_PLATFORM}"
        return 0
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

    if [[ -n "${_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE:-}" ]]; then
        printf '%s' "${_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    _load_credential_values_from_file "${_CRED_FILE}"
    candidate="${SPLUNK_TARGET_ROLE:-}"

    if [[ -n "${candidate}" ]]; then
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_TARGET_ROLE"
            return 0
        fi
        _RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE="${normalized}"
        printf '%s' "${_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    platform_hint="$(_resolve_target_role_platform_hint)"
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

    if [[ -n "${_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE:-}" ]]; then
        printf '%s' "${_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    _load_credential_values_from_file "${_CRED_FILE}"

    if [[ -n "${SPLUNK_SEARCH_TARGET_ROLE:-}" ]]; then
        candidate="${SPLUNK_SEARCH_TARGET_ROLE}"
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_SEARCH_TARGET_ROLE"
            return 0
        fi
        _RESOLVED_SEARCH_SPLUNK_TARGET_ROLE="${normalized}"
        printf '%s' "${_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    if ! _search_profile_role_is_active; then
        return 0
    fi

    candidate="$(_search_profile_credential_value "SPLUNK_TARGET_ROLE")"

    if [[ -n "${candidate}" ]]; then
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_TARGET_ROLE"
            return 0
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

    load_ingest_connection_settings

    candidate="${INGEST_SPLUNK_TARGET_ROLE:-}"
    if [[ -n "${candidate}" ]]; then
        if ! normalized="$(_normalize_target_role "${candidate}")"; then
            _warn_invalid_target_role_once "${candidate}" "SPLUNK_INGEST_PROFILE target role"
            return 0
        fi
        printf '%s' "${normalized}"
        return 0
    fi

    candidate="$(resolve_search_splunk_target_role)"
    if [[ -n "${candidate}" ]]; then
        printf '%s' "${candidate}"
        return 0
    fi

    resolve_splunk_target_role
}

resolve_splunk_target_role() {
    local active_role=""
    local platform_hint=""

    load_splunk_connection_settings

    if [[ -n "${_RESOLVED_SPLUNK_TARGET_ROLE:-}" ]]; then
        printf '%s' "${_RESOLVED_SPLUNK_TARGET_ROLE}"
        return 0
    fi

    platform_hint="$(_resolve_target_role_platform_hint)"

    case "${platform_hint}" in
        cloud)
            active_role="$(resolve_primary_splunk_target_role)"
            ;;
        enterprise|"")
            if _search_profile_role_is_active || { [[ -n "${SPLUNK_SEARCH_TARGET_ROLE:-}" ]] && _is_hybrid_target_config; }; then
                active_role="$(resolve_search_splunk_target_role)"
                if [[ -z "${active_role}" ]]; then
                    active_role="$(resolve_primary_splunk_target_role)"
                fi
            else
                active_role="$(resolve_primary_splunk_target_role)"
            fi
            ;;
        *)
            active_role="$(resolve_primary_splunk_target_role)"
            ;;
    esac

    if [[ -n "${active_role}" ]]; then
        _RESOLVED_SPLUNK_TARGET_ROLE="${active_role}"
        printf '%s' "${_RESOLVED_SPLUNK_TARGET_ROLE}"
    fi

    return 0
}

load_splunk_credentials() {
    load_splunk_platform_settings

    if is_splunk_cloud; then
        if [[ -z "${SPLUNK_USER:-}" && -n "${STACK_USERNAME:-}" ]]; then
            SPLUNK_USER="${STACK_USERNAME}"
        fi
        if [[ -z "${SPLUNK_PASS:-}" && -n "${STACK_PASSWORD:-}" ]]; then
            SPLUNK_PASS="${STACK_PASSWORD}"
        fi
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
        prefer_current_cloud_search_api_uri
    fi
}

load_splunkbase_credentials() {
    _load_credential_values_from_file "${_CRED_FILE}"

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

load_splunk_ssh_credentials() {
    load_splunk_connection_settings

    SPLUNK_SSH_HOST="${SPLUNK_SSH_HOST:-${SPLUNK_HOST:-$(splunk_host_from_uri "${SPLUNK_URI}")}}"
    SPLUNK_SSH_PORT="${SPLUNK_SSH_PORT:-22}"
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
