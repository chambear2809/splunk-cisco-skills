#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-indexer-cluster-rendered"

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""

CLUSTER_MODE="single-site"
CLUSTER_LABEL="prod"
CLUSTER_MANAGER_URI=""
MANAGER_HOSTS=""
MANAGER_SSH_USER="splunk"
MANAGER_REDUNDANCY="false"
MANAGER_SWITCHOVER_MODE="disabled"
MANAGER_LB_URI=""
MANAGER_DNS_NAME=""
REPLICATION_FACTOR="3"
SEARCH_FACTOR="2"
AVAILABLE_SITES=""
SITE_REPLICATION_FACTOR="origin:2,total:3"
SITE_SEARCH_FACTOR="origin:1,total:2"
SITE_MAPPINGS=""
PEER_HOSTS=""
SH_HOSTS=""
FORWARDER_HOSTS=""
PEER_SSH_USER="splunk"
SH_SSH_USER="splunk"
REPLICATION_PORT="9887"
PERCENT_PEERS_TO_RESTART="10"
ROLLING_RESTART_DEFAULT="searchable"
INDEXER_DISCOVERY_TAG="idxc_main"
MIGRATE_KEEP_LEGACY_FACTORS="true"
ROLLING_RESTART_MODE=""
PEER_OFFLINE_MODE=""
PEER_HOST=""
PEER_GUID=""
NEW_MANAGER_URI=""
SITE=""
NEW_SITE=""
INDEXER_HOST=""
ADMIN_PASSWORD_FILE=""
IDXC_SECRET_FILE_ARG=""

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Indexer Cluster Setup

Usage: $(basename "$0") [OPTIONS]

Phases:
  render | preflight | apply | bootstrap |
  bundle-validate | bundle-status | bundle-apply | bundle-apply-skip-validation | bundle-rollback |
  rolling-restart | maintenance-enable | maintenance-disable |
  peer-offline | peer-remove | peer-extend-restart-timeout |
  migrate-to-multisite | replace-manager | decommission-site | move-peer-to-site | migrate-non-clustered |
  status | validate | all

Common options:
  --output-dir PATH
  --cluster-mode single-site|multisite
  --cluster-label NAME
  --cluster-manager-uri URI
  --manager-hosts CSV
  --manager-ssh-user USER
  --manager-redundancy true|false
  --manager-switchover-mode auto|manual|disabled
  --manager-lb-uri URI
  --manager-dns-name NAME
  --replication-factor N (single-site)
  --search-factor M (single-site)
  --available-sites CSV (multisite)
  --site-replication-factor SPEC (multisite)
  --site-search-factor SPEC (multisite)
  --site-mappings SPEC
  --peer-hosts CSV (multisite uses host=siteN)
  --sh-hosts CSV (multisite uses host=siteN)
  --forwarder-hosts CSV
  --peer-ssh-user USER
  --sh-ssh-user USER
  --replication-port PORT
  --percent-peers-to-restart N
  --rolling-restart-default searchable_force|searchable|shutdown|restart
  --indexer-discovery-tag NAME
  --rolling-restart-mode default|searchable|searchable-force
  --peer-offline-mode fast|enforce-counts
  --peer-host HOST
  --peer-guid GUID
  --new-manager-uri URI
  --site SITE
  --new-site SITE
  --indexer-host HOST
  --admin-password-file PATH
  --idxc-secret-file PATH
  --apply
  --dry-run
  --json
  --help

EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) require_arg "$1" $# || exit 1; PHASE="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --cluster-mode) require_arg "$1" $# || exit 1; CLUSTER_MODE="$2"; shift 2 ;;
        --cluster-label) require_arg "$1" $# || exit 1; CLUSTER_LABEL="$2"; shift 2 ;;
        --cluster-manager-uri) require_arg "$1" $# || exit 1; CLUSTER_MANAGER_URI="$2"; shift 2 ;;
        --manager-hosts) require_arg "$1" $# || exit 1; MANAGER_HOSTS="$2"; shift 2 ;;
        --manager-ssh-user) require_arg "$1" $# || exit 1; MANAGER_SSH_USER="$2"; shift 2 ;;
        --manager-redundancy) require_arg "$1" $# || exit 1; MANAGER_REDUNDANCY="$2"; shift 2 ;;
        --manager-switchover-mode) require_arg "$1" $# || exit 1; MANAGER_SWITCHOVER_MODE="$2"; shift 2 ;;
        --manager-lb-uri) require_arg "$1" $# || exit 1; MANAGER_LB_URI="$2"; shift 2 ;;
        --manager-dns-name) require_arg "$1" $# || exit 1; MANAGER_DNS_NAME="$2"; shift 2 ;;
        --replication-factor) require_arg "$1" $# || exit 1; REPLICATION_FACTOR="$2"; shift 2 ;;
        --search-factor) require_arg "$1" $# || exit 1; SEARCH_FACTOR="$2"; shift 2 ;;
        --available-sites) require_arg "$1" $# || exit 1; AVAILABLE_SITES="$2"; shift 2 ;;
        --site-replication-factor) require_arg "$1" $# || exit 1; SITE_REPLICATION_FACTOR="$2"; shift 2 ;;
        --site-search-factor) require_arg "$1" $# || exit 1; SITE_SEARCH_FACTOR="$2"; shift 2 ;;
        --site-mappings) require_arg "$1" $# || exit 1; SITE_MAPPINGS="$2"; shift 2 ;;
        --peer-hosts) require_arg "$1" $# || exit 1; PEER_HOSTS="$2"; shift 2 ;;
        --sh-hosts) require_arg "$1" $# || exit 1; SH_HOSTS="$2"; shift 2 ;;
        --forwarder-hosts) require_arg "$1" $# || exit 1; FORWARDER_HOSTS="$2"; shift 2 ;;
        --peer-ssh-user) require_arg "$1" $# || exit 1; PEER_SSH_USER="$2"; shift 2 ;;
        --sh-ssh-user) require_arg "$1" $# || exit 1; SH_SSH_USER="$2"; shift 2 ;;
        --replication-port) require_arg "$1" $# || exit 1; REPLICATION_PORT="$2"; shift 2 ;;
        --percent-peers-to-restart) require_arg "$1" $# || exit 1; PERCENT_PEERS_TO_RESTART="$2"; shift 2 ;;
        --rolling-restart-default) require_arg "$1" $# || exit 1; ROLLING_RESTART_DEFAULT="$2"; shift 2 ;;
        --indexer-discovery-tag) require_arg "$1" $# || exit 1; INDEXER_DISCOVERY_TAG="$2"; shift 2 ;;
        --rolling-restart-mode) require_arg "$1" $# || exit 1; ROLLING_RESTART_MODE="$2"; shift 2 ;;
        --peer-offline-mode) require_arg "$1" $# || exit 1; PEER_OFFLINE_MODE="$2"; shift 2 ;;
        --peer-host) require_arg "$1" $# || exit 1; PEER_HOST="$2"; shift 2 ;;
        --peer-guid) require_arg "$1" $# || exit 1; PEER_GUID="$2"; shift 2 ;;
        --new-manager-uri) require_arg "$1" $# || exit 1; NEW_MANAGER_URI="$2"; shift 2 ;;
        --site) require_arg "$1" $# || exit 1; SITE="$2"; shift 2 ;;
        --new-site) require_arg "$1" $# || exit 1; NEW_SITE="$2"; shift 2 ;;
        --indexer-host) require_arg "$1" $# || exit 1; INDEXER_HOST="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --idxc-secret-file) require_arg "$1" $# || exit 1; IDXC_SECRET_FILE_ARG="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

require_phase_value() {
    local flag="$1" value="$2" phase="$3"
    if [[ -z "${value}" ]]; then
        log "ERROR: ${flag} is required for ${phase}."
        exit 1
    fi
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

if [[ -z "${CLUSTER_MANAGER_URI}" ]]; then
    log "ERROR: --cluster-manager-uri is required."
    exit 1
fi

validate_choice "${CLUSTER_MODE}" single-site multisite
validate_choice "${MANAGER_REDUNDANCY}" true false
validate_choice "${MANAGER_SWITCHOVER_MODE}" auto manual disabled
validate_choice "${ROLLING_RESTART_DEFAULT}" searchable_force searchable shutdown restart

if [[ -n "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
else
    OUTPUT_DIR="$(resolve_abs_path "${_PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}")"
fi

if [[ -n "${ADMIN_PASSWORD_FILE}" ]]; then
    export SPLUNK_ADMIN_PASSWORD_FILE="${ADMIN_PASSWORD_FILE}"
fi
if [[ -n "${IDXC_SECRET_FILE_ARG}" ]]; then
    export IDXC_SECRET_FILE="${IDXC_SECRET_FILE_ARG}"
fi
export MANAGER_SSH_USER PEER_SSH_USER

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --cluster-mode "${CLUSTER_MODE}"
    --cluster-label "${CLUSTER_LABEL}"
    --cluster-manager-uri "${CLUSTER_MANAGER_URI}"
    --manager-hosts "${MANAGER_HOSTS}"
    --manager-ssh-user "${MANAGER_SSH_USER}"
    --manager-redundancy "${MANAGER_REDUNDANCY}"
    --manager-switchover-mode "${MANAGER_SWITCHOVER_MODE}"
    --manager-lb-uri "${MANAGER_LB_URI}"
    --manager-dns-name "${MANAGER_DNS_NAME}"
    --replication-factor "${REPLICATION_FACTOR}"
    --search-factor "${SEARCH_FACTOR}"
    --available-sites "${AVAILABLE_SITES}"
    --site-replication-factor "${SITE_REPLICATION_FACTOR}"
    --site-search-factor "${SITE_SEARCH_FACTOR}"
    --site-mappings "${SITE_MAPPINGS}"
    --peer-hosts "${PEER_HOSTS}"
    --sh-hosts "${SH_HOSTS}"
    --forwarder-hosts "${FORWARDER_HOSTS}"
    --peer-ssh-user "${PEER_SSH_USER}"
    --sh-ssh-user "${SH_SSH_USER}"
    --replication-port "${REPLICATION_PORT}"
    --percent-peers-to-restart "${PERCENT_PEERS_TO_RESTART}"
    --rolling-restart-default "${ROLLING_RESTART_DEFAULT}"
    --indexer-discovery-tag "${INDEXER_DISCOVERY_TAG}"
    --migrate-keep-legacy-factors "${MIGRATE_KEEP_LEGACY_FACTORS}"
)

render_dir() { printf '%s/cluster' "${OUTPUT_DIR}"; }

render_assets() {
    local extra_args=()
    [[ "${JSON_OUTPUT}" == "true" ]] && extra_args+=(--json)
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" ${extra_args[@]+"${extra_args[@]}"}
}

run_rendered() {
    local rel="$1" dir
    dir="$(render_dir)"
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: (cd ${dir} && ./${rel})"
        return 0
    fi
    if [[ ! -x "${dir}/${rel}" ]]; then
        log "ERROR: Rendered script is missing or not executable: ${dir}/${rel}"
        exit 1
    fi
    (cd "${dir}" && "./${rel}")
}

if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        exec python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run --json
    fi
    python3 "${RENDERER}" "${RENDER_ARGS[@]}" --dry-run
    exit 0
fi

case "${PHASE}" in
    render)
        render_assets
        if [[ "${APPLY}" == "true" ]]; then
            run_rendered bootstrap/sequenced-bootstrap.sh
            run_rendered validate.sh
        fi
        ;;
    preflight)
        render_assets
        log "Preflight: review ${OUTPUT_DIR}/cluster/ before apply."
        ;;
    apply|bootstrap)
        render_assets
        run_rendered bootstrap/sequenced-bootstrap.sh
        ;;
    bundle-validate) render_assets; run_rendered bundle/validate.sh ;;
    bundle-status) render_assets; run_rendered bundle/status.sh ;;
    bundle-apply) render_assets; run_rendered bundle/validate.sh; run_rendered bundle/apply.sh ;;
    bundle-apply-skip-validation) render_assets; run_rendered bundle/apply-skip-validation.sh ;;
    bundle-rollback) render_assets; run_rendered bundle/rollback.sh ;;
    rolling-restart)
        render_assets
        case "${ROLLING_RESTART_MODE:-default}" in
            default) run_rendered restart/rolling-restart.sh ;;
            searchable) run_rendered restart/searchable-rolling-restart.sh ;;
            searchable-force) run_rendered restart/force-searchable.sh ;;
            *) log "ERROR: --rolling-restart-mode must be default|searchable|searchable-force"; exit 1 ;;
        esac
        ;;
    maintenance-enable) render_assets; run_rendered maintenance/enable.sh ;;
    maintenance-disable) render_assets; run_rendered maintenance/disable.sh ;;
    peer-offline)
        render_assets
        if [[ -z "${PEER_HOST}" ]]; then
            log "ERROR: --peer-host is required for peer-offline."
            exit 1
        fi
        export PEER_HOST PEER_SSH_USER
        case "${PEER_OFFLINE_MODE:-fast}" in
            fast) run_rendered peer-ops/offline-fast.sh ;;
            enforce-counts) run_rendered peer-ops/offline-enforce-counts.sh ;;
            *) log "ERROR: --peer-offline-mode must be fast|enforce-counts"; exit 1 ;;
        esac
        ;;
    peer-remove)
        render_assets
        if [[ -z "${PEER_GUID}" ]]; then
            log "ERROR: --peer-guid is required for peer-remove."
            exit 1
        fi
        export PEER_GUID
        run_rendered peer-ops/remove-peer.sh
        ;;
    peer-extend-restart-timeout) render_assets; run_rendered peer-ops/extend-restart-timeout.sh ;;
    migrate-to-multisite) render_assets; run_rendered migration/single-to-multisite.sh ;;
    replace-manager)
        require_phase_value "--new-manager-uri" "${NEW_MANAGER_URI}" "replace-manager"
        export NEW_MANAGER_URI
        render_assets
        run_rendered migration/replace-manager.sh
        ;;
    decommission-site)
        require_phase_value "--site" "${SITE}" "decommission-site"
        export SITE
        render_assets
        run_rendered migration/decommission-site.sh
        ;;
    move-peer-to-site)
        require_phase_value "--peer-host" "${PEER_HOST}" "move-peer-to-site"
        require_phase_value "--new-site" "${NEW_SITE}" "move-peer-to-site"
        export PEER_HOST PEER_SSH_USER NEW_SITE
        render_assets
        run_rendered migration/move-peer-to-site.sh
        ;;
    migrate-non-clustered)
        require_phase_value "--indexer-host" "${INDEXER_HOST}" "migrate-non-clustered"
        export INDEXER_HOST
        render_assets
        run_rendered migration/migrate-non-clustered.sh
        ;;
    status|validate) render_assets; run_rendered validate.sh ;;
    all) render_assets; run_rendered bootstrap/sequenced-bootstrap.sh; run_rendered validate.sh ;;
    *) log "ERROR: Unknown phase '${PHASE}'"; usage 1 ;;
esac
