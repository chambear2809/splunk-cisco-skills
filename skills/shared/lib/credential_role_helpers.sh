#!/usr/bin/env bash
# Target role resolution for Splunk deployments (search-tier, indexer, etc.).
# Sourced by credential_helpers.sh after credentials.sh and
# credential_platform_helpers.sh; not intended for direct use.
#
# Depends on functions from credentials.sh (_load_credential_values_from_file,
# resolve_credential_profile, etc.) and credential_platform_helpers.sh
# (_has_cloud_target_config, _is_hybrid_target_config, etc.).

[[ -n "${_CREDENTIAL_ROLE_HELPERS_LOADED:-}" ]] && return 0
_CREDENTIAL_ROLE_HELPERS_LOADED=true

_RESOLVED_SPLUNK_TARGET_ROLE=""
_RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE=""
_RESOLVED_SEARCH_SPLUNK_TARGET_ROLE=""

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
