#!/usr/bin/env bash
# Splunk platform detection, cloud stack normalization, and deployment type helpers.
# Sourced by credential_helpers.sh after credentials.sh; not intended for direct use.
#
# Depends on functions from credentials.sh (load_splunk_connection_settings,
# _selected_profile_credential_value, etc.) being available in the shell.

[[ -n "${_CREDENTIAL_PLATFORM_HELPERS_LOADED:-}" ]] && return 0
_CREDENTIAL_PLATFORM_HELPERS_LOADED=true

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
