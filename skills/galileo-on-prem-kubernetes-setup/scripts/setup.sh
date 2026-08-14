#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RENDERER="${SCRIPT_DIR}/render_router.py"
DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/galileo-on-prem-rendered"

usage() {
    cat <<'EOF'
Galileo On-Prem Kubernetes Setup (non-mutating parent/router)

Usage:
  bash skills/galileo-on-prem-kubernetes-setup/scripts/setup.sh MODE [options]

Read-only/local modes:
  --render                    Render an immutable orchestration packet
  --doctor                    Render, validate, and fail on coverage or readiness blockers
  --coverage                  Render, print coverage, and fail unless all four coverage arrays are empty
  --status                    Validate and summarize one existing immutable packet
  --validate                  Offline-validate the rendered packet selected by --output-dir

Options:
  --spec PATH                 Deployment spec (required for render/doctor/coverage)
  --output-dir DIR            Output root, or exact bundle for status/validate
  --runtime-inventory PATH    Override artifacts.stack_runtime_inventory with a Stack child report
  --galileo-console-url URL   Confirmed Galileo instance console URL
  --json                      Emit machine-readable result/status output
  --help                      Show help without writing or querying anything

The parent writes only local rendered artifacts. It never calls Kubernetes,
Helm, SSH, registries, Galileo APIs, cloud APIs, or child scripts. Install,
apply, upgrade, rollback, uninstall, delete, execute, registry-write, and
direct-secret options are rejected before output is written.
EOF
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_value() {
    [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || die "$1 requires a value"
}

MODE=""
VALIDATE_AFTER=false
SPEC=""
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
RUNTIME_INVENTORY=""
CONSOLE_URL=""
JSON=false

if [[ $# -eq 0 ]]; then
    usage
    exit 1
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render|--doctor|--coverage|--status)
            [[ -z "${MODE}" ]] || die "select exactly one of --render, --doctor, --coverage, or --status"
            MODE="${1#--}"
            shift
            ;;
        --validate)
            VALIDATE_AFTER=true
            shift
            ;;
        --spec)
            require_value "$1" "${2:-}"
            SPEC="$2"
            shift 2
            ;;
        --output-dir)
            require_value "$1" "${2:-}"
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --runtime-inventory)
            require_value "$1" "${2:-}"
            RUNTIME_INVENTORY="$2"
            shift 2
            ;;
        --galileo-console-url)
            require_value "$1" "${2:-}"
            CONSOLE_URL="$2"
            shift 2
            ;;
        --json)
            JSON=true
            shift
            ;;
        --apply|--install|--upgrade|--rollback|--uninstall|--delete|--execute|--accept-execute|--registry-write|--accept-registry-write|--create-namespace|--purge|--force|--atomic|--reuse-values|--take-ownership|--replace|--cleanup-on-fail|--no-hooks)
            die "$1 is a mutation option and is forbidden by this parent"
            ;;
        --apply=*|--install=*|--upgrade=*|--rollback=*|--uninstall=*|--delete=*|--execute=*|--registry-write=*|--purge=*)
            die "${1%%=*} is a mutation option and is forbidden by this parent"
            ;;
        --token|--password|--authorization|--secret|--api-key|--api-token|--client-secret|--private-key|--access-key|--repository-password|--galileo-api-key)
            die "direct secret options are forbidden; record only child secret-file paths in the spec"
            ;;
        --token=*|--password=*|--authorization=*|--secret=*|--api-key=*|--api-token=*|--client-secret=*|--private-key=*|--access-key=*|--repository-password=*|--galileo-api-key=*)
            die "direct secret options are forbidden; record only child secret-file paths in the spec"
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

if [[ -z "${MODE}" && "${VALIDATE_AFTER}" == "true" ]]; then
    MODE="validate"
elif [[ -z "${MODE}" ]]; then
    die "select --render, --doctor, --coverage, --status, or --validate"
fi

case "${MODE}" in
    render|doctor|coverage)
        [[ -n "${SPEC}" ]] || die "--${MODE} requires --spec"
        args=(--operation "${MODE}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
        [[ -z "${RUNTIME_INVENTORY}" ]] || args+=(--runtime-inventory "${RUNTIME_INVENTORY}")
        [[ -z "${CONSOLE_URL}" ]] || args+=(--galileo-console-url "${CONSOLE_URL}")
        [[ "${VALIDATE_AFTER}" != "true" ]] || args+=(--validate-rendered)
        [[ "${JSON}" != "true" ]] || args+=(--json)
        python3 "${RENDERER}" "${args[@]}"
        ;;
    status)
        [[ -z "${SPEC}" ]] || die "--status does not accept --spec"
        [[ -z "${RUNTIME_INVENTORY}" ]] || die "--status does not accept --runtime-inventory"
        [[ -z "${CONSOLE_URL}" ]] || die "--status does not accept --galileo-console-url"
        args=(--inspect "${OUTPUT_DIR}")
        [[ "${JSON}" != "true" ]] || args+=(--json)
        python3 "${RENDERER}" "${args[@]}"
        ;;
    validate)
        [[ -z "${SPEC}" ]] || die "--validate without a render mode does not accept --spec"
        [[ -z "${RUNTIME_INVENTORY}" ]] || die "--validate does not accept --runtime-inventory"
        [[ -z "${CONSOLE_URL}" ]] || die "--validate does not accept --galileo-console-url"
        args=(--validate-path "${OUTPUT_DIR}")
        [[ "${JSON}" != "true" ]] || args+=(--json)
        python3 "${RENDERER}" "${args[@]}"
        ;;
esac
