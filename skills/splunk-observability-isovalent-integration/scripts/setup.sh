#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
source "${PROJECT_ROOT}/skills/shared/lib/k8s_apply_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-isovalent-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability Isovalent Integration setup

Usage:
  bash skills/splunk-observability-isovalent-integration/scripts/setup.sh [mode] [options]

Modes:
  --render               Render overlay + apply helper + handoff scripts (default)
  --validate             Run static validation against an already-rendered output
  --apply                Merge overlay onto the existing Splunk OTel collector helm
                         release values and run helm upgrade. Requires
                         --accept-k8s-apply, an existing Cilium/Tetragon install,
                         and O11Y_TOKEN_FILE env.
  --dry-run              When combined with --apply, runs helm with --dry-run.
                         Otherwise shows render plan without writing.
  --json                 Emit JSON dry-run output
  --explain              Print plan in plain English

Apply gates:
  --accept-k8s-apply     REQUIRED for --apply.

Options:
  --spec PATH            YAML or JSON spec (default: template.example)
  --output-dir DIR       Rendered output directory
  --realm REALM          Override spec.realm
  --cluster-name NAME    Override spec.cluster_name
  --distribution NAME    openshift | kubernetes | eks | gke
  --kube-context CTX     Expected current context for --apply and context for
                         --live validation; apply fails on mismatch
  --allow-current-context  With --validate --live, explicitly acknowledge the
                           current context instead of naming it (never for apply)
  --export-mode MODE     file (default) | stdout | fluentd
  --legacy-fluentd-hec   Render the DEPRECATED fluentd splunk_hec block
  --platform-hec-url URL Splunk Platform HEC URL; required with an existing
                         --platform-hec-token-file
  --platform-hec-token-file PATH  HEC token file (chmod 600 enforced)
  --render-platform-hec-helper    Hand off HEC token provisioning to splunk-hec-service-setup
  --o11y-token-file PATH O11y Org access token file (passed through to base collector)
  --live                 With --validate, require live Helm/Kubernetes checks
  --signalflow           With --validate, require current Isovalent metric series
  --splunk-search        With --validate, require current Splunk Platform events
  --production           With --validate, require the complete live + SignalFlow
                         + Splunk search production acceptance gate
  --splunk-url URL       Splunk management URL for --splunk-search (https only)
  --splunk-search-token-file PATH
                         Bearer token file for --splunk-search (chmod 600 enforced)
  --api-lookback-seconds N  API probe lookback (default: 600)
  --api-timeout-seconds N   Per-request timeout (default: 20)
  --dashboards-source DIR  Directory of upstream dashboard JSONs to copy + scrub
  --allow-loose-token-perms  Skip the chmod-600 token permission preflight (warns)
  --help                 Show this help

Direct token flags such as --access-token, --token, --bearer-token, --api-token,
--o11y-token, --sf-token, --platform-hec-token, --hec-token are rejected.
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
RENDER_EXPLICIT=false
MODE_VALIDATE=false
MODE_APPLY=false
LIVE=false
SIGNALFLOW=false
SPLUNK_SEARCH=false
PRODUCTION=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
REALM=""
CLUSTER_NAME=""
DISTRIBUTION=""
EXPORT_MODE=""
LEGACY_FLUENTD="false"
PLATFORM_HEC_URL=""
PLATFORM_HEC_TOKEN_FILE=""
RENDER_PLATFORM_HEC_HELPER="false"
O11Y_TOKEN_FILE=""
DASHBOARDS_SOURCE=""
ALLOW_LOOSE_TOKEN_PERMS=false
SPLUNK_MANAGEMENT_URL=""
SPLUNK_SEARCH_TOKEN_FILE=""
API_LOOKBACK_SECONDS="600"
API_TIMEOUT_SECONDS="20"
EXPECTED_KUBE_CONTEXT=""
ALLOW_CURRENT_CONTEXT=false

if [[ $# -eq 0 ]]; then usage; exit 0; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; RENDER_EXPLICIT=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --apply) MODE_APPLY=true; shift ;;
        --accept-k8s-apply) K8S_APPLY_ACCEPTED=true; shift ;;
        --dry-run) DRY_RUN=true; K8S_APPLY_DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; CLUSTER_NAME="$2"; shift 2 ;;
        --distribution) require_arg "$1" "$#" || exit 1; DISTRIBUTION="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; EXPECTED_KUBE_CONTEXT="$2"; shift 2 ;;
        --allow-current-context) ALLOW_CURRENT_CONTEXT=true; shift ;;
        --export-mode)
            require_arg "$1" "$#" || exit 1
            if [[ -z "$2" ]]; then log "ERROR: --export-mode requires a nonempty value."; exit 1; fi
            EXPORT_MODE="$2"
            shift 2
            ;;
        --legacy-fluentd-hec) LEGACY_FLUENTD="true"; shift ;;
        --platform-hec-url) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_URL="$2"; shift 2 ;;
        --platform-hec-token-file) require_arg "$1" "$#" || exit 1; PLATFORM_HEC_TOKEN_FILE="$2"; shift 2 ;;
        --render-platform-hec-helper) RENDER_PLATFORM_HEC_HELPER="true"; shift ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --signalflow) SIGNALFLOW=true; shift ;;
        --splunk-search) SPLUNK_SEARCH=true; shift ;;
        --production) PRODUCTION=true; shift ;;
        --splunk-url) require_arg "$1" "$#" || exit 1; SPLUNK_MANAGEMENT_URL="$2"; shift 2 ;;
        --splunk-search-token-file) require_arg "$1" "$#" || exit 1; SPLUNK_SEARCH_TOKEN_FILE="$2"; shift 2 ;;
        --api-lookback-seconds) require_arg "$1" "$#" || exit 1; API_LOOKBACK_SECONDS="$2"; shift 2 ;;
        --api-timeout-seconds) require_arg "$1" "$#" || exit 1; API_TIMEOUT_SECONDS="$2"; shift 2 ;;
        --dashboards-source) require_arg "$1" "$#" || exit 1; DASHBOARDS_SOURCE="$2"; shift 2 ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --access-token|--token|--bearer-token|--api-token|--o11y-token|--sf-token)
            reject_secret_arg "$1" "--o11y-token-file"
            exit 1
            ;;
        --access-token=*|--token=*|--bearer-token=*|--api-token=*|--o11y-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "--o11y-token-file"
            exit 1
            ;;
        --platform-hec-token|--hec-token)
            reject_secret_arg "$1" "--platform-hec-token-file"
            exit 1
            ;;
        --platform-hec-token=*|--hec-token=*)
            reject_secret_arg "${1%%=*}" "--platform-hec-token-file"
            exit 1
            ;;
        --splunk-search-token|--splunk-token)
            reject_secret_arg "$1" "--splunk-search-token-file"
            exit 1
            ;;
        --splunk-search-token=*|--splunk-token=*)
            reject_secret_arg "${1%%=*}" "--splunk-search-token-file"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ "${MODE_VALIDATE}" == "true" && "${DRY_RUN}" == "true" ]]; then
    log "ERROR: --validate cannot be combined with --dry-run; validation must execute and return real evidence."
    exit 1
fi

# Validation-only mode must inspect the packet already on disk. Re-rendering
# from the default spec here can silently replace the intended cluster identity
# and turn a production validation into a check of unrelated defaults. Keep
# explicit --render --validate composability for render-and-test workflows.
if [[ "${MODE_VALIDATE}" == "true" && "${RENDER_EXPLICIT}" != "true" && "${MODE_APPLY}" != "true" ]]; then
    MODE_RENDER=false
fi

if [[ "${MODE_VALIDATE}" != "true" && (
    "${LIVE}" == "true" || "${SIGNALFLOW}" == "true" || "${SPLUNK_SEARCH}" == "true" || "${PRODUCTION}" == "true" || "${ALLOW_CURRENT_CONTEXT}" == "true" ||
    -n "${SPLUNK_MANAGEMENT_URL}" || -n "${SPLUNK_SEARCH_TOKEN_FILE}"
) ]]; then
    log "ERROR: Live and API validation options require --validate."
    exit 1
fi
if [[ -z "${O11Y_TOKEN_FILE}" && ( "${MODE_APPLY}" == "true" || "${SIGNALFLOW}" == "true" ) ]]; then
    O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
fi

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

_check_token_perms() {
    local label="$1" path="$2"
    python3 - "${path}" "${label}" "${ALLOW_LOOSE_TOKEN_PERMS:-false}" <<'PY'
import os
import stat
import sys

path, label, allow_loose = sys.argv[1:]
try:
    info = os.lstat(path)
except OSError:
    raise SystemExit(f"ERROR: {label} must reference an existing credential file.")
if stat.S_ISLNK(info.st_mode):
    raise SystemExit(f"ERROR: {label} must not be a symbolic link.")
if not stat.S_ISREG(info.st_mode):
    raise SystemExit(f"ERROR: {label} must reference a regular file.")
if info.st_uid != os.geteuid():
    raise SystemExit(f"ERROR: {label} must be owned by the current user.")
if info.st_nlink != 1:
    raise SystemExit(f"ERROR: {label} must have exactly one hard link.")
mode = stat.S_IMODE(info.st_mode)
if mode != 0o600 and allow_loose != "true":
    raise SystemExit(f"ERROR: {label} must be mode 600.")
if info.st_size <= 0 or info.st_size > 16 * 1024:
    raise SystemExit(f"ERROR: {label} has an invalid size.")
if mode != 0o600:
    print(f"WARN: {label} is not mode 600; --allow-loose-token-perms is set.", file=sys.stderr)
PY
}

[[ -n "${O11Y_TOKEN_FILE}" ]] && { _check_token_perms "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1; }
[[ -n "${PLATFORM_HEC_TOKEN_FILE}" ]] && { _check_token_perms "--platform-hec-token-file" "${PLATFORM_HEC_TOKEN_FILE}" || exit 1; }
[[ -n "${SPLUNK_SEARCH_TOKEN_FILE}" ]] && { _check_token_perms "--splunk-search-token-file" "${SPLUNK_SEARCH_TOKEN_FILE}" || exit 1; }

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability Isovalent Integration -- execution plan
============================================================
  Spec:                     ${SPEC}
  Output directory:         ${OUTPUT_DIR}
  Realm:                    ${REALM:-<from spec>}
  Cluster:                  ${CLUSTER_NAME:-<from spec>}
  Distribution:             ${DISTRIBUTION:-<from spec>}
  Expected kube context:    ${EXPECTED_KUBE_CONTEXT:-<required at apply time>}
  Export mode:              ${EXPORT_MODE:-<from spec, default file>}
  Legacy fluentd HEC:       ${LEGACY_FLUENTD}
  Platform HEC URL:         ${PLATFORM_HEC_URL:-<not set>}
  Platform HEC token file:  $(if [[ -n "${PLATFORM_HEC_TOKEN_FILE}" ]]; then printf '<configured>'; else printf '<not set>'; fi)
  O11y token file:          $(if [[ -n "${O11Y_TOKEN_FILE}" ]]; then printf '<configured>'; else printf '<not set>'; fi)
  Dashboards source:        ${DASHBOARDS_SOURCE:-<placeholder README>}
  Mode: render=$(bool_text "${MODE_RENDER}") validate=$(bool_text "${MODE_VALIDATE}") live=$(bool_text "${LIVE}")
  API probes: signalflow=$(bool_text "${SIGNALFLOW}") splunk_search=$(bool_text "${SPLUNK_SEARCH}")
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --realm "${REALM}"
    --cluster-name "${CLUSTER_NAME}"
    --distribution "${DISTRIBUTION}"
    --export-mode "${EXPORT_MODE}"
    --legacy-fluentd-hec "${LEGACY_FLUENTD}"
    --platform-hec-url "${PLATFORM_HEC_URL}"
    --platform-hec-token-file "${PLATFORM_HEC_TOKEN_FILE}"
    --render-platform-hec-helper "${RENDER_PLATFORM_HEC_HELPER}"
    --o11y-token-file "${O11Y_TOKEN_FILE}"
    --dashboards-source "${DASHBOARDS_SOURCE}"
    --allow-loose-token-perms "${ALLOW_LOOSE_TOKEN_PERMS}"
)
# A render-only dry-run should not write files. An apply dry-run still needs
# fresh rendered assets; only the Kubernetes/Helm mutation is dry-run.
if [[ "${DRY_RUN}" == "true" && "${MODE_APPLY}" != "true" ]]; then RENDER_ARGS+=(--dry-run); fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then RENDER_ARGS+=(--json); fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" && "${MODE_APPLY}" != "true" ]]; then exit 0; fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    VALIDATE_ARGS=(
        --output-dir "${OUTPUT_DIR}"
        --api-lookback-seconds "${API_LOOKBACK_SECONDS}"
        --api-timeout-seconds "${API_TIMEOUT_SECONDS}"
    )
    [[ "${LIVE}" == "true" ]] && VALIDATE_ARGS+=(--live)
    [[ -n "${EXPECTED_KUBE_CONTEXT}" ]] && VALIDATE_ARGS+=(--kube-context "${EXPECTED_KUBE_CONTEXT}")
    [[ "${ALLOW_CURRENT_CONTEXT}" == "true" ]] && VALIDATE_ARGS+=(--allow-current-context)
    [[ "${SIGNALFLOW}" == "true" ]] && VALIDATE_ARGS+=(--signalflow)
    [[ "${SPLUNK_SEARCH}" == "true" ]] && VALIDATE_ARGS+=(--splunk-search)
    [[ "${PRODUCTION}" == "true" ]] && VALIDATE_ARGS+=(--production)
    [[ -n "${O11Y_TOKEN_FILE}" ]] && VALIDATE_ARGS+=(--o11y-token-file "${O11Y_TOKEN_FILE}")
    [[ -n "${SPLUNK_MANAGEMENT_URL}" ]] && VALIDATE_ARGS+=(--splunk-url "${SPLUNK_MANAGEMENT_URL}")
    [[ -n "${SPLUNK_SEARCH_TOKEN_FILE}" ]] && VALIDATE_ARGS+=(--splunk-search-token-file "${SPLUNK_SEARCH_TOKEN_FILE}")
    [[ "${ALLOW_LOOSE_TOKEN_PERMS}" == "true" ]] && VALIDATE_ARGS+=(--allow-loose-token-perms)
    bash "${SCRIPT_DIR}/validate.sh" "${VALIDATE_ARGS[@]}"
fi

if [[ "${MODE_APPLY}" == "true" ]]; then
    APPLY_SCRIPT="${OUTPUT_DIR}/scripts/apply-isovalent-overlay.sh"
    if [[ ! -x "${APPLY_SCRIPT}" ]]; then
        log "ERROR: Rendered apply script not found at ${APPLY_SCRIPT}. Run --render first."
        exit 1
    fi
    if [[ -z "${O11Y_TOKEN_FILE}" ]]; then
        log "ERROR: --apply requires --o11y-token-file or SPLUNK_O11Y_TOKEN_FILE."
        exit 1
    fi
    require_apply_acceptance
    if [[ -z "${EXPECTED_KUBE_CONTEXT}" ]]; then
        log "ERROR: --apply requires --kube-context with the exact expected current context."
        exit 1
    fi
    show_kube_context
    log "Applying Isovalent overlay via rendered helper..."
    K8S_APPLY_DRY_RUN="${K8S_APPLY_DRY_RUN}" \
        O11Y_TOKEN_FILE="${O11Y_TOKEN_FILE}" \
        PLATFORM_HEC_TOKEN_FILE="${PLATFORM_HEC_TOKEN_FILE}" \
        PLATFORM_HEC_URL="${PLATFORM_HEC_URL}" \
        ALLOW_LOOSE_TOKEN_PERMS="${ALLOW_LOOSE_TOKEN_PERMS}" \
        EXPECTED_KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT}" \
        bash "${APPLY_SCRIPT}"
fi
