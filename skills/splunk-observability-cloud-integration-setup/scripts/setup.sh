#!/usr/bin/env bash
set -euo pipefail

# Splunk Platform <-> Splunk Observability Cloud integration: primary CLI.
#
# Mirrors the `splunk-cloud-acs-allowlist-setup` and `splunk-observability-otel-collector-setup`
# patterns: render-first by default, file-based-secrets only, idempotent applies
# tracked through `<rendered>/state/apply-state.json`, doctor + discover modes
# for inheriting an existing integration.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
RENDERER="${SCRIPT_DIR}/render_assets.py"
DEFAULT_RENDER_DIR_NAME="splunk-observability-cloud-integration-rendered"

# Prefer the repo-local virtualenv when present (matches CLAUDE.md guidance).
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

MODE="render"
SECTIONS=""
SPEC=""
OUTPUT_DIR=""
TARGET=""
REALM=""
TOKEN_FILE=""
ADMIN_TOKEN_FILE=""
ORG_TOKEN_FILE=""
SERVICE_ACCOUNT_PASSWORD_FILE=""
SPLUNK_CLOUD_ADMIN_JWT_FILE=""
ALLOW_LOOSE_TOKEN_PERMS=false
RBAC_CUTOVER_ACK=false
RENDER_SIM_TEMPLATES=""
ROLLBACK_SECTION=""
JSON_OUTPUT=false
DRY_RUN=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Platform <-> Splunk Observability Cloud Integration Setup

Usage: $(basename "$0") [MODE] [OPTIONS]

Modes (pick one; --render is the default):
  --render                       Produce the numbered plan tree under --output-dir (default mode).
  --apply [SECTIONS]             Apply rendered plan; CSV picks specific sections, or omit for all.
  --validate [--live]            Static checks of a rendered tree; --live adds API checks.
  --doctor                       Run the 20-check diagnostic catalog and print a fix list.
  --discover                     Read-only sweep that writes current-state.json and a delta.
  --quickstart                   Single-shot greenfield Cloud + UID + Discover + SIM scenario.
  --quickstart-enterprise        Splunk Enterprise fast path (SA + SIM + Related Content + LOC TLS).
  --explain                      Print the apply plan in plain English; no API calls.
  --enable-token-auth            Flip Splunk token authentication on (auto-rendered as a doctor fix).
  --rollback SECTION             Render reverse commands for a previously applied section.
  --list-sim-templates           Show the curated SignalFlow modular-input catalog.
  --render-sim-templates CSV     Render only the named SignalFlow templates from the catalog.
  --make-default-deeplink        Emit the multi-org "Make Default" UI deeplink for --realm.

Spec / output:
  --spec PATH                    Spec file (YAML or JSON); defaults to template.example.
  --output-dir PATH              Output directory; defaults to ${DEFAULT_RENDER_DIR_NAME}.
  --target cloud|enterprise      Override spec.target.
  --realm REALM                  Override spec.realm.

File-based secrets (chmod 600 enforced):
  --token-file PATH                          Splunk Observability Cloud user/dashboard token.
  --admin-token-file PATH                    Splunk Observability Cloud admin token (UID + RBAC).
  --org-token-file PATH                      Splunk Observability Cloud org token (SIM Add-on).
  --service-account-password-file PATH       LOC service-account password.
  --splunk-cloud-admin-jwt-file PATH         Splunk Cloud Platform admin JWT (REST fallback for ACS).
  --allow-loose-token-perms                  Override chmod-600 (emits WARN; for short-lived scratch tokens).

Guards:
  --i-accept-rbac-cutover                    Required to actually run enable-centralized-rbac.

Output formatting:
  --json                                     Machine-readable result.
  --dry-run                                  Skip live API calls (apply scaffolding stays render-only).
  -h | --help                                Show this help.

Direct-secret flags below are REJECTED with a friendly hint:
  --token --access-token --api-token --o11y-token --admin-token --org-token --sf-token
  --service-account-password --password
EOF
    exit "${exit_code}"
}

reject_direct_secret() {
    local name="$1"
    cat >&2 <<EOF
Refusing direct-secret flag --${name}. Use a file-based equivalent instead:
  --token-file PATH                          Splunk Observability Cloud user/dashboard token
  --admin-token-file PATH                    Splunk Observability Cloud admin token (UID + RBAC)
  --org-token-file PATH                      Splunk Observability Cloud org token (SIM Add-on)
  --service-account-password-file PATH       LOC service-account password
The token file must be chmod 600. Use:
  bash skills/shared/scripts/write_secret_file.sh /tmp/<name>
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
        --live) export SOICS_VALIDATE_LIVE=true ;;
        --doctor) MODE="doctor" ;;
        --discover) MODE="discover" ;;
        --quickstart) MODE="quickstart" ;;
        --quickstart-enterprise) MODE="quickstart_enterprise" ;;
        --explain) MODE="explain" ;;
        --enable-token-auth) MODE="enable_token_auth" ;;
        --rollback) ROLLBACK_SECTION="$2"; MODE="rollback"; shift ;;
        --list-sim-templates) MODE="list_sim_templates" ;;
        --render-sim-templates) RENDER_SIM_TEMPLATES="$2"; shift ;;
        --make-default-deeplink) MODE="make_default_deeplink" ;;
        --spec) SPEC="$2"; shift ;;
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --target) TARGET="$2"; shift ;;
        --realm) REALM="$2"; shift ;;
        --token-file) TOKEN_FILE="$2"; shift ;;
        --admin-token-file) ADMIN_TOKEN_FILE="$2"; shift ;;
        --org-token-file) ORG_TOKEN_FILE="$2"; shift ;;
        --service-account-password-file) SERVICE_ACCOUNT_PASSWORD_FILE="$2"; shift ;;
        --splunk-cloud-admin-jwt-file) SPLUNK_CLOUD_ADMIN_JWT_FILE="$2"; shift ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true ;;
        --i-accept-rbac-cutover) RBAC_CUTOVER_ACK=true ;;
        --json) JSON_OUTPUT=true ;;
        --dry-run) DRY_RUN=true ;;
        --token|--access-token|--api-token|--o11y-token|--admin-token|--org-token|--sf-token) reject_direct_secret "${1#--}" ;;
        --service-account-password|--password) reject_direct_secret "${1#--}" ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

# Default spec/output paths (operator can override).
if [[ -z "${SPEC}" ]]; then
    SPEC="${SCRIPT_DIR}/../template.example"
fi
if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/${DEFAULT_RENDER_DIR_NAME}"
fi

# Pull SPLUNK_O11Y_REALM / SPLUNK_O11Y_TOKEN_FILE / etc. from credentials when present.
load_observability_cloud_settings 2>/dev/null || true

if [[ -z "${REALM}" && -n "${SPLUNK_O11Y_REALM:-}" ]]; then
    REALM="${SPLUNK_O11Y_REALM}"
fi
if [[ -z "${TOKEN_FILE}" && -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
    TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE}"
fi
if [[ -z "${ADMIN_TOKEN_FILE}" && -n "${SPLUNK_O11Y_ADMIN_TOKEN_FILE:-}" ]]; then
    ADMIN_TOKEN_FILE="${SPLUNK_O11Y_ADMIN_TOKEN_FILE}"
fi
if [[ -z "${ORG_TOKEN_FILE}" && -n "${SPLUNK_O11Y_ORG_TOKEN_FILE:-}" ]]; then
    ORG_TOKEN_FILE="${SPLUNK_O11Y_ORG_TOKEN_FILE}"
fi

assert_secret_file_perms() {
    local path="$1"
    local label="$2"
    [[ -z "${path}" ]] && return 0
    if [[ ! -f "${path}" ]]; then
        echo "FAIL: ${label} (${path}) does not exist." >&2
        exit 2
    fi
    if [[ ! -s "${path}" ]]; then
        echo "FAIL: ${label} (${path}) is empty." >&2
        exit 2
    fi
    local mode
    mode=$(stat -f '%A' "${path}" 2>/dev/null || stat -c '%a' "${path}")
    if [[ "${mode}" != "600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS}" == "true" ]]; then
            echo "WARN: ${label} (${path}) has loose permissions (${mode}); proceeding under --allow-loose-token-perms." >&2
        else
            echo "FAIL: ${label} (${path}) has loose permissions (${mode}); chmod 600 ${path} (or pass --allow-loose-token-perms)." >&2
            exit 2
        fi
    fi
}

run_renderer() {
    local args=("--spec" "${SPEC}" "--output-dir" "${OUTPUT_DIR}")
    [[ -n "${TARGET}" ]] && args+=("--target" "${TARGET}")
    [[ -n "${REALM}" ]] && args+=("--realm" "${REALM}")
    [[ -n "${RENDER_SIM_TEMPLATES}" ]] && args+=("--render-sim-templates" "${RENDER_SIM_TEMPLATES}")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=("--json")
    "${PYTHON_BIN}" "${RENDERER}" "${args[@]}"
}

run_renderer_explain() {
    local args=("--spec" "${SPEC}" "--output-dir" "${OUTPUT_DIR}" "--explain")
    [[ -n "${TARGET}" ]] && args+=("--target" "${TARGET}")
    [[ -n "${REALM}" ]] && args+=("--realm" "${REALM}")
    "${PYTHON_BIN}" "${RENDERER}" "${args[@]}"
}

run_section_apply() {
    local section="$1"
    case "${section}" in
        token_auth)
            assert_secret_file_perms "${ADMIN_TOKEN_FILE}" "--admin-token-file"
            "${PYTHON_BIN}" "${SCRIPT_DIR}/token_auth_api.py" --state-dir "${OUTPUT_DIR}/state" enable
            ;;
        pairing)
            assert_secret_file_perms "${ADMIN_TOKEN_FILE}" "--admin-token-file"
            local args=(
                "--state-dir" "${OUTPUT_DIR}/state"
                "--admin-token-file" "${ADMIN_TOKEN_FILE}"
            )
            [[ -n "${SPLUNK_CLOUD_STACK:-}" ]] && args+=("--splunk-cloud-stack" "${SPLUNK_CLOUD_STACK}")
            [[ -n "${SPLUNK_CLOUD_ADMIN_JWT_FILE}" ]] && args+=("--splunk-cloud-admin-jwt-file" "${SPLUNK_CLOUD_ADMIN_JWT_FILE}")
            [[ -n "${REALM}" ]] && args+=("--realm" "${REALM}")
            "${PYTHON_BIN}" "${SCRIPT_DIR}/o11y_pairing_api.py" "${args[@]}" pair --realm "${REALM}"
            ;;
        rbac|centralized_rbac)
            assert_secret_file_perms "${ADMIN_TOKEN_FILE}" "--admin-token-file"
            "${PYTHON_BIN}" "${SCRIPT_DIR}/o11y_pairing_api.py" --state-dir "${OUTPUT_DIR}/state" enable-capabilities
            if [[ "${RBAC_CUTOVER_ACK}" == "true" ]]; then
                "${PYTHON_BIN}" "${SCRIPT_DIR}/o11y_pairing_api.py" \
                    --state-dir "${OUTPUT_DIR}/state" \
                    --admin-token-file "${ADMIN_TOKEN_FILE}" \
                    --i-accept-rbac-cutover \
                    --realm "${REALM}" \
                    enable-centralized-rbac
            else
                echo "WARN: skipping enable-centralized-rbac (destructive); pass --i-accept-rbac-cutover to apply." >&2
            fi
            ;;
        related_content)
            "${OUTPUT_DIR}/scripts/apply-rbac.sh" || true
            ;;
        discover_app)
            assert_secret_file_perms "${TOKEN_FILE}" "--token-file"
            export SPLUNK_O11Y_TOKEN_FILE="${TOKEN_FILE}"
            "${OUTPUT_DIR}/scripts/apply-discover-app.sh"
            ;;
        log_observer_connect|loc)
            assert_secret_file_perms "${SERVICE_ACCOUNT_PASSWORD_FILE}" "--service-account-password-file"
            export LOC_SERVICE_ACCOUNT_PASSWORD_FILE="${SERVICE_ACCOUNT_PASSWORD_FILE}"
            "${OUTPUT_DIR}/scripts/apply-loc.sh"
            ;;
        sim_addon)
            assert_secret_file_perms "${ORG_TOKEN_FILE}" "--org-token-file"
            export SPLUNK_O11Y_ORG_TOKEN_FILE="${ORG_TOKEN_FILE}"
            "${OUTPUT_DIR}/scripts/apply-app-install.sh" || true
            "${OUTPUT_DIR}/scripts/apply-sim-addon.sh"
            ;;
        *)
            echo "Unknown section: ${section}" >&2
            exit 2
            ;;
    esac
}

run_validate() {
    local validate_mode="${1:-}"
    local args=(--output-dir "${OUTPUT_DIR}")
    case "${validate_mode}" in
        doctor|discover) args+=("--${validate_mode}") ;;
        "") ;;
        *)
            echo "Unknown validate mode: ${validate_mode}" >&2
            exit 2
            ;;
    esac
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    bash "${SCRIPT_DIR}/validate.sh" "${args[@]}"
}

case "${MODE}" in
    render)
        run_renderer
        ;;
    explain)
        run_renderer_explain
        ;;
    apply)
        run_renderer
        local_sections="${SECTIONS}"
        if [[ -z "${local_sections}" ]]; then
            local_sections="token_auth,pairing,centralized_rbac,related_content,discover_app,log_observer_connect,sim_addon"
        fi
        IFS=',' read -ra _sects <<< "${local_sections}"
        for s in "${_sects[@]}"; do
            s="${s// /}"
            [[ -z "${s}" ]] && continue
            echo "==> applying section: ${s}"
            if [[ "${DRY_RUN}" == "true" ]]; then
                echo "(dry-run) would apply ${s}"
                continue
            fi
            run_section_apply "${s}"
        done
        ;;
    validate)
        run_validate
        ;;
    doctor)
        # The doctor checks live + rendered state and writes doctor-report.md.
        run_renderer
        run_validate doctor || true
        ;;
    discover)
        run_renderer
        run_validate discover || true
        ;;
    quickstart)
        # Force target=cloud and run render + apply for the most common scenario.
        TARGET="cloud"
        run_renderer
        SECTIONS="token_auth,pairing,related_content,discover_app,log_observer_connect,sim_addon"
        for s in token_auth pairing related_content discover_app log_observer_connect sim_addon; do
            echo "==> quickstart applying: ${s}"
            run_section_apply "${s}" || true
        done
        bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}" || true
        ;;
    quickstart_enterprise)
        TARGET="enterprise"
        run_renderer
        for s in token_auth related_content log_observer_connect sim_addon; do
            echo "==> quickstart-enterprise applying: ${s}"
            run_section_apply "${s}" || true
        done
        bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}" || true
        ;;
    enable_token_auth)
        "${PYTHON_BIN}" "${SCRIPT_DIR}/token_auth_api.py" --state-dir "${OUTPUT_DIR}/state" enable
        ;;
    rollback)
        # Render-only: emit the reverse plan; never auto-run.
        case "${ROLLBACK_SECTION}" in
            pairing)
                cat <<EOF
# Rollback (render-only): pairing
# There is no public API for unpair. Open Discover Splunk Observability Cloud
# > Configurations and remove the connection through the UI. For UID, also
# coordinate with Splunk Support to deactivate non-UID local login.
EOF
                ;;
            centralized_rbac|rbac)
                cat <<EOF
# Rollback (render-only): centralized_rbac
# enable-centralized-rbac is irreversible without Splunk Support. Open a
# Splunk Support case using support-tickets/deactivate-local-login.md as the
# starting template (the same workflow handles RBAC reversal).
EOF
                ;;
            sim_addon)
                cat <<EOF
# Rollback (render-only): sim_addon
# Disable each modular input through the SIM Add-on REST handler:
curl -k -u "\${SPLUNK_USER}:\${SPLUNK_PASS}" \\
  -X POST "\${SPLUNK_SEARCH_API_URI}/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams/<name>/disable"
# Then delete the account if no longer needed:
curl -k -u "\${SPLUNK_USER}:\${SPLUNK_PASS}" \\
  -X DELETE "\${SPLUNK_SEARCH_API_URI}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account/<name>"
EOF
                ;;
            log_observer_connect|loc)
                cat <<EOF
# Rollback (render-only): log_observer_connect
# Delete the workload rule, the service-account user, and the role:
curl -k -u "\${SPLUNK_USER}:\${SPLUNK_PASS}" \\
  -X DELETE "\${SPLUNK_SEARCH_API_URI}/services/workloads/rules/loc_runtime_abort"
curl -k -u "\${SPLUNK_USER}:\${SPLUNK_PASS}" \\
  -X DELETE "\${SPLUNK_SEARCH_API_URI}/services/authentication/users/<svc>"
curl -k -u "\${SPLUNK_USER}:\${SPLUNK_PASS}" \\
  -X DELETE "\${SPLUNK_SEARCH_API_URI}/services/authorization/roles/<role>"
EOF
                ;;
            *)
                echo "Unknown rollback section: ${ROLLBACK_SECTION}" >&2
                exit 2
                ;;
        esac
        ;;
    list_sim_templates)
        "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --list-sim-templates
        ;;
    make_default_deeplink)
        if [[ -z "${REALM}" ]]; then
            echo "FAIL: --make-default-deeplink requires --realm" >&2
            exit 2
        fi
        "${PYTHON_BIN}" "${RENDERER}" --spec "${SPEC}" --output-dir "${OUTPUT_DIR}" --make-default-deeplink --realm "${REALM}"
        ;;
    *)
        echo "Unknown mode: ${MODE}" >&2
        usage 1
        ;;
esac
