#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/cisco-data-fabric-rendered"
RENDERER="${SCRIPT_DIR}/render_assets.py"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
EXECUTE_SECTIONS_DEFAULT="data-management,federation,ai-activation,context-governance"

usage() {
    cat <<'EOF'
Cisco Data Fabric Setup

Usage:
  bash skills/cisco-data-fabric-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                      Render full feature/product coverage and handoffs
  --validate                    Validate rendered artifacts and semantic coverage
  --doctor                      Render, validate, and report adoption gaps
  --execute SECTION[,SECTION]   Render then run reviewed child render/doctor plans
  --accept-execute              Required for non-dry-run --execute
  --dry-run                     Print the command plan without writing or executing
  --json                        Emit machine-readable render/dry-run output

Delegated sections:
  data-management               Edge Processor and SPL2 child renders
  federation                    Provider-specific Federated Search child render
  ai-activation                 AI Toolkit, MCP client, and Agent Observability renders
  context-governance            Data-readiness doctor and ITSI lint handoffs

Handoff-only sections (explicit --execute exits nonzero):
  storage-catalog               Machine Data Lake, Catalog, and lifecycle handoffs
  experience                    Cisco Cloud Control and AI Canvas handoffs

Configuration:
  --spec PATH                   Optional YAML/JSON intake
  --output-dir DIR              Rendered output directory

This parent never calls a Cisco Data Fabric API and never applies a child plan.
Direct secret flags are rejected; use each child skill's secret-file workflow.
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
    log "ERROR: Direct secret values are not accepted. Use the owning child skill's secret-file workflow."
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
[[ -z "${SPEC}" ]] || RENDER_ARGS+=(--spec "${SPEC}")
if [[ -n "${EXECUTE_SECTIONS}" ]]; then
    RENDER_ARGS+=(--execute "${EXECUTE_SECTIONS}")
elif [[ "${MODE_EXECUTE}" == "true" ]]; then
    RENDER_ARGS+=(--execute "${EXECUTE_SECTIONS_DEFAULT}")
fi
[[ "${DRY_RUN}" != "true" ]] || RENDER_ARGS+=(--dry-run)
[[ "${JSON_OUTPUT}" != "true" ]] || RENDER_ARGS+=(--json)

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

ensure_no_blocking_gaps() {
    python3 - "${OUTPUT_DIR}/gap-register.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
errors = [gap for gap in payload.get("gaps", []) if gap.get("severity") == "error"]
if errors:
    keys = ", ".join(str(gap.get("key", "unknown")) for gap in errors)
    raise SystemExit(
        f"ERROR: refusing delegated execution with {len(errors)} blocking intake gap(s): {keys}. "
        f"Review {path} and rerender after correction."
    )
PY
}

ensure_selected_sections_ready() {
    local sections="$1"
    python3 - "${OUTPUT_DIR}/apply-plan.json" "${sections}" <<'PY'
import json
import sys
from pathlib import Path

plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
selected = [item.strip() for item in sys.argv[2].split(",") if item.strip()]
by_name = {section.get("name"): section for section in plan.get("sections", [])}
missing = [name for name in selected if not by_name.get(name, {}).get("commands")]
if missing:
    raise SystemExit(
        "ERROR: refusing before any delegated command runs because selected "
        f"section(s) have no reviewed child command: {', '.join(missing)}. "
        "Complete the referenced intake/specs and rerender."
    )
PY
}

execute_section() {
    local section="$1" script
    case "${section}" in
        data-management|federation|storage-catalog|ai-activation|context-governance|experience)
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
    log "Cisco Data Fabric doctor completed. Review ${OUTPUT_DIR}/doctor-report.md and ${OUTPUT_DIR}/gap-register.md." >&2
fi

if [[ "${MODE_EXECUTE}" == "true" ]]; then
    sections="${EXECUTE_SECTIONS:-${EXECUTE_SECTIONS_DEFAULT}}"
    [[ "${sections}" != "all" ]] || sections="${EXECUTE_SECTIONS_DEFAULT}"
    IFS=',' read -ra section_array <<< "${sections}"
    for section in "${section_array[@]}"; do
        section="${section//[[:space:]]/}"
        case "${section}" in
            storage-catalog|experience)
                log "ERROR: '${section}' is a rendered operator handoff, not an executable mutation."
                log "       No delegated sections were executed."
                exit 2
                ;;
        esac
    done
    ensure_no_blocking_gaps
    ensure_selected_sections_ready "${sections}"
    for section in "${section_array[@]}"; do
        section="${section//[[:space:]]/}"
        execute_section "${section}"
    done
fi
