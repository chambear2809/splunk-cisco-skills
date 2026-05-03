#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

INSTALL_APP_SCRIPT="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"
VALIDATE_SCRIPT="${SCRIPT_DIR}/validate.sh"
ITSI_APP_ID="1841"

SOURCE="splunkbase"
APP_VERSION=""
LOCAL_FILE=""
NO_RESTART=false
INSTALL=false
VALIDATE=false
MODE_SET=false
DRY_RUN=false
JSON_OUTPUT=false
INSTALL_CMD=()
FALLBACK_CMD=()
VALIDATE_CMD=(bash "${VALIDATE_SCRIPT}")

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk ITSI Setup

Usage: $(basename "$0") [OPTIONS]

Modes:
  --install             Install ITSI only
  --validate            Validate ITSI only
  --dry-run             Show the install/validate plan without changing Splunk
  --json                Emit JSON with --dry-run

Options:
  --source splunkbase|local
  --app-version VER     Pin a Splunkbase ITSI version
  --file PATH           Local package path, or Splunkbase fallback package path
  --no-restart          Skip installer restart handling
  --help                Show this help

Default with no mode is install followed by validate.
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) INSTALL=true; MODE_SET=true; shift ;;
        --validate) VALIDATE=true; MODE_SET=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --source) require_arg "$1" $# || exit 1; SOURCE="$2"; shift 2 ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --file) require_arg "$1" $# || exit 1; LOCAL_FILE="$2"; shift 2 ;;
        --no-restart) NO_RESTART=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${MODE_SET}" != "true" ]]; then
    INSTALL=true
    VALIDATE=true
fi

case "${SOURCE}" in
    splunkbase|local) ;;
    *) echo "ERROR: --source must be splunkbase or local." >&2; exit 1 ;;
esac

build_install_command() {
    INSTALL_CMD=(bash "${INSTALL_APP_SCRIPT}" --source "${SOURCE}" --no-update)
    if [[ "${SOURCE}" == "splunkbase" ]]; then
        INSTALL_CMD+=(--app-id "${ITSI_APP_ID}")
        [[ -n "${APP_VERSION}" ]] && INSTALL_CMD+=(--app-version "${APP_VERSION}")
    else
        [[ -n "${LOCAL_FILE}" ]] || { echo "ERROR: --file is required with --source local." >&2; exit 1; }
        INSTALL_CMD+=(--file "${LOCAL_FILE}")
    fi
    [[ "${NO_RESTART}" == "true" ]] && INSTALL_CMD+=(--no-restart)
    return 0
}

build_fallback_command() {
    FALLBACK_CMD=()
    if [[ "${SOURCE}" == "splunkbase" && -n "${LOCAL_FILE}" ]]; then
        FALLBACK_CMD=(bash "${INSTALL_APP_SCRIPT}" --source local --file "${LOCAL_FILE}" --no-update)
        [[ "${NO_RESTART}" == "true" ]] && FALLBACK_CMD+=(--no-restart)
    fi
    return 0
}

render_shell_command() {
    printf '%q ' "$@"
}

join_unit() {
    local IFS=$'\037'
    printf '%s' "$*"
}

emit_plan() {
    local phases=()
    build_install_command
    build_fallback_command
    [[ "${INSTALL}" == "true" ]] && phases+=("install")
    [[ "${VALIDATE}" == "true" ]] && phases+=("validate")

    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        python3 - <<'PY'
import json
import os
import sys

sep = "\x1f"
payload = {
    "ok": True,
    "dry_run": True,
    "app_id": os.environ["ITSI_APP_ID"],
    "phases": os.environ.get("JSON_PHASES", "").split(sep)
    if os.environ.get("JSON_PHASES")
    else [],
    "install_command": os.environ.get("JSON_INSTALL_COMMAND", "").split(sep)
    if os.environ.get("JSON_INSTALL_COMMAND")
    else [],
    "fallback_install_command": os.environ.get("JSON_FALLBACK_COMMAND", "").split(sep)
    if os.environ.get("JSON_FALLBACK_COMMAND")
    else [],
    "validate_command": os.environ.get("JSON_VALIDATE_COMMAND", "").split(sep)
    if os.environ.get("JSON_VALIDATE_COMMAND")
    else [],
}
json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
    else
        echo "Planned phases:"
        printf '  - %s\n' "${phases[@]}"
        if [[ "${INSTALL}" == "true" ]]; then
            echo "Install command:"
            echo "  $(render_shell_command "${INSTALL_CMD[@]}")"
            if [[ -n "${FALLBACK_CMD[0]+set}" ]]; then
                echo "Fallback install command:"
                echo "  $(render_shell_command "${FALLBACK_CMD[@]}")"
            fi
        fi
        if [[ "${VALIDATE}" == "true" ]]; then
            echo "Validate command:"
            echo "  $(render_shell_command "${VALIDATE_CMD[@]}")"
        fi
    fi
}

if [[ "${DRY_RUN}" == "true" ]]; then
    build_install_command
    build_fallback_command
    phases=()
    [[ "${INSTALL}" == "true" ]] && phases+=("install")
    [[ "${VALIDATE}" == "true" ]] && phases+=("validate")
    JSON_PHASES="$(join_unit "${phases[@]}")" \
    JSON_INSTALL_COMMAND="$(join_unit "${INSTALL_CMD[@]}")" \
    JSON_FALLBACK_COMMAND="$(join_unit "${FALLBACK_CMD[@]}")" \
    JSON_VALIDATE_COMMAND="$(join_unit "${VALIDATE_CMD[@]}")" \
    ITSI_APP_ID="${ITSI_APP_ID}" \
    emit_plan
    exit 0
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    echo "ERROR: --json is only supported with --dry-run." >&2
    exit 1
fi

if [[ "${INSTALL}" == "true" ]]; then
    build_install_command
    build_fallback_command
    if ! "${INSTALL_CMD[@]}"; then
        if [[ -n "${FALLBACK_CMD[0]+set}" ]]; then
            echo "WARN: Splunkbase ITSI install failed; trying local fallback package." >&2
            "${FALLBACK_CMD[@]}"
        else
            exit 1
        fi
    fi
fi

if [[ "${VALIDATE}" == "true" ]]; then
    "${VALIDATE_CMD[@]}"
fi
