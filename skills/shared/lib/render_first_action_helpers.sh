#!/usr/bin/env bash
# Shared action helpers for render-first skills with guarded execution modes.

if [[ -z "${REPO_ROOT:-}" ]]; then
    _RF_ACTION_HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    REPO_ROOT="$(cd "${_RF_ACTION_HELPER_DIR}/../../.." && pwd)"
fi

rf_join_unit() {
    local IFS=$'\037'
    printf '%s' "$*"
}

rf_print_command() {
    printf '  '
    printf '%q ' "$@"
    printf '\n'
}

rf_run_command() {
    if [[ "${DRY_RUN:-false}" == "true" ]]; then
        printf 'DRY RUN:\n'
        rf_print_command "$@"
        return 0
    fi
    "$@"
}

rf_require_local_file() {
    local flag_name="$1"
    local file_path="$2"
    if [[ -z "${file_path}" ]]; then
        echo "ERROR: ${flag_name} is required for this action." >&2
        exit 1
    fi
    if [[ ! -f "${file_path}" ]]; then
        echo "ERROR: File not found: ${file_path}" >&2
        exit 1
    fi
    return 0
}

rf_build_app_install_command() {
    local app_id="$1"
    local source="$2"
    local local_file="$3"
    local app_version="$4"
    local no_restart="$5"

    RF_INSTALL_CMD=(bash "${REPO_ROOT}/skills/splunk-app-install/scripts/install_app.sh" --source "${source}")
    case "${source}" in
        splunkbase)
            [[ -n "${app_id}" && "${app_id}" != "N/A" ]] || {
                echo "ERROR: Splunkbase install requires a known app id." >&2
                exit 1
            }
            RF_INSTALL_CMD+=(--app-id "${app_id}" --no-update)
            [[ -n "${app_version}" ]] && RF_INSTALL_CMD+=(--app-version "${app_version}")
            ;;
        local)
            rf_require_local_file "--file" "${local_file}"
            RF_INSTALL_CMD+=(--file "${local_file}" --no-update)
            ;;
        *)
            echo "ERROR: --source must be splunkbase or local." >&2
            exit 1
            ;;
    esac
    [[ "${no_restart}" == "true" ]] && RF_INSTALL_CMD+=(--no-restart)
    return 0
}

rf_emit_action_plan_json() {
    RF_SKILL_NAME="${1}" \
    RF_PRODUCT_NAME="${2}" \
    RF_PHASES="${3}" \
    RF_RENDER_COMMAND="${4}" \
    RF_INSTALL_COMMAND="${5}" \
    RF_VALIDATE_COMMAND="${6}" \
    RF_NOTES="${7}" \
    python3 - <<'PY'
import json
import os
import sys

sep = "\x1f"

def split_env(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return value.split(sep) if value else []

payload = {
    "ok": True,
    "dry_run": True,
    "skill_name": os.environ["RF_SKILL_NAME"],
    "product": os.environ["RF_PRODUCT_NAME"],
    "phases": split_env("RF_PHASES"),
    "render_command": split_env("RF_RENDER_COMMAND"),
    "install_command": split_env("RF_INSTALL_COMMAND"),
    "validate_command": split_env("RF_VALIDATE_COMMAND"),
    "notes": split_env("RF_NOTES"),
}
json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
}

rf_emit_action_plan_text() {
    local product="$1"
    local phases_join="$2"
    shift 2
    local phases=()
    local IFS=$'\037'
    read -r -a phases <<<"${phases_join}"
    unset IFS

    echo "Action plan: ${product}"
    echo "Planned phases:"
    printf '  - %s\n' "${phases[@]}"
}
