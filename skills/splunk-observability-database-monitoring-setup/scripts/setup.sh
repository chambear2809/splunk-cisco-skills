#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings
if [[ -n "${SPLUNK_O11Y_REALM:-}" ]]; then export SPLUNK_O11Y_REALM; fi

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-database-monitoring-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability Database Monitoring setup (collector/chart 0.155.0)

Usage:
  bash skills/splunk-observability-database-monitoring-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                  Render production DBMon assets (default)
  --validate                Run static validation against freshly rendered output
  --live                    Add scoped, read-only Kubernetes runtime validation
  --api                     Add read-only Observability validation and require data
  --collector-validate      Validate generated Collector config with image 0.155.0
  --apply, --apply-k8s      Render, validate, then apply the Kubernetes overlay
  --apply-linux             Render, validate, then apply the Linux fragment
  --rollback-k8s            Run the generated Helm rollback helper
  --rollback-linux          Run the generated Linux rollback helper
  --dry-run                 Never mutate. For apply, run the generated dry-run path.
  --json                    Emit JSON for a render-only dry run
  --explain                 Print the planned operation and exit

Mutation gates:
  --accept-k8s-apply        REQUIRED for --apply-k8s
  --accept-linux-apply      REQUIRED for --apply-linux
  --accept-k8s-rollback     REQUIRED for --rollback-k8s
  --accept-linux-rollback   REQUIRED for --rollback-linux
  --accept-collector-upgrade
                            REQUIRED when the installed chart is not 0.155.0
  --accept-dbmon-reconfigure
                            REQUIRED to replace/remove existing DBMon receivers or pipelines

Options:
  --spec PATH               YAML or JSON spec (default: template.example)
  --output-dir DIR          Rendered output directory
  --realm REALM             Override spec.realm
  --cluster-name NAME       Override spec.cluster_name
  --distribution NAME       kubernetes | aks | eks | eks/auto-mode |
                            gke | gke/autopilot | openshift | linux | windows
  --collector-version VER   Override collector version (default: v0.155.0)
  --base-values PATH        Existing chart values for a review-only merged artifact
  --allow-unsupported-targets
                            Explicit lab opt-in outside the support matrix
  --db-credentials-env-file PATH
                            Secret-backed env file consumed by --apply-linux
  --rollback-revision N     Explicit state-matching previous Helm revision
  --live-since DURATION     Runtime log lookback (default: 5m)
  --api-metric NAME         Ad-hoc metric to require; repeatable and requires --api-filter.
  --api-filter KEY=VALUE    SignalFlow filter; repeatable and never inferred
  --api-lookback-seconds N  SignalFlow lookback (default: 600)
  --help                    Show this help

Direct secret flags are rejected. Supply database credentials through Kubernetes
Secrets or an owner-only Linux env file, and the Observability token through
SPLUNK_O11Y_TOKEN_FILE only for --api.
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

resolve_abs_path_no_follow() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().absolute(), end="")
PY
}

MODE_RENDER=true
MODE_VALIDATE=false
MODE_APPLY_K8S=false
MODE_APPLY_LINUX=false
MODE_ROLLBACK_K8S=false
MODE_ROLLBACK_LINUX=false
LIVE_VALIDATE=false
API_VALIDATE=false
COLLECTOR_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false
ACCEPT_K8S_APPLY=false
ACCEPT_LINUX_APPLY=false
ACCEPT_K8S_ROLLBACK=false
ACCEPT_LINUX_ROLLBACK=false
ACCEPT_COLLECTOR_UPGRADE=false
ACCEPT_DBMON_RECONFIGURE=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
REALM=""
CLUSTER_NAME=""
DISTRIBUTION=""
COLLECTOR_VERSION=""
BASE_VALUES=""
DB_CREDENTIALS_ENV_FILE=""
ROLLBACK_REVISION=""
ALLOW_UNSUPPORTED_TARGETS=false
LIVE_SINCE="5m"
API_LOOKBACK_SECONDS="600"
API_METRICS=()
API_FILTERS=()

if [[ $# -eq 0 ]]; then usage; exit 0; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --live) LIVE_VALIDATE=true; MODE_VALIDATE=true; shift ;;
        --api) API_VALIDATE=true; MODE_VALIDATE=true; shift ;;
        --collector-validate) COLLECTOR_VALIDATE=true; MODE_VALIDATE=true; shift ;;
        --apply|--apply-k8s)
            MODE_APPLY_K8S=true; MODE_VALIDATE=true; MODE_RENDER=true; shift ;;
        --apply-linux)
            MODE_APPLY_LINUX=true; MODE_VALIDATE=true; MODE_RENDER=true; shift ;;
        --rollback-k8s)
            MODE_ROLLBACK_K8S=true; MODE_RENDER=false; shift ;;
        --rollback-linux)
            MODE_ROLLBACK_LINUX=true; MODE_RENDER=false; shift ;;
        --accept-k8s-apply) ACCEPT_K8S_APPLY=true; shift ;;
        --accept-linux-apply) ACCEPT_LINUX_APPLY=true; shift ;;
        --accept-k8s-rollback) ACCEPT_K8S_ROLLBACK=true; shift ;;
        --accept-linux-rollback) ACCEPT_LINUX_ROLLBACK=true; shift ;;
        --accept-collector-upgrade) ACCEPT_COLLECTOR_UPGRADE=true; shift ;;
        --accept-dbmon-reconfigure) ACCEPT_DBMON_RECONFIGURE=true; shift ;;
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
        --db-credentials-env-file)
            require_arg "$1" "$#" || exit 1; DB_CREDENTIALS_ENV_FILE="$2"; shift 2 ;;
        --rollback-revision)
            require_arg "$1" "$#" || exit 1; ROLLBACK_REVISION="$2"; shift 2 ;;
        --allow-unsupported-targets) ALLOW_UNSUPPORTED_TARGETS=true; shift ;;
        --live-since) require_arg "$1" "$#" || exit 1; LIVE_SINCE="$2"; shift 2 ;;
        --api-metric) require_arg "$1" "$#" || exit 1; API_METRICS+=("$2"); shift 2 ;;
        --api-filter) require_arg "$1" "$#" || exit 1; API_FILTERS+=("$2"); shift 2 ;;
        --api-lookback-seconds)
            require_arg "$1" "$#" || exit 1; API_LOOKBACK_SECONDS="$2"; shift 2 ;;
        --o11y-token|--access-token|--token|--bearer-token|--api-token|--sf-token)
            reject_secret_arg "$1" "SPLUNK_O11Y_TOKEN_FILE"; exit 1 ;;
        --o11y-token=*|--access-token=*|--token=*|--bearer-token=*|--api-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "SPLUNK_O11Y_TOKEN_FILE"; exit 1 ;;
        --password|--db-password|--datasource|--connection-string|--client-secret|--private-key|--api-key)
            reject_secret_arg "$1" "credentials env/Secret references"; exit 1 ;;
        --password=*|--db-password=*|--datasource=*|--connection-string=*|--client-secret=*|--private-key=*|--api-key=*)
            reject_secret_arg "${1%%=*}" "credentials env/Secret references"; exit 1 ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: ${1%%=*}"; usage; exit 1 ;;
    esac
done

action_count=0
for selected in "${MODE_APPLY_K8S}" "${MODE_APPLY_LINUX}" "${MODE_ROLLBACK_K8S}" "${MODE_ROLLBACK_LINUX}"; do
    if [[ "${selected}" == "true" ]]; then action_count=$((action_count + 1)); fi
done
if (( action_count > 1 )); then
    log "ERROR: Select only one apply or rollback action per invocation."
    exit 1
fi
if [[ "${JSON_OUTPUT}" == "true" && ( "${MODE_VALIDATE}" == "true" || ${action_count} -gt 0 ) ]]; then
    log "ERROR: --json is supported only for render-only dry runs."
    exit 1
fi
if ! [[ "${API_LOOKBACK_SECONDS}" =~ ^[1-9][0-9]*$ ]]; then
    log "ERROR: --api-lookback-seconds must be a positive integer."
    exit 1
fi
if [[ -n "${ROLLBACK_REVISION}" && ! "${ROLLBACK_REVISION}" =~ ^[1-9][0-9]*$ ]]; then
    log "ERROR: --rollback-revision must be a positive Helm revision."
    exit 1
fi

OUTPUT_DIR="$(resolve_abs_path_no_follow "${OUTPUT_DIR}")"
SPEC="$(resolve_abs_path "${SPEC}")"
if [[ -n "${BASE_VALUES}" ]]; then BASE_VALUES="$(resolve_abs_path "${BASE_VALUES}")"; fi
if [[ -n "${DB_CREDENTIALS_ENV_FILE}" ]]; then
    DB_CREDENTIALS_ENV_FILE="$(resolve_abs_path_no_follow "${DB_CREDENTIALS_ENV_FILE}")"
fi

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability Database Monitoring -- execution plan
==========================================================
  Spec:               ${SPEC}
  Output directory:   ${OUTPUT_DIR}
  Realm:              ${REALM:-<from spec or environment>}
  Cluster:            ${CLUSTER_NAME:-<from spec>}
  Distribution:       ${DISTRIBUTION:-<from spec>}
  Collector/chart:    ${COLLECTOR_VERSION:-v0.155.0} / 0.155.0
  Unsupported mode:   ${ALLOW_UNSUPPORTED_TARGETS}
  Render/validate:    $(bool_text "${MODE_RENDER}") / $(bool_text "${MODE_VALIDATE}")
  Live/API/config:    $(bool_text "${LIVE_VALIDATE}") / $(bool_text "${API_VALIDATE}") / $(bool_text "${COLLECTOR_VALIDATE}")
  Apply K8s/Linux:    $(bool_text "${MODE_APPLY_K8S}") / $(bool_text "${MODE_APPLY_LINUX}")
  Rollback K8s/Linux: $(bool_text "${MODE_ROLLBACK_K8S}") / $(bool_text "${MODE_ROLLBACK_LINUX}")
  Dry run:            ${DRY_RUN}
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
if [[ "${ALLOW_UNSUPPORTED_TARGETS}" == "true" ]]; then RENDER_ARGS+=(--allow-unsupported-targets); fi

# An apply always renders real, fresh artifacts first. --dry-run belongs to the
# generated action helper; passing it to the renderer would leave stale files.
if [[ "${DRY_RUN}" == "true" && ${action_count} -eq 0 ]]; then RENDER_ARGS+=(--dry-run); fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then RENDER_ARGS+=(--json); fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi
if [[ "${DRY_RUN}" == "true" && ${action_count} -eq 0 ]]; then exit 0; fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    VALIDATE_ARGS=(--output-dir "${OUTPUT_DIR}")
    if [[ "${LIVE_VALIDATE}" == "true" ]]; then
        VALIDATE_ARGS+=(--live --live-since "${LIVE_SINCE}")
    fi
    if [[ "${COLLECTOR_VALIDATE}" == "true" ]]; then VALIDATE_ARGS+=(--collector-validate); fi
    if [[ "${API_VALIDATE}" == "true" ]]; then
        VALIDATE_ARGS+=(--api --api-lookback-seconds "${API_LOOKBACK_SECONDS}")
        for metric in "${API_METRICS[@]}"; do VALIDATE_ARGS+=(--api-metric "${metric}"); done
        for filter in "${API_FILTERS[@]}"; do VALIDATE_ARGS+=(--api-filter "${filter}"); done
    fi
    bash "${SCRIPT_DIR}/validate.sh" "${VALIDATE_ARGS[@]}"
fi

run_helper() {
    local helper="$1"
    shift
    if [[ ! -x "${helper}" ]]; then
        log "ERROR: Generated action helper not found or executable: ${helper}"
        exit 1
    fi
    bash "${helper}" "$@"
}

if [[ "${MODE_APPLY_K8S}" == "true" ]]; then
    [[ "${ACCEPT_K8S_APPLY}" == "true" ]] || { log "ERROR: --accept-k8s-apply is required."; exit 1; }
    K8S_APPLY_DRY_RUN="${DRY_RUN}"
    export K8S_APPLY_DRY_RUN ACCEPT_K8S_APPLY ACCEPT_COLLECTOR_UPGRADE ACCEPT_DBMON_RECONFIGURE
    run_helper "${OUTPUT_DIR}/scripts/apply-dbmon-overlay.sh"
elif [[ "${MODE_APPLY_LINUX}" == "true" ]]; then
    [[ "${ACCEPT_LINUX_APPLY}" == "true" ]] || { log "ERROR: --accept-linux-apply is required."; exit 1; }
    [[ -n "${DB_CREDENTIALS_ENV_FILE}" ]] || {
        log "ERROR: --apply-linux requires --db-credentials-env-file PATH."; exit 1;
    }
    LINUX_APPLY_DRY_RUN="${DRY_RUN}"
    DBMON_ENV_FILE="${DB_CREDENTIALS_ENV_FILE}"
    export LINUX_APPLY_DRY_RUN DBMON_ENV_FILE ACCEPT_LINUX_APPLY
    run_helper "${OUTPUT_DIR}/scripts/apply-dbmon-linux.sh"
elif [[ "${MODE_ROLLBACK_K8S}" == "true" ]]; then
    [[ "${ACCEPT_K8S_ROLLBACK}" == "true" ]] || { log "ERROR: --accept-k8s-rollback is required."; exit 1; }
    [[ -x "${OUTPUT_DIR}/scripts/rollback-dbmon-k8s.sh" ]] || {
        log "ERROR: Generated Kubernetes rollback helper not found in ${OUTPUT_DIR}."; exit 1;
    }
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would execute the generated Kubernetes rollback helper."
        exit 0
    fi
    export ACCEPT_K8S_ROLLBACK
    run_helper "${OUTPUT_DIR}/scripts/rollback-dbmon-k8s.sh" "${ROLLBACK_REVISION}"
elif [[ "${MODE_ROLLBACK_LINUX}" == "true" ]]; then
    [[ "${ACCEPT_LINUX_ROLLBACK}" == "true" ]] || { log "ERROR: --accept-linux-rollback is required."; exit 1; }
    [[ -x "${OUTPUT_DIR}/scripts/rollback-dbmon-linux.sh" ]] || {
        log "ERROR: Generated Linux rollback helper not found in ${OUTPUT_DIR}."; exit 1;
    }
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would execute the generated Linux rollback helper."
        exit 0
    fi
    export ACCEPT_LINUX_ROLLBACK
    run_helper "${OUTPUT_DIR}/scripts/rollback-dbmon-linux.sh"
fi
