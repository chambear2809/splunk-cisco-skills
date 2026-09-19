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
_DEPLOYMENT_BUNDLE_CHECK_ERROR=false

deployment_profile_has_explicit_endpoint() {
    local profile_name="${1:-}"
    local key value

    [[ -n "${profile_name}" ]] || return 1
    for key in SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_HOST; do
        if ! value="$(_credential_profile_value_for_profile_key "${profile_name}" "${key}")"; then
            return 2
        fi
        [[ -n "${value}" ]] && return 0
    done
    return 1
}

deployment_execution_mode_for_profile() {
    local profile_name="${1:-}"
    local ssh_host="" target_uri target_host explicit_ssh_host="" explicit_profile_host="" explicit_endpoint=false explicit_status=0

    if [[ -n "${profile_name}" ]]; then
        if ! explicit_ssh_host="$(_credential_profile_value_for_profile_key \
            "${profile_name}" "SPLUNK_SSH_HOST")"; then
            return 1
        fi
        if deployment_profile_has_explicit_endpoint "${profile_name}"; then
            explicit_endpoint=true
        else
            explicit_status=$?
            (( explicit_status == 1 )) || return 1
        fi
        if [[ -n "${explicit_ssh_host}" ]]; then
            ssh_host="${explicit_ssh_host}"
        elif [[ "${explicit_endpoint}" != "true" ]]; then
            # A profile that supplies no endpoint may intentionally inherit the
            # current route, including its explicitly configured SSH alias.
            ssh_host="${SPLUNK_SSH_HOST:-}"
        else
            # An API URI alone does not authorize an SSH hop.  Bundle
            # operations stay local unless the profile explicitly supplies an
            # SSH host (or a host field that intentionally denotes the remote
            # machine).  This also prevents a REST-only ingest profile from
            # causing an accidental connection attempt to its API hostname.
            if ! explicit_profile_host="$(_credential_profile_value_for_profile_key \
                "${profile_name}" "SPLUNK_HOST")"; then
                return 1
            fi
            ssh_host="${explicit_profile_host}"
        fi
    else
        ssh_host="${SPLUNK_SSH_HOST:-}"
    fi
    if [[ -n "${profile_name}" && "${explicit_endpoint}" == "true" \
        && -z "${ssh_host}" ]]; then
        if ! target_uri="$(deployment_profile_uri "${profile_name}")"; then
            return 1
        fi
        target_host="$(splunk_host_from_uri "${target_uri}")"
        case "${target_host}" in
            ""|localhost|127.0.0.1)
                printf '%s' "local"
                return 0
                ;;
            *)
                echo "ERROR: Deployment profile '${profile_name}' has a remote API endpoint but no explicit SSH route; refusing local bundle execution." >&2
                return 1
                ;;
        esac
    fi
    if [[ -n "${ssh_host}" ]]; then
        case "${ssh_host}" in
            localhost|127.0.0.1) printf '%s' "local" ;;
            *) printf '%s' "ssh" ;;
        esac
        return 0
    fi

    if ! target_uri="$(deployment_profile_uri "${profile_name}")"; then
        return 1
    fi
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
    if ! _profile_endpoint_uri "${profile_name}"; then
        return 1
    fi
}

deployment_profile_target_role() {
    local profile_name="${1:-}"
    local candidate normalized

    if ! candidate="$(_credential_value_for_profile_key "${profile_name}" "SPLUNK_TARGET_ROLE")"; then
        return 1
    fi
    [[ -n "${candidate}" ]] || return 0
    if normalized="$(_normalize_target_role "${candidate}")"; then
        printf '%s' "${normalized}"
        return 0
    fi
    echo "ERROR: Profile target role is invalid; refusing deployment routing." >&2
    return 1
}

deployment_bundle_kind_for_current_target() {
    local role deployer_profile cluster_manager_profile
    if ! role="$(resolve_splunk_target_role)"; then
        return 1
    fi
    case "${role}" in
        search-tier)
            if ! deployer_profile="$(resolve_deployer_credential_profile)"; then
                return 1
            fi
            if [[ -n "${deployer_profile}" ]]; then
                printf '%s' "shc"
                return 0
            fi
            ;;
        indexer)
            if ! cluster_manager_profile="$(resolve_cluster_manager_credential_profile)"; then
                return 1
            fi
            if [[ -n "${cluster_manager_profile}" ]]; then
                printf '%s' "idxc"
                return 0
            fi
            ;;
    esac
}

deployment_bundle_profile_for_current_target() {
    local kind
    if ! kind="$(deployment_bundle_kind_for_current_target)"; then
        return 1
    fi
    case "${kind}" in
        shc) resolve_deployer_credential_profile ;;
        idxc) resolve_cluster_manager_credential_profile ;;
    esac
}

deployment_should_use_bundle_for_current_target() {
    local plane kind
    _DEPLOYMENT_BUNDLE_CHECK_ERROR=false
    # Load file-backed selectors in this shell. Resolver command substitutions
    # run in subshells, so their assignments cannot establish the delivery
    # plane used by the parent routing decision.
    if ! load_splunk_connection_settings; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if ! plane="$(resolve_delivery_plane)"; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if ! kind="$(deployment_bundle_kind_for_current_target)"; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi

    if [[ -z "${kind}" ]]; then
        if [[ "${plane}" == "bundle" ]]; then
            _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
            return 2
        fi
        return 1
    fi
    case "${plane}" in
        bundle) return 0 ;;
        auto) return 0 ;;
        *) return 1 ;;
    esac
}

deployment_should_manage_search_config_via_bundle() {
    local plane role deployer_profile
    _DEPLOYMENT_BUNDLE_CHECK_ERROR=false
    if ! load_splunk_connection_settings; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if ! role="$(resolve_splunk_target_role)"; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if ! plane="$(resolve_delivery_plane)"; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if [[ "${role}" != "search-tier" ]]; then
        if [[ "${plane}" == "bundle" ]]; then
            _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
            return 2
        fi
        return 1
    fi
    if ! deployer_profile="$(resolve_deployer_credential_profile)"; then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    if [[ -z "${deployer_profile}" ]]; then
        if [[ "${plane}" == "bundle" ]]; then
            _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
            return 2
        fi
        return 1
    fi
    [[ "${plane}" == "bundle" || "${plane}" == "auto" ]]
}

deployment_index_bundle_profile() {
    local ingest_role plane cluster_manager_profile
    # Keep the delivery plane and profile selectors in the caller's shell;
    # command substitutions below intentionally return values only.
    if ! load_splunk_connection_settings; then
        return 2
    fi
    if ! ingest_role="$(resolve_ingest_target_role)"; then
        return 2
    fi
    if ! plane="$(resolve_delivery_plane)"; then
        return 2
    fi
    if [[ "${ingest_role}" != "indexer" ]]; then
        [[ "${plane}" == "bundle" ]] && return 2
        return 1
    fi
    if ! cluster_manager_profile="$(resolve_cluster_manager_credential_profile)"; then
        return 2
    fi
    if [[ -z "${cluster_manager_profile}" ]]; then
        [[ "${plane}" == "bundle" ]] && return 2
        return 1
    fi
    [[ "${plane}" == "bundle" || "${plane}" == "auto" ]] || return 1
    printf '%s' "${cluster_manager_profile}"
}

deployment_hec_bundle_profile() {
    deployment_index_bundle_profile
}

deployment_should_manage_ingest_hec_via_bundle() {
    local bundle_status=0
    _DEPLOYMENT_BUNDLE_CHECK_ERROR=false
    if deployment_hec_bundle_profile >/dev/null; then
        return 0
    else
        bundle_status=$?
    fi
    if (( bundle_status == 2 )); then
        _DEPLOYMENT_BUNDLE_CHECK_ERROR=true
        return 2
    fi
    return 1
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

    if ! target_uri="$(deployment_profile_uri "${profile_name}")"; then
        return 1
    fi
    [[ -n "${target_uri}" ]] || return 1

    if [[ -n "${current_sk}" && -n "${current_uri}" && "${target_uri}" == "${current_uri}" ]]; then
        DEPLOYMENT_REST_URI="${target_uri}"
        DEPLOYMENT_REST_SK="${current_sk}"
        return 0
    fi

    if ! target_user="$(deployment_profile_value "${profile_name}" "SPLUNK_USER")" \
        || ! target_pass="$(deployment_profile_value "${profile_name}" "SPLUNK_PASS")"; then
        return 1
    fi
    [[ -n "${target_user}" && -n "${target_pass}" ]] || return 1

    saved_user="${SPLUNK_USER-}"
    saved_pass="${SPLUNK_PASS-}"
    SPLUNK_USER="${target_user}"
    SPLUNK_PASS="${target_pass}"
    if ! DEPLOYMENT_REST_SK="$(get_session_key "${target_uri}" 2>/dev/null)"; then
        SPLUNK_USER="${saved_user}"
        SPLUNK_PASS="${saved_pass}"
        DEPLOYMENT_REST_SK=""
        return 1
    fi
    SPLUNK_USER="${saved_user}"
    SPLUNK_PASS="${saved_pass}"

    [[ -n "${DEPLOYMENT_REST_SK}" ]] || return 1
    # shellcheck disable=SC2034
    DEPLOYMENT_REST_URI="${target_uri}"
}

deployment_prepare_index_rest_context() {
    local current_sk="${1:-}"
    local current_uri="${2:-}"
    local index_profile="" cluster_profile="" ingest_role=""
    local plane=""

    if ! load_splunk_connection_settings; then
        return 1
    fi
    if ! cluster_profile="$(resolve_cluster_manager_credential_profile)"; then
        return 1
    fi
    if ! ingest_role="$(resolve_ingest_target_role)"; then
        return 1
    fi
    if ! plane="$(resolve_delivery_plane)"; then
        return 1
    fi
    if [[ "${ingest_role}" == "indexer" && -n "${cluster_profile}" \
        && ( "${plane}" == "bundle" || "${plane}" == "auto" ) ]]; then
        if ! index_profile="$(deployment_index_bundle_profile)"; then
            return 1
        fi
        deployment_prepare_rest_context "${index_profile}" "${current_sk}" "${current_uri}"
        return $?
    fi
    if ! index_profile="$(resolve_ingest_credential_profile)"; then
        return 1
    fi
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
    local key value index endpoint_uri endpoint_host ssh_host="" ssh_port=""
    local explicit_ssh_host="" explicit_resolve=""
    local explicit_endpoint=false explicit_status=0
    local ssh_policy=preserve ssh_port_policy=preserve resolve_policy=preserve
    local -a reset_keys=(
        SPLUNK_TARGET_ROLE SPLUNK_HEC_URL SPLUNK_ALLOW_INSECURE_HTTP
    )
    local -a keys=(
        SPLUNK_USER SPLUNK_PASS SPLUNK_SSH_USER SPLUNK_SSH_PASS SPLUNK_REMOTE_TMPDIR SPLUNK_REMOTE_SUDO
        SPLUNK_TARGET_ROLE SPLUNK_HEC_URL SPLUNK_ALLOW_INSECURE_HTTP
    )
    local -a values=()

    if ! endpoint_uri="$(_profile_endpoint_uri "${profile_name}")"; then
        return 1
    fi
    if [[ -n "${profile_name}" ]]; then
        if ! explicit_ssh_host="$(_credential_profile_value_for_profile_key \
            "${profile_name}" "SPLUNK_SSH_HOST")"; then
            return 1
        fi
        if ! explicit_resolve="$(_credential_profile_value_for_profile_key \
            "${profile_name}" "SPLUNK_RESOLVE")"; then
            return 1
        fi
        if deployment_profile_has_explicit_endpoint "${profile_name}"; then
            explicit_endpoint=true
        else
            explicit_status=$?
            (( explicit_status == 1 )) || return 1
        fi
        if [[ -n "${explicit_ssh_host}" ]]; then
            ssh_host="${explicit_ssh_host}"
        elif [[ "${explicit_endpoint}" == "true" ]]; then
            # Do not splice the current target's SSH alias into a distinct
            # profile-local endpoint. Default to that endpoint's host so a
            # missing profile SSH override fails on-target rather than routing
            # a mutation to the prior host.
            ssh_host="$(splunk_host_from_uri "${endpoint_uri}")"
        elif ! ssh_host="$(deployment_profile_value "${profile_name}" "SPLUNK_SSH_HOST")"; then
            return 1
        fi
        if ! ssh_port="$(deployment_profile_value "${profile_name}" "SPLUNK_SSH_PORT")"; then
            return 1
        fi
        if [[ -n "${ssh_port}" ]]; then
            ssh_port_policy="set"
        else
            ssh_port_policy=clear
        fi
        if [[ -n "${explicit_resolve}" ]]; then
            resolve_policy="set"
        elif [[ "${explicit_endpoint}" == "true" ]]; then
            # A distinct profile-local endpoint must not retain a resolver pin
            # for the previous target unless that profile explicitly supplies
            # its own mapping.
            resolve_policy=clear
        fi
    else
        ssh_host="${SPLUNK_SSH_HOST:-}"
    fi

    for key in "${keys[@]}"; do
        if ! value="$(deployment_profile_value "${profile_name}" "${key}")"; then
            return 1
        fi
        values+=("${value}")
    done

    if [[ -n "${profile_name}" ]]; then
        for key in "${reset_keys[@]}"; do
            unset "${key}" 2>/dev/null || true
        done
    fi

    for index in "${!keys[@]}"; do
        if [[ -n "${values[$index]}" ]]; then
            printf -v "${keys[$index]}" '%s' "${values[$index]}"
        fi
    done

    if [[ -n "${endpoint_uri}" ]]; then
        endpoint_host="$(splunk_host_from_uri "${endpoint_uri}")"
        [[ -n "${endpoint_host}" ]] || return 1
        if [[ -n "${profile_name}" ]]; then
            if [[ -n "${ssh_host}" ]]; then
                ssh_policy="set"
            else
                ssh_policy=clear
            fi
        fi
        _credential_transition_runtime_route \
            "${endpoint_uri}" "${ssh_policy}" "${ssh_host}" \
            "${ssh_port_policy}" "${ssh_port}" \
            "${resolve_policy}" "${explicit_resolve}" || return 1
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
    if ! load_splunk_connection_settings; then
        return 1
    fi
    if ! deployment_apply_profile_globals "${profile_name}"; then
        return 1
    fi
    "$@"
)

deployment_bundle_apply_current_profile() {
    local kind="${1:-}"
    local target_uri="${2:-}"
    local auth_user="${3:-}"
    local auth_pass="${4:-}"
    local execution_mode splunk_home cred_file staged_cred_file apply_script

    execution_mode="$(deployment_execution_mode_for_profile "")" || return 1
    splunk_home="${SPLUNK_HOME:-/opt/splunk}"
    [[ -n "${target_uri}" ]] || target_uri="${SPLUNK_URI:-}"
    [[ -n "${auth_user}" ]] || auth_user="${SPLUNK_USER:-}"
    [[ -n "${auth_pass}" ]] || auth_pass="${SPLUNK_PASS:-}"

    case "${kind}" in
        shc)
            [[ -n "${target_uri}" && -n "${auth_user}" && -n "${auth_pass}" ]] || return 1
            _prepare_splunk_transport_for_uri \
                "${target_uri}" "Search-head-cluster bundle authentication" || return 1
            ;;
        idxc)
            [[ -n "${auth_user}" && -n "${auth_pass}" ]] || return 1
            ;;
        *)
            return 1
            ;;
    esac

    # Stage credentials as a target-local file; SSH targets cannot read a local
    # mktemp path from the remote shell.
    #
    # Use newline-delimited storage (user on line 1, password on line 2) so
    # passwords containing ':' do not corrupt the read. The remote `splunk`
    # CLI accepts the same `username\npassword\n` order on stdin.
    cred_file="$(mktemp)"
    chmod 600 "${cred_file}"
    printf '%s\n%s\n' "${auth_user}" "${auth_pass}" > "${cred_file}"
    staged_cred_file="$(hbs_stage_file_for_execution "${execution_mode}" "${cred_file}" "splunk-bundle-cred.$$")" || {
        rm -f "${cred_file}"
        return 1
    }

    case "${kind}" in
        shc)
            apply_script="$(cat <<EOF
set -euo pipefail
cred_file=$(printf '%q' "${staged_cred_file}")
trap 'rm -f "\${cred_file}"' EXIT INT TERM
{ IFS= read -r auth_user; IFS= read -r auth_pass; } < "\${cred_file}"
printf '%s\n%s\n' "\${auth_user}" "\${auth_pass}" | $(printf '%q' "${splunk_home}/bin/splunk") apply shcluster-bundle -target $(printf '%q' "${target_uri}") -answer-yes
EOF
)"
            ;;
        idxc)
            apply_script="$(cat <<EOF
set -euo pipefail
cred_file=$(printf '%q' "${staged_cred_file}")
trap 'rm -f "\${cred_file}"' EXIT INT TERM
{ IFS= read -r auth_user; IFS= read -r auth_pass; } < "\${cred_file}"
printf '%s\n%s\n' "\${auth_user}" "\${auth_pass}" | $(printf '%q' "${splunk_home}/bin/splunk") apply cluster-bundle -answer-yes
EOF
)"
            ;;
        *)
            hbs_remove_target_path "${execution_mode}" "${staged_cred_file}"
            rm -f "${cred_file}"
            return 1
            ;;
    esac

    hbs_run_target_cmd_with_stdin "${execution_mode}" "$(hbs_prefix_with_sudo "${execution_mode}" "bash -s --")" "${apply_script}"
    local rc=$?
    hbs_remove_target_path "${execution_mode}" "${staged_cred_file}"
    rm -f "${cred_file}"
    return "${rc}"
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

    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")" || return 1
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
    local execution_mode app_dir app_conf app_conf_state content

    execution_mode="$(deployment_execution_mode_for_profile "")" || return 1
    app_dir="${target_root%/}/${app_name}"
    app_conf="${app_dir}/default/app.conf"
    content=$'[install]\nstate = enabled\n\n[ui]\nis_visible = false\n'

    hbs_run_target_cmd "${execution_mode}" \
        "$(hbs_prefix_with_sudo "${execution_mode}" "$(hbs_shell_join mkdir -p "${app_dir}/default" "${app_dir}/local")")" >/dev/null \
        || return 1

    if ! app_conf_state="$(hbs_capture_target_cmd "${execution_mode}" \
        "if [[ -f $(hbs_shell_join "${app_conf}") ]]; then printf '%s' present; else printf '%s' absent; fi" \
        2>/dev/null)"; then
        return 1
    fi
    case "${app_conf_state}" in
        present) return 0 ;;
        absent) ;;
        *) return 1 ;;
    esac

    hbs_write_target_file "${execution_mode}" "${app_conf}" "644" "${content}" "false" >/dev/null \
        || return 1
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
    local execution_mode app_dir observed_state

    app_dir="$(deployment_bundle_app_dir_current_profile "${kind}" "${app_name}")" || return 2
    execution_mode="$(deployment_execution_mode_for_profile "")" || return 2
    if ! observed_state="$(hbs_capture_target_cmd "${execution_mode}" \
        "if [[ -d $(hbs_shell_join "${app_dir}") ]]; then printf '%s' present; else printf '%s' absent; fi" \
        2>/dev/null)"; then
        return 2
    fi
    case "${observed_state}" in
        present) return 0 ;;
        absent) return 1 ;;
        *) return 2 ;;
    esac
}

deployment_bundle_app_exists_on_profile() (
    local profile_name="${1:-}"
    local kind="${2:-}"
    local app_name="${3:-}"

    if ! load_splunk_connection_settings; then
        return 2
    fi
    if ! deployment_apply_profile_globals "${profile_name}"; then
        return 2
    fi
    deployment_bundle_app_exists_current_profile "${kind}" "${app_name}"
)

deployment_bundle_app_exists_for_current_target() {
    local profile_name kind

    profile_name="$(deployment_bundle_profile_for_current_target)" || return 2
    kind="$(deployment_bundle_kind_for_current_target)" || return 2
    [[ -n "${profile_name}" && -n "${kind}" ]] || return 2
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
    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")" || return 1

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
    if ! existing_content="$(deployment_capture_target_file_with_profile \
        "${profile_name}" "${target_path}" 2>/dev/null)"; then
        return 1
    fi
    merged_content="$(deployment_conf_merge "${existing_content}" "${stanza_name}" "${body}")" || return 1

    deployment_bundle_write_conf_content_on_profile "${profile_name}" "${kind}" "${app_name}" "${conf_name}" "${merged_content}"
}

deployment_bundle_set_conf_for_current_target() {
    local app_name="${1:-}"
    local conf_name="${2:-}"
    local stanza_name="${3:-}"
    local body="${4:-}"
    local profile_name kind

    profile_name="$(deployment_bundle_profile_for_current_target)" || return 1
    kind="$(deployment_bundle_kind_for_current_target)" || return 1
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

if not target or len(existing.encode("utf-8")) > 1024 * 1024:
    raise SystemExit(1)

for raw_line in existing.splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or line.startswith(";"):
        continue
    if line.startswith("[") or line.endswith("]"):
        if not (line.startswith("[") and line.endswith("]")):
            raise SystemExit(1)
        current = line[1:-1].strip()
        if not current or "[" in current or "]" in current or current in sections:
            raise SystemExit(1)
        sections[current] = OrderedDict()
        continue
    if "=" not in raw_line or current is None:
        raise SystemExit(1)
    key, value = raw_line.split("=", 1)
    key = key.strip()
    if not key or key in sections[current]:
        raise SystemExit(1)
    sections[current][key] = value.strip()

aliases = [f"http://{target}", target]
matching_stanzas = [alias for alias in aliases if alias in sections]
if not matching_stanzas:
    print("{}", end="")
    raise SystemExit(0)
if len(matching_stanzas) != 1:
    raise SystemExit(1)
stanza_name = matching_stanzas[0]

global_values = sections.get("http", OrderedDict())
token_values = sections.get(stanza_name, OrderedDict())
default_index = token_values.get("index", "")
disabled = str(token_values.get("disabled", global_values.get("disabled", "")))
global_disabled = str(global_values.get("disabled", ""))
valid_boolean_values = {"", "0", "1", "false", "true", "no", "yes", "off", "on"}
if disabled.strip().lower() not in valid_boolean_values:
    raise SystemExit(1)
if global_disabled.strip().lower() not in valid_boolean_values:
    raise SystemExit(1)
record = {
    "name": stanza_name,
    "disabled": disabled,
    "global_disabled": global_disabled,
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
    local profile_name target_path content

    profile_name="$(deployment_hec_bundle_profile)" || return 1
    target_path="$(deployment_bundle_conf_path_on_profile "${profile_name}" "idxc" "${DEPLOYMENT_MANAGED_HEC_APP}" "inputs")" || return 1
    if ! content="$(deployment_capture_target_file_with_profile \
        "${profile_name}" "${target_path}" 2>/dev/null)"; then
        return 1
    fi
    printf '%s' "${content}"
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
    local token_record disabled global_disabled disabled_normalized global_disabled_normalized

    if ! token_record="$(deployment_get_bundle_hec_token_record \
        "${token_name}" 2>/dev/null)"; then
        return 1
    fi
    if [[ -z "${token_record}" || "${token_record}" == "{}" ]]; then
        printf '%s' "missing"
        return 0
    fi

    disabled="$(rest_json_field "${token_record}" "disabled")"
    global_disabled="$(rest_json_field "${token_record}" "global_disabled")"
    disabled_normalized="$(printf '%s' "${disabled}" | tr '[:upper:]' '[:lower:]')"
    global_disabled_normalized="$(printf '%s' "${global_disabled}" | tr '[:upper:]' '[:lower:]')"
    case "${disabled_normalized}" in
        ""|0|false|no|off|1|true|yes|on) ;;
        *) return 1 ;;
    esac
    case "${global_disabled_normalized}" in
        ""|0|false|no|off|1|true|yes|on) ;;
        *) return 1 ;;
    esac
    case "${disabled_normalized}:${global_disabled_normalized}" in
        1:*|true:*|yes:*|on:*|*:1|*:true|*:yes|*:on)
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

    if ! token_record="$(deployment_get_bundle_hec_token_record \
        "${token_name}" 2>/dev/null)"; then
        return 1
    fi
    token_value="$(rest_json_field "${token_record}" "token")"
    deployment_bundle_write_hec_token "${token_name}" "${default_index}" "${indexes_csv}" "${use_ack}" "0" "${token_value}"
}

deployment_enable_cluster_bundle_hec_token() {
    local token_name="${1:-}"
    local token_record default_index indexes_csv use_ack token_value

    if ! token_record="$(deployment_get_bundle_hec_token_record \
        "${token_name}" 2>/dev/null)"; then
        return 1
    fi
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

    if ! token_record="$(deployment_get_bundle_hec_token_record \
        "${token_name}" 2>/dev/null)"; then
        return 1
    fi
    [[ -n "${token_record}" && "${token_record}" != "{}" ]] || return 1

    indexes_csv="$(rest_json_field "${token_record}" "indexes")"
    use_ack="$(rest_json_field "${token_record}" "useACK")"
    [[ -n "${use_ack}" ]] || use_ack="0"
    token_value="$(rest_json_field "${token_record}" "token")"
    disabled_state="$(rest_json_field "${token_record}" "disabled")"
    case "${disabled_state}" in
        1|true|True|yes|Yes|on|On) disabled_state="1" ;;
        ""|0|false|False|no|No|off|Off) disabled_state="0" ;;
        *) return 1 ;;
    esac

    deployment_bundle_write_hec_token "${token_name}" "${target_index}" "${indexes_csv}" "${use_ack}" "${disabled_state}" "${token_value}"
}

deployment_install_app_via_bundle() {
    local file_path="${1:-}"
    local app_name="${2:-}"
    local profile_name kind execution_mode target_root staged_path
    local script_content

    profile_name="$(deployment_bundle_profile_for_current_target)" || return 1
    kind="$(deployment_bundle_kind_for_current_target)" || return 1
    [[ -n "${profile_name}" && -n "${kind}" ]] || return 1

    target_root="$(deployment_run_with_profile "${profile_name}" deployment_bundle_root_for_kind "${kind}")" || return 1
    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")" || return 1
    staged_path="$(deployment_run_with_profile "${profile_name}" hbs_stage_file_for_execution "${execution_mode}" "${file_path}" "$(basename "${file_path}").bundle.$$")" || return 1

    # The heredoc body and the EOF terminator must remain at column 0; the body is delivered
    # verbatim to a remote bash interpreter via hbs_run_target_cmd_with_stdin.
    script_content="$(cat <<EOF
set -euo pipefail
tmp_dir="\$(mktemp -d)"
trap 'rm -rf "\${tmp_dir}" $(printf '%q' "${staged_path}")' EXIT
safe_extract_tar() {
  python3 - "\$1" "\$2" <<'PY'
import os
from pathlib import PurePosixPath
import sys
import tarfile


def fail(message):
    print(f"ERROR: Unsafe archive member: {message}", file=sys.stderr)
    sys.exit(1)


def safe_relative_path(value):
    normalized = str(value or "").replace("\\\\", "/").strip()
    path = PurePosixPath(normalized)
    return bool(normalized) and not path.is_absolute() and ".." not in path.parts


archive_path, destination = sys.argv[1], sys.argv[2]
destination = os.path.abspath(destination)
with tarfile.open(archive_path, "r:*") as archive:
    members = archive.getmembers()
    for member in members:
        if not safe_relative_path(member.name):
            fail(member.name)
        target = os.path.abspath(os.path.join(destination, member.name))
        if os.path.commonpath([destination, target]) != destination:
            fail(member.name)
        if member.isdev() or member.isfifo():
            fail(f"{member.name} uses a special file type")
        if member.issym() or member.islnk():
            if not safe_relative_path(member.linkname):
                fail(f"{member.name} -> {member.linkname}")
            link_target = os.path.abspath(os.path.join(os.path.dirname(target), member.linkname))
            if os.path.commonpath([destination, link_target]) != destination:
                fail(f"{member.name} -> {member.linkname}")
    try:
        archive.extractall(destination, members=members, filter="data")
    except TypeError:
        archive.extractall(destination, members=members)
PY
}
safe_extract_tar $(printf '%q' "${staged_path}") "\${tmp_dir}"
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

    profile_name="$(deployment_bundle_profile_for_current_target)" || return 1
    kind="$(deployment_bundle_kind_for_current_target)" || return 1
    [[ -n "${profile_name}" && -n "${kind}" && -n "${app_name}" ]] || return 1

    target_root="$(deployment_run_with_profile "${profile_name}" deployment_bundle_root_for_kind "${kind}")" || return 1
    target_dir="${target_root%/}/${app_name}"
    execution_mode="$(deployment_execution_mode_for_profile "${profile_name}")" || return 1
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
    local response http_code actual

    if deployment_should_manage_search_config_via_bundle; then
        deployment_bundle_set_conf_for_current_target "${app_name}" "app" "ui" "is_visible=${visible_value}"
        return $?
    fi
    if [[ "${_DEPLOYMENT_BUNDLE_CHECK_ERROR:-false}" == "true" ]]; then
        return 1
    fi

    response="$(splunk_curl "${sk}" -X POST \
        "${uri}/services/apps/local/${app_name}" \
        -d "visible=${visible_value}" -d "output_mode=json" \
        -w '\n%{http_code}')" || return 1
    http_code="$(printf '%s\n' "${response}" | tail -n 1)"
    case "${http_code}" in
        200|201) ;;
        *)
            echo "ERROR: setting ${app_name} visibility failed (HTTP ${http_code:-unknown})" >&2
            return 1
            ;;
    esac

    actual="$(splunk_curl "${sk}" \
        "${uri}/services/apps/local/${app_name}?output_mode=json" \
        | python3 -c '
import json, sys
payload = json.load(sys.stdin)
entry = payload.get("entry") or []
if not entry or not isinstance(entry[0].get("content"), dict):
    raise SystemExit("app metadata response did not contain entry[0].content")
value = entry[0]["content"].get("visible")
print("true" if value is True or str(value).lower() in {"true", "1"} else "false")
')" || return 1
    [[ "${actual}" == "${visible_value,,}" ]] || {
        echo "ERROR: ${app_name} visibility readback is ${actual}, expected ${visible_value}" >&2
        return 1
    }
}
