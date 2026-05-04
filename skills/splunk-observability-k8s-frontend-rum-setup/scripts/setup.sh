#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-k8s-frontend-rum-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability Kubernetes Frontend RUM + Session Replay setup

Usage:
  bash skills/splunk-observability-k8s-frontend-rum-setup/scripts/setup.sh [mode] [options]

Modes (pick one; --render is default):
  --render                          Render assets (no cluster mutation)
  --guided                          Interactive Q&A walk-through; writes a spec then renders
  --discover-frontend-workloads     Read-only kubectl walk + starter inventory
  --apply-injection                 Apply rendered manifests + rollout restart
  --uninstall-injection             Reverse from backup, rollout restart, delete ConfigMaps
  --validate                        Forward to validate.sh against the rendered output

Identity:
  --spec PATH                       YAML or JSON spec (default: template.example)
  --output-dir DIR                  Rendered output directory
  --realm REALM                     Override spec.realm
  --application-name NAME           Override spec.application_name
  --deployment-environment ENV      prod | staging | dev | qa ...
  --version VERSION                 Override spec.version
  --cluster-name NAME               Override spec.cluster_name
  --cookie-domain DOMAIN            Override spec.cookie_domain
  --rum-token-file PATH             Splunk RUM access token file (chmod 600)
  --o11y-token-file PATH            Splunk Observability Org access token file (used by source-map upload)
  --allow-loose-token-perms         Skip the chmod-600 token permission preflight (warns)

Endpoints + agent versioning:
  --endpoint-domain DOMAIN          splunkcloud (default) | signalfx (legacy)
  --cdn-base URL                    Override the auto-derived CDN URL prefix
  --beacon-endpoint-override URL    Override the auto-derived rum-ingest beacon URL
  --agent-version VERSION           v1 default; latest requires --allow-latest-version
  --allow-latest-version            Permit agent_version=latest
  --agent-sri SHA384                Operator-supplied SRI hash for the exact-version <script>
  --session-recorder-sri SHA384     SRI hash for the session recorder script
  --legacy-ie11-build               Emit IE11 fallback <script>

Workload selection (multi-workload, mixed-mode):
  --workload Kind/NS/NAME=mode      mode: nginx-configmap | ingress-snippet | init-container | runtime-config (repeatable)
  --inventory-file PATH             Read workloads from a previously rendered discovery/workloads.yaml

SplunkRum.init knobs:
  --debug, --persistance MODE, --user-tracking-mode MODE,
  --global-attribute KEY=VAL, --ignore-url URL_OR_REGEX,
  --exporter-otlp, --sampler-type TYPE, --sampler-ratio RATIO,
  --module-disable MODULE, --module-enable MODULE,
  --interactions-extra-event NAME

Frustration Signals 2.0:
  --rage-click-disable, --rage-click-count N, --rage-click-timeframe-seconds N,
  --rage-click-ignore-selector CSS,
  --enable-dead-click, --dead-click-time-window-ms MS, --dead-click-ignore-url URL,
  --enable-error-click, --error-click-time-window-ms MS, --error-click-ignore-url URL,
  --enable-thrashed-cursor, --thrashed-cursor-threshold FLOAT,
  --thrashed-cursor-throttle-ms MS

Browser RUM privacy:
  --mask-all-text, --no-mask-all-text,
  --privacy-rule mask|unmask|exclude=CSS_SELECTOR

Session Replay (enterprise tier):
  --enable-session-replay, --accept-session-replay-enterprise (REQUIRED gate),
  --session-replay-recorder splunk|rrweb,
  --session-replay-mask-all-inputs, --session-replay-no-mask-all-inputs,
  --session-replay-mask-all-text, --session-replay-no-mask-all-text,
  --session-replay-rule mask|unmask|exclude=CSS_SELECTOR,
  --session-replay-max-export-interval-ms MS,
  --session-replay-sampler-ratio RATIO,
  --session-replay-feature canvas|video|iframes|pack-assets|cache-assets,
  --session-replay-pack-asset styles|fonts|images,
  --session-replay-background-service-src URL

Source maps:
  --source-maps-enable, --source-maps-disable,
  --source-maps-bundler cli|webpack,
  --source-maps-injection-target-dir DIR,
  --source-maps-ci github_actions|gitlab_ci|none

APM linking:
  --apm-linking-enable, --apm-linking-disable,
  --apm-linking-backend-url URL

CSP advisory:
  --csp-emit-advisory, --csp-no-emit-advisory

Hand-offs:
  --no-handoff-dashboards, --no-handoff-detectors, --no-handoff-cloud-integration,
  --enable-handoff-auto-instrumentation

Apply gates:
  --accept-frontend-injection       REQUIRED for --apply-injection and --uninstall-injection
  --kube-context CTX

Common:
  --dry-run                         Show plan without writing
  --json                            Emit JSON metadata + plan
  --explain                         Print plan in plain English
  --gitops-mode                     Render YAML manifests only; omit apply/uninstall/sourcemap-upload scripts
  --help                            Show this help

Direct token flags such as --rum-token, --access-token, --token, --bearer-token,
--api-token, --o11y-token, --sf-token, --hec-token, --platform-hec-token,
--api-key are REJECTED. Use a chmod-600 token file referenced by
SPLUNK_O11Y_RUM_TOKEN_FILE (RUM token) or SPLUNK_O11Y_TOKEN_FILE (Org access
token).
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

# Mode flags
MODE_RENDER="false"
MODE_GUIDED="false"
MODE_DISCOVER="false"
MODE_APPLY="false"
MODE_UNINSTALL="false"
MODE_VALIDATE="false"

EXPLAIN="false"
GITOPS_MODE="false"
ACCEPT_FRONTEND_INJECTION="false"
ACCEPT_SESSION_REPLAY_ENTERPRISE="false"
ALLOW_LATEST_VERSION="false"
ALLOW_LOOSE_TOKEN_PERMS="false"
KUBE_CONTEXT=""

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
RUM_TOKEN_FILE="${SPLUNK_O11Y_RUM_TOKEN_FILE:-}"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"

# Pass-through args collected for the Python renderer.
RENDER_ARGS=()

_pass()      { RENDER_ARGS+=("$1" "$2"); }
_pass_flag() { RENDER_ARGS+=("$1"); }

if [[ $# -eq 0 ]]; then usage; exit 0; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER="true"; shift ;;
        --guided) MODE_GUIDED="true"; shift ;;
        --discover-frontend-workloads) MODE_DISCOVER="true"; _pass_flag --discover-frontend-workloads; shift ;;
        --apply-injection) MODE_APPLY="true"; shift ;;
        --uninstall-injection) MODE_UNINSTALL="true"; shift ;;
        --validate) MODE_VALIDATE="true"; shift ;;

        --dry-run) _pass_flag --dry-run; shift ;;
        --json) _pass_flag --json; shift ;;
        --explain) EXPLAIN="true"; shift ;;
        --gitops-mode) GITOPS_MODE="true"; _pass_flag --gitops-mode; shift ;;
        --accept-frontend-injection) ACCEPT_FRONTEND_INJECTION="true"; shift ;;
        --accept-session-replay-enterprise) ACCEPT_SESSION_REPLAY_ENTERPRISE="true"; _pass_flag --accept-session-replay-enterprise; shift ;;
        --allow-latest-version) ALLOW_LATEST_VERSION="true"; _pass_flag --allow-latest-version; shift ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS="true"; shift ;;

        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; shift 2 ;;
        --rum-token-file) require_arg "$1" "$#" || exit 1; RUM_TOKEN_FILE="$2"; shift 2 ;;
        --o11y-token-file) require_arg "$1" "$#" || exit 1; O11Y_TOKEN_FILE="$2"; shift 2 ;;

        # Identity
        --realm) require_arg "$1" "$#" || exit 1; _pass --realm "$2"; shift 2 ;;
        --application-name) require_arg "$1" "$#" || exit 1; _pass --application-name "$2"; shift 2 ;;
        --deployment-environment) require_arg "$1" "$#" || exit 1; _pass --deployment-environment "$2"; shift 2 ;;
        --version) require_arg "$1" "$#" || exit 1; _pass --version "$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; _pass --cluster-name "$2"; shift 2 ;;
        --cookie-domain) require_arg "$1" "$#" || exit 1; _pass --cookie-domain "$2"; shift 2 ;;

        # Endpoints + agent versioning
        --endpoint-domain) require_arg "$1" "$#" || exit 1; _pass --endpoint-domain "$2"; shift 2 ;;
        --cdn-base) require_arg "$1" "$#" || exit 1; _pass --cdn-base "$2"; shift 2 ;;
        --beacon-endpoint-override) require_arg "$1" "$#" || exit 1; _pass --beacon-endpoint-override "$2"; shift 2 ;;
        --agent-version) require_arg "$1" "$#" || exit 1; _pass --agent-version "$2"; shift 2 ;;
        --agent-sri) require_arg "$1" "$#" || exit 1; _pass --agent-sri "$2"; shift 2 ;;
        --session-recorder-sri) require_arg "$1" "$#" || exit 1; _pass --session-recorder-sri "$2"; shift 2 ;;
        --legacy-ie11-build) _pass_flag --legacy-ie11-build; shift ;;

        # Workload
        --workload) require_arg "$1" "$#" || exit 1; _pass --workload "$2"; shift 2 ;;
        --inventory-file) require_arg "$1" "$#" || exit 1; _pass --inventory-file "$2"; shift 2 ;;

        # SplunkRum.init knobs
        --debug) _pass_flag --debug; shift ;;
        --persistance) require_arg "$1" "$#" || exit 1; _pass --persistance "$2"; shift 2 ;;
        --user-tracking-mode) require_arg "$1" "$#" || exit 1; _pass --user-tracking-mode "$2"; shift 2 ;;
        --global-attribute) require_arg "$1" "$#" || exit 1; _pass --global-attribute "$2"; shift 2 ;;
        --ignore-url) require_arg "$1" "$#" || exit 1; _pass --ignore-url "$2"; shift 2 ;;
        --exporter-otlp) _pass_flag --exporter-otlp; shift ;;
        --sampler-type) require_arg "$1" "$#" || exit 1; _pass --sampler-type "$2"; shift 2 ;;
        --sampler-ratio) require_arg "$1" "$#" || exit 1; _pass --sampler-ratio "$2"; shift 2 ;;
        --module-disable) require_arg "$1" "$#" || exit 1; _pass --module-disable "$2"; shift 2 ;;
        --module-enable) require_arg "$1" "$#" || exit 1; _pass --module-enable "$2"; shift 2 ;;
        --interactions-extra-event) require_arg "$1" "$#" || exit 1; _pass --interactions-extra-event "$2"; shift 2 ;;

        # Frustration Signals 2.0
        --rage-click-disable) _pass_flag --rage-click-disable; shift ;;
        --rage-click-count) require_arg "$1" "$#" || exit 1; _pass --rage-click-count "$2"; shift 2 ;;
        --rage-click-timeframe-seconds) require_arg "$1" "$#" || exit 1; _pass --rage-click-timeframe-seconds "$2"; shift 2 ;;
        --rage-click-ignore-selector) require_arg "$1" "$#" || exit 1; _pass --rage-click-ignore-selector "$2"; shift 2 ;;
        --enable-dead-click) _pass_flag --enable-dead-click; shift ;;
        --dead-click-time-window-ms) require_arg "$1" "$#" || exit 1; _pass --dead-click-time-window-ms "$2"; shift 2 ;;
        --dead-click-ignore-url) require_arg "$1" "$#" || exit 1; _pass --dead-click-ignore-url "$2"; shift 2 ;;
        --enable-error-click) _pass_flag --enable-error-click; shift ;;
        --error-click-time-window-ms) require_arg "$1" "$#" || exit 1; _pass --error-click-time-window-ms "$2"; shift 2 ;;
        --error-click-ignore-url) require_arg "$1" "$#" || exit 1; _pass --error-click-ignore-url "$2"; shift 2 ;;
        --enable-thrashed-cursor) _pass_flag --enable-thrashed-cursor; shift ;;
        --thrashed-cursor-threshold) require_arg "$1" "$#" || exit 1; _pass --thrashed-cursor-threshold "$2"; shift 2 ;;
        --thrashed-cursor-throttle-ms) require_arg "$1" "$#" || exit 1; _pass --thrashed-cursor-throttle-ms "$2"; shift 2 ;;

        # Browser RUM privacy
        --mask-all-text) _pass_flag --mask-all-text; shift ;;
        --no-mask-all-text) _pass_flag --no-mask-all-text; shift ;;
        --privacy-rule) require_arg "$1" "$#" || exit 1; _pass --privacy-rule "$2"; shift 2 ;;

        # Session Replay
        --enable-session-replay) _pass_flag --enable-session-replay; shift ;;
        --session-replay-recorder) require_arg "$1" "$#" || exit 1; _pass --session-replay-recorder "$2"; shift 2 ;;
        --session-replay-mask-all-inputs) _pass_flag --session-replay-mask-all-inputs; shift ;;
        --session-replay-no-mask-all-inputs) _pass_flag --session-replay-no-mask-all-inputs; shift ;;
        --session-replay-mask-all-text) _pass_flag --session-replay-mask-all-text; shift ;;
        --session-replay-no-mask-all-text) _pass_flag --session-replay-no-mask-all-text; shift ;;
        --session-replay-rule) require_arg "$1" "$#" || exit 1; _pass --session-replay-rule "$2"; shift 2 ;;
        --session-replay-max-export-interval-ms) require_arg "$1" "$#" || exit 1; _pass --session-replay-max-export-interval-ms "$2"; shift 2 ;;
        --session-replay-sampler-ratio) require_arg "$1" "$#" || exit 1; _pass --session-replay-sampler-ratio "$2"; shift 2 ;;
        --session-replay-feature) require_arg "$1" "$#" || exit 1; _pass --session-replay-feature "$2"; shift 2 ;;
        --session-replay-pack-asset) require_arg "$1" "$#" || exit 1; _pass --session-replay-pack-asset "$2"; shift 2 ;;
        --session-replay-background-service-src) require_arg "$1" "$#" || exit 1; _pass --session-replay-background-service-src "$2"; shift 2 ;;

        # Source maps
        --source-maps-enable) _pass_flag --source-maps-enable; shift ;;
        --source-maps-disable) _pass_flag --source-maps-disable; shift ;;
        --source-maps-bundler) require_arg "$1" "$#" || exit 1; _pass --source-maps-bundler "$2"; shift 2 ;;
        --source-maps-injection-target-dir) require_arg "$1" "$#" || exit 1; _pass --source-maps-injection-target-dir "$2"; shift 2 ;;
        --source-maps-ci) require_arg "$1" "$#" || exit 1; _pass --source-maps-ci "$2"; shift 2 ;;

        # APM linking
        --apm-linking-enable) _pass_flag --apm-linking-enable; shift ;;
        --apm-linking-disable) _pass_flag --apm-linking-disable; shift ;;
        --apm-linking-backend-url) require_arg "$1" "$#" || exit 1; _pass --apm-linking-backend-url "$2"; shift 2 ;;

        # CSP
        --csp-emit-advisory) _pass_flag --csp-emit-advisory; shift ;;
        --csp-no-emit-advisory) _pass_flag --csp-no-emit-advisory; shift ;;

        # Handoffs
        --no-handoff-dashboards) _pass_flag --no-handoff-dashboards; shift ;;
        --no-handoff-detectors) _pass_flag --no-handoff-detectors; shift ;;
        --no-handoff-cloud-integration) _pass_flag --no-handoff-cloud-integration; shift ;;
        --enable-handoff-auto-instrumentation) _pass_flag --enable-handoff-auto-instrumentation; shift ;;

        # Reject token-shaped flags loudly. The renderer also rejects them but
        # catching at the wrapper layer gives a clearer error.
        --rum-token|--access-token|--token|--bearer-token|--api-token|--o11y-token|--sf-token|--hec-token|--platform-hec-token|--api-key)
            reject_secret_arg "$1" "--rum-token-file or --o11y-token-file"
            exit 1
            ;;

        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

# Default to --render when no mode is set.
if [[ "${MODE_RENDER}" == "false" && "${MODE_GUIDED}" == "false" \
      && "${MODE_DISCOVER}" == "false" && "${MODE_APPLY}" == "false" \
      && "${MODE_UNINSTALL}" == "false" && "${MODE_VALIDATE}" == "false" ]]; then
    MODE_RENDER="true"
fi

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

_token_perm_octal() {
    local target="$1" mode=""
    mode="$(stat -f '%A' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    mode="$(stat -c '%a' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    printf ''
}

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" && -r "${path}" ]] || return 0
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then return 0; fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS}" == "true" ]]; then
            log "  WARN: ${label} permissions are ${mode}; --allow-loose-token-perms is set, proceeding."
            return 0
        fi
        log "ERROR: ${label} (${path}) is mode ${mode}; tokens must be mode 600."
        return 1
    fi
}

[[ -n "${RUM_TOKEN_FILE}" ]] && { _check_token_perms "--rum-token-file" "${RUM_TOKEN_FILE}" || exit 1; _pass --rum-token-file "${RUM_TOKEN_FILE}"; }
[[ -n "${O11Y_TOKEN_FILE}" ]] && { _check_token_perms "--o11y-token-file" "${O11Y_TOKEN_FILE}" || exit 1; _pass --o11y-token-file "${O11Y_TOKEN_FILE}"; }

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability Kubernetes Frontend RUM -- execution plan
==============================================================
  Spec:                ${SPEC}
  Output directory:    ${OUTPUT_DIR}
  Mode: render=$(bool_text "${MODE_RENDER}") guided=$(bool_text "${MODE_GUIDED}") \
discover=$(bool_text "${MODE_DISCOVER}") apply=$(bool_text "${MODE_APPLY}") \
uninstall=$(bool_text "${MODE_UNINSTALL}") validate=$(bool_text "${MODE_VALIDATE}")
  RUM token file:      ${RUM_TOKEN_FILE:-<not set>}
  O11y token file:     ${O11Y_TOKEN_FILE:-<not set>}
  Apply gate:          $(bool_text "${ACCEPT_FRONTEND_INJECTION}")
  Session Replay gate: $(bool_text "${ACCEPT_SESSION_REPLAY_ENTERPRISE}")
  Latest version OK:   $(bool_text "${ALLOW_LATEST_VERSION}")
  Gitops mode:         $(bool_text "${GITOPS_MODE}")
EXPLAIN
    exit 0
fi

# Pick the python interpreter (prefer repo-local venv).
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
else
    PYTHON_BIN="$(command -v python3)"
fi

run_render() {
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" \
        --spec "${SPEC}" \
        --output-dir "${OUTPUT_DIR}" \
        "${RENDER_ARGS[@]}"
}

# ---------------------------------------------------------------------------
# Guided mode: an interactive Q&A walk-through that writes a populated spec
# alongside the default template, then renders.
# ---------------------------------------------------------------------------

run_guided() {
    local guided_spec="${SKILL_DIR}/template.guided.yaml"
    log "Guided mode writes a populated spec to ${guided_spec}, then renders."
    log "Press Enter to accept the [default] for any prompt."

    _ask() {
        local var="$1" prompt="$2" default_value="${3:-}"
        local answer
        if [[ -n "${default_value}" ]]; then
            read -r -p "${prompt} [${default_value}]: " answer || answer=""
            [[ -z "${answer}" ]] && answer="${default_value}"
        else
            read -r -p "${prompt}: " answer || answer=""
        fi
        printf -v "${var}" '%s' "${answer}"
    }

    local realm app env version cluster cookie token_path mode session_replay
    local sr_ratio sr_recorder dead_click error_click thrash_cursor source_maps
    local injection_mode workload_kind workload_ns workload_name

    _ask realm "Splunk Observability realm (us0|us1|us2|eu0|eu1|eu2|au0|jp0)" "us0"
    _ask app "Application name (lands as applicationName)" "frontend"
    _ask env "Deployment environment (prod|staging|dev)" "prod"
    _ask version "Application version (lands as app.version)" "0.1.0"
    _ask cluster "Kubernetes cluster name (descriptive)" ""
    _ask cookie "Cookie domain for cross-subdomain sessions (empty for hostname)" ""
    _ask token_path "Path to chmod-600 RUM token file (empty to set later)" "${RUM_TOKEN_FILE}"
    _ask injection_mode "Default injection mode (nginx-configmap|ingress-snippet|init-container|runtime-config)" "nginx-configmap"
    _ask workload_kind "First workload kind (Deployment|StatefulSet|DaemonSet)" "Deployment"
    _ask workload_ns "First workload namespace" "${env}"
    _ask workload_name "First workload name" "${app}-web"
    _ask session_replay "Enable Session Replay (enterprise tier) [y/N]" "n"
    if [[ "${session_replay,,}" == "y" || "${session_replay,,}" == "yes" ]]; then
        _ask sr_recorder "Session Replay recorder (splunk|rrweb)" "splunk"
        _ask sr_ratio "Session Replay sampler ratio (0.0-1.0)" "0.5"
    fi
    _ask dead_click "Enable dead-click frustration signal [y/N]" "n"
    _ask error_click "Enable error-click frustration signal [y/N]" "n"
    _ask thrash_cursor "Enable thrashed-cursor frustration signal [y/N]" "n"
    _ask source_maps "Render source-map upload helper [Y/n]" "y"

    {
        echo "# Auto-generated by setup.sh --guided. Edit freely; this is a normal spec."
        echo "api_version: ${API_VERSION:-splunk-observability-k8s-frontend-rum-setup/v1}"
        echo "realm: ${realm}"
        echo "application_name: ${app}"
        echo "deployment_environment: ${env}"
        echo "version: ${version}"
        [[ -n "${cluster}" ]] && echo "cluster_name: ${cluster}"
        [[ -n "${cookie}" ]]  && echo "cookie_domain: ${cookie}"
        [[ -n "${token_path}" ]] && echo "rum_token_file: ${token_path}"
        echo "endpoints:"
        echo "  domain: splunkcloud"
        echo "agent_version: v1"
        echo "workloads:"
        echo "  - kind: ${workload_kind}"
        echo "    namespace: ${workload_ns}"
        echo "    name: ${workload_name}"
        echo "    injection_mode: ${injection_mode}"
        echo "instrumentations:"
        echo "  user_tracking_mode: anonymousTracking"
        echo "  modules:"
        echo "    webvitals: true"
        echo "    errors: true"
        echo "  frustration_signals:"
        echo "    rage_click:"
        echo "      enabled: true"
        if [[ "${dead_click,,}" == "y" || "${dead_click,,}" == "yes" ]]; then
            echo "    dead_click:"
            echo "      enabled: true"
        fi
        if [[ "${error_click,,}" == "y" || "${error_click,,}" == "yes" ]]; then
            echo "    error_click:"
            echo "      enabled: true"
        fi
        if [[ "${thrash_cursor,,}" == "y" || "${thrash_cursor,,}" == "yes" ]]; then
            echo "    thrashed_cursor:"
            echo "      enabled: true"
        fi
        if [[ "${session_replay,,}" == "y" || "${session_replay,,}" == "yes" ]]; then
            echo "session_replay:"
            echo "  enabled: true"
            echo "  recorder: ${sr_recorder:-splunk}"
            echo "  sampler_ratio: ${sr_ratio:-0.5}"
            echo "  mask_all_inputs: true"
            echo "  mask_all_text: true"
        fi
        if [[ "${source_maps,,}" == "n" || "${source_maps,,}" == "no" ]]; then
            echo "source_maps:"
            echo "  enabled: false"
        else
            echo "source_maps:"
            echo "  enabled: true"
            echo "  bundler: cli"
        fi
        echo "handoffs:"
        echo "  dashboard_builder: true"
        echo "  native_ops: true"
        echo "  cloud_integration: true"
    } > "${guided_spec}"
    log "Wrote spec to ${guided_spec}"
    SPEC="${guided_spec}"
    if [[ "${session_replay,,}" == "y" || "${session_replay,,}" == "yes" ]]; then
        if [[ "${ACCEPT_SESSION_REPLAY_ENTERPRISE}" == "false" ]]; then
            log "Session Replay enabled. Re-run with --accept-session-replay-enterprise to render."
            exit 0
        fi
    fi
    run_render
}

run_apply() {
    if [[ "${ACCEPT_FRONTEND_INJECTION}" != "true" ]]; then
        log "ERROR: --apply-injection requires --accept-frontend-injection (rolling restarts will occur)."
        exit 1
    fi
    if [[ ! -f "${OUTPUT_DIR}/k8s-rum/apply-injection.sh" ]]; then
        log "ERROR: Rendered output not found at ${OUTPUT_DIR}/k8s-rum/. Run --render first."
        exit 1
    fi
    log "Applying via ${OUTPUT_DIR}/k8s-rum/apply-injection.sh"
    if [[ -n "${KUBE_CONTEXT}" ]]; then
        KUBECTL_CONTEXT="${KUBE_CONTEXT}" bash "${OUTPUT_DIR}/k8s-rum/apply-injection.sh"
    else
        bash "${OUTPUT_DIR}/k8s-rum/apply-injection.sh"
    fi
}

run_uninstall() {
    if [[ "${ACCEPT_FRONTEND_INJECTION}" != "true" ]]; then
        log "ERROR: --uninstall-injection requires --accept-frontend-injection (rolling restarts will occur)."
        exit 1
    fi
    if [[ ! -f "${OUTPUT_DIR}/k8s-rum/uninstall-injection.sh" ]]; then
        log "ERROR: Rendered output not found at ${OUTPUT_DIR}/k8s-rum/. Run --render first."
        exit 1
    fi
    bash "${OUTPUT_DIR}/k8s-rum/uninstall-injection.sh"
}

run_discover() {
    log "Discovery: read-only kubectl walk for frontend candidates."
    local discovery_dir="${OUTPUT_DIR}/discovery"
    mkdir -p "${discovery_dir}"
    {
        echo "# Discovered services with frontend-typical ports (80, 8080, 3000)."
        echo "services:"
        if command -v kubectl >/dev/null 2>&1; then
            kubectl get svc --all-namespaces -o jsonpath='{range .items[?(@.spec.ports[*].port==80)]}{"  - namespace: "}{.metadata.namespace}{"\n    name: "}{.metadata.name}{"\n    ports: "}{.spec.ports[*].port}{"\n"}{end}' 2>/dev/null || echo "  # kubectl not configured"
        else
            echo "  # kubectl not found; install or run from a host with cluster credentials."
        fi
    } > "${discovery_dir}/services.yaml"
    {
        echo "# Discovered Deployments / DaemonSets / StatefulSets that look like frontends"
        echo "# (image patterns: nginx, httpd, node)."
        echo "# Set per-workload injection_mode to one of:"
        echo "#   nginx-configmap | ingress-snippet | init-container | runtime-config"
        echo "workloads: []"
        if command -v kubectl >/dev/null 2>&1; then
            for kind in deployment statefulset daemonset; do
                kubectl get "${kind}" --all-namespaces \
                    -o jsonpath='{range .items[*]}{.metadata.namespace}{"|"}{.metadata.name}{"|"}{.spec.template.spec.containers[*].image}{"\n"}{end}' 2>/dev/null \
                | awk -F'|' -v k="${kind^}" '
                    $3 ~ /(nginx|httpd|node)/ {
                        printf "# - kind: %s\n#   namespace: %s\n#   name: %s\n#   image: %s\n#   injection_mode: nginx-configmap\n", k, $1, $2, $3
                    }'
            done
        fi
    } > "${discovery_dir}/workloads.yaml"
    log "Wrote ${discovery_dir}/services.yaml and workloads.yaml. Edit and re-run with --inventory-file."
}

# Mode dispatch.
if [[ "${MODE_GUIDED}" == "true" ]]; then
    run_guided
elif [[ "${MODE_DISCOVER}" == "true" ]]; then
    if [[ "${MODE_RENDER}" == "true" ]]; then run_render; else run_discover; fi
elif [[ "${MODE_RENDER}" == "true" ]]; then
    run_render
fi

if [[ "${MODE_APPLY}" == "true" ]]; then run_apply; fi
if [[ "${MODE_UNINSTALL}" == "true" ]]; then run_uninstall; fi
if [[ "${MODE_VALIDATE}" == "true" ]]; then
    bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
fi
