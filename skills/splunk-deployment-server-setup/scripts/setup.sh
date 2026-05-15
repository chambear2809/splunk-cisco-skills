#!/usr/bin/env bash
set -euo pipefail

# Splunk Deployment Server Setup: primary CLI.
#
# Phase-driven UX:
#   render | preflight | bootstrap | reload | inspect |
#   ha-pair | migrate-clients | status | validate
#
# File-based secrets only. Splunk admin credentials come from the project-root
# credentials file (chmod 600). Never pass passwords as argv or env-var prefixes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-deployment-server-rendered"

PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

PHASE="render"
DRY_RUN=false
JSON_OUTPUT=false
APPLY=false
OUTPUT_DIR=""

DS_HOST=""
DS_URI=""
DS_SECONDARY_HOST=""
DS_SECONDARY_URI=""
LB_URI=""
LB_TYPE="haproxy"
FLEET_SIZE=""
PHONE_HOME_INTERVAL=""
HANDSHAKE_RETRY_INTERVAL=""
MAX_CLIENT_APPS=""
NEW_DS_URI=""
STAGED_ROLLOUT_PCT="10"
SPLUNK_HOME="/opt/splunk"
ADMIN_PASSWORD_FILE=""
ACCEPT_CASCADING_DS_WORKAROUND=false
HA_PAIR=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Deployment Server Setup

Usage: $(basename "$0") [OPTIONS]

Phases:
  render              Produce config and script assets; no live changes.
  preflight           Check DS role, deployment-apps layout, serverclass.conf parse.
  bootstrap           Enable deploy-server role and validate initial config.
  reload              POST _reload to pick up serverclass.conf changes without restart.
  inspect             Fetch client list, lag, app version drift; write fleet-report.json.
  ha-pair             Render HA pair LB config + sync scripts.
  migrate-clients     Render (and optionally execute) mass targetUri client migration.
  status              Live /services/deployment/server/clients snapshot.
  validate            Static checks + (with --live) REST health check.

Common options:
  --output-dir PATH
  --ds-host HOSTNAME                 Deployment server hostname
  --ds-uri URI                       https://host:8089
  --splunk-home PATH                 SPLUNK_HOME on DS host (default /opt/splunk)

phoneHome tuning (optional; set explicitly or use --fleet-size for recommendations):
  --fleet-size N                     Recommend phoneHome tuning for fleet of N UFs
  --phone-home-interval SECS         phoneHomeIntervalInSecs override
  --handshake-retry-interval SECS    handshakeRetryIntervalInSecs override
  --max-client-apps N                maxNumberOfClientApps override

HA pair options:
  --ha-pair                          Render HA pair configuration
  --ds-secondary-host HOSTNAME       Secondary DS hostname
  --ds-secondary-uri URI             Secondary DS https://host:8089
  --lb-uri URI                       Load balancer URI (e.g. ds-lb.example.com:8089)
  --lb-type haproxy|aws-nlb          LB type for rendered config (default haproxy)

Client migration options:
  --new-ds-uri URI                   Target DS URI for migration
  --staged-rollout-pct N             Percentage of clients to migrate per wave (default 10)

Safety gates:
  --accept-cascading-ds-workaround   Required to render cascading DS workaround recipes

File-based secrets (chmod 600 required):
  --admin-password-file PATH         Splunk admin password file (for bootstrap/reload/inspect)

Other:
  --apply                            Execute rendered scripts
  --live                             Enable live API checks in validate/inspect phases
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
        --live) RENDERER_ARGS_EXTRA+=("--live"); shift ;;
        --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --ds-host) require_arg "$1" $# || exit 1; DS_HOST="$2"; shift 2 ;;
        --ds-uri) require_arg "$1" $# || exit 1; DS_URI="$2"; shift 2 ;;
        --ds-secondary-host) require_arg "$1" $# || exit 1; DS_SECONDARY_HOST="$2"; shift 2 ;;
        --ds-secondary-uri) require_arg "$1" $# || exit 1; DS_SECONDARY_URI="$2"; shift 2 ;;
        --lb-uri) require_arg "$1" $# || exit 1; LB_URI="$2"; shift 2 ;;
        --lb-type) require_arg "$1" $# || exit 1; LB_TYPE="$2"; shift 2 ;;
        --fleet-size) require_arg "$1" $# || exit 1; FLEET_SIZE="$2"; shift 2 ;;
        --phone-home-interval) require_arg "$1" $# || exit 1; PHONE_HOME_INTERVAL="$2"; shift 2 ;;
        --handshake-retry-interval) require_arg "$1" $# || exit 1; HANDSHAKE_RETRY_INTERVAL="$2"; shift 2 ;;
        --max-client-apps) require_arg "$1" $# || exit 1; MAX_CLIENT_APPS="$2"; shift 2 ;;
        --new-ds-uri) require_arg "$1" $# || exit 1; NEW_DS_URI="$2"; shift 2 ;;
        --staged-rollout-pct) require_arg "$1" $# || exit 1; STAGED_ROLLOUT_PCT="$2"; shift 2 ;;
        --splunk-home) require_arg "$1" $# || exit 1; SPLUNK_HOME="$2"; shift 2 ;;
        --admin-password-file) require_arg "$1" $# || exit 1; ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --ha-pair) HA_PAIR=true; shift ;;
        --accept-cascading-ds-workaround) ACCEPT_CASCADING_DS_WORKAROUND=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

# Default output dir
if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}"
fi

# Validate lb-type
if [[ "${HA_PAIR}" == "true" ]]; then
    case "${LB_TYPE}" in
        haproxy|aws-nlb) ;;
        *) echo "ERROR: --lb-type must be haproxy or aws-nlb." >&2; exit 1 ;;
    esac
fi

RENDERER_ARGS=(
    "--phase" "${PHASE}"
    "--output-dir" "${OUTPUT_DIR}"
    "--splunk-home" "${SPLUNK_HOME}"
    "--staged-rollout-pct" "${STAGED_ROLLOUT_PCT}"
    "--lb-type" "${LB_TYPE}"
)

[[ -n "${DS_HOST}" ]] && RENDERER_ARGS+=("--ds-host" "${DS_HOST}")
[[ -n "${DS_URI}" ]] && RENDERER_ARGS+=("--ds-uri" "${DS_URI}")
[[ -n "${DS_SECONDARY_HOST}" ]] && RENDERER_ARGS+=("--ds-secondary-host" "${DS_SECONDARY_HOST}")
[[ -n "${DS_SECONDARY_URI}" ]] && RENDERER_ARGS+=("--ds-secondary-uri" "${DS_SECONDARY_URI}")
[[ -n "${LB_URI}" ]] && RENDERER_ARGS+=("--lb-uri" "${LB_URI}")
[[ -n "${FLEET_SIZE}" ]] && RENDERER_ARGS+=("--fleet-size" "${FLEET_SIZE}")
[[ -n "${PHONE_HOME_INTERVAL}" ]] && RENDERER_ARGS+=("--phone-home-interval" "${PHONE_HOME_INTERVAL}")
[[ -n "${HANDSHAKE_RETRY_INTERVAL}" ]] && RENDERER_ARGS+=("--handshake-retry-interval" "${HANDSHAKE_RETRY_INTERVAL}")
[[ -n "${MAX_CLIENT_APPS}" ]] && RENDERER_ARGS+=("--max-client-apps" "${MAX_CLIENT_APPS}")
[[ -n "${NEW_DS_URI}" ]] && RENDERER_ARGS+=("--new-ds-uri" "${NEW_DS_URI}")
[[ -n "${ADMIN_PASSWORD_FILE}" ]] && RENDERER_ARGS+=("--admin-password-file" "${ADMIN_PASSWORD_FILE}")
[[ "${HA_PAIR}" == "true" ]] && RENDERER_ARGS+=("--ha-pair")
[[ "${ACCEPT_CASCADING_DS_WORKAROUND}" == "true" ]] && RENDERER_ARGS+=("--accept-cascading-ds-workaround")
[[ "${APPLY}" == "true" ]] && RENDERER_ARGS+=("--apply")
[[ "${DRY_RUN}" == "true" ]] && RENDERER_ARGS+=("--dry-run")
[[ "${JSON_OUTPUT}" == "true" ]] && RENDERER_ARGS+=("--json")

# Append any extra args collected during parsing (e.g. --live)
if [[ -n "${RENDERER_ARGS_EXTRA[*]+x}" ]]; then
    RENDERER_ARGS+=("${RENDERER_ARGS_EXTRA[@]}")
fi

exec "${PYTHON_BIN}" "${RENDERER}" "${RENDERER_ARGS[@]}"
