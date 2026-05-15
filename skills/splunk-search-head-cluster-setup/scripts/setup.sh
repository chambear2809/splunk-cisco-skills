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
  --member-host HOSTNAME             For decommission-member / remove-member

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
        --member-host) require_arg "$1" $# || exit 1; MEMBER_HOST="$2"; shift 2 ;;
        --existing-sh-host) require_arg "$1" $# || exit 1; EXISTING_SH_HOST="$2"; shift 2 ;;
        --additional-member-hosts) require_arg "$1" $# || exit 1; ADDITIONAL_MEMBER_HOSTS="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --shc-secret-file) require_arg "$1" $# || exit 1; SHC_SECRET_FILE="$2"; shift 2 ;;
        --accept-skip-validation) ACCEPT_SKIP_VALIDATION=true; shift ;;
        --accept-kvstore-reset) ACCEPT_KVSTORE_RESET=true; shift ;;
        --accept-force-restart) ACCEPT_FORCE_RESTART=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

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
[[ -n "${CAPTAIN_URI}" ]] && RENDERER_ARGS+=("--captain-uri" "${CAPTAIN_URI}")
[[ -n "${TARGET_CAPTAIN_URI}" ]] && RENDERER_ARGS+=("--target-captain-uri" "${TARGET_CAPTAIN_URI}")
[[ -n "${ADMIN_PASSWORD_FILE}" ]] && RENDERER_ARGS+=("--admin-password-file" "${ADMIN_PASSWORD_FILE}")
[[ -n "${SHC_SECRET_FILE}" ]] && RENDERER_ARGS+=("--shc-secret-file" "${SHC_SECRET_FILE}")
[[ -n "${EXISTING_SH_HOST}" ]] && RENDERER_ARGS+=("--existing-sh-host" "${EXISTING_SH_HOST}")
[[ -n "${ADDITIONAL_MEMBER_HOSTS}" ]] && RENDERER_ARGS+=("--additional-member-hosts" "${ADDITIONAL_MEMBER_HOSTS}")
[[ "${ACCEPT_SKIP_VALIDATION}" == "true" ]] && RENDERER_ARGS+=("--accept-skip-validation")
[[ "${ACCEPT_KVSTORE_RESET}" == "true" ]] && RENDERER_ARGS+=("--accept-kvstore-reset")
[[ "${ACCEPT_FORCE_RESTART}" == "true" ]] && RENDERER_ARGS+=("--accept-force-restart")
[[ "${APPLY}" == "true" ]] && RENDERER_ARGS+=("--apply")
[[ "${DRY_RUN}" == "true" ]] && RENDERER_ARGS+=("--dry-run")
[[ "${JSON_OUTPUT}" == "true" ]] && RENDERER_ARGS+=("--json")

exec "${PYTHON_BIN}" "${RENDERER}" "${RENDERER_ARGS[@]}"
