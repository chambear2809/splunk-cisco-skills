#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

APP_NAME="Splunk_AI_Assistant_Cloud"
APP_ID="7245"
LATEST_VERIFIED_APP_VERSION="2.0.0"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh}"
VALIDATE_SCRIPT="${VALIDATE_SCRIPT:-${SCRIPT_DIR}/validate.sh}"

DO_INSTALL=false
DO_VALIDATE=false
VALIDATE_EXPLICIT=false
DO_SUBMIT_ONBOARDING=false
DO_COMPLETE_ONBOARDING=false
DO_SET_PROXY=false
DO_CLEAR_PROXY=false

APP_VERSION=""
EMAIL=""
REGION=""
COMPANY_NAME=""
TENANT_NAME=""
ACTIVATION_CODE_FILE=""
PROXY_URL=""
PROXY_USERNAME=""
PROXY_PASSWORD_FILE=""

SK=""
AUTO_VALIDATE_EXPECTS_ONBOARDED=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk AI Assistant Setup

Usage: $(basename "$0") [OPTIONS]

Operations:
  --install                          Install or update ${APP_NAME} from Splunkbase
  --validate                         Run the post-install validation checks
  --submit-onboarding-form           Submit Enterprise cloud-connected onboarding details
  --complete-onboarding              Complete Enterprise activation using an activation-code file
  --set-proxy                        Configure the Enterprise outbound proxy used by the app
  --clear-proxy                      Remove the Enterprise outbound proxy configuration
  (no flags)                         Install/update and then validate

Options:
  --app-version VER                  Pin a specific Splunkbase version instead of latest (${LATEST_VERIFIED_APP_VERSION})
  --email EMAIL                      Onboarding contact email
  --region REGION                    Onboarding region token such as usa
  --company-name NAME                Customer company name for onboarding submission
  --tenant-name NAME                 Tenant name used during onboarding submission
  --activation-code-file PATH        File containing the activation code/token
  --proxy-url URL                    Proxy URL such as https://proxy.example.com:8443
  --proxy-username USER              Proxy username when proxy auth is required
  --proxy-password-file PATH         File containing the proxy password
  --help                             Show this help text

Examples:
  $(basename "$0")
  $(basename "$0") --install
  $(basename "$0") --submit-onboarding-form --email ops@example.com \\
    --region usa --company-name Example --tenant-name example-prod
  $(basename "$0") --complete-onboarding --activation-code-file /tmp/saia_activation_code
  $(basename "$0") --set-proxy --proxy-url https://proxy.example.com:8443
  $(basename "$0") --validate

EOF
    exit "${exit_code}"
}

ensure_search_tier_target() {
    local role

    role="$(resolve_splunk_target_role 2>/dev/null || true)"
    if [[ -n "${role}" && "${role}" != "search-tier" ]]; then
        log "ERROR: ${APP_NAME} belongs on the search tier, not role '${role}'."
        exit 1
    fi
}

ensure_session() {
    if [[ -n "${SK}" ]]; then
        return 0
    fi

    load_splunk_credentials || {
        log "ERROR: Splunk credentials are required."
        exit 1
    }
    SK="$(get_session_key "${SPLUNK_URI}")" || {
        log "ERROR: Could not authenticate to Splunk."
        exit 1
    }
}

ensure_app_installed() {
    ensure_session
    if ! rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
        log "ERROR: ${APP_NAME} is not installed. Run --install first."
        exit 1
    fi
}

ensure_enterprise_for_setup_actions() {
    if is_splunk_cloud; then
        log "ERROR: Enterprise setup actions are not supported on Splunk Cloud targets."
        log "       Splunk Cloud support for ${APP_NAME} is install/update plus validation only."
        exit 1
    fi
}

ensure_prompted_value() {
    local var_name="$1"
    local prompt="$2"
    local default_value="${3:-}"
    local current_value="${!var_name:-}"

    if [[ -z "${current_value}" ]] && hbs_is_interactive; then
        current_value="$(hbs_prompt_value "${prompt}" "${default_value}")"
        printf -v "${var_name}" '%s' "${current_value}"
    fi

    if [[ -z "${!var_name:-}" ]]; then
        log "ERROR: ${prompt} is required."
        exit 1
    fi
}

ensure_prompted_path() {
    local var_name="$1"
    local prompt="$2"
    local current_value="${!var_name:-}"

    if [[ -z "${current_value}" ]] && hbs_is_interactive; then
        current_value="$(hbs_prompt_secret_path "${prompt}")"
        printf -v "${var_name}" '%s' "${current_value}"
    fi

    if [[ -z "${!var_name:-}" ]]; then
        log "ERROR: ${prompt} is required."
        exit 1
    fi
}

canonicalize_onboarding_region() {
    local raw_region="$1"
    local normalized lookup

    normalized="$(printf '%s' "${raw_region}" | tr '[:upper:]' '[:lower:]')"
    lookup="$(printf '%s' "${raw_region}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]_-')"

    case "${lookup}" in
        us|usa|unitedstates)
            printf '%s' "usa"
            return 0
            ;;
    esac

    case "${normalized}" in
        *[!a-z0-9_-]*)
            log "ERROR: Onboarding region must use the app region token (letters, numbers, dash, underscore), for example 'usa'."
            exit 1
            ;;
    esac

    printf '%s' "${normalized}"
}

normalize_onboarding_region() {
    local original_region="${REGION}"
    local canonical_region

    canonical_region="$(canonicalize_onboarding_region "${REGION}")"
    if [[ "${canonical_region}" != "${original_region}" ]]; then
        log "Normalizing onboarding region '${original_region}' to '${canonical_region}'."
    fi
    REGION="${canonical_region}"
}

saia_handler_url() {
    local handler="$1"
    printf '%s/servicesNS/nobody/%s/%s?output_mode=json' "${SPLUNK_URI}" "${APP_NAME}" "${handler}"
}

saia_request_with_code() {
    local method="$1"
    local handler="$2"
    local payload="${3:-}"
    local url

    url="$(saia_handler_url "${handler}")"

    if [[ -n "${payload}" ]]; then
        splunk_curl "${SK}" \
            -X "${method}" \
            "${url}" \
            -H "Source-App-ID: ${APP_NAME}" \
            -H "Content-Type: application/json" \
            -d "${payload}" \
            -w '\n%{http_code}' 2>/dev/null || echo "000"
    else
        splunk_curl "${SK}" \
            -X "${method}" \
            "${url}" \
            -H "Source-App-ID: ${APP_NAME}" \
            -w '\n%{http_code}' 2>/dev/null || echo "000"
    fi
}

http_code_from_response() {
    printf '%s\n' "${1}" | tail -1
}

body_from_response() {
    printf '%s\n' "${1}" | sed '$d'
}

fail_on_bad_response() {
    local action="$1"
    local response="$2"
    local code body

    code="$(http_code_from_response "${response}")"
    body="$(body_from_response "${response}")"

    log "ERROR: ${action} failed (HTTP ${code})."
    if [[ -n "${body}" ]]; then
        sanitize_response "${body}" 10 >&2
    fi
    exit 1
}

build_onboarding_payload() {
    python3 - "${EMAIL}" "${REGION}" "${COMPANY_NAME}" "${TENANT_NAME}" <<'PY'
import json
import sys

print(
    json.dumps(
        {
            "email": sys.argv[1],
            "region": sys.argv[2],
            "company_name": sys.argv[3],
            "tenant_name": sys.argv[4],
        }
    ),
    end="",
)
PY
}

build_activation_payload() {
    local activation_code="$1"
    python3 - 3<<<"${activation_code}" <<'PY'
import json
import os

with os.fdopen(3, encoding="utf-8") as handle:
    activation_code = handle.read()
if activation_code.endswith("\n"):
    activation_code = activation_code[:-1]
print(json.dumps({"activation_code": activation_code}), end="")
PY
}

build_proxy_payload() {
    local proxy_password="$1"
    python3 - "${PROXY_URL}" "${PROXY_USERNAME}" 3<<<"${proxy_password}" <<'PY'
from urllib.parse import urlsplit
import json
import os
import sys

proxy_url, username = sys.argv[1:]
with os.fdopen(3, encoding="utf-8") as handle:
    password = handle.read()
if password.endswith("\n"):
    password = password[:-1]
parts = urlsplit(proxy_url)

if parts.scheme not in ("http", "https"):
    print("ERROR: --proxy-url must use http:// or https://.", file=sys.stderr)
    raise SystemExit(1)
if not parts.hostname:
    print("ERROR: --proxy-url must include a hostname.", file=sys.stderr)
    raise SystemExit(1)
if parts.port is None:
    print("ERROR: --proxy-url must include an explicit port.", file=sys.stderr)
    raise SystemExit(1)
if parts.username or parts.password:
    print(
        "ERROR: Put proxy credentials in --proxy-username and --proxy-password-file, not in --proxy-url.",
        file=sys.stderr,
    )
    raise SystemExit(1)
if parts.path not in ("", "/") or parts.query or parts.fragment:
    print("ERROR: --proxy-url must contain only scheme, host, and port.", file=sys.stderr)
    raise SystemExit(1)
if bool(username) != bool(password):
    print(
        "ERROR: --proxy-username and --proxy-password-file must be provided together.",
        file=sys.stderr,
    )
    raise SystemExit(1)

payload = {
    "proxy_settings": {
        "type": parts.scheme,
        "hostname": parts.hostname,
        "port": str(parts.port),
    }
}
if username:
    payload["proxy_settings"]["username"] = username
    payload["proxy_settings"]["password"] = password

print(json.dumps(payload), end="")
PY
}

describe_proxy_target() {
    python3 - "${PROXY_URL}" "${PROXY_USERNAME}" <<'PY'
from urllib.parse import urlsplit
import sys

parts = urlsplit(sys.argv[1])
auth = " with auth" if sys.argv[2] else ""
print(f"{parts.scheme}://{parts.hostname}:{parts.port}{auth}", end="")
PY
}

describe_activation_result() {
    local payload="$1"
    ACTIVATION_RESULT_PAYLOAD="${payload}" python3 <<'PY'
import json
import os

payload = json.loads(os.environ.get("ACTIVATION_RESULT_PAYLOAD", "{}"))
tenant_name = payload.get("tenant_name") or "unknown"
tenant_hostname = payload.get("tenant_hostname") or "unknown"
print(f"{tenant_name} ({tenant_hostname})", end="")
PY
}

install_or_update() {
    local update_flag="--no-update"
    local -a cmd

    if is_splunk_cloud; then
        # The shared installer already handles the "update if present, else install"
        # behavior for ACS Splunkbase installs. Avoid a pre-install REST login here.
        update_flag="--update"
        log "Installing or updating ${APP_NAME} on Splunk Cloud from Splunkbase app ID ${APP_ID}..."
    else
        ensure_session
        if rest_check_app "${SK}" "${SPLUNK_URI}" "${APP_NAME}"; then
            update_flag="--update"
            log "Updating ${APP_NAME} from Splunkbase app ID ${APP_ID}..."
        else
            log "Installing ${APP_NAME} from Splunkbase app ID ${APP_ID}..."
        fi
    fi

    cmd=(
        bash
        "${APP_INSTALL_SCRIPT}"
        --source
        splunkbase
        --app-id
        "${APP_ID}"
        "${update_flag}"
    )

    if [[ -n "${APP_VERSION}" ]]; then
        cmd+=(--app-version "${APP_VERSION}")
    fi

    "${cmd[@]}"
}

print_platform_notes() {
    log ""
    if is_splunk_cloud; then
        log "Splunk Cloud note: keep this app on the public Splunkbase install path."
        log "Latest verified release is ${LATEST_VERIFIED_APP_VERSION}; Agent Mode is limited to supported AWS commercial regions."
        log "FedRAMP IL2 support is limited in ${LATEST_VERIFIED_APP_VERSION}: no Agent Mode, training/fine-tuning data off by default, and Splunk-hosted models only."
        log "Open the app in Splunk Web after install to confirm Context, Model Runtime, and feature availability on the target stack."
    else
        log "Splunk Enterprise note: this app still uses Splunk-managed cloud services."
        log "Latest verified release is ${LATEST_VERIFIED_APP_VERSION}; prefer Splunk Enterprise 9.3+ for unpinned latest installs."
        log "Allow outbound HTTPS to *.scs.splunk.com:443 from the search head."
        log "Use --submit-onboarding-form, --complete-onboarding, and optional proxy settings to drive the cloud-connected setup flow."
        log "If the target is an SHC and deployer-target credentials are configured, the shared installer can use deployer bundle delivery."
    fi
}

submit_onboarding_form() {
    local payload response code

    ensure_prompted_value EMAIL "Onboarding email"
    ensure_prompted_value REGION "Onboarding region"
    ensure_prompted_value COMPANY_NAME "Company name"
    ensure_prompted_value TENANT_NAME "Tenant name"
    normalize_onboarding_region

    payload="$(build_onboarding_payload)"
    response="$(saia_request_with_code "POST" "submitonboardingform" "${payload}")"
    code="$(http_code_from_response "${response}")"

    if [[ "${code}" != "200" ]]; then
        fail_on_bad_response "Submitting onboarding form" "${response}"
    fi

    log "Submitted onboarding details for tenant '${TENANT_NAME}' in region '${REGION}'."
    log "Expected next state: onboarding submitted, activation pending."
    log "The remaining blocker is the Splunk-issued activation code/token, which may not arrive immediately."
    log "Validation will now confirm the pending setup state."
    log "When the activation code/token is available, save it to a local file, then run:"
    log "  bash skills/splunk-ai-assistant-setup/scripts/setup.sh --complete-onboarding --activation-code-file /path/to/activation_code"
    DO_VALIDATE=true
}

complete_onboarding() {
    local activation_code payload response code result_summary

    ensure_prompted_path ACTIVATION_CODE_FILE "Activation code file path"
    activation_code="$(read_secret_file "${ACTIVATION_CODE_FILE}")"
    if [[ -z "${activation_code}" ]]; then
        log "ERROR: Activation code file is empty: ${ACTIVATION_CODE_FILE}"
        exit 1
    fi

    payload="$(build_activation_payload "${activation_code}")"
    response="$(saia_request_with_code "POST" "completeonboarding" "${payload}")"
    code="$(http_code_from_response "${response}")"

    if [[ "${code}" != "200" ]]; then
        fail_on_bad_response "Completing onboarding" "${response}"
    fi

    result_summary="$(describe_activation_result "$(body_from_response "${response}")" 2>/dev/null || echo "unknown")"
    log "Completed cloud-connected activation for ${result_summary}."
    AUTO_VALIDATE_EXPECTS_ONBOARDED=true
}

set_proxy() {
    local proxy_password payload response code

    ensure_prompted_value PROXY_URL "Proxy URL"

    if [[ -n "${PROXY_USERNAME}" && -z "${PROXY_PASSWORD_FILE}" ]]; then
        ensure_prompted_path PROXY_PASSWORD_FILE "Proxy password file path"
    fi
    if [[ -z "${PROXY_USERNAME}" && -n "${PROXY_PASSWORD_FILE}" ]]; then
        log "ERROR: --proxy-password-file requires --proxy-username."
        exit 1
    fi

    proxy_password=""
    if [[ -n "${PROXY_PASSWORD_FILE}" ]]; then
        proxy_password="$(read_secret_file "${PROXY_PASSWORD_FILE}")"
    fi

    payload="$(build_proxy_payload "${proxy_password}")"
    response="$(saia_request_with_code "POST" "cloudconnectedproxysettings" "${payload}")"
    code="$(http_code_from_response "${response}")"

    if [[ "${code}" != "200" ]]; then
        fail_on_bad_response "Setting proxy configuration" "${response}"
    fi

    log "Configured cloud-connected proxy: $(describe_proxy_target)."
}

clear_proxy() {
    local response code

    response="$(saia_request_with_code "DELETE" "cloudconnectedproxysettings")"
    code="$(http_code_from_response "${response}")"

    if [[ "${code}" != "200" ]]; then
        fail_on_bad_response "Clearing proxy configuration" "${response}"
    fi

    log "Cleared the cloud-connected proxy configuration."
}

run_validation() {
    local -a cmd

    cmd=(bash "${VALIDATE_SCRIPT}")
    if [[ "${AUTO_VALIDATE_EXPECTS_ONBOARDED}" == "true" ]]; then
        cmd+=(--expect-configured true --expect-onboarded true)
    fi

    if "${cmd[@]}"; then
        return 0
    fi

    if [[ "${DO_INSTALL}" == "true" && "${VALIDATE_EXPLICIT}" != "true" ]] && is_splunk_cloud; then
        log "WARNING: Install completed, but post-install validation could not finish."
        log "         Splunk Cloud validation needs search-tier REST access on :8089 and any required allowlisting."
        return 0
    fi

    return 1
}

validate_args() {
    if [[ -n "${EMAIL}" && "${DO_SUBMIT_ONBOARDING}" != "true" ]]; then
        log "ERROR: --email requires --submit-onboarding-form."
        exit 1
    fi
    if [[ -n "${REGION}" && "${DO_SUBMIT_ONBOARDING}" != "true" ]]; then
        log "ERROR: --region requires --submit-onboarding-form."
        exit 1
    fi
    if [[ -n "${COMPANY_NAME}" && "${DO_SUBMIT_ONBOARDING}" != "true" ]]; then
        log "ERROR: --company-name requires --submit-onboarding-form."
        exit 1
    fi
    if [[ -n "${TENANT_NAME}" && "${DO_SUBMIT_ONBOARDING}" != "true" ]]; then
        log "ERROR: --tenant-name requires --submit-onboarding-form."
        exit 1
    fi
    if [[ -n "${ACTIVATION_CODE_FILE}" && "${DO_COMPLETE_ONBOARDING}" != "true" ]]; then
        log "ERROR: --activation-code-file requires --complete-onboarding."
        exit 1
    fi
    if [[ -n "${PROXY_URL}" && "${DO_SET_PROXY}" != "true" ]]; then
        log "ERROR: --proxy-url requires --set-proxy."
        exit 1
    fi
    if [[ -n "${PROXY_USERNAME}" && "${DO_SET_PROXY}" != "true" ]]; then
        log "ERROR: --proxy-username requires --set-proxy."
        exit 1
    fi
    if [[ -n "${PROXY_PASSWORD_FILE}" && "${DO_SET_PROXY}" != "true" ]]; then
        log "ERROR: --proxy-password-file requires --set-proxy."
        exit 1
    fi
    if [[ "${DO_SET_PROXY}" == "true" && "${DO_CLEAR_PROXY}" == "true" ]]; then
        log "ERROR: --set-proxy and --clear-proxy cannot be used together."
        exit 1
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install) DO_INSTALL=true; shift ;;
        --validate) DO_VALIDATE=true; VALIDATE_EXPLICIT=true; shift ;;
        --submit-onboarding-form) DO_SUBMIT_ONBOARDING=true; shift ;;
        --complete-onboarding) DO_COMPLETE_ONBOARDING=true; shift ;;
        --set-proxy) DO_SET_PROXY=true; shift ;;
        --clear-proxy) DO_CLEAR_PROXY=true; shift ;;
        --app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --email) require_arg "$1" $# || exit 1; EMAIL="$2"; shift 2 ;;
        --region) require_arg "$1" $# || exit 1; REGION="$2"; shift 2 ;;
        --company-name) require_arg "$1" $# || exit 1; COMPANY_NAME="$2"; shift 2 ;;
        --tenant-name) require_arg "$1" $# || exit 1; TENANT_NAME="$2"; shift 2 ;;
        --activation-code-file) require_arg "$1" $# || exit 1; ACTIVATION_CODE_FILE="$2"; shift 2 ;;
        --proxy-url) require_arg "$1" $# || exit 1; PROXY_URL="$2"; shift 2 ;;
        --proxy-username) require_arg "$1" $# || exit 1; PROXY_USERNAME="$2"; shift 2 ;;
        --proxy-password-file) require_arg "$1" $# || exit 1; PROXY_PASSWORD_FILE="$2"; shift 2 ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ "${DO_INSTALL}" != "true" \
    && "${DO_VALIDATE}" != "true" \
    && "${DO_SUBMIT_ONBOARDING}" != "true" \
    && "${DO_COMPLETE_ONBOARDING}" != "true" \
    && "${DO_SET_PROXY}" != "true" \
    && "${DO_CLEAR_PROXY}" != "true" ]]; then
    DO_INSTALL=true
    DO_VALIDATE=true
fi

warn_if_current_skill_role_unsupported
ensure_search_tier_target
validate_args

if [[ "${DO_INSTALL}" == "true" ]]; then
    install_or_update
    print_platform_notes
fi

if [[ "${DO_SUBMIT_ONBOARDING}" == "true" \
    || "${DO_COMPLETE_ONBOARDING}" == "true" \
    || "${DO_SET_PROXY}" == "true" \
    || "${DO_CLEAR_PROXY}" == "true" ]]; then
    ensure_enterprise_for_setup_actions
    ensure_app_installed
fi

if [[ "${DO_CLEAR_PROXY}" == "true" ]]; then
    clear_proxy
fi

if [[ "${DO_SET_PROXY}" == "true" ]]; then
    set_proxy
fi

if [[ "${DO_SUBMIT_ONBOARDING}" == "true" ]]; then
    submit_onboarding_form
fi

if [[ "${DO_COMPLETE_ONBOARDING}" == "true" ]]; then
    complete_onboarding
fi

if [[ "${DO_VALIDATE}" == "true" || "${AUTO_VALIDATE_EXPECTS_ONBOARDED}" == "true" ]]; then
    run_validation
fi
