#!/usr/bin/env bash
# Splunk On-Call setup orchestrator.
#
# Render-first by default. Mutates only when --apply, --send-alert,
# --install-splunk-app, or --uninstall is passed. File-based secrets only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_oncall_settings >/dev/null 2>&1 || true

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-oncall-rendered"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON:-python3}"
fi

usage() {
    cat <<'EOF'
Splunk On-Call (formerly VictorOps) full lifecycle.

Usage:
  bash skills/splunk-oncall-setup/scripts/setup.sh [mode] [options]

Modes (default: --render):
  --render              Render and validate a spec into apply-plan.json + payloads/.
  --validate            Validate a spec and/or rendered output.
  --apply               Render, validate, then execute API actions against api.victorops.com.
  --send-alert          Send a single alert through the REST endpoint integration.
  --install-splunk-app  Install/configure the Splunk-side companion apps (3546, 4886, 5863).
  --uninstall           Uninstall the Splunk-side companion apps.
  --dry-run             With --apply or --install-splunk-app, show actions without mutating.
  --json                Emit JSON output where supported.

Options:
  --spec PATH                 YAML or JSON spec for --render/--validate/--apply/--install-splunk-app.
  --rest-alert-spec PATH      Spec containing rest_alerts[] for --send-alert.
  --output-dir DIR            Rendered output directory (default: project-root/splunk-oncall-rendered).
  --api-id ID                 Splunk On-Call X-VO-Api-Id (non-secret).
  --api-key-file PATH         File containing the X-VO-Api-Key (chmod 600).
  --api-base URL              API host override (default: https://api.victorops.com).
  --integration-key-file PATH File containing the REST endpoint integration key (chmod 600).
  --routing-key NAME          Routing key for --send-alert (defaults to SPLUNK_ONCALL_DEFAULT_ROUTING_KEY).
  --self-test                 With --send-alert, fire INFO + RECOVERY against a synthetic entity_id.
  --rest-base URL             REST endpoint host override.
  --help                      Show this help.

Direct secret flags such as --api-key, --vo-api-key, --x-vo-api-key,
--integration-key, --rest-key, --token, --password, and --secret are rejected.
Use the matching *-file flag instead.
EOF
}

RENDER=false
VALIDATE=false
APPLY=false
SEND_ALERT=false
INSTALL_SPLUNK_APP=false
UNINSTALL=false
DRY_RUN=false
JSON_OUTPUT=false
SELF_TEST=false

SPEC=""
REST_ALERT_SPEC=""
OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
API_ID="${SPLUNK_ONCALL_API_ID:-}"
API_KEY_FILE="${SPLUNK_ONCALL_API_KEY_FILE:-}"
API_BASE="https://api.victorops.com"
INTEGRATION_KEY_FILE="${SPLUNK_ONCALL_REST_INTEGRATION_KEY_FILE:-}"
ROUTING_KEY="${SPLUNK_ONCALL_DEFAULT_ROUTING_KEY:-}"
REST_BASE="https://alert.victorops.com/integrations/generic/20131114/alert"

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --validate) VALIDATE=true; shift ;;
        --apply) APPLY=true; RENDER=true; VALIDATE=true; shift ;;
        --send-alert) SEND_ALERT=true; shift ;;
        --install-splunk-app) INSTALL_SPLUNK_APP=true; shift ;;
        --uninstall) UNINSTALL=true; INSTALL_SPLUNK_APP=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --self-test) SELF_TEST=true; SEND_ALERT=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --rest-alert-spec) require_arg "$1" "$#" || exit 1; REST_ALERT_SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --api-id) require_arg "$1" "$#" || exit 1; API_ID="$2"; shift 2 ;;
        --api-key-file) require_arg "$1" "$#" || exit 1; API_KEY_FILE="$2"; shift 2 ;;
        --api-base) require_arg "$1" "$#" || exit 1; API_BASE="$2"; shift 2 ;;
        --integration-key-file) require_arg "$1" "$#" || exit 1; INTEGRATION_KEY_FILE="$2"; shift 2 ;;
        --routing-key) require_arg "$1" "$#" || exit 1; ROUTING_KEY="$2"; shift 2 ;;
        --rest-base) require_arg "$1" "$#" || exit 1; REST_BASE="$2"; shift 2 ;;
        --api-key|--vo-api-key|--x-vo-api-key|--oncall-api-key|--on-call-api-key)
            reject_secret_arg "$1" "--api-key-file"; exit 1 ;;
        --api-key=*|--vo-api-key=*|--x-vo-api-key=*|--oncall-api-key=*|--on-call-api-key=*)
            reject_secret_arg "${1%%=*}" "--api-key-file"; exit 1 ;;
        --integration-key|--rest-key)
            reject_secret_arg "$1" "--integration-key-file"; exit 1 ;;
        --integration-key=*|--rest-key=*)
            reject_secret_arg "${1%%=*}" "--integration-key-file"; exit 1 ;;
        --token|--access-token|--api-token|--password|--secret|--bearer-token)
            reject_secret_arg "$1" "--<*>-file"; exit 1 ;;
        --token=*|--access-token=*|--api-token=*|--password=*|--secret=*|--bearer-token=*)
            reject_secret_arg "${1%%=*}" "--<*>-file"; exit 1 ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ "${RENDER}" != "true" && "${VALIDATE}" != "true" && "${APPLY}" != "true" \
    && "${SEND_ALERT}" != "true" && "${INSTALL_SPLUNK_APP}" != "true" ]]; then
    RENDER=true
fi

json_flag=()
[[ "${JSON_OUTPUT}" == "true" ]] && json_flag=(--json)

ensure_yaml_for_spec() {
    local spec_path="$1"
    [[ -z "${spec_path}" ]] && return 0
    case "${spec_path}" in
        *.json|*.JSON) return 0 ;;
    esac
    if ! "${PYTHON_BIN}" -c 'import yaml' >/dev/null 2>&1; then
        log "ERROR: YAML specs require PyYAML for ${PYTHON_BIN}."
        log "Install repo Python dependencies with: ${PYTHON_BIN} -m pip install -r requirements-agent.txt"
        log "Or use the JSON example at skills/splunk-oncall-setup/templates/oncall.example.json."
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Validate-only / Render
# ---------------------------------------------------------------------------

if [[ "${VALIDATE}" == "true" && "${RENDER}" != "true" ]]; then
    validate_args=()
    [[ -n "${SPEC}" ]] && { ensure_yaml_for_spec "${SPEC}" || exit 1; validate_args+=(--spec "${SPEC}"); }
    # Only validate the rendered output when the operator explicitly points
    # at a directory that already exists. The default output dir is created
    # only by --render; in pure --validate flows we don't want to fail just
    # because nothing has been rendered yet.
    if [[ -n "${OUTPUT_DIR}" && -d "${OUTPUT_DIR}" ]]; then
        validate_args+=(--output-dir "${OUTPUT_DIR}")
    fi
    "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_oncall.py" "${validate_args[@]}" "${json_flag[@]}"
    exit $?
fi

if [[ "${RENDER}" == "true" ]]; then
    if [[ -z "${SPEC}" ]]; then
        log "ERROR: --spec is required for render and apply."
        exit 1
    fi
    ensure_yaml_for_spec "${SPEC}" || exit 1
    render_args=(--spec "${SPEC}" --output-dir "${OUTPUT_DIR}")
    if [[ "${JSON_OUTPUT}" == "true" && "${APPLY}" != "true" ]]; then
        render_args+=(--json)
    fi
    if [[ "${JSON_OUTPUT}" == "true" && "${APPLY}" == "true" ]]; then
        # JSON+apply: route render and validate to stderr so the only
        # stdout JSON document comes from oncall_api.py.
        "${PYTHON_BIN}" "${SCRIPT_DIR}/render_oncall.py" "${render_args[@]}" >&2
        "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_oncall.py" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" >&2
    elif [[ "${JSON_OUTPUT}" == "true" ]]; then
        # JSON without apply: render emits JSON on stdout; route validate
        # output to stderr so the stdout stream stays valid JSON.
        "${PYTHON_BIN}" "${SCRIPT_DIR}/render_oncall.py" "${render_args[@]}"
        "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_oncall.py" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" >&2
    else
        "${PYTHON_BIN}" "${SCRIPT_DIR}/render_oncall.py" "${render_args[@]}"
        "${PYTHON_BIN}" "${SCRIPT_DIR}/validate_oncall.py" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}"
    fi
fi

# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

if [[ "${APPLY}" == "true" ]]; then
    if [[ "${DRY_RUN}" != "true" ]]; then
        if [[ -z "${API_ID}" ]]; then
            log "ERROR: --api-id is required for live --apply (or set SPLUNK_ONCALL_API_ID)."
            exit 1
        fi
        if [[ -z "${API_KEY_FILE}" || ! -r "${API_KEY_FILE}" ]]; then
            log "ERROR: --api-key-file must be readable for live --apply."
            exit 1
        fi
    fi
    apply_args=(apply --plan-dir "${OUTPUT_DIR}" --api-base "${API_BASE}")
    [[ -n "${API_ID}" ]] && apply_args+=(--api-id "${API_ID}")
    [[ -n "${API_KEY_FILE}" ]] && apply_args+=(--api-key-file "${API_KEY_FILE}")
    [[ "${DRY_RUN}" == "true" ]] && apply_args+=(--dry-run)
    "${PYTHON_BIN}" "${SCRIPT_DIR}/oncall_api.py" "${apply_args[@]}"
fi

# ---------------------------------------------------------------------------
# Send REST endpoint alert
# ---------------------------------------------------------------------------

if [[ "${SEND_ALERT}" == "true" ]]; then
    if [[ -z "${INTEGRATION_KEY_FILE}" || ! -r "${INTEGRATION_KEY_FILE}" ]]; then
        log "ERROR: --integration-key-file must be readable for --send-alert."
        exit 1
    fi
    if [[ -z "${ROUTING_KEY}" ]]; then
        log "ERROR: --routing-key is required for --send-alert (or set SPLUNK_ONCALL_DEFAULT_ROUTING_KEY)."
        exit 1
    fi
    rest_args=(--integration-key-file "${INTEGRATION_KEY_FILE}" --routing-key "${ROUTING_KEY}" --rest-base "${REST_BASE}")
    if [[ "${SELF_TEST}" == "true" ]]; then
        rest_args+=(--self-test)
    else
        if [[ -z "${REST_ALERT_SPEC}" ]]; then
            log "ERROR: --rest-alert-spec is required when --send-alert is used without --self-test."
            exit 1
        fi
        ensure_yaml_for_spec "${REST_ALERT_SPEC}" || exit 1
        rest_args+=(--alert-spec "${REST_ALERT_SPEC}")
    fi
    [[ "${DRY_RUN}" == "true" ]] && rest_args+=(--dry-run)
    "${PYTHON_BIN}" "${SCRIPT_DIR}/rest_endpoint.py" "${rest_args[@]}"
fi

# ---------------------------------------------------------------------------
# Splunk-side install
# ---------------------------------------------------------------------------

if [[ "${INSTALL_SPLUNK_APP}" == "true" ]]; then
    if [[ -z "${SPEC}" ]]; then
        log "ERROR: --spec is required for --install-splunk-app and --uninstall."
        exit 1
    fi
    ensure_yaml_for_spec "${SPEC}" || exit 1
    install_args=(--spec "${SPEC}")
    [[ "${UNINSTALL}" == "true" ]] && install_args+=(--uninstall)
    if [[ "${DRY_RUN}" == "true" ]]; then
        bash "${SCRIPT_DIR}/splunk_side_install.sh" "${install_args[@]}" "${json_flag[@]}"
    else
        install_args+=(--apply)
        [[ -n "${API_ID}" ]] && install_args+=(--api-id "${API_ID}")
        [[ -n "${API_KEY_FILE}" ]] && install_args+=(--api-key-file "${API_KEY_FILE}")
        bash "${SCRIPT_DIR}/splunk_side_install.sh" "${install_args[@]}" "${json_flag[@]}"
    fi
fi
