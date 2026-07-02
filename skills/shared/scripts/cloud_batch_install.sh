#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../lib/platform_version_helpers.sh"

REGISTRY_FILE="${REGISTRY_FILE:-${_PROJECT_ROOT}/skills/shared/app_registry.json}"

usage() {
    cat <<EOF
Batch-install Splunkbase apps on Splunk Cloud via ACS.

Installs all specified apps with --no-restart batching, then triggers a single
ACS restart at the end. Uses the app registry for license-ack URLs.

Usage: $(basename "$0") [OPTIONS] <app_id> [app_id...]

Options:
  --version VER        Version to install (applies to all apps)
  --target-splunk-version VER
                       Compatibility target (MAJOR.MINOR[.PATCH]); defaults to
                       the shared Splunk Cloud platform contract
  --accept-unsupported-platform
                       Override a known incompatibility only with documented
                       vendor/operator approval
  --accept-unverified-release
                       Request public latest instead of each repo-verified version;
                       this does not certify those releases
  --no-restart         Skip the final ACS restart
  --help               Show this help

Example:
  $(basename "$0") 7777 7828 5580
EOF
    exit "${1:-0}"
}

APP_IDS=()
APP_VERSION=""
RESTART=true
TARGET_SPLUNK_VERSION="${SPLUNK_TARGET_VERSION:-}"
ACCEPT_UNSUPPORTED_PLATFORM="${SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM:-false}"
ACCEPT_UNVERIFIED_RELEASE="${SPLUNK_ACCEPT_UNVERIFIED_RELEASE:-false}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --target-splunk-version) require_arg "$1" $# || exit 1; TARGET_SPLUNK_VERSION="$2"; shift 2 ;;
        --accept-unsupported-platform) ACCEPT_UNSUPPORTED_PLATFORM=true; shift ;;
        --accept-unverified-release) ACCEPT_UNVERIFIED_RELEASE=true; shift ;;
        --no-restart) RESTART=false; shift ;;
        --help) usage ;;
        --*) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
        *) APP_IDS+=("$1"); shift ;;
    esac
done

if (( ${#APP_IDS[@]} == 0 )); then
    log "ERROR: At least one Splunkbase app ID is required."
    usage
fi

if ! is_splunk_cloud; then
    log "ERROR: This script is for Splunk Cloud only."
    exit 1
fi

expand_dependency_app_ids() {
    if [[ ! -f "${REGISTRY_FILE}" ]]; then
        printf '%s\n' "${APP_IDS[@]}"
        return 0
    fi

    python3 -c "
import json, sys

with open(sys.argv[1]) as f:
    registry = json.load(f)

deps = {
    str(app.get('splunkbase_id', '')): [str(dep) for dep in app.get('install_requires', []) if str(dep)]
    for app in registry.get('apps', [])
}

seen = set()
ordered = []

def add(app_id):
    if not app_id or app_id in seen:
        return
    for dep_id in deps.get(app_id, []):
        add(dep_id)
    seen.add(app_id)
    ordered.append(app_id)

for requested in sys.argv[2:]:
    add(str(requested))

print('\\n'.join(ordered), end='')
" "${REGISTRY_FILE}" "${APP_IDS[@]}"
}

resolve_license_ack() {
    local app_id="$1"
    if [[ -f "${REGISTRY_FILE}" ]]; then
        python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == sys.argv[2]:
        print(app.get('license_ack_url', ''), end='')
        break
" "${REGISTRY_FILE}" "${app_id}" 2>/dev/null || true
    fi
}

resolve_app_name() {
    local app_id="$1"
    if [[ -f "${REGISTRY_FILE}" ]]; then
        python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == sys.argv[2]:
        print(app.get('app_name', ''), end='')
        break
" "${REGISTRY_FILE}" "${app_id}" 2>/dev/null || true
    fi
}

normalize_splunk_minor_version() {
    python3 - "${1:-}" <<'PY'
import re
import sys

value = sys.argv[1].strip()
match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", value)
if not match:
    raise SystemExit(1)
print(f"{match.group(1)}.{match.group(2)}", end="")
PY
}

resolve_target_splunk_version() {
    local raw="${TARGET_SPLUNK_VERSION:-}"
    if [[ -z "${raw}" ]]; then
        raw="$(spv_cloud_doc_train_default)"
    fi
    if ! TARGET_SPLUNK_VERSION="$(normalize_splunk_minor_version "${raw}")"; then
        log "ERROR: Target Splunk version '${raw}' must use MAJOR.MINOR or MAJOR.MINOR.PATCH."
        return 1
    fi
    export SPLUNK_TARGET_VERSION="${TARGET_SPLUNK_VERSION}"
    export SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM="${ACCEPT_UNSUPPORTED_PLATFORM}"
    export SPLUNK_ACCEPT_UNVERIFIED_RELEASE="${ACCEPT_UNVERIFIED_RELEASE}"
}

resolve_app_compatibility() {
    local app_id="$1"
    local target="$2"
    local selected_version="${3:-}"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 - "${REGISTRY_FILE}" "${app_id}" "${target}" "${selected_version}" <<'PY'
import json
import sys

registry_path, target_id, target_version, requested_version = sys.argv[1:]
with open(registry_path, encoding="utf-8") as handle:
    registry = json.load(handle)
for app in registry.get("apps", []):
    if str(app.get("splunkbase_id", "")) != target_id:
        continue
    verified = str(app.get("latest_verified_version", ""))
    release = str(app.get("latest_release_version", ""))
    selected = requested_version or release
    if selected == verified:
        if "verified_platform_versions" in app:
            platforms = [str(item) for item in app["verified_platform_versions"]]
        elif verified == release:
            platforms = [str(item) for item in app.get("platform_versions", [])]
        else:
            platforms = []
        evidence = "repo-verified"
    elif selected == release:
        platforms = [str(item) for item in app.get("platform_versions", [])]
        evidence = "public-latest"
    else:
        platforms = []
        evidence = "unregistered-version"
    fields = (
        "supported" if target_version in platforms else "unsupported",
        str(app.get("app_name", "")),
        ",".join(platforms),
        verified,
        release,
        selected,
        evidence,
        str(app.get("cloud_compatible", "")).lower(),
        str(app.get("install_method_single", "")),
        str(app.get("install_method_distributed", "")),
    )
    print("|".join(fields), end="")
    break
PY
}

preflight_app_compatibility() {
    local app_id="$1"
    local metadata status app_name platforms verified release
    local selected_version evidence
    local cloud_compatible install_method_single install_method_distributed
    selected_version="$(resolve_app_install_version "${app_id}")"
    metadata="$(resolve_app_compatibility "${app_id}" "${TARGET_SPLUNK_VERSION}" "${selected_version}")"
    if [[ -z "${metadata}" ]]; then
        log "INFO: App ID ${app_id} is not in the registry; compatibility with Splunk ${TARGET_SPLUNK_VERSION} must be verified separately."
        return 0
    fi

    IFS='|' read -r status app_name platforms verified release selected_version evidence cloud_compatible \
        install_method_single install_method_distributed <<< "${metadata}"
    if [[ "${cloud_compatible}" == "false" ]]; then
        if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" == "true" ]]; then
            log "WARNING: Explicit Cloud-placement override accepted for ${app_name:-app ID ${app_id}} even though Splunkbase marks cloud_compatible=false (single=${install_method_single:-unknown}, distributed=${install_method_distributed:-unknown})."
            log "WARNING: Proceed only with documented Splunk Support/vendor approval for this exact package and topology."
        else
            log "ERROR: ${app_name:-App ID ${app_id}} is explicitly cloud_compatible=false on Splunkbase."
            log "Cloud install methods: single=${install_method_single:-unknown}, distributed=${install_method_distributed:-unknown}."
            log "Refusing the entire batch before ACS mutation. Use a customer-managed runtime or pass --accept-unsupported-platform only with documented Splunk Support/vendor approval."
            return 1
        fi
    fi
    if [[ "${status}" != "supported" ]]; then
        if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" == "true" ]]; then
            log "WARNING: Explicit override accepted for ${app_name:-app ID ${app_id}} version ${selected_version:-unknown} (${evidence}) on Splunk ${TARGET_SPLUNK_VERSION}; advertised versions: ${platforms:-none}."
        else
            log "ERROR: ${app_name:-App ID ${app_id}} version ${selected_version:-unknown} (${evidence}) does not advertise Splunk ${TARGET_SPLUNK_VERSION} compatibility."
            log "Selected-release platform versions: ${platforms:-none}."
            if [[ "${evidence}" == "repo-verified" && -z "${platforms}" && "${release}" != "${verified}" ]]; then
                log "The repo-verified pin has no current public compatibility evidence for this target; use --accept-unverified-release to review public latest."
            fi
            log "Refusing the entire batch before ACS mutation. Pass --accept-unsupported-platform only with documented vendor approval."
            return 1
        fi
    else
        log "Compatibility preflight passed: ${app_name:-app ID ${app_id}} version ${selected_version:-unknown} (${evidence}) advertises Splunk ${TARGET_SPLUNK_VERSION}."
    fi

    if [[ -z "${APP_VERSION}" && "${ACCEPT_UNVERIFIED_RELEASE}" != "true" && -n "${verified}" ]]; then
        if [[ -n "${release}" && "${release}" != "${verified}" ]]; then
            log "App ID ${app_id}: using repo-verified version ${verified}; public latest ${release} remains unverified by this repo."
        else
            log "App ID ${app_id}: using repo-verified version ${verified}."
        fi
    elif [[ -z "${APP_VERSION}" && "${ACCEPT_UNVERIFIED_RELEASE}" == "true" ]]; then
        log "WARNING: App ID ${app_id}: public latest requested without repository package verification."
    fi
}

resolve_app_install_version() {
    local app_id="$1"
    if [[ -n "${APP_VERSION}" ]]; then
        printf '%s' "${APP_VERSION}"
        return 0
    fi
    if [[ "${ACCEPT_UNVERIFIED_RELEASE}" != "true" && -f "${REGISTRY_FILE}" ]]; then
        python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == sys.argv[2]:
        print(app.get('latest_verified_version', ''), end='')
        break
" "${REGISTRY_FILE}" "${app_id}" 2>/dev/null || true
    fi
}

verify_app_identity() {
    local sk="$1" uri="$2" app_name="$3"
    local actual_id
    actual_id=$(splunk_curl "${sk}" \
        "${uri}/servicesNS/nobody/${app_name}/configs/conf-app/package?output_mode=json" \
        2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print(data['entry'][0]['content'].get('id', ''), end='')
except Exception:
    print('', end='')
" 2>/dev/null || true)

    if [[ -z "${actual_id}" ]]; then
        log "  WARNING: Could not verify identity of ${app_name} (REST query failed)."
        return 1
    elif [[ "${actual_id}" != "${app_name}" ]]; then
        log "  WARNING: App directory '${app_name}' contains '${actual_id}' files."
        log "           ACS deployment may be corrupted. Uninstall and reinstall individually."
        return 1
    fi
    return 0
}

expanded_app_ids=()
while IFS= read -r expanded_id || [[ -n "${expanded_id}" ]]; do
    [[ -n "${expanded_id}" ]] || continue
    expanded_app_ids+=("${expanded_id}")
done < <(expand_dependency_app_ids)

if (( ${#expanded_app_ids[@]} > 0 )); then
    APP_IDS=("${expanded_app_ids[@]}")
fi

resolve_target_splunk_version || exit 1
for app_id in "${APP_IDS[@]}"; do
    preflight_app_compatibility "${app_id}" || exit 1
done

acs_prepare_context || exit 1

log "=== Cloud Batch Install ==="
log "Apps: ${APP_IDS[*]}"
log ""

failures=0
verify_failures=0
for app_id in "${APP_IDS[@]}"; do
    log "Installing Splunkbase app ID ${app_id}..."
    warn_if_role_unsupported_for_app_id "${app_id}"

    license_ack="$(resolve_license_ack "${app_id}")"
    install_version="$(resolve_app_install_version "${app_id}")"

    declare -a cmd=(apps install splunkbase --splunkbase-id "${app_id}")
    [[ -n "${install_version}" ]] && cmd+=(--version "${install_version}")
    [[ -n "${license_ack}" ]] && cmd+=(--acs-licensing-ack "${license_ack}")
    cloud_requires_local_scope && cmd+=(--scope local)

    set +e
    output=$(acs_command "${cmd[@]}" 2>&1)
    rc=$?
    set -e

    if (( rc == 0 )); then
        log "  Installed app ID ${app_id}."
    else
        # Detect HTTP 409 conflict by parsing the structured ACS payload
        # (acs_command sets --format structured) rather than grepping the
        # human-readable string, which has shifted between ACS releases.
        already_installed=$(printf '%s' "${output}" | python3 -c '
import json
import sys

raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)
items = data if isinstance(data, list) else [data]
for item in items:
    if not isinstance(item, dict):
        continue
    response = item.get("response")
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except Exception:
            response = {}
    if isinstance(response, dict):
        status = response.get("statusCode") or response.get("status_code") or response.get("status")
        if str(status) == "409":
            print("yes", end="")
            sys.exit(0)
    status = item.get("statusCode") or item.get("status_code") or item.get("status")
    if str(status) == "409":
        print("yes", end="")
        sys.exit(0)
' 2>/dev/null || true)
        if [[ "${already_installed}" == "yes" ]]; then
            log "  App ID ${app_id} already installed (skipped)."
        else
            log "  ERROR: Failed to install app ID ${app_id} (rc=${rc})."
            [[ -n "${output}" ]] && log "  ${output}"
            failures=$((failures + 1))
        fi
    fi
done

if (( failures > 0 )); then
    log ""
    log "WARNING: ${failures} app(s) failed to install."
fi

if ${RESTART}; then
    log ""
    log "Checking if ACS restart is required..."
    cloud_restart_if_required 900
    log "Stack is Ready."
fi

log ""
log "--- Verifying app identity ---"
load_splunk_credentials
verify_sk=$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)
if [[ -n "${verify_sk}" ]]; then
    for app_id in "${APP_IDS[@]}"; do
        expected_name="$(resolve_app_name "${app_id}")"
        if [[ -z "${expected_name}" ]]; then
            continue
        fi
        if ! verify_app_identity "${verify_sk}" "${SPLUNK_URI}" "${expected_name}"; then
            verify_failures=$((verify_failures + 1))
        else
            log "  ${expected_name}: OK"
        fi
    done
    if (( verify_failures > 0 )); then
        log ""
        log "WARNING: ${verify_failures} app(s) may have corrupted deployments."
        log "Uninstall the affected apps and reinstall them individually."
    fi
else
    log "  Skipped (no search-tier REST access)."
fi

log ""
log "=== Batch install complete ==="

if (( failures > 0 || verify_failures > 0 )); then
    exit 1
fi
