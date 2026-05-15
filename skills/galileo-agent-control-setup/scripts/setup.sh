#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/galileo-agent-control-rendered"
RENDERER="${SCRIPT_DIR}/render_assets.py"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
APPLY_SECTIONS_DEFAULT="server,auth,controls,python-runtime,typescript-runtime,otel-sink,splunk-sink,splunk-hec,otel-collector,dashboards,detectors"

usage() {
    cat <<'EOF'
Galileo Agent Control Setup

Usage:
  bash skills/galileo-agent-control-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                      Render artifacts (default when --apply is not set)
  --validate                    Validate rendered artifacts
  --doctor                      Render, validate, and summarize coverage
  --apply [SECTIONS]            Render then apply selected comma-separated sections.
                                With no list, applies all sections.
  --dry-run                     Show the render/apply plan without writing or applying
  --json                        Emit JSON for render and dry-run output

Apply sections:
  server                        Agent Control Docker/external server readiness
  auth                          File-backed auth environment templates
  controls                      Policy/control templates
  python-runtime                Python @control() runtime snippets
  typescript-runtime            TypeScript runtime snippets
  otel-sink                     OpenTelemetry sink environment handoff
  splunk-sink                   Custom Splunk HEC control-event sink
  splunk-hec                    Delegate HEC token/service setup to splunk-hec-service-setup
  otel-collector                Delegate Splunk OTel Collector setup
  dashboards                    Delegate Observability dashboards
  detectors                     Delegate Observability detectors

Configuration:
  --spec PATH                   Optional YAML/JSON spec (api_version: galileo-agent-control-setup/v1)
  --output-dir DIR              Rendered output directory
  --server-url URL              Agent Control server URL (default: http://localhost:8000)
  --server-host HOST            Server bind host for rendered env
  --server-port PORT            Server port for rendered env
  --agent-name NAME             Agent Control agent name
  --agent-description TEXT      Agent Control agent description
  --deployment-environment ENV  Deployment environment resource attribute
  --service-name NAME           OTel service.name for runtime assets
  --otlp-endpoint URL           OTLP HTTP endpoint for Agent Control OTel sink
  --splunk-platform enterprise|cloud
  --splunk-hec-url URL          Splunk HEC event URL or base HEC URL
  --splunk-index INDEX          Splunk destination index (default: agent_control)
  --splunk-source SOURCE        Splunk source (default: agent-control)
  --splunk-sourcetype VALUE     Splunk sourcetype (default: agent_control:events:json)
  --hec-token-name NAME         HEC token name for handoff
  --hec-allowed-indexes CSV     HEC allowed indexes for handoff
  --realm REALM                 Splunk Observability realm
  --collector-cluster-name NAME Splunk OTel Collector cluster name
  --runtime-target-dir DIR      Optional local app target for runtime snippets

Secret files:
  --agent-control-api-key-file PATH     Agent Control agent API key file
  --agent-control-admin-key-file PATH   Agent Control admin API key file
  --splunk-hec-token-file PATH          Splunk HEC token file
  --o11y-token-file PATH                Splunk Observability token file

Direct token/password flags such as --agent-control-api-key,
--agent-control-admin-key, --splunk-hec-token, --o11y-token, --token, --api-key,
--password, and --authorization are rejected.
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
    log "ERROR: Direct secret values are not accepted. Use --agent-control-api-key-file, --agent-control-admin-key-file, --splunk-hec-token-file, or --o11y-token-file."
    exit 1
}

require_value() {
    require_arg "$1" "$2" || exit 1
}

MODE_RENDER=false
MODE_VALIDATE=false
MODE_DOCTOR=false
MODE_APPLY=false
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
        --spec) require_value "$1" "$#"; SPEC="$2"; shift 2 ;;
        --output-dir) require_value "$1" "$#"; OUTPUT_DIR="$2"; shift 2 ;;
        --server-url|--server-host|--server-port|--agent-name|--agent-description|--deployment-environment|--service-name|--otlp-endpoint|--splunk-platform|--splunk-hec-url|--splunk-index|--splunk-source|--splunk-sourcetype|--hec-token-name|--hec-allowed-indexes|--realm|--collector-cluster-name|--runtime-target-dir|--agent-control-api-key-file|--agent-control-admin-key-file|--splunk-hec-token-file|--o11y-token-file)
            require_value "$1" "$#"
            RENDER_ARGS+=("$1" "$2")
            shift 2
            ;;
        --agent-control-api-key|--agent-control-admin-key|--splunk-hec-token|--hec-token|--o11y-token|--access-token|--api-key|--api-token|--authorization|--bearer-token|--password|--sf-token|--token)
            reject_secret_flag
            ;;
        --agent-control-api-key=*|--agent-control-admin-key=*|--splunk-hec-token=*|--hec-token=*|--o11y-token=*|--access-token=*|--api-key=*|--api-token=*|--authorization=*|--bearer-token=*|--password=*|--sf-token=*|--token=*)
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
        server) script="apply-server.sh" ;;
        auth) script="apply-auth.sh" ;;
        controls) script="apply-controls.sh" ;;
        python-runtime) script="apply-python-runtime.sh" ;;
        typescript-runtime) script="apply-typescript-runtime.sh" ;;
        otel-sink) script="apply-otel-sink.sh" ;;
        splunk-sink) script="apply-splunk-sink.sh" ;;
        splunk-hec) script="apply-splunk-hec.sh" ;;
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
    log "Galileo Agent Control doctor completed. Review ${OUTPUT_DIR}/coverage-report.json and ${OUTPUT_DIR}/handoff.md."
fi

if [[ "${MODE_APPLY}" == "true" ]]; then
    sections="${APPLY_SECTIONS:-${APPLY_SECTIONS_DEFAULT}}"
    if [[ "${APPLY_SECTIONS}" == "all" ]]; then
        sections="${APPLY_SECTIONS_DEFAULT}"
    fi
    IFS=',' read -ra section_array <<< "${sections}"
    for section in "${section_array[@]}"; do
        section="${section//[[:space:]]/}"
        apply_section "${section}"
    done
fi
