#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/galileo-platform-rendered"
RENDERER="${SCRIPT_DIR}/render_assets.py"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"

APPLY_SECTIONS_DEFAULT="readiness,observe-export,observe-runtime,protect-runtime,evaluate-assets,splunk-hec,splunk-otlp,otel-collector,dashboards,detectors"

usage() {
    cat <<'EOF'
Galileo Platform Setup

Usage:
  bash skills/galileo-platform-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                      Render artifacts (default when --apply is not set)
  --validate                    Validate rendered artifacts
  --doctor                      Render, validate, and summarize coverage
  --apply [SECTIONS]            Render then apply selected comma-separated sections.
                                With no list, applies all sections, or only
                                Splunk Observability Cloud sections with --o11y-only.
  --dry-run                     Show the render/apply plan without writing or applying
  --json                        Emit JSON for render and dry-run output
  --o11y-only                   Pure Splunk Observability Cloud mode. Skips
                                Splunk Platform HEC/export/OTLP defaults and
                                the OTel Collector platform HEC helper.

Apply sections:
  readiness                     Render/optionally probe Galileo endpoint and readiness checklist
  observe-export                Run the Galileo export_records to Splunk HEC bridge
  observe-runtime               Copy or point to Observe OpenTelemetry/OpenInference snippets
  protect-runtime               Copy or point to Protect invoke runtime snippets
  evaluate-assets               Render evaluation, experiment, dataset, metric, and annotation assets
  splunk-hec                    Delegate HEC token/service setup to splunk-hec-service-setup
  splunk-otlp                   Delegate Splunk Platform OTLP input to splunk-connect-for-otlp-setup
  otel-collector                Delegate Splunk OTel Collector setup to splunk-observability-otel-collector-setup
  dashboards                    Delegate Observability dashboards to splunk-observability-dashboard-builder
  detectors                     Delegate detectors/native ops to splunk-observability-native-ops

Configuration:
  --spec PATH                   Optional YAML/JSON spec (api_version: galileo-platform-setup/v1)
  --output-dir DIR              Rendered output directory
  --project-id ID               Galileo project ID for REST export
  --project-name NAME           Galileo project name for OTel runtime snippets
  --log-stream-id ID            Galileo log stream ID for REST export
  --log-stream NAME             Galileo log stream name for OTel runtime snippets
  --galileo-api-base URL        Galileo REST API base (default: https://api.galileo.ai)
  --galileo-console-url URL     Galileo console URL; used to derive API base when supplied
  --galileo-otel-endpoint URL   Galileo OTLP traces endpoint
  --experiment-id ID            Galileo experiment ID for export/evaluation assets
  --metrics-testing-id ID       Galileo metrics testing ID for export/evaluation assets
  --export-format jsonl|csv     Galileo export_records format (default: jsonl)
  --redact true|false           export_records redaction setting (default: true)
  --root-type session|trace|span
  --since ISO8601               REST export lower-bound
  --until ISO8601               REST export upper-bound
  --cursor-file PATH            REST export cursor path
  --splunk-platform enterprise|cloud
  --splunk-hec-url URL          Splunk HEC event URL or base HEC URL
  --splunk-index INDEX          Splunk destination index (default: galileo)
  --splunk-source SOURCE        Splunk source (default: galileo)
  --splunk-sourcetype VALUE     Splunk sourcetype (default: galileo:observe:json)
  --hec-token-name NAME         HEC token name for handoff
  --hec-allowed-indexes CSV     HEC allowed indexes for handoff
  --realm REALM                 Splunk Observability realm
  --service-name NAME           OTel service.name for runtime assets
  --deployment-environment NAME OTel deployment.environment
  --otlp-receiver-host HOST     Splunk Connect for OTLP receiver host
  --otlp-grpc-port PORT         OTLP gRPC receiver port
  --otlp-http-port PORT         OTLP HTTP receiver port
  --collector-cluster-name NAME Splunk OTel Collector cluster name
  --kube-namespace NAME         Kubernetes namespace for runtime helper
  --kube-workload NAME          Kubernetes deployment name for runtime helper
  --runtime-target-dir DIR      Optional local app target for Python runtime snippet

Secret files:
  --galileo-api-key-file PATH   Galileo API key file
  --splunk-hec-token-file PATH  Splunk HEC token file
  --o11y-token-file PATH        Splunk Observability token file

Direct token/password flags such as --galileo-api-key, --splunk-hec-token,
--o11y-token, --token, --api-key, --password, and --authorization are rejected.
EOF
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

reject_secret_flag() {
    log "ERROR: Direct secret values are not accepted. Use --galileo-api-key-file, --splunk-hec-token-file, or --o11y-token-file."
    exit 1
}

require_value() {
    require_arg "$1" "$2" || exit 1
}

MODE_RENDER=false
MODE_VALIDATE=false
MODE_DOCTOR=false
MODE_APPLY=false
O11Y_ONLY=false
APPLY_SECTIONS=""
DRY_RUN=false
JSON_OUTPUT=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC=""
RENDER_ARGS=()

if [[ $# -eq 0 ]]; then
    MODE_RENDER=true
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --doctor) MODE_DOCTOR=true; MODE_RENDER=true; MODE_VALIDATE=true; shift ;;
        --apply)
            MODE_APPLY=true
            MODE_RENDER=true
            if [[ $# -ge 2 && ! "$2" =~ ^-- ]]; then
                APPLY_SECTIONS="$2"
                shift 2
            else
                shift
            fi
            ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --o11y-only) O11Y_ONLY=true; RENDER_ARGS+=("$1"); shift ;;
        --spec) require_value "$1" "$#"; SPEC="$2"; shift 2 ;;
        --output-dir) require_value "$1" "$#"; OUTPUT_DIR="$2"; shift 2 ;;
        --project-id|--project-name|--log-stream-id|--log-stream|--galileo-api-base|--galileo-console-url|--galileo-otel-endpoint|--experiment-id|--metrics-testing-id|--export-format|--redact|--root-type|--since|--until|--cursor-file|--splunk-platform|--splunk-hec-url|--splunk-index|--splunk-source|--splunk-sourcetype|--splunk-host|--hec-token-name|--hec-allowed-indexes|--realm|--service-name|--deployment-environment|--otlp-receiver-host|--otlp-grpc-port|--otlp-http-port|--collector-cluster-name|--kube-namespace|--kube-workload|--runtime-target-dir|--galileo-api-key-file|--splunk-hec-token-file|--o11y-token-file)
            require_value "$1" "$#"
            RENDER_ARGS+=("$1" "$2")
            shift 2
            ;;
        --galileo-api-key|--galileo-bearer-token|--splunk-hec-token|--hec-token|--o11y-token|--access-token|--api-key|--api-token|--authorization|--bearer-token|--password|--sf-token|--token)
            reject_secret_flag
            ;;
        --galileo-api-key=*|--galileo-bearer-token=*|--splunk-hec-token=*|--hec-token=*|--o11y-token=*|--access-token=*|--api-key=*|--api-token=*|--authorization=*|--bearer-token=*|--password=*|--sf-token=*|--token=*)
            reject_secret_flag
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

if [[ -n "${APPLY_SECTIONS}" ]]; then
    RENDER_ARGS+=(--apply "${APPLY_SECTIONS}")
fi
if [[ -n "${SPEC}" ]]; then
    RENDER_ARGS+=(--spec "${SPEC}")
fi
if [[ "${DRY_RUN}" == "true" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi

render_assets() {
    python3 "${RENDERER}" --output-dir "${OUTPUT_DIR}" "${RENDER_ARGS[@]}"
}

run_validate() {
    bash "${VALIDATE_SCRIPT}" --output-dir "${OUTPUT_DIR}"
}

apply_section() {
    local section="$1" script=""
    case "${section}" in
        readiness) script="apply-readiness.sh" ;;
        observe-export) script="apply-observe-export.sh" ;;
        observe-runtime) script="apply-observe-runtime.sh" ;;
        protect-runtime) script="apply-protect-runtime.sh" ;;
        evaluate-assets) script="apply-evaluate-assets.sh" ;;
        splunk-hec) script="apply-splunk-hec.sh" ;;
        splunk-otlp) script="apply-splunk-otlp.sh" ;;
        otel-collector) script="apply-otel-collector.sh" ;;
        dashboards) script="apply-dashboards.sh" ;;
        detectors) script="apply-detectors.sh" ;;
        "") return 0 ;;
        *) log "ERROR: Unknown apply section: ${section}"; exit 1 ;;
    esac
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: ${OUTPUT_DIR}/scripts/${script}"
        return 0
    fi
    bash "${OUTPUT_DIR}/scripts/${script}"
}

if [[ "${MODE_RENDER}" == "true" ]]; then
    render_assets
fi

if [[ "${DRY_RUN}" == "true" ]]; then
    exit 0
fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    run_validate
fi

if [[ "${MODE_DOCTOR}" == "true" ]]; then
    log "Galileo platform doctor completed. Review ${OUTPUT_DIR}/readiness/readiness-report.json, ${OUTPUT_DIR}/coverage-report.json, and ${OUTPUT_DIR}/handoff.md."
fi

if [[ "${MODE_APPLY}" == "true" ]]; then
    sections="${APPLY_SECTIONS:-${APPLY_SECTIONS_DEFAULT}}"
    if [[ "${APPLY_SECTIONS}" == "all" ]]; then
        sections="${APPLY_SECTIONS_DEFAULT}"
    fi
    if [[ "${O11Y_ONLY}" == "true" && ( -z "${APPLY_SECTIONS}" || "${APPLY_SECTIONS}" == "all" ) ]]; then
        sections="readiness,observe-runtime,protect-runtime,evaluate-assets,otel-collector,dashboards,detectors"
    fi
    IFS=',' read -ra section_array <<< "${sections}"
    for section in "${section_array[@]}"; do
        section="${section//[[:space:]]/}"
        if [[ "${O11Y_ONLY}" == "true" ]]; then
            case "${section}" in
                observe-export|splunk-hec|splunk-otlp)
                    log "ERROR: --o11y-only cannot apply Splunk Platform section: ${section}"
                    exit 1
                    ;;
            esac
        fi
        apply_section "${section}"
    done
fi
