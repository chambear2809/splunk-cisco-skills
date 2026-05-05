#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings
if [[ -n "${SPLUNK_O11Y_REALM:-}" ]]; then
    export SPLUNK_O11Y_REALM
fi

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-database-monitoring-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability Database Monitoring setup

Usage:
  bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                  Render DBMon collector assets (default)
  --validate                Run static validation against rendered output
  --live                    With --validate, run read-only Kubernetes probes
  --api                     With --validate, run read-only Observability API probes
  --dry-run                 Show the render plan without writing
  --json                    Emit JSON dry-run output
  --explain                 Print plan in plain English

Options:
  --spec PATH               YAML or JSON spec (default: template.example)
  --output-dir DIR          Rendered output directory
  --realm REALM             Override spec.realm
  --cluster-name NAME       Override spec.cluster_name
  --distribution NAME       kubernetes | openshift | eks | gke | linux
  --collector-version VER   Override spec.collector.version (default v0.150.0)
  --base-values PATH        Existing Splunk OTel chart values to merge with DBMon
  --allow-unsupported-targets
                            Render lab/demo targets outside Splunk's DBMon matrix
  --live-since DURATION     Log lookback for --live (default: 2m)
  --api-metric NAME         DBMon metric for --api (default postgresql.database.count)
  --api-lookback-seconds N  SignalFlow lookback for --api (default: 600)
  --help                    Show this help

Direct secret flags rejected: --o11y-token, --access-token, --token,
--bearer-token, --api-token, --sf-token, --password, --db-password,
--datasource, --connection-string.
EOF
}

bool_text() { if [[ "$1" == "true" ]]; then printf 'true'; else printf 'false'; fi; }

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

MODE_RENDER=true
MODE_VALIDATE=false
LIVE_VALIDATE=false
API_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
REALM=""
CLUSTER_NAME=""
DISTRIBUTION=""
COLLECTOR_VERSION=""
BASE_VALUES=""
ALLOW_UNSUPPORTED_TARGETS=false
LIVE_SINCE="2m"
API_METRIC="postgresql.database.count"
API_LOOKBACK_SECONDS="600"

if [[ $# -eq 0 ]]; then usage; exit 0; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --live) LIVE_VALIDATE=true; shift ;;
        --api) API_VALIDATE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; CLUSTER_NAME="$2"; shift 2 ;;
        --distribution) require_arg "$1" "$#" || exit 1; DISTRIBUTION="$2"; shift 2 ;;
        --collector-version) require_arg "$1" "$#" || exit 1; COLLECTOR_VERSION="$2"; shift 2 ;;
        --base-values) require_arg "$1" "$#" || exit 1; BASE_VALUES="$2"; shift 2 ;;
        --allow-unsupported-targets) ALLOW_UNSUPPORTED_TARGETS=true; shift ;;
        --live-since) require_arg "$1" "$#" || exit 1; LIVE_SINCE="$2"; shift 2 ;;
        --api-metric) require_arg "$1" "$#" || exit 1; API_METRIC="$2"; shift 2 ;;
        --api-lookback-seconds) require_arg "$1" "$#" || exit 1; API_LOOKBACK_SECONDS="$2"; shift 2 ;;
        --o11y-token|--access-token|--token|--bearer-token|--api-token|--sf-token)
            reject_secret_arg "$1" "SPLUNK_O11Y_TOKEN_FILE"
            exit 1
            ;;
        --password|--db-password|--datasource|--connection-string)
            reject_secret_arg "$1" "credentials.*_env or credentials.kubernetes_secret in the spec"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
if [[ -n "${BASE_VALUES}" ]]; then
    BASE_VALUES="$(resolve_abs_path "${BASE_VALUES}")"
fi

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability Database Monitoring -- execution plan
==========================================================
  Spec:              ${SPEC}
  Output directory:  ${OUTPUT_DIR}
  Realm:             ${REALM:-<from spec or credentials>}
  Cluster:           ${CLUSTER_NAME:-<from spec>}
  Distribution:      ${DISTRIBUTION:-<from spec>}
  Collector version: ${COLLECTOR_VERSION:-<from spec, default v0.150.0>}
  Base values:       ${BASE_VALUES:-<none>}
  Unsupported mode:  ${ALLOW_UNSUPPORTED_TARGETS}
  Mode: render=$(bool_text "${MODE_RENDER}") validate=$(bool_text "${MODE_VALIDATE}") live=$(bool_text "${LIVE_VALIDATE}") api=$(bool_text "${API_VALIDATE}")
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --realm "${REALM}"
    --cluster-name "${CLUSTER_NAME}"
    --distribution "${DISTRIBUTION}"
    --collector-version "${COLLECTOR_VERSION}"
    --base-values "${BASE_VALUES}"
)
if [[ "${DRY_RUN}" == "true" ]]; then RENDER_ARGS+=(--dry-run); fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then RENDER_ARGS+=(--json); fi
if [[ "${ALLOW_UNSUPPORTED_TARGETS}" == "true" ]]; then
    RENDER_ARGS+=(--allow-unsupported-targets)
fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then exit 0; fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    VALIDATE_ARGS=(--output-dir "${OUTPUT_DIR}")
    if [[ "${LIVE_VALIDATE}" == "true" ]]; then
        VALIDATE_ARGS+=(--live --live-since "${LIVE_SINCE}")
    fi
    if [[ "${API_VALIDATE}" == "true" ]]; then
        VALIDATE_ARGS+=(--api --api-metric "${API_METRIC}" --api-lookback-seconds "${API_LOOKBACK_SECONDS}")
    fi
    bash "${SCRIPT_DIR}/validate.sh" "${VALIDATE_ARGS[@]}"
fi
