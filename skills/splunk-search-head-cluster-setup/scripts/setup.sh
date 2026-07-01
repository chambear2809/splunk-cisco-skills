#!/usr/bin/env bash
set -euo pipefail

# Splunk Search Head Cluster Setup: primary CLI.
#
# Phase-driven UX mirroring splunk-indexer-cluster-setup:
#   render | preflight | bootstrap |
#   bundle-validate | bundle-status | bundle-apply |
#   bundle-apply-skip-validation | bundle-rollback |
#   rolling-restart | transfer-captain |
#   add-member | decommission-member | remove-member |
#   kvstore-status | kvstore-reset |
#   replace-deployer | migrate-standalone-to-shc |
#   status | validate
#
# File-based secrets only. The SHC pass4SymmKey is in --shc-secret-file.
# The Splunk admin password is in --admin-password-file.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-search-head-cluster-rendered"

PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""

SHC_LABEL="prod_shc"
DEPLOYER_HOST=""
DEPLOYER_URI=""
MEMBER_HOSTS=""
NEW_MEMBER_HOST=""
MEMBER_HOST=""
MEMBER_URI=""
REPLICATION_FACTOR="3"
KVSTORE_REPLICATION_FACTOR="3"
KVSTORE_PORT="8191"
HEARTBEAT_TIMEOUT="60"
HEARTBEAT_PERIOD="5"
RESTART_INACTIVITY_TIMEOUT="600"
ROLLING_RESTART_MODE="searchable"
CAPTAIN_URI=""
TARGET_CAPTAIN_URI=""
ADMIN_PASSWORD_FILE=""
SHC_SECRET_FILE=""
EXISTING_SH_HOST=""
ADDITIONAL_MEMBER_HOSTS=""
ACCEPT_SKIP_VALIDATION=false
ACCEPT_KVSTORE_RESET=false
ACCEPT_FORCE_RESTART=false
ACCEPT_MEMBER_REMOVE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Search Head Cluster Setup

Usage: $(basename "$0") [OPTIONS]

Phases:
  render | preflight | bootstrap |
  bundle-validate | bundle-status | bundle-apply |
  bundle-apply-skip-validation | bundle-rollback |
  rolling-restart | transfer-captain |
  add-member | decommission-member | remove-member |
  kvstore-status | kvstore-reset |
  replace-deployer | migrate-standalone-to-shc |
  status | validate

Common options:
  --output-dir PATH
  --shc-label NAME                   SHC label (must match across all members)
  --deployer-host HOSTNAME
  --deployer-uri URI                 https://host:8089
  --member-hosts CSV                 Comma-separated member hostnames
  --replication-factor N             SHC replication factor (default 3; min 3)
  --kvstore-replication-factor N     KV Store replication factor (default 3)
  --kvstore-port PORT                KV Store port (default 8191)
  --heartbeat-timeout SECS           (default 60)
  --heartbeat-period SECS            (default 5)
  --restart-inactivity-timeout SECS  (default 600)

Rolling restart options:
  --rolling-restart-mode default|searchable|forced
  --captain-uri URI                  Captain's management URI
  --target-captain-uri URI           New captain for transfer-captain phase

Member operations:
  --new-member-host HOSTNAME         For add-member phase
  --member-host MEMBER_GUID          Deprecated alias for --member-guid
  --member-guid MEMBER_GUID          SHC member GUID for decommission/remove
  --member-uri URI                   Member management URI for KV Store reset

KV Store operations:
  --accept-kvstore-reset             Required for kvstore-reset phase

Migration options:
  --existing-sh-host HOSTNAME        For migrate-standalone-to-shc phase
  --additional-member-hosts CSV      New members to add during migration

File-based secrets (chmod 600 required):
  --admin-password-file PATH
  --shc-secret-file PATH

Safety gates:
  --accept-skip-validation           Required for bundle-apply-skip-validation
  --accept-force-restart             Required for forced rolling restart
  --accept-member-remove             Required for administrative member removal

Other:
  --apply                            Execute rendered scripts (used with non-render phases)
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
        --shc-label) require_arg "$1" $# || exit 1; SHC_LABEL="$2"; shift 2 ;;
        --deployer-host) require_arg "$1" $# || exit 1; DEPLOYER_HOST="$2"; shift 2 ;;
        --deployer-uri) require_arg "$1" $# || exit 1; DEPLOYER_URI="$2"; shift 2 ;;
        --member-hosts) require_arg "$1" $# || exit 1; MEMBER_HOSTS="$2"; shift 2 ;;
        --replication-factor) require_arg "$1" $# || exit 1; REPLICATION_FACTOR="$2"; shift 2 ;;
        --kvstore-replication-factor) require_arg "$1" $# || exit 1; KVSTORE_REPLICATION_FACTOR="$2"; shift 2 ;;
        --kvstore-port) require_arg "$1" $# || exit 1; KVSTORE_PORT="$2"; shift 2 ;;
        --heartbeat-timeout) require_arg "$1" $# || exit 1; HEARTBEAT_TIMEOUT="$2"; shift 2 ;;
        --heartbeat-period) require_arg "$1" $# || exit 1; HEARTBEAT_PERIOD="$2"; shift 2 ;;
        --restart-inactivity-timeout) require_arg "$1" $# || exit 1; RESTART_INACTIVITY_TIMEOUT="$2"; shift 2 ;;
        --rolling-restart-mode) require_arg "$1" $# || exit 1; ROLLING_RESTART_MODE="$2"; shift 2 ;;
        --captain-uri) require_arg "$1" $# || exit 1; CAPTAIN_URI="$2"; shift 2 ;;
        --target-captain-uri) require_arg "$1" $# || exit 1; TARGET_CAPTAIN_URI="$2"; shift 2 ;;
        --new-member-host) require_arg "$1" $# || exit 1; NEW_MEMBER_HOST="$2"; shift 2 ;;
        --member-host|--member-guid|--member-uuid) require_arg "$1" $# || exit 1; MEMBER_HOST="$2"; shift 2 ;;
        --member-uri) require_arg "$1" $# || exit 1; MEMBER_URI="$2"; shift 2 ;;
        --existing-sh-host) require_arg "$1" $# || exit 1; EXISTING_SH_HOST="$2"; shift 2 ;;
        --additional-member-hosts) require_arg "$1" $# || exit 1; ADDITIONAL_MEMBER_HOSTS="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --shc-secret-file) require_arg "$1" $# || exit 1; SHC_SECRET_FILE="$2"; shift 2 ;;
        --accept-skip-validation) ACCEPT_SKIP_VALIDATION=true; shift ;;
        --accept-kvstore-reset) ACCEPT_KVSTORE_RESET=true; shift ;;
        --accept-force-restart) ACCEPT_FORCE_RESTART=true; shift ;;
        --accept-member-remove) ACCEPT_MEMBER_REMOVE=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

case "${PHASE}" in
    render|preflight|bootstrap|bundle-validate|bundle-status|bundle-apply|bundle-apply-skip-validation|bundle-rollback|rolling-restart|transfer-captain|add-member|decommission-member|remove-member|kvstore-status|kvstore-reset|replace-deployer|migrate-standalone-to-shc|status|validate) ;;
    *) echo "ERROR: unsupported --phase '${PHASE}'." >&2; usage 1 ;;
esac

for value_name in REPLICATION_FACTOR KVSTORE_REPLICATION_FACTOR KVSTORE_PORT HEARTBEAT_TIMEOUT HEARTBEAT_PERIOD RESTART_INACTIVITY_TIMEOUT; do
    value="${!value_name}"
    if [[ ! "${value}" =~ ^[0-9]+$ ]]; then
        echo "ERROR: ${value_name} must be a positive integer." >&2
        exit 1
    fi
done
if (( KVSTORE_PORT > 65535 )); then
    echo "ERROR: KVSTORE_PORT cannot exceed 65535." >&2
    exit 1
fi
if (( HEARTBEAT_PERIOD >= HEARTBEAT_TIMEOUT )); then
    echo "ERROR: --heartbeat-period must be less than --heartbeat-timeout." >&2
    exit 1
fi
if (( REPLICATION_FACTOR < 3 || KVSTORE_REPLICATION_FACTOR < 3 )); then
    echo "ERROR: SHC and KV Store replication factors must both be at least 3." >&2
    exit 1
fi
if [[ "${PHASE}" == "bootstrap" ]]; then
    IFS=',' read -r -a _members <<< "${MEMBER_HOSTS}"
    if (( ${#_members[@]} < 3 )); then
        echo "ERROR: bootstrap requires at least three --member-hosts." >&2
        exit 1
    fi
    if (( REPLICATION_FACTOR > ${#_members[@]} || KVSTORE_REPLICATION_FACTOR > ${#_members[@]} )); then
        echo "ERROR: replication factors cannot exceed the member count." >&2
        exit 1
    fi
fi
if [[ "${PHASE}" == "add-member" && -z "${NEW_MEMBER_HOST}" ]]; then
    echo "ERROR: add-member requires --new-member-host." >&2
    exit 1
fi
if [[ "${PHASE}" == "decommission-member" || "${PHASE}" == "remove-member" ]]; then
    [[ -n "${MEMBER_HOST}" ]] || { echo "ERROR: ${PHASE} requires --member-guid." >&2; exit 1; }
fi
if [[ "${PHASE}" == "remove-member" && "${ACCEPT_MEMBER_REMOVE}" != "true" ]]; then
    echo "ERROR: remove-member requires --accept-member-remove after graceful decommission and health verification." >&2
    exit 2
fi
if [[ "${PHASE}" == "kvstore-reset" && -z "${MEMBER_URI}" ]]; then
    echo "ERROR: kvstore-reset requires --member-uri." >&2
    exit 1
fi
case "${PHASE}" in
    rolling-restart|decommission-member|remove-member|kvstore-status|status|validate)
        if [[ -z "${CAPTAIN_URI}" ]]; then
            echo "ERROR: ${PHASE} requires --captain-uri for the current captain; inventory order is not a safe substitute." >&2
            exit 1
        fi
        ;;
esac
if [[ "${JSON_OUTPUT}" == "true" && "${PHASE}" != "render" ]]; then
    echo "ERROR: --json is render-only; action phases produce operator output." >&2
    exit 1
fi
if [[ "${PHASE}" == "render" && "${APPLY}" == "true" ]]; then
    echo "ERROR: --apply with --phase render is ambiguous; select an explicit action phase." >&2
    exit 1
fi

# Validate rolling restart mode
if [[ "${PHASE}" == "rolling-restart" ]]; then
    case "${ROLLING_RESTART_MODE}" in
        default|searchable|forced) ;;
        *) echo "ERROR: --rolling-restart-mode must be default|searchable|forced." >&2; exit 1 ;;
    esac
    if [[ "${ROLLING_RESTART_MODE}" == "forced" && "${ACCEPT_FORCE_RESTART}" == "false" ]]; then
        echo "ERROR: forced rolling restart requires --accept-force-restart." >&2
        exit 1
    fi
fi

# Validate skip-validation gate
if [[ "${PHASE}" == "bundle-apply-skip-validation" && "${ACCEPT_SKIP_VALIDATION}" == "false" ]]; then
    echo "ERROR: bundle-apply-skip-validation requires --accept-skip-validation." >&2
    exit 1
fi

# Validate kvstore-reset gate
if [[ "${PHASE}" == "kvstore-reset" && "${ACCEPT_KVSTORE_RESET}" == "false" ]]; then
    echo "ERROR: kvstore-reset requires --accept-kvstore-reset." >&2
    exit 1
fi

# Default output dir
if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}"
fi

RENDERER_ARGS=(
    "--phase" "${PHASE}"
    "--output-dir" "${OUTPUT_DIR}"
    "--shc-label" "${SHC_LABEL}"
    "--replication-factor" "${REPLICATION_FACTOR}"
    "--kvstore-replication-factor" "${KVSTORE_REPLICATION_FACTOR}"
    "--kvstore-port" "${KVSTORE_PORT}"
    "--heartbeat-timeout" "${HEARTBEAT_TIMEOUT}"
    "--heartbeat-period" "${HEARTBEAT_PERIOD}"
    "--restart-inactivity-timeout" "${RESTART_INACTIVITY_TIMEOUT}"
    "--rolling-restart-mode" "${ROLLING_RESTART_MODE}"
)

[[ -n "${DEPLOYER_HOST}" ]] && RENDERER_ARGS+=("--deployer-host" "${DEPLOYER_HOST}")
[[ -n "${DEPLOYER_URI}" ]] && RENDERER_ARGS+=("--deployer-uri" "${DEPLOYER_URI}")
[[ -n "${MEMBER_HOSTS}" ]] && RENDERER_ARGS+=("--member-hosts" "${MEMBER_HOSTS}")
[[ -n "${NEW_MEMBER_HOST}" ]] && RENDERER_ARGS+=("--new-member-host" "${NEW_MEMBER_HOST}")
[[ -n "${MEMBER_HOST}" ]] && RENDERER_ARGS+=("--member-host" "${MEMBER_HOST}")
[[ -n "${MEMBER_URI}" ]] && RENDERER_ARGS+=("--member-uri" "${MEMBER_URI}")
[[ -n "${CAPTAIN_URI}" ]] && RENDERER_ARGS+=("--captain-uri" "${CAPTAIN_URI}")
[[ -n "${TARGET_CAPTAIN_URI}" ]] && RENDERER_ARGS+=("--target-captain-uri" "${TARGET_CAPTAIN_URI}")
[[ -n "${ADMIN_PASSWORD_FILE}" ]] && RENDERER_ARGS+=("--admin-password-file" "${ADMIN_PASSWORD_FILE}")
[[ -n "${SHC_SECRET_FILE}" ]] && RENDERER_ARGS+=("--shc-secret-file" "${SHC_SECRET_FILE}")
[[ -n "${EXISTING_SH_HOST}" ]] && RENDERER_ARGS+=("--existing-sh-host" "${EXISTING_SH_HOST}")
[[ -n "${ADDITIONAL_MEMBER_HOSTS}" ]] && RENDERER_ARGS+=("--additional-member-hosts" "${ADDITIONAL_MEMBER_HOSTS}")
[[ "${ACCEPT_SKIP_VALIDATION}" == "true" ]] && RENDERER_ARGS+=("--accept-skip-validation")
[[ "${ACCEPT_KVSTORE_RESET}" == "true" ]] && RENDERER_ARGS+=("--accept-kvstore-reset")
[[ "${ACCEPT_FORCE_RESTART}" == "true" ]] && RENDERER_ARGS+=("--accept-force-restart")
[[ "${JSON_OUTPUT}" == "true" ]] && RENDERER_ARGS+=("--json")

if [[ "${DRY_RUN}" == "true" ]]; then
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        python3 - "${PHASE}" "${OUTPUT_DIR}" <<'PY'
import json, sys
print(json.dumps({"skill": "splunk-search-head-cluster-setup", "phase": sys.argv[1], "output_dir": sys.argv[2], "dry_run": True}))
PY
    else
        echo "DRY RUN: would render SHC assets under ${OUTPUT_DIR}/shc and execute phase ${PHASE}."
    fi
    exit 0
fi

"${PYTHON_BIN}" "${RENDERER}" "${RENDERER_ARGS[@]}"

run_rendered() {
    local rel="$1"
    local script="${OUTPUT_DIR}/shc/${rel}"
    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "DRY RUN: ${script}"
        return 0
    fi
    if [[ ! -x "${script}" ]]; then
        echo "ERROR: rendered action is missing or not executable: ${script}" >&2
        exit 1
    fi
    "${script}"
}

case "${PHASE}" in
    render) ;;
    preflight) bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}" ;;
    bootstrap) run_rendered bootstrap/sequenced-bootstrap.sh ;;
    bundle-validate) run_rendered bundle/validate.sh ;;
    bundle-status) run_rendered bundle/status.sh ;;
    bundle-apply) run_rendered bundle/validate.sh; run_rendered bundle/apply.sh ;;
    bundle-apply-skip-validation) run_rendered bundle/apply-skip-validation.sh ;;
    bundle-rollback) run_rendered bundle/rollback.sh ;;
    rolling-restart)
        case "${ROLLING_RESTART_MODE}" in
            default) run_rendered restart/rolling-restart.sh ;;
            searchable) run_rendered restart/searchable-rolling-restart.sh ;;
            forced) export ACCEPT_FORCE_RESTART=true; run_rendered restart/force-searchable.sh ;;
        esac
        ;;
    transfer-captain) run_rendered restart/transfer-captain.sh ;;
    add-member) run_rendered members/add-member.sh ;;
    decommission-member) run_rendered members/decommission-member.sh ;;
    remove-member) run_rendered members/remove-member.sh ;;
    kvstore-status) run_rendered kvstore/status.sh ;;
    kvstore-reset) run_rendered kvstore/reset-status.sh ;;
    replace-deployer) run_rendered migration/replace-deployer.sh ;;
    migrate-standalone-to-shc) run_rendered migration/standalone-to-shc.sh ;;
    status|validate) run_rendered validate.sh ;;
esac
