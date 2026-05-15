#!/usr/bin/env bash
set -euo pipefail

# Splunk Observability Cloud GCP Integration Setup
#
# Render-first CLI — mirrors splunk-observability-aws-integration:
#   --render (default), --apply [SECTIONS], --validate [--live],
#   --doctor, --discover, --quickstart, --quickstart-from-live,
#   --explain, --rollback SECTION, --list-services
#
# File-based secrets only. The Splunk O11y token and GCP SA key are
# read from chmod-600 files. Never passed in argv.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RENDERER="${SCRIPT_DIR}/render_assets.py"
SKILL_NAME="splunk-observability-gcp-integration"
DEFAULT_RENDER_DIR_NAME="splunk-observability-gcp-integration-rendered"

PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

MODE="render"
SECTIONS=""
SPEC=""
OUTPUT_DIR=""
REALM=""
TOKEN_FILE=""
KEY_FILE=""
ALLOW_LOOSE_TOKEN_PERMS=false
JSON_OUTPUT=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Observability Cloud — GCP Integration Setup

Usage: $(basename "$0") [MODE] [OPTIONS]

Modes (pick one; --render is the default):
  --render                       Produce the numbered plan tree under --output-dir.
  --apply [SECTIONS]             Call POST/PUT /v2/integration. Sections: integration,validation.
  --validate [--live]            Static checks; --live adds probe GET /v2/integration.
  --doctor                       Validate services, poll-rate, namedToken, credential-hash.
  --discover                     List existing GCP integrations via GET /v2/integration.
  --quickstart                   Render + print exact --apply command.
  --quickstart-from-live         Snapshot a live integration into observed.yaml.
  --explain                      Print the apply plan in plain English; no API calls.
  --rollback SECTION             Disable or delete the integration. Sections: integration, delete.
  --list-services                Print the supported GCP services enum (32 entries).

Spec / output:
  --spec PATH                    Spec file (YAML or JSON); defaults to template.example.
  --output-dir PATH              Output directory; defaults to ${DEFAULT_RENDER_DIR_NAME}.
  --realm REALM                  Override spec.realm.

File-based secrets (chmod 600 enforced):
  --token-file PATH              Splunk O11y admin user API access token.
  --key-file PATH                GCP Service Account JSON key file.
  --allow-loose-token-perms      Override chmod-600 check (WARN-only).

Behaviour flags:
  --dry-run                      Skip live API calls; render only.
  --json                         Machine-readable result.
  -h | --help                    Show this help.

Direct-secret flags below are REJECTED:
  --secret --password --api-key --project-key --token

Examples:
  # Render from template.example:
  bash $0 --realm us1

  # Full apply:
  bash $0 --apply --spec my-spec.yaml --realm us1 \\
    --token-file /tmp/splunk_token \\
    --key-file /tmp/gcp-sa-key.json
EOF
    exit "${exit_code}"
}

reject_direct_secret() {
    local name="$1"
    cat >&2 <<EOF
Refusing direct-secret flag --${name}. Use file-based equivalents:
  --key-file PATH       GCP Service Account JSON key file
  --token-file PATH     Splunk O11y API access token
See skills/${SKILL_NAME}/SKILL.md for credential setup instructions.
EOF
    exit 2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE="render" ;;
        --apply)
            MODE="apply"
            if [[ $# -ge 2 && "$2" != --* ]]; then
                SECTIONS="$2"; shift
            fi
            ;;
        --validate) MODE="validate" ;;
        --live) export SGCP_VALIDATE_LIVE=true ;;
        --doctor) MODE="doctor" ;;
        --discover) MODE="discover" ;;
        --quickstart) MODE="quickstart" ;;
        --quickstart-from-live) MODE="quickstart_from_live" ;;
        --explain) MODE="explain" ;;
        --rollback) MODE="rollback"; SECTIONS="${2:-}"; [[ -n "${SECTIONS:-}" ]] && shift ;;
        --list-services) MODE="list_services" ;;
        --spec) SPEC="$2"; shift ;;
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --realm) REALM="$2"; shift ;;
        --token-file) TOKEN_FILE="$2"; shift ;;
        --key-file) KEY_FILE="$2"; shift ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true ;;
        --dry-run) DRY_RUN=true ;;
        --json) JSON_OUTPUT=true ;;
        --secret|--password|--api-key|--project-key|--token) reject_direct_secret "${1#--}" ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${SPEC}" ]]; then
    SPEC="${SCRIPT_DIR}/../template.example"
fi
if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}"
fi

load_observability_cloud_settings 2>/dev/null || true
if [[ -z "${REALM}" && -n "${SPLUNK_O11Y_REALM:-}" ]]; then
    REALM="${SPLUNK_O11Y_REALM}"
fi
if [[ -z "${TOKEN_FILE}" && -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
    TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE}"
fi

file_mode_octal() {
    local path="$1"
    "${PYTHON_BIN}" - "${path}" <<'PY'
import os, stat, sys
print(format(stat.S_IMODE(os.stat(sys.argv[1]).st_mode), "03o"))
PY
}

assert_secret_file_perms() {
    local path="$1"
    local label="$2"
    [[ -z "${path}" ]] && return 0
    if [[ ! -f "${path}" ]]; then
        echo "FAIL: ${label} (${path}) does not exist." >&2; exit 2
    fi
    if [[ ! -s "${path}" ]]; then
        echo "FAIL: ${label} (${path}) is empty." >&2; exit 2
    fi
    local mode
    mode="$(file_mode_octal "${path}")"
    if [[ "${mode}" != "600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS}" == "true" ]]; then
            echo "WARN: ${label} (${path}) has loose permissions (${mode}); proceeding under --allow-loose-token-perms." >&2
        else
            echo "FAIL: ${label} (${path}) has loose permissions (${mode}); chmod 600 ${path}" >&2; exit 2
        fi
    fi
}

run_renderer() {
    local args=("--spec" "${SPEC}" "--output-dir" "${OUTPUT_DIR}")
    [[ -n "${REALM}" ]] && args+=("--realm" "${REALM}")
    [[ -n "${KEY_FILE}" ]] && args+=("--key-file" "${KEY_FILE}")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=("--json")
    "${PYTHON_BIN}" "${RENDERER}" "${args[@]}"
}

run_validate() {
    local args=(--output-dir "${OUTPUT_DIR}")
    [[ "${SGCP_VALIDATE_LIVE:-}" == "true" ]] && args+=(--live)
    [[ -n "${TOKEN_FILE}" ]] && args+=(--token-file "${TOKEN_FILE}")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    bash "${SCRIPT_DIR}/validate.sh" "${args[@]}"
}

run_doctor() {
    bash "${SCRIPT_DIR}/doctor.sh" \
        --output-dir "${OUTPUT_DIR}" \
        --realm "${REALM:-us1}" \
        ${JSON_OUTPUT:+--json}
}

case "${MODE}" in
    render)
        run_renderer
        ;;
    explain)
        run_renderer
        echo ""
        echo "==> Review the rendered plan in: ${OUTPUT_DIR}"
        echo "==> When ready, apply with:"
        echo "    bash ${0} --apply --spec ${SPEC} --realm ${REALM:-<realm>} --token-file /tmp/splunk_token"
        ;;
    apply)
        assert_secret_file_perms "${TOKEN_FILE}" "Splunk O11y token"
        assert_secret_file_perms "${KEY_FILE}" "GCP SA key"
        run_renderer
        local_sections="${SECTIONS}"
        if [[ -z "${local_sections}" ]]; then
            local_sections="integration,validation"
        fi
        IFS=',' read -ra _sects <<< "${local_sections}"
        for s in "${_sects[@]}"; do
            s="${s// /}"
            [[ -z "${s}" ]] && continue
            echo "==> applying section: ${s}"
            case "${s}" in
                integration)
                    if [[ "${DRY_RUN}" == "true" ]]; then
                        echo "(dry-run) would POST/PUT ${OUTPUT_DIR}/rest/create.json to /v2/integration"
                    else
                        local key_file_args=()
                        [[ -n "${KEY_FILE}" ]] && key_file_args+=(--key-file "${KEY_FILE}")
                        "${PYTHON_BIN}" "${SCRIPT_DIR}/gcp_integration_api.py" \
                            --realm "${REALM:-us1}" \
                            --token-file "${TOKEN_FILE}" \
                            "${key_file_args[@]}" \
                            --payload-file "${OUTPUT_DIR}/rest/create.json" \
                            --state-dir "${OUTPUT_DIR}/state" \
                            upsert
                    fi
                    ;;
                validation)
                    run_validate
                    ;;
                *)
                    echo "Unknown section: ${s}" >&2; exit 2
                    ;;
            esac
        done
        ;;
    validate)
        run_validate
        ;;
    doctor)
        run_renderer
        run_doctor
        ;;
    discover)
        if [[ -z "${TOKEN_FILE}" ]]; then
            echo "ERROR: --token-file is required for --discover." >&2; exit 2
        fi
        assert_secret_file_perms "${TOKEN_FILE}" "Splunk O11y token"
        "${PYTHON_BIN}" "${SCRIPT_DIR}/gcp_integration_api.py" \
            --realm "${REALM:-us1}" \
            --token-file "${TOKEN_FILE}" \
            --state-dir "${OUTPUT_DIR}/state" \
            --output "${OUTPUT_DIR}/state/current-state.json" \
            discover
        echo "==> Written to ${OUTPUT_DIR}/state/current-state.json"
        ;;
    quickstart)
        echo "==> Quickstart: rendering plan from ${SPEC}..."
        run_renderer
        echo ""
        echo "==> Plan rendered to: ${OUTPUT_DIR}"
        echo ""
        echo "==> Review the REST payload and Terraform, then apply:"
        echo "    bash ${0} --apply --spec ${SPEC} --realm ${REALM:-<realm>} \\"
        echo "      --token-file /tmp/splunk_token \\"
        echo "      --key-file /tmp/gcp-sa-key.json"
        ;;
    quickstart_from_live)
        if [[ -z "${TOKEN_FILE}" ]]; then
            echo "ERROR: --token-file is required for --quickstart-from-live." >&2; exit 2
        fi
        assert_secret_file_perms "${TOKEN_FILE}" "Splunk O11y token"
        mkdir -p "${OUTPUT_DIR}/state"
        "${PYTHON_BIN}" "${SCRIPT_DIR}/gcp_integration_api.py" \
            --realm "${REALM:-us1}" \
            --token-file "${TOKEN_FILE}" \
            --state-dir "${OUTPUT_DIR}/state" \
            --output "${OUTPUT_DIR}/state/current-state.json" \
            discover
        echo "==> Live state written to ${OUTPUT_DIR}/state/current-state.json"
        echo "==> Review and convert to a spec:"
        echo "    cp skills/${SKILL_NAME}/template.example template.observed.yaml"
        ;;
    rollback)
        case "${SECTIONS}" in
            integration|"")
                echo "==> Rollback: disabling GCP integration in Splunk O11y..."
                if [[ -z "${TOKEN_FILE}" ]]; then
                    echo "ERROR: --token-file is required for rollback." >&2; exit 2
                fi
                assert_secret_file_perms "${TOKEN_FILE}" "Splunk O11y token"
                "${PYTHON_BIN}" "${SCRIPT_DIR}/gcp_integration_api.py" \
                    --realm "${REALM:-us1}" \
                    --token-file "${TOKEN_FILE}" \
                    --state-dir "${OUTPUT_DIR}/state" \
                    --payload-file "${OUTPUT_DIR}/rest/create.json" \
                    disable
                ;;
            delete)
                echo "==> Rollback (delete): removing GCP integration from Splunk O11y..."
                if [[ -z "${TOKEN_FILE}" ]]; then
                    echo "ERROR: --token-file is required for rollback delete." >&2; exit 2
                fi
                assert_secret_file_perms "${TOKEN_FILE}" "Splunk O11y token"
                "${PYTHON_BIN}" "${SCRIPT_DIR}/gcp_integration_api.py" \
                    --realm "${REALM:-us1}" \
                    --token-file "${TOKEN_FILE}" \
                    --state-dir "${OUTPUT_DIR}/state" \
                    --payload-file "${OUTPUT_DIR}/rest/create.json" \
                    delete
                ;;
            *)
                echo "Unknown rollback section: ${SECTIONS}. Supported: integration, delete" >&2; exit 2
                ;;
        esac
        ;;
    list_services)
        "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --list-services
        ;;
    *)
        echo "Unknown mode: ${MODE}" >&2; usage 1
        ;;
esac
