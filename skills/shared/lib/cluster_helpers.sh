#!/usr/bin/env bash
# Indexer cluster helpers for Splunk Enterprise.
# Sourced by setup/validate scripts in splunk-indexer-cluster-setup; safe to
# source elsewhere.
#
# Contract:
#   - Sourced into scripts that use 'set -euo pipefail'.
#   - Functions that check state return non-zero on "not found".
#   - Functions that perform actions return non-zero on failure.
#
# Security contract:
#   - All callers pass a Splunk session key (sk) obtained via
#     `get_session_key_from_password_file`. The admin password is read from
#     a chmod 600 file and fed to curl via `--data-urlencode @file`, never
#     placed on argv.
#   - All REST calls go through `splunk_curl` so the session key flows
#     through `-K <(...)` and stays off argv too.
#   - No helper here uses `splunk` CLI `-auth admin:pw` or `curl -u admin:pw`
#     against a Splunk management endpoint. The previous SSH+CLI patterns
#     are replaced by the REST equivalents at the cluster manager.

[[ -n "${_CLUSTER_HELPERS_LOADED:-}" ]] && return 0
_CLUSTER_HELPERS_LOADED=true

if [[ -z "${_CRED_HELPERS_LOADED:-}" ]]; then
    _CLUSTER_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # shellcheck disable=SC1091
    source "${_CLUSTER_LIB_DIR}/credential_helpers.sh"
fi

# cluster_bundle_validate <manager_uri> <sk> [check_restart]
# POST /services/cluster/manager/control/default/validate_bundle
cluster_bundle_validate() {
    local manager_uri="$1" sk="$2"
    local check_restart="${3:-false}" body=""
    if _bool_is_true "${check_restart}"; then
        body="check-restart=true"
    fi
    splunk_curl_post "${sk}" "${body}" \
        "${manager_uri}/services/cluster/manager/control/default/validate_bundle?output_mode=json"
}

# cluster_bundle_status <manager_uri> <sk>
# GET /services/cluster/manager/info exposes the bundle generation and apply
# state.
cluster_bundle_status() {
    local manager_uri="$1" sk="$2"
    splunk_curl "${sk}" \
        "${manager_uri}/services/cluster/manager/info?output_mode=json"
}

# cluster_bundle_apply <manager_uri> <sk> [--skip-validation]
# POST /services/cluster/manager/control/default/apply
cluster_bundle_apply() {
    local manager_uri="$1" sk="$2"
    shift 2
    local body=""
    if [[ "${1:-}" == "--skip-validation" ]]; then
        body="ignore_validation_errors=true"
    fi
    splunk_curl_post "${sk}" "${body}" \
        "${manager_uri}/services/cluster/manager/control/default/apply?output_mode=json"
}

# cluster_bundle_rollback <manager_uri> <sk>
cluster_bundle_rollback() {
    local manager_uri="$1" sk="$2"
    splunk_curl_post "${sk}" "" \
        "${manager_uri}/services/cluster/manager/control/default/rollback?output_mode=json"
}

# cluster_rolling_restart <manager_uri> <sk> <mode>
# mode: default | searchable | searchable-force
cluster_rolling_restart() {
    local manager_uri="$1" sk="$2" mode="${3:-default}"
    local body
    case "${mode}" in
        default)
            body=""
            ;;
        searchable)
            body="searchable=true"
            ;;
        searchable-force)
            local rit="${RESTART_INACTIVITY_TIMEOUT:-600}" dft="${DECOMMISSION_FORCE_TIMEOUT:-180}"
            body="searchable=true&force=true&restart_inactivity_timeout=${rit}&decommission_force_timeout=${dft}"
            ;;
        *)
            log "ERROR: cluster_rolling_restart mode must be default|searchable|searchable-force"
            return 1
            ;;
    esac
    splunk_curl_post "${sk}" "${body}" \
        "${manager_uri}/services/cluster/manager/control/default/rolling_restart?output_mode=json"
}

# cluster_peer_offline_fast <peer_uri> <sk> [timeout_secs]
# POST /services/cluster/peer/control/control/decommission on the *peer*'s
# own management URI. peer_uri is the peer's https://host:8089, not the
# manager's.
cluster_peer_offline_fast() {
    local peer_uri="$1" sk="$2" timeout="${3:-300}"
    splunk_curl_post "${sk}" "decommission_node_force_timeout=${timeout}" \
        "${peer_uri}/services/cluster/peer/control/control/decommission?output_mode=json"
}

# cluster_peer_offline_enforce_counts <peer_uri> <sk>
# Enforce-counts (graceful) variant of the same endpoint.
cluster_peer_offline_enforce_counts() {
    local peer_uri="$1" sk="$2"
    splunk_curl_post "${sk}" "enforce_counts=true" \
        "${peer_uri}/services/cluster/peer/control/control/decommission?output_mode=json"
}

# cluster_remove_peer <manager_uri> <sk> <peer_guid>
# POST /services/cluster/manager/control/default/remove_peers
cluster_remove_peer() {
    local manager_uri="$1" sk="$2" peer_guid="$3"
    splunk_curl_post "${sk}" "peers=${peer_guid}" \
        "${manager_uri}/services/cluster/manager/control/default/remove_peers?output_mode=json"
}

# cluster_maintenance_enable <manager_uri> <sk>
cluster_maintenance_enable() {
    local manager_uri="$1" sk="$2"
    splunk_curl_post "${sk}" "" \
        "${manager_uri}/services/cluster/manager/control/default/maintenance?output_mode=json&mode=on"
}

# cluster_maintenance_disable <manager_uri> <sk>
cluster_maintenance_disable() {
    local manager_uri="$1" sk="$2"
    splunk_curl_post "${sk}" "" \
        "${manager_uri}/services/cluster/manager/control/default/maintenance?output_mode=json&mode=off"
}

# cluster_show_status_verbose <manager_uri> <sk>
# Composite status: combine /info, /peers, /buckets summary.
cluster_show_status_verbose() {
    local manager_uri="$1" sk="$2"
    splunk_curl "${sk}" \
        "${manager_uri}/services/cluster/manager/info?output_mode=json"
    splunk_curl "${sk}" \
        "${manager_uri}/services/cluster/manager/peers?output_mode=json&count=0"
}

# cluster_audit_snapshot <manager_uri> <sk> <output_dir>
# Snapshots all read-only cluster manager REST endpoints into
# <output_dir>/<endpoint>.json with mode 0600 and the dir at 0700.
cluster_audit_snapshot() {
    local manager_uri="$1" sk="$2" output_dir="$3"
    mkdir -p "${output_dir}"
    chmod 0700 "${output_dir}" 2>/dev/null || true

    local endpoint
    for endpoint in info health peers sites buckets generation status; do
        ( umask 077 && splunk_curl "${sk}" \
            "${manager_uri}/services/cluster/manager/${endpoint}?output_mode=json&count=0" \
            > "${output_dir}/manager-${endpoint}.json" 2>/dev/null ) \
            || ( umask 077 && echo '{}' > "${output_dir}/manager-${endpoint}.json" )
    done
    ( umask 077 && cluster_bundle_status "${manager_uri}" "${sk}" \
        > "${output_dir}/cluster-bundle-status.json" 2>/dev/null ) \
        || ( umask 077 && echo '{}' > "${output_dir}/cluster-bundle-status.json" )
}
