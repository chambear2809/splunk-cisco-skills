#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-k8s-auto-instrumentation-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability Kubernetes auto-instrumentation setup

Usage:
  bash skills/splunk-observability-k8s-auto-instrumentation-setup/scripts/setup.sh [mode] [options]

Modes (pick one; render is default):
  --render                        Render overlay assets (no cluster mutation)
  --discover-workloads            Read-only kubectl walk + starter inventory
  --apply-instrumentation         kubectl apply -f instrumentation-cr.yaml
  --apply-annotations             Strategic-merge patch + rollout restart
  --uninstall-instrumentation     Reverse patches, rollout restart, delete CR
  --dry-run                       Preview; composable with render/apply/uninstall
  --json                          Emit JSON metadata/plan
  --explain                       Print plan in plain English
  --gitops-mode                   Render YAML only; skip apply helper scripts

Identity:
  --spec PATH                     YAML/JSON spec (default: template.example)
  --output-dir DIR                Rendered output directory
  --realm REALM                   Splunk O11y realm
  --cluster-name NAME             Cluster identity
  --deployment-environment ENV    prod | staging | dev | qa ...
  --namespace NS                  Instrumentation CR namespace (default splunk-otel)
  --instrumentation-cr-name NAME  Default CR name
  --distribution NAME             eks | eks/auto-mode | eks/fargate | gke | gke/autopilot | openshift | aks | generic
  --base-release NAME             Base collector helm release
  --base-namespace NS             Base collector namespace

Languages + CR config:
  --languages csv                 java,nodejs,python,dotnet,go,apache-httpd,nginx,sdk
  --java-image URI                Override ghcr.io/signalfx/splunk-otel-java
  --nodejs-image URI              Override ghcr.io/signalfx/splunk-otel-js
  --python-image URI              Override ghcr.io/signalfx/splunk-otel-python
  --dotnet-image URI              Override ghcr.io/signalfx/splunk-otel-dotnet
  --go-image URI                  Override ghcr.io/signalfx/splunk-otel-go
  --apache-httpd-image URI        Override apache-httpd instrumentation image
  --nginx-image URI               Override nginx instrumentation image
  --extra-env LANG=KEY=VAL        Per-language extra env (repeatable)
  --resource-limits LANG=cpu=X,memory=Y  Per-language init container limits (repeatable)

Trace + runtime:
  --propagators csv               tracecontext,baggage,b3[,b3multi,jaeger,xray,...]
  --sampler TYPE                  always_on | parentbased_always_on | traceidratio ...
  --sampler-argument VALUE
  --profiling-enabled             SPLUNK_PROFILER_ENABLED=true
  --profiling-memory-enabled      SPLUNK_PROFILER_MEMORY_ENABLED=true
  --profiler-call-stack-interval-ms MS
  --runtime-metrics-enabled       SPLUNK_METRICS_ENABLED=true (Java + Node only)
  --use-labels-for-resource-attributes
  --multi-instrumentation         Operator feature gate (required for >1 CR)
  --extra-resource-attr KEY=VAL   Repeatable

Endpoint:
  --agent-endpoint URL            Default http://\$(SPLUNK_OTEL_AGENT):4317
  --gateway-endpoint URL          Required for eks/fargate
  --per-language-endpoint L=URL   Per-language HTTP OTLP override (repeatable)

Operator + OBI:
  --operator-watch-namespaces csv
  --webhook-cert-mode MODE        auto | cert-manager | external
  --installation-job-enabled BOOL
  --enable-obi
  --obi-namespaces csv
  --obi-exclude-namespaces csv
  --obi-version VERSION
  --accept-obi-privileged
  --render-openshift-scc BOOL

Image pull + vendor:
  --image-pull-secret NAME
  --detect-vendors                Scan for Datadog/New Relic/AppD/Dynatrace
  --exclude-vendor csv

Annotations:
  --annotate-namespace NS=csv     Namespace-level inject-<lang> (repeatable)
  --annotate-workload Kind/NS/NAME=lang[,container-names=a,b][,dotnet-runtime=...][,go-target-exe=...][,cr=ns/name][,disable=true]
  --inventory-file PATH

Target filter (apply/uninstall):
  --target Kind/NS/NAME           Repeatable
  --target-all                    Apply/uninstall all recorded workloads
  --purge-crs                     Uninstall: also delete every rendered CR
  --purge-backup                  Uninstall: delete backup ConfigMap

Apply gates:
  --accept-auto-instrumentation   Required for apply-annotations + uninstall
  --kube-context CTX

Backup:
  --backup-configmap NAME
  --restore-from-backup

  --help                          Show this help

Direct token flags such as --access-token, --token, --bearer-token, --api-token,
--o11y-token, --sf-token, --hec-token, --platform-hec-token, --api-key are
rejected. This skill does not take tokens on argv; the base collector skill
owns ingest-token handling.
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
MODE="render"
DRY_RUN="false"
JSON_OUTPUT="false"
EXPLAIN="false"
GITOPS_MODE="false"
DISCOVER_WORKLOADS="false"
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"

# Flag pass-throughs collected into an array for render_assets.py.
RENDER_ARGS=()
ACCEPT_AUTO_INSTRUMENTATION="false"
ACCEPT_OBI_PRIVILEGED="false"
KUBE_CONTEXT=""

# Track --target / --target-all / --purge-* separately so the apply / uninstall
# dispatch can forward them to the rendered scripts. They still flow to
# render_assets.py via RENDER_ARGS as well (so metadata.json records intent).
TARGET_ARGS=()
TARGET_ALL="false"
PURGE_CRS="false"
PURGE_BACKUP="false"

# Accept the named flag and push straight to render args.
_pass() {
    RENDER_ARGS+=("$1" "$2")
}

if [[ $# -eq 0 ]]; then usage; exit 0; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE="render"; shift ;;
        --apply-instrumentation) MODE="apply-instrumentation"; shift ;;
        --apply-annotations) MODE="apply-annotations"; shift ;;
        --uninstall-instrumentation) MODE="uninstall-instrumentation"; shift ;;
        --discover-workloads) DISCOVER_WORKLOADS="true"; shift ;;
        --dry-run) DRY_RUN="true"; shift ;;
        --json) JSON_OUTPUT="true"; shift ;;
        --explain) EXPLAIN="true"; shift ;;
        --gitops-mode) GITOPS_MODE="true"; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; _pass --realm "$2"; shift 2 ;;
        --cluster-name) require_arg "$1" "$#" || exit 1; _pass --cluster-name "$2"; shift 2 ;;
        --deployment-environment) require_arg "$1" "$#" || exit 1; _pass --deployment-environment "$2"; shift 2 ;;
        --namespace) require_arg "$1" "$#" || exit 1; _pass --namespace "$2"; shift 2 ;;
        --instrumentation-cr-name) require_arg "$1" "$#" || exit 1; _pass --instrumentation-cr-name "$2"; shift 2 ;;
        --distribution) require_arg "$1" "$#" || exit 1; _pass --distribution "$2"; shift 2 ;;
        --base-release) require_arg "$1" "$#" || exit 1; _pass --base-release "$2"; shift 2 ;;
        --base-namespace) require_arg "$1" "$#" || exit 1; _pass --base-namespace "$2"; shift 2 ;;
        --languages) require_arg "$1" "$#" || exit 1; _pass --languages "$2"; shift 2 ;;
        --java-image) require_arg "$1" "$#" || exit 1; _pass --java-image "$2"; shift 2 ;;
        --nodejs-image) require_arg "$1" "$#" || exit 1; _pass --nodejs-image "$2"; shift 2 ;;
        --python-image) require_arg "$1" "$#" || exit 1; _pass --python-image "$2"; shift 2 ;;
        --dotnet-image) require_arg "$1" "$#" || exit 1; _pass --dotnet-image "$2"; shift 2 ;;
        --go-image) require_arg "$1" "$#" || exit 1; _pass --go-image "$2"; shift 2 ;;
        --apache-httpd-image) require_arg "$1" "$#" || exit 1; _pass --apache-httpd-image "$2"; shift 2 ;;
        --nginx-image) require_arg "$1" "$#" || exit 1; _pass --nginx-image "$2"; shift 2 ;;
        --extra-env) require_arg "$1" "$#" || exit 1; RENDER_ARGS+=(--extra-env "$2"); shift 2 ;;
        --resource-limits) require_arg "$1" "$#" || exit 1; RENDER_ARGS+=(--resource-limits "$2"); shift 2 ;;
        --propagators) require_arg "$1" "$#" || exit 1; _pass --propagators "$2"; shift 2 ;;
        --sampler) require_arg "$1" "$#" || exit 1; _pass --sampler "$2"; shift 2 ;;
        --sampler-argument) require_arg "$1" "$#" || exit 1; _pass --sampler-argument "$2"; shift 2 ;;
        --profiling-enabled) RENDER_ARGS+=(--profiling-enabled); shift ;;
        --profiling-memory-enabled) RENDER_ARGS+=(--profiling-memory-enabled); shift ;;
        --profiler-call-stack-interval-ms) require_arg "$1" "$#" || exit 1; _pass --profiler-call-stack-interval-ms "$2"; shift 2 ;;
        --runtime-metrics-enabled) RENDER_ARGS+=(--runtime-metrics-enabled); shift ;;
        --use-labels-for-resource-attributes) RENDER_ARGS+=(--use-labels-for-resource-attributes); shift ;;
        --multi-instrumentation) RENDER_ARGS+=(--multi-instrumentation); shift ;;
        --extra-resource-attr) require_arg "$1" "$#" || exit 1; RENDER_ARGS+=(--extra-resource-attr "$2"); shift 2 ;;
        --agent-endpoint) require_arg "$1" "$#" || exit 1; _pass --agent-endpoint "$2"; shift 2 ;;
        --gateway-endpoint) require_arg "$1" "$#" || exit 1; _pass --gateway-endpoint "$2"; shift 2 ;;
        --per-language-endpoint) require_arg "$1" "$#" || exit 1; RENDER_ARGS+=(--per-language-endpoint "$2"); shift 2 ;;
        --operator-watch-namespaces) require_arg "$1" "$#" || exit 1; _pass --operator-watch-namespaces "$2"; shift 2 ;;
        --webhook-cert-mode) require_arg "$1" "$#" || exit 1; _pass --webhook-cert-mode "$2"; shift 2 ;;
        --installation-job-enabled) require_arg "$1" "$#" || exit 1; _pass --installation-job-enabled "$2"; shift 2 ;;
        --enable-obi) RENDER_ARGS+=(--enable-obi); shift ;;
        --obi-namespaces) require_arg "$1" "$#" || exit 1; _pass --obi-namespaces "$2"; shift 2 ;;
        --obi-exclude-namespaces) require_arg "$1" "$#" || exit 1; _pass --obi-exclude-namespaces "$2"; shift 2 ;;
        --obi-version) require_arg "$1" "$#" || exit 1; _pass --obi-version "$2"; shift 2 ;;
        --accept-obi-privileged) ACCEPT_OBI_PRIVILEGED="true"; RENDER_ARGS+=(--accept-obi-privileged); shift ;;
        --render-openshift-scc) require_arg "$1" "$#" || exit 1; _pass --render-openshift-scc "$2"; shift 2 ;;
        --image-pull-secret) require_arg "$1" "$#" || exit 1; _pass --image-pull-secret "$2"; shift 2 ;;
        --detect-vendors) RENDER_ARGS+=(--detect-vendors); shift ;;
        --exclude-vendor) require_arg "$1" "$#" || exit 1; _pass --exclude-vendor "$2"; shift 2 ;;
        --annotate-namespace) require_arg "$1" "$#" || exit 1; RENDER_ARGS+=(--annotate-namespace "$2"); shift 2 ;;
        --annotate-workload) require_arg "$1" "$#" || exit 1; RENDER_ARGS+=(--annotate-workload "$2"); shift 2 ;;
        --inventory-file) require_arg "$1" "$#" || exit 1; _pass --inventory-file "$2"; shift 2 ;;
        --target) require_arg "$1" "$#" || exit 1; RENDER_ARGS+=(--target "$2"); TARGET_ARGS+=(--target "$2"); shift 2 ;;
        --target-all) RENDER_ARGS+=(--target-all); TARGET_ALL="true"; shift ;;
        --purge-crs) RENDER_ARGS+=(--purge-crs); PURGE_CRS="true"; shift ;;
        --purge-backup) RENDER_ARGS+=(--purge-backup); PURGE_BACKUP="true"; shift ;;
        --accept-auto-instrumentation) ACCEPT_AUTO_INSTRUMENTATION="true"; RENDER_ARGS+=(--accept-auto-instrumentation); shift ;;
        --kube-context) require_arg "$1" "$#" || exit 1; KUBE_CONTEXT="$2"; _pass --kube-context "$2"; shift 2 ;;
        --backup-configmap) require_arg "$1" "$#" || exit 1; _pass --backup-configmap "$2"; shift 2 ;;
        --restore-from-backup) RENDER_ARGS+=(--restore-from-backup); shift ;;
        --access-token|--token|--bearer-token|--api-token|--o11y-token|--sf-token|--hec-token|--platform-hec-token|--org-token|--api-key)
            reject_secret_arg "$1" "(this skill does not take tokens on argv; base collector owns ingest-token handling)"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
RENDER_ARGS=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --mode "${MODE}" "${RENDER_ARGS[@]}")
if [[ "${DISCOVER_WORKLOADS}" == "true" ]]; then
    RENDER_ARGS+=(--discover-workloads)
fi
if [[ "${GITOPS_MODE}" == "true" ]]; then
    RENDER_ARGS+=(--gitops-mode)
fi
# For render-only modes --dry-run is a render preview (no files written).
# For apply / uninstall modes --dry-run is a cluster-operation preview, so
# the render must run for real and --dry-run flows only to the rendered
# helper script.
if [[ "${DRY_RUN}" == "true" && "${MODE}" == "render" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi
if [[ "${EXPLAIN}" == "true" ]]; then
    RENDER_ARGS+=(--explain)
fi

# Prefer repo-local venv python (matches splunk-cisco-skills MCP launcher).
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
else
    PYTHON_BIN="$(command -v python3)"
fi

if [[ "${EXPLAIN}" == "true" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
    exit 0
fi

# Render always runs first (it writes metadata.json that the apply/uninstall
# helper scripts consume). Discover-workloads skips the render path entirely.
if [[ "${DISCOVER_WORKLOADS}" == "true" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
    exit 0
fi

"${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"

# Render-only modes finish here. For apply / uninstall modes --dry-run flows
# through to the rendered scripts so the operator can preview the cluster
# operations they are about to authorise.
if [[ "${MODE}" == "render" && "${DRY_RUN}" == "true" ]]; then
    exit 0
fi

# Common args forwarded to every rendered script.
COMMON_ARGS=()
if [[ -n "${KUBE_CONTEXT}" ]]; then
    COMMON_ARGS+=(--kube-context "${KUBE_CONTEXT}")
fi
if [[ "${DRY_RUN}" == "true" ]]; then
    COMMON_ARGS+=(--dry-run)
fi

case "${MODE}" in
    render)
        : # render-only; rendered scripts can be invoked manually
        ;;
    apply-instrumentation)
        SCRIPT="${OUTPUT_DIR}/k8s-instrumentation/apply-instrumentation.sh"
        if [[ ! -x "${SCRIPT}" ]]; then
            log "ERROR: Rendered ${SCRIPT} is missing; re-run --render first."
            exit 1
        fi
        APPLY_ARGS=("${COMMON_ARGS[@]+"${COMMON_ARGS[@]}"}")
        if [[ "${ACCEPT_OBI_PRIVILEGED}" == "true" ]]; then
            APPLY_ARGS+=(--accept-obi-privileged)
        fi
        bash "${SCRIPT}" "${APPLY_ARGS[@]+"${APPLY_ARGS[@]}"}"
        ;;
    apply-annotations)
        SCRIPT="${OUTPUT_DIR}/k8s-instrumentation/apply-annotations.sh"
        if [[ ! -x "${SCRIPT}" ]]; then
            log "ERROR: Rendered ${SCRIPT} is missing; re-run --render first."
            exit 1
        fi
        APPLY_ARGS=("${COMMON_ARGS[@]+"${COMMON_ARGS[@]}"}")
        if [[ "${ACCEPT_AUTO_INSTRUMENTATION}" == "true" ]]; then
            APPLY_ARGS+=(--accept-auto-instrumentation)
        fi
        # Forward operator-supplied target selection. Default to --target-all
        # only when the operator did not pass any --target / --target-all flag.
        if [[ ${#TARGET_ARGS[@]} -gt 0 ]]; then
            APPLY_ARGS+=("${TARGET_ARGS[@]}")
        fi
        if [[ "${TARGET_ALL}" == "true" ]]; then
            APPLY_ARGS+=(--target-all)
        elif [[ ${#TARGET_ARGS[@]} -eq 0 ]]; then
            APPLY_ARGS+=(--target-all)
        fi
        bash "${SCRIPT}" "${APPLY_ARGS[@]}"
        ;;
    uninstall-instrumentation)
        SCRIPT="${OUTPUT_DIR}/k8s-instrumentation/uninstall.sh"
        if [[ ! -x "${SCRIPT}" ]]; then
            log "ERROR: Rendered ${SCRIPT} is missing; re-run --render first."
            exit 1
        fi
        APPLY_ARGS=("${COMMON_ARGS[@]+"${COMMON_ARGS[@]}"}")
        if [[ "${ACCEPT_AUTO_INSTRUMENTATION}" == "true" ]]; then
            APPLY_ARGS+=(--accept-auto-instrumentation)
        fi
        if [[ ${#TARGET_ARGS[@]} -gt 0 ]]; then
            APPLY_ARGS+=("${TARGET_ARGS[@]}")
        fi
        if [[ "${TARGET_ALL}" == "true" ]]; then
            APPLY_ARGS+=(--target-all)
        elif [[ ${#TARGET_ARGS[@]} -eq 0 ]]; then
            APPLY_ARGS+=(--target-all)
        fi
        if [[ "${PURGE_CRS}" == "true" ]]; then
            APPLY_ARGS+=(--purge-crs)
        fi
        if [[ "${PURGE_BACKUP}" == "true" ]]; then
            APPLY_ARGS+=(--purge-backup)
        fi
        bash "${SCRIPT}" "${APPLY_ARGS[@]}"
        ;;
    *)
        log "ERROR: Unknown mode ${MODE}"
        exit 1
        ;;
esac
