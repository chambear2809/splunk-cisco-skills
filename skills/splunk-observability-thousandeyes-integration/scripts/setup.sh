#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-thousandeyes-rendered"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python3" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
elif [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

usage() {
    cat <<'EOF'
Splunk Observability ThousandEyes Integration setup

Usage:
  bash skills/splunk-observability-thousandeyes-integration/scripts/setup.sh [mode] --spec PATH [options]

Modes:
  --render                Render artifacts (default if no mode given)
  --apply SECTIONS        Render then apply explicit sections; SECTIONS is comma-
                          separated (stream, apm, tests, alert_rules, labels, tags,
                          te_dashboards, templates). The literal all selects all
                          currently automatable sections.
  --validate              Run static validation against an already-rendered output
  --dry-run               Show the plan without writing
  --json                  Emit JSON dry-run output
  --explain               Print plan in plain English (no API calls or writes)

Required:
  --spec PATH             YAML or JSON spec (api_version: splunk-observability-thousandeyes-integration/v1)

Optional:
  --realm REALM           Splunk Observability realm (overrides spec.realm)
  --output-dir DIR        Rendered output directory
  --te-token-file PATH    ThousandEyes API token file
  --o11y-ingest-token-file PATH
                          Splunk Observability Org access token (ingest scope)
  --o11y-api-token-file PATH
                          Splunk Observability User API access token
  --i-accept-te-mutations Allow mutating TE-side asset apply (tests/alerts/labels/...)
  --deploy-templates      For --apply templates, also POST /v7/templates/{id}/deploy
  --help                  Show this help

Direct token flags such as --te-token, --access-token, --token, --bearer-token,
--api-token, --o11y-token, --sf-token are rejected.
EOF
}

bool_text() {
    if [[ "$1" == "true" ]]; then printf 'true'; else printf 'false'; fi
}

resolve_abs_path() {
    "${PYTHON_BIN}" - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

MODE_RENDER=true
MODE_APPLY=false
APPLY_SECTIONS=""
MODE_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC=""
# Only honor --realm from CLI; the spec.realm always takes precedence over
# the SPLUNK_O11Y_REALM env var so the rendered ingest URL matches what the
# spec author intended. (Setting SPLUNK_O11Y_REALM is still useful for
# splunk-observability-otel-collector-setup which has no per-spec realm.)
REALM=""
TE_TOKEN_FILE=""
# Rendering is intentionally credential-free.  Keep the configured default
# separate so a stale or not-yet-created credentials-file path cannot block
# --render/--validate/--dry-run.  Live apply may still consume the configured
# file when the operator does not pass an explicit override.
DEFAULT_O11Y_INGEST_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
O11Y_INGEST_TOKEN_FILE=""
O11Y_API_TOKEN_FILE=""
ACCEPT_TE_MUTATIONS=false
DEPLOY_TEMPLATES=false

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --apply)
            MODE_APPLY=true
            MODE_RENDER=true
            # A live apply always requires an explicit list (or "all").
            if [[ $# -ge 2 && ! "$2" =~ ^-- ]]; then
                APPLY_SECTIONS="$2"
                shift 2
            else
                shift
            fi
            ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --te-token-file) require_arg "$1" "$#" || exit 1; TE_TOKEN_FILE="$2"; shift 2 ;;
        --o11y-ingest-token-file) require_arg "$1" "$#" || exit 1; O11Y_INGEST_TOKEN_FILE="$2"; shift 2 ;;
        --o11y-api-token-file) require_arg "$1" "$#" || exit 1; O11Y_API_TOKEN_FILE="$2"; shift 2 ;;
        --i-accept-te-mutations) ACCEPT_TE_MUTATIONS=true; shift ;;
        --deploy-templates) DEPLOY_TEMPLATES=true; shift ;;
        --te-token|--access-token|--token|--bearer-token|--api-token)
            reject_secret_arg "$1" "--te-token-file"
            exit 1
            ;;
        --o11y-token|--sf-token)
            reject_secret_arg "$1" "--o11y-ingest-token-file or --o11y-api-token-file"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ "${MODE_APPLY}" == "true" && -z "${O11Y_INGEST_TOKEN_FILE}" ]]; then
    O11Y_INGEST_TOKEN_FILE="${DEFAULT_O11Y_INGEST_TOKEN_FILE}"
fi

if [[ -z "${SPEC}" ]]; then
    log "ERROR: --spec is required."
    exit 1
fi

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

_token_perm_octal() {
    local target="$1" mode=""
    mode="$(stat -f '%A' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    mode="$(stat -c '%a' "${target}" 2>/dev/null)" && { printf '%s' "${mode}"; return 0; }
    printf ''
}

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" ]] || return 0
    if [[ -L "${path}" || ! -f "${path}" || ! -s "${path}" ]]; then
        log "ERROR: ${label} (${path}) must be a non-empty regular, non-symlink file."
        return 1
    fi
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then
        log "ERROR: Could not stat ${label} (${path})."
        return 1
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        log "ERROR: ${label} (${path}) is mode ${mode}; tokens must be mode 600."
        log "       Run 'chmod 600 ${path}' to fix."
        return 1
    fi
    if ! "${PYTHON_BIN}" - "${path}" <<'PY'
from pathlib import Path
import sys
try:
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
except (OSError, UnicodeError):
    raise SystemExit(1)
raise SystemExit(0 if len(lines) == 1 and bool(lines[0]) and "\x00" not in lines[0] else 1)
PY
    then
        log "ERROR: ${label} (${path}) must contain exactly one non-empty UTF-8 line."
        return 1
    fi
}

# Always preflight readable token files even on --render so misconfigured perms
# are surfaced as early as possible.
[[ -n "${TE_TOKEN_FILE}" ]] && { _check_token_perms "--te-token-file" "${TE_TOKEN_FILE}" || exit 1; }
[[ -n "${O11Y_INGEST_TOKEN_FILE}" ]] && { _check_token_perms "--o11y-ingest-token-file" "${O11Y_INGEST_TOKEN_FILE}" || exit 1; }
[[ -n "${O11Y_API_TOKEN_FILE}" ]] && { _check_token_perms "--o11y-api-token-file" "${O11Y_API_TOKEN_FILE}" || exit 1; }

if [[ "${MODE_APPLY}" == "true" ]]; then
    if [[ -z "${APPLY_SECTIONS}" ]]; then
        log "ERROR: --apply requires an explicit section list or the literal all."
        exit 1
    fi
    [[ "${APPLY_SECTIONS}" == "all" ]] && APPLY_SECTIONS="stream,apm,tests,alert_rules,templates"
    if ! APPLY_SECTIONS="$("${PYTHON_BIN}" - "${APPLY_SECTIONS}" <<'PY'
import sys

allowed = {"stream", "apm", "tests", "alert_rules", "labels", "tags", "te_dashboards", "templates"}
sections = [item.strip() for item in sys.argv[1].split(",")]
if not sections or any(not item for item in sections):
    raise SystemExit("ERROR: --apply contains an empty section name.")
unknown = sorted(set(sections) - allowed)
if unknown:
    raise SystemExit(f"ERROR: Unknown apply section(s): {', '.join(unknown)}")
if len(sections) != len(set(sections)):
    raise SystemExit("ERROR: --apply section names must be unique.")
print(",".join(sections), end="")
PY
    )"; then
        exit 1
    fi
    case ",${APPLY_SECTIONS}," in
        *,labels,*|*,tags,*|*,te_dashboards,*)
            log "ERROR: labels, tags, and te_dashboards are render-only handoffs until authoritative API ID/readback schemas are encoded; no changes were made."
            exit 1
            ;;
    esac
    [[ "${ACCEPT_TE_MUTATIONS}" == "true" ]] || {
        log "ERROR: every live TE apply requires --i-accept-te-mutations."
        exit 1
    }
    [[ -n "${TE_TOKEN_FILE}" ]] || { log "ERROR: --apply requires --te-token-file."; exit 1; }
    case ",${APPLY_SECTIONS}," in
        *,stream,*) [[ -n "${O11Y_INGEST_TOKEN_FILE}" ]] || { log "ERROR: --apply stream requires --o11y-ingest-token-file."; exit 1; } ;;
    esac
    case ",${APPLY_SECTIONS}," in
        *,apm,*) [[ -n "${O11Y_API_TOKEN_FILE}" ]] || { log "ERROR: --apply apm requires --o11y-api-token-file."; exit 1; } ;;
    esac
    if [[ "${DEPLOY_TEMPLATES}" == "true" && ",${APPLY_SECTIONS}," != *,templates,* ]]; then
        log "ERROR: --deploy-templates is valid only when templates is selected."
        exit 1
    fi
fi

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
Splunk Observability ThousandEyes Integration — execution plan
==============================================================
  Spec:                ${SPEC}
  Realm:               ${REALM:-<from spec>}
  Output directory:    ${OUTPUT_DIR}
  TE token file:       ${TE_TOKEN_FILE:-<not set>}
  O11y ingest token:   ${O11Y_INGEST_TOKEN_FILE:-<not set>}
  O11y API token:      ${O11Y_API_TOKEN_FILE:-<not set>}
  Apply sections:      ${APPLY_SECTIONS:-<none>}
  Mutations accepted:  $(bool_text "${ACCEPT_TE_MUTATIONS}")
  Deploy templates:    $(bool_text "${DEPLOY_TEMPLATES}")
  Mode: render=$(bool_text "${MODE_RENDER}") apply=$(bool_text "${MODE_APPLY}") validate=$(bool_text "${MODE_VALIDATE}")
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --realm "${REALM}"
    --te-token-file "${TE_TOKEN_FILE}"
    --o11y-ingest-token-file "${O11Y_INGEST_TOKEN_FILE}"
    --o11y-api-token-file "${O11Y_API_TOKEN_FILE}"
    --apply "${APPLY_SECTIONS}"
    --accept-te-mutations "$(bool_text "${ACCEPT_TE_MUTATIONS}")"
)
if [[ "${DRY_RUN}" == "true" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    "${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then
    exit 0
fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
fi

if [[ "${MODE_APPLY}" == "true" ]]; then
    # Validate the complete requested set before the first remote mutation.
    # metadata.json reflects the just-rendered, schema-validated spec.
    "${PYTHON_BIN}" - "${OUTPUT_DIR}/metadata.json" "${APPLY_SECTIONS}" <<'PY'
import json
from pathlib import Path
import sys

metadata_path = Path(sys.argv[1])
try:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"ERROR: cannot read rendered metadata {metadata_path}: {exc}")
if not isinstance(metadata, dict):
    raise SystemExit("ERROR: rendered metadata must be a JSON object.")
account_group_id = str(metadata.get("account_group_id", "")).strip()
if not account_group_id.isdigit():
    raise SystemExit("ERROR: live apply requires a numeric account_group_id in the spec.")

requirements = {
    "stream": ("stream_enabled", True),
    "apm": ("apm_connector_enabled", True),
    "tests": ("tests_count", "positive"),
    "alert_rules": ("alert_rules_count", "positive"),
    "templates": ("templates_count", "positive"),
}
for section in sys.argv[2].split(","):
    field, expected = requirements[section]
    value = metadata.get(field)
    valid = value is True if expected is True else isinstance(value, int) and not isinstance(value, bool) and value > 0
    if not valid:
        raise SystemExit(f"ERROR: selected section {section!r} has no enabled/rendered payloads ({field}={value!r}).")
PY
fi

run_apply_step() {
    local section="$1" script="$2"
    local script_path="${OUTPUT_DIR}/scripts/${script}"
    if [[ ! -f "${script_path}" ]]; then
        log "ERROR: selected apply script is missing: ${script_path}"
        return 1
    fi
    log "Applying ${section}: ${script_path}"
    TE_TOKEN_FILE="${TE_TOKEN_FILE}" \
        O11Y_INGEST_TOKEN_FILE="${O11Y_INGEST_TOKEN_FILE}" \
        O11Y_API_TOKEN_FILE="${O11Y_API_TOKEN_FILE}" \
        ACCEPT_TE_MUTATIONS="$(bool_text "${ACCEPT_TE_MUTATIONS}")" \
        DEPLOY_TEMPLATES="$(bool_text "${DEPLOY_TEMPLATES}")" \
        ASSET_KIND="${section}" \
        PYTHON_BIN="${PYTHON_BIN}" \
        bash "${script_path}"
}

if [[ "${MODE_APPLY}" == "true" ]]; then
    IFS=',' read -ra _SECTIONS_ARR <<< "${APPLY_SECTIONS}"
    for section in "${_SECTIONS_ARR[@]}"; do
        case "${section}" in
            stream)         run_apply_step stream apply-stream.sh ;;
            apm)            run_apply_step apm apply-apm-connector.sh ;;
            tests)          run_apply_step tests apply-tests.sh ;;
            alert_rules)    run_apply_step alert_rules apply-alert-rules.sh ;;
            labels|tags)    run_apply_step "${section}" apply-labels-tags.sh ;;
            te_dashboards)  run_apply_step te_dashboards apply-te-dashboards.sh ;;
            templates)      run_apply_step templates apply-template.sh ;;
            "" )            ;;
            *)
                log "ERROR: Unknown apply section: ${section}"
                exit 1
                ;;
        esac
    done
fi
