#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck disable=SC1091
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh}"
VALIDATE_SCRIPT="${VALIDATE_SCRIPT:-${SCRIPT_DIR}/validate.sh}"
OUTPUT_DIR="${PROJECT_ROOT}/splunk-ai-ml-toolkit-rendered"
SPEC=""
MODE="render"
PSC_TARGET=""
PLATFORM=""
SPLUNK_VERSION=""
DSDL_RUNTIME=""
INCLUDE_DSDL=false
NO_DSDL=false
LEGACY_ANOMALY_AUDIT=false
JSON_OUTPUT=false
DRY_RUN=false

usage() {
    cat <<'EOF'
Splunk AI/ML Toolkit Setup

Usage:
  setup.sh [MODE] [OPTIONS]

Modes:
  --render                         Render coverage and apply plan (default)
  --validate                       Validate rendered output; composable with --render
  --doctor                         Render doctor report and legacy audit guidance
  --discover                       Print product catalog and coverage surface
  --install                        Render, then install/update PSC, AI Toolkit, optional DSDL

Options:
  --spec PATH
  --output-dir DIR
  --platform enterprise|cloud
  --splunk-version VERSION
  --psc-target linux64|windows64|mac-intel|mac-arm|linux32|auto
  --include-dsdl
  --no-dsdl
  --dsdl-runtime handoff|docker|kubernetes|openshift|hpc|gpu|airgap
  --legacy-anomaly-audit
  --json
  --dry-run
  --help

Direct-secret flags are rejected:
  --token --access-token --api-token --password --client-secret --llm-api-key
EOF
}

reject_direct_secret_flag() {
    reject_secret_arg "$1" "file-backed credentials handled by the owning setup skill"
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE="render"; shift ;;
        --validate) MODE="validate"; shift ;;
        --doctor) MODE="doctor"; LEGACY_ANOMALY_AUDIT=true; shift ;;
        --discover) MODE="discover"; shift ;;
        --install) MODE="install"; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --platform) require_arg "$1" "$#" || exit 1; PLATFORM="$2"; shift 2 ;;
        --splunk-version) require_arg "$1" "$#" || exit 1; SPLUNK_VERSION="$2"; shift 2 ;;
        --psc-target) require_arg "$1" "$#" || exit 1; PSC_TARGET="$2"; shift 2 ;;
        --include-dsdl) INCLUDE_DSDL=true; shift ;;
        --no-dsdl) NO_DSDL=true; shift ;;
        --dsdl-runtime) require_arg "$1" "$#" || exit 1; DSDL_RUNTIME="$2"; shift 2 ;;
        --legacy-anomaly-audit) LEGACY_ANOMALY_AUDIT=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --token|--access-token|--api-token|--password|--client-secret|--llm-api-key)
            reject_direct_secret_flag "$1"
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

renderer_args=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
if [[ -n "${PLATFORM}" ]]; then
    renderer_args+=(--platform "${PLATFORM}")
fi
if [[ -n "${SPLUNK_VERSION}" ]]; then
    renderer_args+=(--splunk-version "${SPLUNK_VERSION}")
fi
if [[ -n "${PSC_TARGET}" ]]; then
    renderer_args+=(--psc-target "${PSC_TARGET}")
fi
if [[ "${INCLUDE_DSDL}" == "true" ]]; then
    renderer_args+=(--include-dsdl)
fi
if [[ "${NO_DSDL}" == "true" ]]; then
    renderer_args+=(--no-dsdl)
fi
if [[ -n "${DSDL_RUNTIME}" ]]; then
    renderer_args+=(--dsdl-runtime "${DSDL_RUNTIME}")
fi
if [[ "${LEGACY_ANOMALY_AUDIT}" == "true" ]]; then
    renderer_args+=(--legacy-anomaly-audit)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    renderer_args+=(--json)
fi

if [[ "${MODE}" == "discover" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" --discover
    exit $?
fi

if [[ "${MODE}" == "validate" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${renderer_args[@]}"
    bash "${VALIDATE_SCRIPT}" --rendered-dir "${OUTPUT_DIR}"
    exit $?
fi

if [[ "${MODE}" == "doctor" || "${MODE}" == "render" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${renderer_args[@]}"
    if [[ "${MODE}" == "doctor" ]]; then
        bash "${VALIDATE_SCRIPT}" --rendered-dir "${OUTPUT_DIR}"
    fi
    exit $?
fi

if [[ "${MODE}" == "install" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${renderer_args[@]}"
    bash "${VALIDATE_SCRIPT}" --rendered-dir "${OUTPUT_DIR}"
    "${PYTHON_BIN}" - "${OUTPUT_DIR}/apply-plan.json" "${APP_INSTALL_SCRIPT}" "${DRY_RUN}" <<'PY'
import json
import shlex
import subprocess
import sys
from pathlib import Path

plan_path = Path(sys.argv[1])
install_script = sys.argv[2]
dry_run = sys.argv[3] == "true"
plan = json.loads(plan_path.read_text(encoding="utf-8"))
for step in plan.get("steps", []):
    if step.get("automation") != "delegated" or not step.get("app_id"):
        continue
    command = ["bash", install_script, "--source", "splunkbase", "--app-id", str(step["app_id"]), "--update"]
    if dry_run:
        print("DRY-RUN:", " ".join(shlex.quote(part) for part in command))
        continue
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)
PY
    bash "${VALIDATE_SCRIPT}" --rendered-dir "${OUTPUT_DIR}"
    exit $?
fi

log "ERROR: Unsupported mode ${MODE}"
exit 1
