#!/usr/bin/env bash
set -euo pipefail

# Splunk Platform <-> Splunk Observability Cloud integration: primary CLI.
#
# Mirrors the `splunk-cloud-acs-admin-setup` and `splunk-observability-otel-collector-setup`
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
  --apply SECTIONS               Apply an explicit CSV list of supported sections.
  --validate [--live]            Static checks of a rendered tree; --live adds API checks.
  --doctor                       Render the static 20-check review catalog and fix list.
  --discover                     Write a read-only inventory scaffold to current-state.json.
  --quickstart                   Render/validate the greenfield Cloud scenario; no mutation.
  --quickstart-enterprise        Render/validate the Enterprise scenario; no mutation.
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
load_observability_cloud_settings
load_splunk_connection_settings

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
    if [[ -L "${path}" || ! -f "${path}" ]]; then
        echo "FAIL: ${label} (${path}) must be a regular, non-symlink file." >&2
        exit 2
    fi
    if [[ ! -s "${path}" ]]; then
        echo "FAIL: ${label} (${path}) is empty." >&2
        exit 2
    fi
    local mode
    mode=$(stat -f '%A' "${path}" 2>/dev/null || stat -c '%a' "${path}")
    if [[ "${mode}" != "600" ]]; then
        echo "FAIL: ${label} (${path}) must have mode 600 (found ${mode}); chmod 600 ${path}." >&2
        exit 2
    fi
    if ! "${PYTHON_BIN}" - "${path}" <<'PY'
from pathlib import Path
import sys

try:
    lines = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
except (OSError, UnicodeError):
    raise SystemExit(1)
if len(lines) != 1 or not lines[0] or "\x00" in lines[0]:
    raise SystemExit(1)
PY
    then
        echo "FAIL: ${label} (${path}) must contain exactly one non-empty UTF-8 line." >&2
        exit 2
    fi
}

require_secret_file_option() {
    local path="$1"
    local label="$2"
    if [[ -z "${path}" ]]; then
        echo "FAIL: ${label} is required for this selected live section." >&2
        exit 2
    fi
    assert_secret_file_perms "${path}" "${label}"
}

require_splunk_rest_credentials() {
    if [[ -z "${SPLUNK_SEARCH_API_URI:-}" || -z "${SPLUNK_USER:-}" || -z "${SPLUNK_PASS:-}" ]]; then
        echo "FAIL: SPLUNK_SEARCH_API_URI, SPLUNK_USER, and SPLUNK_PASS are required for this selected live section." >&2
        exit 2
    fi
    if ! "${PYTHON_BIN}" - "${SPLUNK_SEARCH_API_URI}" <<'PY'
import sys
import urllib.parse

parsed = urllib.parse.urlsplit(sys.argv[1])
try:
    parsed.port
except ValueError:
    raise SystemExit(1)
valid = (
    parsed.scheme.lower() == "https"
    and bool(parsed.hostname)
    and parsed.username is None
    and parsed.password is None
    and not parsed.query
    and not parsed.fragment
    and parsed.path in {"", "/"}
    and not any(ch.isspace() for ch in sys.argv[1])
)
raise SystemExit(0 if valid else 1)
PY
    then
        echo "FAIL: SPLUNK_SEARCH_API_URI must be an absolute https://host[:port] URL without embedded credentials, path, query, fragment, or whitespace." >&2
        exit 2
    fi
    case "${SPLUNK_VERIFY_SSL:-true}" in
        false|FALSE|0|no|NO)
            echo "WARNING: SPLUNK_VERIFY_SSL disables certificate verification; the peer is not authenticated and credentials may be intercepted." >&2
            ;;
        *)
            if [[ -n "${SPLUNK_CA_CERT:-}" && ( -L "${SPLUNK_CA_CERT}" || ! -r "${SPLUNK_CA_CERT}" || ! -f "${SPLUNK_CA_CERT}" ) ]]; then
                echo "FAIL: SPLUNK_CA_CERT must be a readable regular, non-symlink file." >&2
                exit 2
            fi
            ;;
    esac
    export SPLUNK_SEARCH_API_URI SPLUNK_USER SPLUNK_PASS
    export SPLUNK_VERIFY_SSL="${SPLUNK_VERIFY_SSL:-true}"
    [[ -n "${SPLUNK_CA_CERT:-}" ]] && export SPLUNK_CA_CERT
}

APPLY_TARGET=""
APPLY_STACK=""
APPLY_PAIRING_MODE=""
APPLY_UID_STATUS=""
APPLY_SA_STATUS=""
APPLY_DISCOVER_STATUS=""
APPLY_RBAC_CUTOVER_STATUS=""
APPLY_RBAC_CAPABILITIES_STATUS=""
APPLY_RBAC_ROLE_STATUS=""
APPLY_LOC_STATUS=""
APPLY_SIM_STATUS=""

load_apply_metadata() {
    local metadata
    metadata="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/apply-plan.json" <<'PY'
import json
import sys

plan = json.load(open(sys.argv[1], encoding="utf-8"))
coverage = {}
for step in plan.get("steps", []):
    coverage.update(step.get("coverage", {}))
print("|".join([
    str(plan.get("target", "")),
    str(plan.get("splunk_cloud_stack", "")),
    str(plan.get("pairing_mode", "")),
    str(coverage.get("pairing.uid", {}).get("status", "")),
    str(coverage.get("pairing.sa", {}).get("status", "")),
    str(coverage.get("discover_app.read_permission", {}).get("status", "")),
    str(coverage.get("centralized_rbac.cutover", {}).get("status", "")),
    str(coverage.get("centralized_rbac.capabilities", {}).get("status", "")),
    str(coverage.get("centralized_rbac.o11y_access", {}).get("status", "")),
    str(coverage.get("log_observer_connect.user", {}).get("status", "")),
    str(coverage.get("sim_addon.account", {}).get("status", "")),
]))
PY
)"
    IFS='|' read -r APPLY_TARGET APPLY_STACK APPLY_PAIRING_MODE APPLY_UID_STATUS APPLY_SA_STATUS APPLY_DISCOVER_STATUS APPLY_RBAC_CUTOVER_STATUS APPLY_RBAC_CAPABILITIES_STATUS APPLY_RBAC_ROLE_STATUS APPLY_LOC_STATUS APPLY_SIM_STATUS <<< "${metadata}"
    if [[ -z "${APPLY_TARGET}" || -z "${APPLY_PAIRING_MODE}" ]]; then
        echo "FAIL: rendered apply-plan metadata is incomplete; refusing live mutation." >&2
        exit 2
    fi
}

preflight_section_apply() {
    local section="$1"
    case "${section}" in
        token_auth)
            require_splunk_rest_credentials
            "${PYTHON_BIN}" "${SCRIPT_DIR}/token_auth_api.py" status >/dev/null
            ;;
        pairing)
            if [[ "${APPLY_TARGET}" == "enterprise" ]]; then
                echo "ERROR: pairing is not a Splunk Enterprise action; use log_observer_connect instead." >&2
                exit 2
            fi
            case "${APPLY_PAIRING_MODE}" in
              unified_identity)
                if [[ "${APPLY_UID_STATUS}" != "api_apply" ]]; then
                    echo "ERROR: Unified Identity pairing is unavailable for this target/realm; no changes were made." >&2
                    exit 2
                fi
                require_secret_file_option "${ADMIN_TOKEN_FILE}" "--admin-token-file"
                require_secret_file_option "${SPLUNK_CLOUD_ADMIN_JWT_FILE}" "--splunk-cloud-admin-jwt-file"
                if [[ -z "${APPLY_STACK}" ]]; then
                    echo "ERROR: rendered apply plan has no Splunk Cloud stack; no changes were made." >&2
                    exit 2
                fi
                ;;
              service_account)
                if [[ "${APPLY_SA_STATUS}" != "api_apply" ]]; then
                    echo "ERROR: API-token pairing is unavailable for this target/version; no changes were made." >&2
                    exit 2
                fi
                require_secret_file_option "${TOKEN_FILE}" "--token-file"
                require_splunk_rest_credentials
                "${PYTHON_BIN}" "${SCRIPT_DIR}/discover_app_api.py" preflight-access-tokens >/dev/null
                ;;
              *)
                echo "ERROR: unknown effective pairing mode in apply plan: ${APPLY_PAIRING_MODE}" >&2
                exit 2
                ;;
            esac
            ;;
        rbac|centralized_rbac)
            if [[ "${APPLY_TARGET}" != "cloud" || "${APPLY_UID_STATUS}" == "not_applicable" ]]; then
                echo "ERROR: centralized RBAC is not applicable to this target or realm." >&2
                exit 2
            fi
            if [[ "${APPLY_RBAC_CUTOVER_STATUS}" == "handoff" ]]; then
                echo "ERROR: centralized RBAC cutover has no safe live transport; refusing before changes." >&2
                exit 2
            fi
            if [[ "${APPLY_RBAC_CAPABILITIES_STATUS}" != "api_apply" && "${APPLY_RBAC_ROLE_STATUS}" != "api_apply" ]]; then
                echo "ERROR: centralized_rbac has no requested supported mutation." >&2
                exit 2
            fi
            if [[ "${APPLY_RBAC_ROLE_STATUS}" == "api_apply" ]]; then
                require_splunk_rest_credentials
            fi
            if [[ "${APPLY_RBAC_CAPABILITIES_STATUS}" == "api_apply" ]]; then
                command -v acs >/dev/null 2>&1 || {
                    echo "FAIL: acs CLI is required for the selected centralized_rbac section." >&2
                    exit 2
                }
            fi
            ;;
        discover_app)
            if [[ "${APPLY_DISCOVER_STATUS}" != "api_apply" ]]; then
                echo "ERROR: discover_app is unavailable for this target/version." >&2
                exit 2
            fi
            require_splunk_rest_credentials
            "${PYTHON_BIN}" "${SCRIPT_DIR}/discover_app_api.py" preflight >/dev/null
            ;;
        log_observer_connect|loc)
            if [[ "${APPLY_LOC_STATUS}" != "api_apply" ]]; then
                echo "ERROR: log_observer_connect.enable=false; no live action was requested." >&2
                exit 2
            fi
            require_secret_file_option "${SERVICE_ACCOUNT_PASSWORD_FILE}" "--service-account-password-file"
            require_splunk_rest_credentials
            ;;
        sim_addon)
            if [[ "${APPLY_SIM_STATUS}" != "api_apply" ]]; then
                echo "ERROR: sim_addon.install=false; no live action was requested." >&2
                exit 2
            fi
            require_secret_file_option "${ORG_TOKEN_FILE}" "--org-token-file"
            require_splunk_rest_credentials
            "${PYTHON_BIN}" "${SCRIPT_DIR}/sim_addon_api.py" preflight-platform >/dev/null
            ;;
        related_content)
            echo "ERROR: related_content is a role-capability handoff and has no safe live apply path." >&2
            exit 2
            ;;
        *)
            echo "Unknown section: ${section}" >&2
            exit 2
            ;;
    esac
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
            "${PYTHON_BIN}" "${SCRIPT_DIR}/token_auth_api.py" --state-dir "${OUTPUT_DIR}/state" enable
            ;;
        pairing)
            export PYTHON_BIN
            export PAIRING_STATE_DIR="${OUTPUT_DIR}/state"
            if [[ "${APPLY_PAIRING_MODE}" == "unified_identity" ]]; then
                export SPLUNK_O11Y_ADMIN_TOKEN_FILE="${ADMIN_TOKEN_FILE}"
                export PAIRING_API="${SCRIPT_DIR}/o11y_pairing_api.py"
                export SPLUNK_CLOUD_STACK="${APPLY_STACK}"
                export SPLUNK_CLOUD_ADMIN_JWT_FILE
            else
                export SPLUNK_O11Y_TOKEN_FILE="${TOKEN_FILE}"
                export DISCOVER_API="${SCRIPT_DIR}/discover_app_api.py"
            fi
            "${OUTPUT_DIR}/scripts/apply-pairing.sh"
            ;;
        rbac|centralized_rbac)
            "${OUTPUT_DIR}/scripts/apply-rbac.sh"
            echo "INFO: supported capability/role actions applied; centralized RBAC cutover remains a separate handoff."
            ;;
        related_content)
            cat "${OUTPUT_DIR}/05-related-content.md"
            echo "ERROR: safe role-capability merge is not implemented; no changes were made." >&2
            echo "HANDOFF: assign the listed capabilities to the listed roles through an approved Splunk role workflow." >&2
            return 2
            ;;
        discover_app)
            export PYTHON_BIN
            export DISCOVER_API="${SCRIPT_DIR}/discover_app_api.py"
            export DISCOVER_STATE_DIR="${OUTPUT_DIR}/state"
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
            export PYTHON_BIN
            export SIM_API="${SCRIPT_DIR}/sim_addon_api.py"
            export SIM_STATE_DIR="${OUTPUT_DIR}/state"
            export SIM_CATALOG_DIR="${OUTPUT_DIR}/sim-addon/signalflow-catalog"
            # The SIM REST handlers do not exist until the app install
            # succeeds, so installation is a required dependency.
            "${OUTPUT_DIR}/scripts/apply-app-install.sh"
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
    if [[ "${SOICS_VALIDATE_LIVE:-false}" == "true" ]]; then
        require_splunk_rest_credentials
        args+=(--live)
    fi
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
        load_apply_metadata
        local_sections="${SECTIONS}"
        if [[ -z "${local_sections}" ]]; then
            if [[ "${DRY_RUN}" != "true" ]]; then
                echo "ERROR: --apply without an explicit section list is refused because this plan can contain UI/admin handoffs." >&2
                echo "Choose from: token_auth,pairing,centralized_rbac,discover_app,log_observer_connect,sim_addon." >&2
                echo "related_content and centralized RBAC cutover fail closed when no safe mutation path exists." >&2
                exit 2
            fi
            local_sections="token_auth,pairing,centralized_rbac,related_content,discover_app,log_observer_connect,sim_addon"
        fi
        IFS=',' read -ra _sects <<< "${local_sections}"
        if [[ "${DRY_RUN}" != "true" ]]; then
            for s in "${_sects[@]}"; do
                s="${s// /}"
                [[ -z "${s}" ]] && continue
                preflight_section_apply "${s}"
            done
        fi
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
        # The doctor writes a static review matrix. Use --validate --live for
        # the limited read-only reachability checks currently implemented.
        run_renderer
        run_validate doctor
        ;;
    discover)
        run_renderer
        run_validate discover
        ;;
    quickstart)
        # Force target=cloud and render the common scenario without claiming
        # completion of UI/admin handoffs.
        TARGET="cloud"
        run_renderer
        echo "==> Quickstart rendered to ${OUTPUT_DIR}; no live changes were made."
        echo "==> Apply reviewed supported sections explicitly, for example:"
        echo "    bash ${0} --apply token_auth,pairing,discover_app --spec ${SPEC} --realm ${REALM:-<realm>}"
        echo "==> Review UI/admin handoffs in 05-related-content.md and 09-handoff.md."
        bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
        ;;
    quickstart_enterprise)
        TARGET="enterprise"
        run_renderer
        echo "==> Enterprise quickstart rendered to ${OUTPUT_DIR}; no live changes were made."
        echo "==> Apply supported sections explicitly and review the Related Content handoff."
        bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
        ;;
    enable_token_auth)
        require_splunk_rest_credentials
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
source skills/shared/lib/credential_helpers.sh
SK="\$(get_session_key "\${SPLUNK_SEARCH_API_URI}")"
splunk_curl_post "\${SK}" "" --fail-with-body --show-error \\
  "\${SPLUNK_SEARCH_API_URI}/servicesNS/nobody/Splunk_TA_sim/data/inputs/splunk_infrastructure_monitoring_data_streams/<name>/disable"
# Then delete the account if no longer needed:
splunk_curl "\${SK}" --fail-with-body --show-error \\
  -X DELETE "\${SPLUNK_SEARCH_API_URI}/servicesNS/nobody/Splunk_TA_sim/splunk_infrastructure_monitoring_account/<name>"
EOF
                ;;
            log_observer_connect|loc)
                cat <<EOF
# Rollback (render-only): log_observer_connect
# Delete the workload rule, the service-account user, and the role:
source skills/shared/lib/credential_helpers.sh
SK="\$(get_session_key "\${SPLUNK_SEARCH_API_URI}")"
splunk_curl "\${SK}" --fail-with-body --show-error \\
  -X DELETE "\${SPLUNK_SEARCH_API_URI}/services/workloads/rules/loc_runtime_abort"
splunk_curl "\${SK}" --fail-with-body --show-error \\
  -X DELETE "\${SPLUNK_SEARCH_API_URI}/services/authentication/users/<svc>"
splunk_curl "\${SK}" --fail-with-body --show-error \\
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
