#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/cisco-cloud-control-rendered"
RENDERER="${SCRIPT_DIR}/render_assets.py"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
EXECUTE_SECTIONS_DEFAULT="data-fabric,mcp,agent-observability,observability-content"

usage() {
    cat <<'EOF'
Cisco Cloud Control Setup

Usage:
  bash skills/cisco-cloud-control-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                      Render Cisco Cloud Control readiness artifacts
  --validate                    Validate rendered artifacts
  --doctor                      Render, validate, and write doctor-report.md
  --execute SECTION[,SECTION]   Render then execute selected delegated sections
  --accept-execute              Required for non-dry-run --execute
  --dry-run                     Show render/execute plan without writing or executing
  --json                        Emit JSON for render and dry-run output

Delegated executable sections:
  data-fabric                   Delegate Data Fabric prerequisite plans
  mcp                           Delegate Splunk and ThousandEyes MCP setup
  agent-observability           Delegate Splunk AI Agent Monitoring setup
  observability-content         Delegate dashboard and detector render plans
Handoff-only sections (rendered; explicit --execute exits nonzero):
  domain-readiness              Emit Cisco domain child-skill handoffs
  cloud-control-studio          UI handoff only
  ai-canvas                     AI Canvas handoff only

Configuration:
  --spec PATH                   Optional YAML/JSON spec
  --output-dir DIR              Rendered output directory

Direct secret flags such as --token, --password, --api-key, --client-secret,
and --private-key are rejected. Use child skill secret-file options in reviewed
child specs instead.
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
    log "ERROR: Direct secret values are not accepted. Use delegated child skill secret-file options."
    exit 1
}

require_value() {
    require_arg "$1" "$2" || exit 1
}

MODE_RENDER=false
MODE_VALIDATE=false
MODE_DOCTOR=false
MODE_EXECUTE=false
ACCEPT_EXECUTE=false
DRY_RUN=false
JSON_OUTPUT=false
EXECUTE_SECTIONS=""
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
        --execute)
            MODE_EXECUTE=true
            MODE_RENDER=true
            if [[ $# -ge 2 && ! "$2" =~ ^-- ]]; then
                EXECUTE_SECTIONS="$2"
                shift 2
            else
                shift
            fi
            ;;
        --accept-execute) ACCEPT_EXECUTE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --spec) require_value "$1" "$#"; SPEC="$2"; shift 2 ;;
        --output-dir) require_value "$1" "$#"; OUTPUT_DIR="$2"; shift 2 ;;
        --token|--password|--api-key|--api-token|--access-token|--bearer-token|--client-secret|--private-key|--secret)
            reject_secret_flag
            ;;
        --token=*|--password=*|--api-key=*|--api-token=*|--access-token=*|--bearer-token=*|--client-secret=*|--private-key=*|--secret=*)
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

if [[ "${MODE_EXECUTE}" == "true" && "${DRY_RUN}" != "true" && "${ACCEPT_EXECUTE}" != "true" ]]; then
    log "ERROR: --execute requires --accept-execute unless --dry-run is set."
    exit 1
fi

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

if [[ -n "${SPEC}" ]]; then
    RENDER_ARGS+=(--spec "${SPEC}")
fi
if [[ -n "${EXECUTE_SECTIONS}" ]]; then
    RENDER_ARGS+=(--execute "${EXECUTE_SECTIONS}")
elif [[ "${MODE_EXECUTE}" == "true" ]]; then
    RENDER_ARGS+=(--execute "${EXECUTE_SECTIONS_DEFAULT}")
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
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        bash "${VALIDATE_SCRIPT}" --output-dir "${OUTPUT_DIR}" >&2
    else
        bash "${VALIDATE_SCRIPT}" --output-dir "${OUTPUT_DIR}"
    fi
}

execute_section() {
    local section="$1" script
    case "${section}" in
        data-fabric|mcp|agent-observability|observability-content|domain-readiness|cloud-control-studio|ai-canvas)
            script="${OUTPUT_DIR}/scripts/execute-${section}.sh"
            ;;
        "") return 0 ;;
        *) log "ERROR: Unknown execute section: ${section}"; exit 1 ;;
    esac
    [[ -x "${script}" ]] || { log "ERROR: Missing executable script: ${script}"; exit 1; }
    bash "${script}"
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
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        log "Cisco Cloud Control doctor completed. Review ${OUTPUT_DIR}/doctor-report.md and ${OUTPUT_DIR}/coverage-report.json." >&2
    else
        log "Cisco Cloud Control doctor completed. Review ${OUTPUT_DIR}/doctor-report.md and ${OUTPUT_DIR}/coverage-report.json."
    fi
fi

if [[ "${MODE_EXECUTE}" == "true" ]]; then
    sections="${EXECUTE_SECTIONS:-${EXECUTE_SECTIONS_DEFAULT}}"
    if [[ "${sections}" == "all" ]]; then
        sections="${EXECUTE_SECTIONS_DEFAULT}"
    fi
    IFS=',' read -ra section_array <<< "${sections}"
    # Refuse an unsupported/handoff-only selection before running any delegated
    # mutation. This prevents a mixed request from applying earlier sections
    # and only then discovering that a later section cannot execute.
    for section in "${section_array[@]}"; do
        section="${section//[[:space:]]/}"
        case "${section}" in
            domain-readiness|cloud-control-studio|ai-canvas)
                log "ERROR: '${section}' is a rendered operator handoff, not an executable mutation."
                log "       Review its artifact under ${OUTPUT_DIR}; no delegated sections were executed."
                exit 2
                ;;
        esac
    done
    for section in "${section_array[@]}"; do
        section="${section//[[:space:]]/}"
        execute_section "${section}"
    done
fi
