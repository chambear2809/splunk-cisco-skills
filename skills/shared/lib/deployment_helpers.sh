#!/usr/bin/env bash
# Shared deployment-plane helpers for clustered Enterprise, ingest targeting,
# and bundle-managed config writes.

[[ -n "${_DEPLOYMENT_HELPERS_LOADED:-}" ]] && return 0
_DEPLOYMENT_HELPERS_LOADED=true

DEPLOYMENT_SHC_APPS_DIR="${DEPLOYMENT_SHC_APPS_DIR:-etc/shcluster/apps}"
DEPLOYMENT_IDXC_APPS_DIR="${DEPLOYMENT_IDXC_APPS_DIR:-etc/manager-apps}"
DEPLOYMENT_MANAGED_INDEXES_APP="${DEPLOYMENT_MANAGED_INDEXES_APP:-ZZZ_cisco_skills_indexes}"
DEPLOYMENT_MANAGED_HEC_APP="${DEPLOYMENT_MANAGED_HEC_APP:-ZZZ_cisco_skills_hec}"

DEPLOYMENT_REST_URI=""
DEPLOYMENT_REST_SK=""

deployment_execution_mode_for_profile() {
    local profile_name="${1:-}"
    local ssh_host target_uri target_host

    if [[ -n "${profile_name}" ]]; then
        ssh_host="$(_credential_value_for_profile_key "${profile_name}" "SPLUNK_SSH_HOST")"
    else
        ssh_host="${SPLUNK_SSH_HOST:-}"
    fi
    if [[ -n "${ssh_host}" ]]; then
        case "${ssh_host}" in
            localhost|127.0.0.1) printf '%s' "local" ;;
            *) printf '%s' "ssh" ;;
        esac
        return 0
    fi

    target_uri="$(deployment_profile_uri "${profile_name}")"
    target_host="$(splunk_host_from_uri "${target_uri}")"
    case "${target_host}" in
        ""|localhost|127.0.0.1) printf '%s' "local" ;;
        *) printf '%s' "ssh" ;;
    esac
}

deployment_profile_value() {
    local profile_name="${1:-}"
    local target_key="${2:-}"
    _profile_value_or_current "${profile_name}" "${target_key}"
}

deployment_profile_uri() {
    local profile_name="${1:-}"
    local host mgmt_port uri search_api_uri

    search_api_uri="$(deployment_profile_value "${profile_name}" "SPLUNK_SEARCH_API_URI")"
    uri="$(deployment_profile_value "${profile_name}" "SPLUNK_URI")"
    host="$(deployment_profile_value "${profile_name}" "SPLUNK_HOST")"
    mgmt_port="$(deployment_profile_value "${profile_name}" "SPLUNK_MGMT_PORT")"
    [[ -z "${mgmt_port}" ]] && mgmt_port="${SPLUNK_MGMT_PORT:-8089}"

    if [[ -n "${search_api_uri}" ]]; then
        printf '%s' "${search_api_uri}"
    elif [[ -n "${uri}" ]]; then
        printf '%s' "${uri}"
    elif [[ -n "${host}" ]]; then
        printf 'https://%s:%s' "${host}" "${mgmt_port}"
    fi
}

deployment_profile_target_role() {
    local profile_name="${1:-}"
    local candidate normalized

    candidate="$(_credential_value_for_profile_key "${profile_name}" "SPLUNK_TARGET_ROLE")"
    [[ -n "${candidate}" ]] || return 0
    if normalized="$(_normalize_target_role "${candidate}")"; then
        printf '%s' "${normalized}"
    fi
}

deployment_bundle_kind_for_current_target() {
    local role
    role="$(resolve_splunk_target_role)"
    case "${role}" in
        search-tier)
            if [[ -n "$(resolve_deployer_credential_profile)" ]]; then
                printf '%s' "shc"
                return 0
            fi
            ;;
        indexer)
            if [[ -n "$(resolve_cluster_manager_credential_profile)" ]]; then
                printf '%s' "idxc"
                return 0
            fi
            ;;
    esac
}

deployment_bundle_profile_for_current_target() {
    local kind
    kind="$(deployment_bundle_kind_for_current_target)"
    case "${kind}" in
        shc) resolve_deployer_credential_profile ;;
        idxc) resolve_cluster_manager_credential_profile ;;
    esac
}

deployment_should_use_bundle_for_current_target() {
    local plane kind
    plane="$(resolve_delivery_plane)"
    kind="$(deployment_bundle_kind_for_current_target)"

    [[ -n "${kind}" ]] || return 1
    case "${plane}" in
        bundle) return 0 ;;
        auto) return 0 ;;
        *) return 1 ;;
    esac
}

deployment_should_manage_search_config_via_bundle() {
    local plane
    plane="$(resolve_delivery_plane)"
    [[ "$(resolve_splunk_target_role)" == "search-tier" ]] || return 1
    [[ -n "$(resolve_deployer_credential_profile)" ]] || return 1
    [[ "${plane}" == "bundle" || "${plane}" == "auto" ]]
}

deployment_index_bundle_profile() {
    local ingest_role plane
    ingest_role="$(resolve_ingest_target_role)"
    plane="$(resolve_delivery_plane)"
    [[ "${ingest_role}" == "indexer" ]] || return 1
    [[ -n "$(resolve_cluster_manager_credential_profile)" ]] || return 1
    [[ "${plane}" == "bundle" || "${plane}" == "auto" ]] || return 1
    resolve_cluster_manager_credential_profile
}

deployment_hec_bundle_profile() {
    deployment_index_bundle_profile
}

deployment_should_manage_ingest_hec_via_bundle() {
    deployment_hec_bundle_profile >/dev/null 2>&1
}

deployment_prepare_rest_context() {
    local profile_name="${1:-}"
    local current_sk="${2:-}"
    local current_uri="${3:-}"
    local target_uri target_user target_pass saved_user saved_pass

    DEPLOYMENT_REST_URI=""
    DEPLOYMENT_REST_SK=""

    if [[ -z "${profile_name}" ]]; then
        DEPLOYMENT_REST_URI="${current_uri:-${SPLUNK_URI:-}}"
        DEPLOYMENT_REST_SK="${current_sk:-}"
        return 0
    fi

    target_uri="$(deployment_profile_uri "${profile_name}")"
    [[ -n "${target_uri}" ]] || return 1

    if [[ -n "${current_sk}" && -n "${current_uri}" && "${target_uri}" == "${current_uri}" ]]; then
        DEPLOYMENT_REST_URI="${target_uri}"
        DEPLOYMENT_REST_SK="${current_sk}"
        return 0
    fi

    target_user="$(deployment_profile_value "${profile_name}" "SPLUNK_USER")"
    target_pass="$(deployment_profile_value "${profile_name}" "SPLUNK_PASS")"
    [[ -n "${target_user}" && -n "${target_pass}" ]] || return 1

    saved_user="${SPLUNK_USER-}"
    saved_pass="${SPLUNK_PASS-}"
    SPLUNK_USER="${target_user}"
    SPLUNK_PASS="${target_pass}"
    DEPLOYMENT_REST_SK="$(get_session_key "${target_uri}" 2>/dev/null || true)"
    SPLUNK_USER="${saved_user}"
    SPLUNK_PASS="${saved_pass}"

    [[ -n "${DEPLOYMENT_REST_SK}" ]] || return 1
    # shellcheck disable=SC2034
    DEPLOYMENT_REST_URI="${target_uri}"
}

deployment_prepare_index_rest_context() {
    local current_sk="${1:-}"
    local current_uri="${2:-}"
    local index_profile=""

    if index_profile="$(deployment_index_bundle_profile 2>/dev/null || true)" && [[ -n "${index_profile}" ]]; then
        deployment_prepare_rest_context "${index_profile}" "${current_sk}" "${current_uri}"
        return $?
    fi

    index_profile="$(resolve_ingest_credential_profile 2>/dev/null || true)"
    deployment_prepare_rest_context "${index_profile}" "${current_sk}" "${current_uri}"
}

deployment_bundle_root_for_kind() {
    local kind="${1:-}"
    local splunk_home="${2:-${SPLUNK_HOME:-/opt/splunk}}"
    case "${kind}" in
        shc) printf '%s/%s' "${splunk_home}" "${DEPLOYMENT_SHC_APPS_DIR}" ;;
        idxc) printf '%s/%s' "${splunk_home}" "${DEPLOYMENT_IDXC_APPS_DIR}" ;;
        *)
            return 1
            ;;
    esac
}

deployment_bundle_app_dir_current_profile() {
    local kind="${1:-}"
    local app_name="${2:-}"
    local target_root

    [[ -n "${kind}" && -n "${app_name}" ]] || return 1
    target_root="$(deployment_bundle_root_for_kind "${kind}")" || return 1
    printf '%s/%s' "${target_root%/}" "${app_name}"
}

deployment_bundle_app_dir_on_profile() {
    local profile_name="${1:-}"
    local kind="${2:-}"
    local app_name="${3:-}"

    deployment_run_with_profile "${profile_name}" deployment_bundle_app_dir_current_profile "${kind}" "${app_name}"
}

deployment_bundle_conf_path_current_profile() {
    local kind="${1:-}"
    local app_name="${2:-}"
    local conf_name="${3:-}"
    local app_dir

    [[ -n "${kind}" && -n "${app_name}" && -n "${conf_name}" ]] || return 1
    app_dir="$(deployment_bundle_app_dir_current_profile "${kind}" "${app_name}")" || return 1
    printf '%s/local/%s.conf' "${app_dir}" "${conf_name}"
}

deployment_bundle_conf_path_on_profile() {
    local profile_name="${1:-}"
    local kind="${2:-}"
    local app_name="${3:-}"
    local conf_name="${4:-}"

    deployment_run_with_profile "${profile_name}" deployment_bundle_conf_path_current_profile "${kind}" "${app_name}" "${conf_name}"
}

deployment_apply_profile_globals() {
    local profile_name="${1:-}"
    local key value
    local -a reset_keys=(
        SPLUNK_HOST SPLUNK_MGMT_PORT SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_SSH_HOST SPLUNK_TARGET_ROLE SPLUNK_HEC_URL
    )
    local -a keys=(
        SPLUNK_HOST SPLUNK_MGMT_PORT SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_USER SPLUNK_PASS
        SPLUNK_SSH_HOST SPLUNK_SSH_PORT SPLUNK_SSH_USER SPLUNK_SSH_PASS SPLUNK_REMOTE_TMPDIR SPLUNK_REMOTE_SUDO
        SPLUNK_TARGET_ROLE SPLUNK_HEC_URL
    )

    if [[ -n "${profile_name}" ]]; then
        for key in "${reset_keys[@]}"; do
            unset "${key}" 2>/dev/null || true
        done
    fi

    for key in "${keys[@]}"; do
        value="$(deployment_profile_value "${profile_name}" "${key}")"
        if [[ -n "${value}" ]]; then
            printf -v "${key}" '%s' "${value}"
        fi
    done

    if [[ -n "${SPLUNK_SEARCH_API_URI:-}" ]]; then
        SPLUNK_URI="${SPLUNK_SEARCH_API_URI}"
    elif [[ -n "${SPLUNK_URI:-}" ]]; then
        SPLUNK_SEARCH_API_URI="${SPLUNK_URI}"
    elif [[ -n "${SPLUNK_HOST:-}" ]]; then
        SPLUNK_URI="https://${SPLUNK_HOST}:${SPLUNK_MGMT_PORT:-8089}"
        SPLUNK_SEARCH_API_URI="${SPLUNK_URI}"
    fi
}

deployment_bundle_os_user() {
    if [[ -n "${SPLUNK_BUNDLE_OS_USER:-}" ]]; then
        printf '%s' "${SPLUNK_BUNDLE_OS_USER}"
    elif [[ -n "${SPLUNK_SSH_USER:-}" && "${SPLUNK_SSH_USER}" != "root" ]]; then
        printf '%s' "${SPLUNK_SSH_USER}"
    else
        printf '%s' "splunk"
    fi
}

deployment_run_with_profile() (
    local profile_name="${1:-}"
    shift
    load_splunk_connection_settings
    deployment_apply_profile_globals "${profile_name}"
    "$@"
)

deployment_bundle_apply_current_profile() {
    local kind="${1:-}"
    local target_uri="${2:-}"
    local auth_user="${3:-}"
    local auth_pass="${4:-}"
    local execution_mode splunk_home bundle_user apply_cmd

    execution_mode="$(deployment_execution_mode_for_profile "")"
    splunk_home="${SPLUNK_HOME:-/opt/splunk}"
    bundle_user="$(deployment_bundle_os_user)"
    [[ -n "${target_uri}" ]] || target_uri="${SPLUNK_URI:-}"
    [[ -n "${auth_user}" ]] || auth_user="${SPLUNK_USER:-}"
    [[ -n "${auth_pass}" ]] || auth_pass="${SPLUNK_PASS:-}"

    case "${kind}" in
        shc)
            [[ -n "${target_uri}" && -n "${auth_user}" && -n "${auth_pass}" ]] || return 1
            apply_cmd="$(hbs_shell_join "${splunk_home}/bin/splunk" apply shcluster-bundle -target "${target_uri}" -auth "${auth_user}:${auth_pass}" -answer-yes)"
            ;;
        idxc)
            [[ -n "${auth_user}" && -n "${auth_pass}" ]] || return 1
            apply_cmd="$(hbs_shell_join "${splunk_home}/bin/splunk" apply cluster-bundle -auth "${auth_user}:${auth_pass}" -answer-yes)"
            ;;
        *)
            return 1
            ;;
    esac

    hbs_run_as_user_cmd "${execution_mode}" "${bundle_user}" "${apply_cmd}"
}

deployment_bundle_apply_on_profile() {
    local profile_name="${1:-}"
    local kind="${2:-}"
    local target_uri="${3:-}"
    local auth_user="${4:-}"
    local auth_pass="${5:-}"

    [[ -n "${profile_name}" && -n "${kind}" ]] || return 1
    deployment_run_with_profile "${profile_name}" deployment_bundle_apply_current_profile "${kind}" "${target_uri}" "${auth_user}" "${auth_pass}"
}

deployment_capture_target_file_with_profile() {
    local profile_name="${1:-}"
    local target_path="${2:-}"
    local execution_mode

    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")"
    deployment_run_with_profile "${profile_name}" \
        hbs_capture_target_cmd "${execution_mode}" "if [[ -f $(hbs_shell_join "${target_path}") ]]; then cat $(hbs_shell_join "${target_path}"); fi"
}

deployment_conf_merge() {
    local existing_content="${1:-}"
    local stanza_name="${2:-}"
    local body="${3:-}"
    EXISTING_CONF_CONTENT="${existing_content}" python3 - "${stanza_name}" "${body}" <<'PY'
from collections import OrderedDict
from urllib.parse import parse_qsl
import os
import sys

stanza_name = sys.argv[1]
body = sys.argv[2]
existing = os.environ.get("EXISTING_CONF_CONTENT", "")

sections = OrderedDict()
current = None

for raw_line in existing.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        continue
    if line.startswith("[") and line.endswith("]"):
        current = line[1:-1].strip()
        sections.setdefault(current, OrderedDict())
        continue
    if "=" not in raw_line or current is None:
        continue
    key, value = raw_line.split("=", 1)
    sections.setdefault(current, OrderedDict())[key.strip()] = value.strip()

target = sections.setdefault(stanza_name, OrderedDict())
for key, value in parse_qsl(body, keep_blank_values=True):
    target[key] = value

for section_name, values in sections.items():
    print(f"[{section_name}]")
    for key, value in values.items():
        print(f"{key} = {value}")
    print("")
PY
}

deployment_bundle_scaffold_app_current_profile() {
    local target_root="${1:-}"
    local app_name="${2:-}"
    local execution_mode app_dir app_conf content

    execution_mode="$(deployment_execution_mode_for_profile "")"
    app_dir="${target_root%/}/${app_name}"
    app_conf="${app_dir}/default/app.conf"
    content=$'[install]\nstate = enabled\n\n[ui]\nis_visible = false\n'

    hbs_run_target_cmd "${execution_mode}" \
        "$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join mkdir -p "${app_dir}/default" "${app_dir}/local")")" >/dev/null

    if [[ "$(hbs_capture_target_cmd "${execution_mode}" "if [[ -f $(hbs_shell_join "${app_conf}") ]]; then echo yes; fi" 2>/dev/null || true)" == "yes" ]]; then
        return 0
    fi

    hbs_write_target_file "${execution_mode}" "${app_conf}" "644" "${content}" "false" >/dev/null
}

deployment_bundle_scaffold_app() {
    local profile_name="${1:-}"
    local target_root="${2:-}"
    local app_name="${3:-}"

    deployment_run_with_profile "${profile_name}" deployment_bundle_scaffold_app_current_profile "${target_root}" "${app_name}"
}

deployment_bundle_app_exists_current_profile() {
    local kind="${1:-}"
    local app_name="${2:-}"
    local execution_mode app_dir

    app_dir="$(deployment_bundle_app_dir_current_profile "${kind}" "${app_name}")" || return 1
    execution_mode="$(deployment_execution_mode_for_profile "")"
    [[ "$(hbs_capture_target_cmd "${execution_mode}" "if [[ -d $(hbs_shell_join "${app_dir}") ]]; then echo yes; fi" 2>/dev/null || true)" == "yes" ]]
}

deployment_bundle_app_exists_on_profile() {
    local profile_name="${1:-}"
    local kind="${2:-}"
    local app_name="${3:-}"

    deployment_run_with_profile "${profile_name}" deployment_bundle_app_exists_current_profile "${kind}" "${app_name}"
}

deployment_bundle_app_exists_for_current_target() {
    local profile_name kind

    profile_name="$(deployment_bundle_profile_for_current_target)"
    kind="$(deployment_bundle_kind_for_current_target)"
    [[ -n "${profile_name}" && -n "${kind}" ]] || return 1
    deployment_bundle_app_exists_on_profile "${profile_name}" "${kind}" "${1:-}"
}

deployment_bundle_write_conf_content_on_profile() {
    local profile_name="${1:-}"
    local kind="${2:-}"
    local app_name="${3:-}"
    local conf_name="${4:-}"
    local conf_content="${5:-}"
    local target_root target_path execution_mode

    [[ -n "${profile_name}" && -n "${kind}" && -n "${app_name}" && -n "${conf_name}" ]] || return 1

    target_root="$(deployment_run_with_profile "${profile_name}" deployment_bundle_root_for_kind "${kind}")" || return 1
    target_path="$(deployment_run_with_profile "${profile_name}" deployment_bundle_conf_path_current_profile "${kind}" "${app_name}" "${conf_name}")" || return 1
    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")"

    deployment_bundle_scaffold_app "${profile_name}" "${target_root}" "${app_name}" || return 1
    deployment_run_with_profile "${profile_name}" hbs_write_target_file "${execution_mode}" "${target_path}" "644" "${conf_content}" "false" || return 1
    deployment_bundle_apply_on_profile "${profile_name}" "${kind}" "" "" ""
}

deployment_bundle_set_conf_on_profile() {
    local profile_name="${1:-}"
    local kind="${2:-}"
    local app_name="${3:-}"
    local conf_name="${4:-}"
    local stanza_name="${5:-}"
    local body="${6:-}"
    local target_path existing_content merged_content

    [[ -n "${profile_name}" && -n "${kind}" && -n "${app_name}" && -n "${conf_name}" && -n "${stanza_name}" ]] || return 1

    target_path="$(deployment_bundle_conf_path_on_profile "${profile_name}" "${kind}" "${app_name}" "${conf_name}")" || return 1
    existing_content="$(deployment_capture_target_file_with_profile "${profile_name}" "${target_path}" 2>/dev/null || true)"
    merged_content="$(deployment_conf_merge "${existing_content}" "${stanza_name}" "${body}")" || return 1

    deployment_bundle_write_conf_content_on_profile "${profile_name}" "${kind}" "${app_name}" "${conf_name}" "${merged_content}"
}

deployment_bundle_set_conf_for_current_target() {
    local app_name="${1:-}"
    local conf_name="${2:-}"
    local stanza_name="${3:-}"
    local body="${4:-}"
    local profile_name kind

    profile_name="$(deployment_bundle_profile_for_current_target)"
    kind="$(deployment_bundle_kind_for_current_target)"
    [[ -n "${profile_name}" && -n "${kind}" ]] || return 1
    deployment_bundle_set_conf_on_profile "${profile_name}" "${kind}" "${app_name}" "${conf_name}" "${stanza_name}" "${body}"
}

deployment_create_cluster_bundle_index() {
    local index_name="${1:-}"
    local max_size="${2:-512000}"
    local index_type="${3:-event}"
    local profile_name
    local body

    profile_name="$(deployment_index_bundle_profile)" || return 1
    body="$(form_urlencode_pairs homePath "\$SPLUNK_DB/${index_name}/db" coldPath "\$SPLUNK_DB/${index_name}/colddb" thawedPath "\$SPLUNK_DB/${index_name}/thaweddb" maxTotalDataSizeMB "${max_size}" datatype "${index_type}")" || return 1
    deployment_bundle_set_conf_on_profile "${profile_name}" "idxc" "${DEPLOYMENT_MANAGED_INDEXES_APP}" "indexes" "${index_name}" "${body}"
}

deployment_generate_hec_token_value() {
    python3 - <<'PY'
import uuid

print(uuid.uuid4(), end="")
PY
}

deployment_hec_token_record_from_conf() {
    local conf_content="${1:-}"
    local token_name="${2:-}"

    EXISTING_CONF_CONTENT="${conf_content}" python3 - "${token_name}" <<'PY'
from collections import OrderedDict
import json
import os
import sys

target = sys.argv[1]
existing = os.environ.get("EXISTING_CONF_CONTENT", "")
sections = OrderedDict()
current = None

for raw_line in existing.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        continue
    if line.startswith("[") and line.endswith("]"):
        current = line[1:-1].strip()
        sections.setdefault(current, OrderedDict())
        continue
    if "=" not in raw_line or current is None:
        continue
    key, value = raw_line.split("=", 1)
    sections.setdefault(current, OrderedDict())[key.strip()] = value.strip()

aliases = [f"http://{target}", target]
stanza_name = next((alias for alias in aliases if alias in sections), "")
if not stanza_name:
    print("{}", end="")
    raise SystemExit(0)

global_values = sections.get("http", OrderedDict())
token_values = sections.get(stanza_name, OrderedDict())
default_index = token_values.get("index", "")
record = {
    "name": stanza_name,
    "disabled": str(token_values.get("disabled", global_values.get("disabled", ""))),
    "global_disabled": str(global_values.get("disabled", "")),
    "useACK": str(token_values.get("useACK", token_values.get("useAck", ""))),
    "indexes": str(token_values.get("indexes", "")),
    "default_index": str(default_index),
    "index": str(default_index),
    "token": str(token_values.get("token", "")),
}
print(json.dumps(record), end="")
PY
}

deployment_bundle_hec_inputs_content() {
    local profile_name target_path

    profile_name="$(deployment_hec_bundle_profile)" || return 1
    target_path="$(deployment_bundle_conf_path_on_profile "${profile_name}" "idxc" "${DEPLOYMENT_MANAGED_HEC_APP}" "inputs")" || return 1
    deployment_capture_target_file_with_profile "${profile_name}" "${target_path}" 2>/dev/null || true
}

deployment_get_bundle_hec_token_record() {
    local token_name="${1:-}"
    local conf_content

    [[ -n "${token_name}" ]] || return 1
    conf_content="$(deployment_bundle_hec_inputs_content)" || return 1
    deployment_hec_token_record_from_conf "${conf_content}" "${token_name}"
}

deployment_get_bundle_hec_token_state() {
    local token_name="${1:-}"
    local token_record disabled global_disabled

    token_record="$(deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null || echo "{}")"
    if [[ -z "${token_record}" || "${token_record}" == "{}" ]]; then
        printf '%s' "missing"
        return 0
    fi

    disabled="$(rest_json_field "${token_record}" "disabled")"
    global_disabled="$(rest_json_field "${token_record}" "global_disabled")"
    case "${disabled}:${global_disabled}" in
        1:*|true:*|True:*|*:1|*:true|*:True)
            printf '%s' "disabled"
            ;;
        *)
            printf '%s' "enabled"
            ;;
    esac
}

deployment_bundle_write_hec_token() {
    local token_name="${1:-}"
    local default_index="${2:-}"
    local indexes_csv="${3:-}"
    local use_ack="${4:-0}"
    local disabled_state="${5:-0}"
    local token_value="${6:-}"
    local profile_name existing_content merged_content token_body

    [[ -n "${token_name}" && -n "${default_index}" ]] || return 1
    [[ -n "${token_value}" ]] || token_value="$(deployment_generate_hec_token_value)" || return 1

    profile_name="$(deployment_hec_bundle_profile)" || return 1
    existing_content="$(deployment_bundle_hec_inputs_content)" || return 1
    merged_content="$(deployment_conf_merge "${existing_content}" "http" "disabled=0")" || return 1
    token_body="$(form_urlencode_pairs disabled "${disabled_state}" useACK "${use_ack}" index "${default_index}" token "${token_value}")" || return 1
    if [[ -n "${indexes_csv}" ]]; then
        token_body="${token_body}&$(form_urlencode_pairs indexes "${indexes_csv}")"
    fi
    merged_content="$(deployment_conf_merge "${merged_content}" "http://${token_name}" "${token_body}")" || return 1
    deployment_bundle_write_conf_content_on_profile "${profile_name}" "idxc" "${DEPLOYMENT_MANAGED_HEC_APP}" "inputs" "${merged_content}"
}

deployment_create_cluster_bundle_hec_token() {
    local token_name="${1:-}"
    local default_index="${2:-}"
    local indexes_csv="${3:-}"
    local use_ack="${4:-0}"
    local token_record token_value

    token_record="$(deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null || echo "{}")"
    token_value="$(rest_json_field "${token_record}" "token")"
    deployment_bundle_write_hec_token "${token_name}" "${default_index}" "${indexes_csv}" "${use_ack}" "0" "${token_value}"
}

deployment_enable_cluster_bundle_hec_token() {
    local token_name="${1:-}"
    local token_record default_index indexes_csv use_ack token_value

    token_record="$(deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null || echo "{}")"
    [[ -n "${token_record}" && "${token_record}" != "{}" ]] || return 1

    default_index="$(rest_json_field "${token_record}" "default_index")"
    [[ -n "${default_index}" ]] || default_index="$(rest_json_field "${token_record}" "index")"
    indexes_csv="$(rest_json_field "${token_record}" "indexes")"
    use_ack="$(rest_json_field "${token_record}" "useACK")"
    [[ -n "${use_ack}" ]] || use_ack="0"
    token_value="$(rest_json_field "${token_record}" "token")"

    deployment_bundle_write_hec_token "${token_name}" "${default_index}" "${indexes_csv}" "${use_ack}" "0" "${token_value}"
}

deployment_update_cluster_bundle_hec_token_default_index() {
    local token_name="${1:-}"
    local target_index="${2:-}"
    local token_record indexes_csv use_ack token_value disabled_state

    token_record="$(deployment_get_bundle_hec_token_record "${token_name}" 2>/dev/null || echo "{}")"
    [[ -n "${token_record}" && "${token_record}" != "{}" ]] || return 1

    indexes_csv="$(rest_json_field "${token_record}" "indexes")"
    use_ack="$(rest_json_field "${token_record}" "useACK")"
    [[ -n "${use_ack}" ]] || use_ack="0"
    token_value="$(rest_json_field "${token_record}" "token")"
    disabled_state="$(rest_json_field "${token_record}" "disabled")"
    case "${disabled_state}" in
        1|true|True) disabled_state="1" ;;
        *) disabled_state="0" ;;
    esac

    deployment_bundle_write_hec_token "${token_name}" "${target_index}" "${indexes_csv}" "${use_ack}" "${disabled_state}" "${token_value}"
}

deployment_install_app_via_bundle() {
    local file_path="${1:-}"
    local app_name="${2:-}"
    local profile_name kind execution_mode target_root staged_path
    local script_content

    profile_name="$(deployment_bundle_profile_for_current_target)"
    kind="$(deployment_bundle_kind_for_current_target)"
    [[ -n "${profile_name}" && -n "${kind}" ]] || return 1

    target_root="$(deployment_run_with_profile "${profile_name}" deployment_bundle_root_for_kind "${kind}")" || return 1
    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")"
    staged_path="$(deployment_run_with_profile "${profile_name}" hbs_stage_file_for_execution "${execution_mode}" "${file_path}" "$(basename "${file_path}").bundle.$$")" || return 1

    script_content="$(cat <<EOF
set -euo pipefail
tmp_dir="$(mktemp -d)"
trap 'rm -rf "\${tmp_dir}" $(printf '%q' "${staged_path}")' EXIT
tar -xf $(printf '%q' "${staged_path}") -C "\${tmp_dir}"
bundle_root=$(printf '%q' "${target_root}")
requested_app_name=$(printf '%q' "${app_name}")
source_dir="\${tmp_dir}/\${requested_app_name}"
if [[ ! -d "\${source_dir}" ]]; then
  first_dir="\$(find "\${tmp_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  [[ -n "\${first_dir}" ]] || exit 1
  source_dir="\${first_dir}"
fi
if [[ -n "\${requested_app_name}" ]]; then
  app_name="\${requested_app_name}"
else
  app_name="\$(basename "\${source_dir}")"
fi
mkdir -p "\${bundle_root}"
target_dir="\${bundle_root}/\${app_name}"
if [[ -e "\${target_dir}" ]]; then
  mv "\${target_dir}" "\${target_dir}.bak.\$(date '+%Y%m%d%H%M%S')"
fi
mkdir -p "\${target_dir}"
cp -R "\${source_dir}/." "\${target_dir}/"
EOF
)"

    deployment_run_with_profile "${profile_name}" hbs_run_target_cmd_with_stdin "${execution_mode}" "$(hbs_prefix_with_sudo "${execution_mode}" "bash -s --")" "${script_content}" || return 1

    deployment_bundle_apply_on_profile "${profile_name}" "${kind}" "" "" ""
}

deployment_uninstall_app_via_bundle() {
    local app_name="${1:-}"
    local profile_name kind execution_mode target_root target_dir script_content

    profile_name="$(deployment_bundle_profile_for_current_target)"
    kind="$(deployment_bundle_kind_for_current_target)"
    [[ -n "${profile_name}" && -n "${kind}" && -n "${app_name}" ]] || return 1

    target_root="$(deployment_run_with_profile "${profile_name}" deployment_bundle_root_for_kind "${kind}")" || return 1
    target_dir="${target_root%/}/${app_name}"
    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")"
    script_content="$(cat <<EOF
set -euo pipefail
target_dir=$(printf '%q' "${target_dir}")
if [[ -e "\${target_dir}" ]]; then
  mv "\${target_dir}" "\${target_dir}.removed.\$(date '+%Y%m%d%H%M%S')"
fi
EOF
)"

    deployment_run_with_profile "${profile_name}" hbs_run_target_cmd_with_stdin "${execution_mode}" "$(hbs_prefix_with_sudo "${execution_mode}" "bash -s --")" "${script_content}" || return 1

    deployment_bundle_apply_on_profile "${profile_name}" "${kind}" "" "" ""
}

deployment_set_app_visible() {
    local sk="${1:-}"
    local uri="${2:-}"
    local app_name="${3:-}"
    local visible_value="${4:-true}"
    local encoded_app_name

    if deployment_should_manage_search_config_via_bundle; then
        deployment_bundle_set_conf_for_current_target "${app_name}" "app" "ui" "is_visible=${visible_value}"
        return $?
    fi

    encoded_app_name=$(_urlencode "${app_name}")
    splunk_curl "${sk}" -X POST \
        "${uri}/services/apps/local/${encoded_app_name}" \
        -d "visible=${visible_value}" -d "output_mode=json" >/dev/null 2>&1
}
