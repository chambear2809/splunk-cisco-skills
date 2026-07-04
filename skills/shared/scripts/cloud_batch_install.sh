#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../lib/platform_version_helpers.sh"

REGISTRY_FILE="${REGISTRY_FILE:-${_PROJECT_ROOT}/skills/shared/app_registry.json}"
REGISTRY_AUDIT="${SCRIPT_DIR}/audit_splunkbase_registry.py"

require_registry_provenance() {
    local audit_output
    if [[ ! -f "${REGISTRY_FILE}" ]]; then
        log "ERROR: Refusing the entire batch before ACS mutation: app registry is missing at ${REGISTRY_FILE}."
        return 1
    fi
    if [[ ! -x "${REGISTRY_AUDIT}" ]]; then
        log "ERROR: Refusing the entire batch before ACS mutation: registry provenance verifier is unavailable."
        return 1
    fi
    if ! audit_output="$(python3 "${REGISTRY_AUDIT}" --registry "${REGISTRY_FILE}" 2>&1)"; then
        log "ERROR: Refusing the entire batch before ACS mutation: Splunkbase registry provenance validation failed."
        [[ -n "${audit_output}" ]] && printf '%s\n' "${audit_output}" >&2
        return 1
    fi
}

usage() {
    cat <<EOF
Batch-install Splunkbase apps on Splunk Cloud via ACS.

Installs all specified apps with --no-restart batching, then triggers a single
ACS restart at the end. Uses the app registry for license-ack URLs.

Usage: $(basename "$0") [OPTIONS] <app_id> [app_id...]

Options:
  --version VER        Exact version for one explicitly requested root app;
                       expanded dependencies keep their registry-selected pins
  --target-splunk-version VER
                       Compatibility target (MAJOR.MINOR[.PATCH]); defaults to
                       the shared Splunk Cloud platform contract
  --accept-unsupported-platform
                       Override a known incompatibility only with documented
                       vendor/operator approval
  --accept-unverified-release
                       Pin the registry-recorded public latest instead of each
                       repo-verified version;
                       also acknowledges independently reviewed unknown numeric IDs;
                       this does not certify those releases
  --accept-historical-review-only-pin
                       Permit an older reviewed pin no longer returned by the current
                       public release API; requires independent package/version approval
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
ACCEPT_HISTORICAL_REVIEW_ONLY_PIN="${SPLUNK_ACCEPT_HISTORICAL_REVIEW_ONLY_PIN:-false}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --target-splunk-version) require_arg "$1" $# || exit 1; TARGET_SPLUNK_VERSION="$2"; shift 2 ;;
        --accept-unsupported-platform) ACCEPT_UNSUPPORTED_PLATFORM=true; shift ;;
        --accept-unverified-release) ACCEPT_UNVERIFIED_RELEASE=true; shift ;;
        --accept-historical-review-only-pin) ACCEPT_HISTORICAL_REVIEW_ONLY_PIN=true; shift ;;
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

validate_splunkbase_id() {
    local app_id="${1:-}"
    [[ "${app_id}" =~ ^[1-9][0-9]*$ ]]
}

validate_app_version() {
    local version="${1:-}"
    (( ${#version} <= 128 )) || return 1
    [[ "${version}" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]]
}

for app_id in "${APP_IDS[@]}"; do
    if ! validate_splunkbase_id "${app_id}"; then
        log "ERROR: Splunkbase app ID '${app_id}' must be a positive numeric ID."
        exit 1
    fi
done

if [[ -n "${APP_VERSION}" ]] && ! validate_app_version "${APP_VERSION}"; then
    log "ERROR: --version must be 1-128 characters using only letters, digits, '.', '_', '+', or '-'."
    exit 1
fi

if [[ -n "${APP_VERSION}" ]] && (( ${#APP_IDS[@]} != 1 )); then
    log "ERROR: --version requires exactly one explicitly requested root app ID."
    log "Use separate invocations when root apps require different exact versions."
    exit 1
fi

require_registry_provenance || exit 1

if ! is_splunk_cloud; then
    log "ERROR: This script is for Splunk Cloud only."
    exit 1
fi

expand_dependency_app_ids() {
    python3 - "${REGISTRY_FILE}" "${APP_IDS[@]}" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    registry = json.load(handle)

apps = {
    str(app.get("splunkbase_id", "")): app
    for app in registry.get("apps", [])
    if str(app.get("splunkbase_id", "")).isdigit()
}
dependencies = {}
for app_id, app in apps.items():
    raw = app.get("install_requires", [])
    if not isinstance(raw, list):
        print(f"ERROR: app {app_id} install_requires must be a list", file=sys.stderr)
        raise SystemExit(1)
    parsed = []
    seen_dependencies = set()
    for dependency in raw:
        if not isinstance(dependency, str) or not re.fullmatch(r"[1-9]\d*", dependency):
            print(f"ERROR: app {app_id} has an invalid dependency ID", file=sys.stderr)
            raise SystemExit(1)
        if dependency in seen_dependencies:
            print(f"ERROR: app {app_id} repeats dependency {dependency}", file=sys.stderr)
            raise SystemExit(1)
        if dependency == app_id:
            print(f"ERROR: app {app_id} depends on itself", file=sys.stderr)
            raise SystemExit(1)
        if dependency not in apps:
            print(f"ERROR: app {app_id} dependency {dependency} is missing", file=sys.stderr)
            raise SystemExit(1)
        seen_dependencies.add(dependency)
        parsed.append(dependency)
    dependencies[app_id] = parsed

state = {}
stack = []
ordered = []

def add(app_id):
    status = state.get(app_id, 0)
    if status == 2:
        return
    if status == 1:
        start = stack.index(app_id)
        cycle = stack[start:] + [app_id]
        print(f"ERROR: dependency cycle detected: {' -> '.join(cycle)}", file=sys.stderr)
        raise SystemExit(1)
    state[app_id] = 1
    stack.append(app_id)
    for dependency in dependencies.get(app_id, []):
        add(dependency)
    stack.pop()
    state[app_id] = 2
    ordered.append(app_id)

for requested in sys.argv[2:]:
    add(str(requested))

print("\n".join(ordered), end="")
PY
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
        evidence = (
            "historical-review-only"
            if app.get("verified_release_evidence_status")
            == "historical-review-only-not-currently-reproducible"
            else "repo-verified"
        )
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
        str(app.get("verified_release_evidence_status", "source-verified-current-release-api")),
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
    local verified_evidence_status
    selected_version="$(resolve_app_install_version "${app_id}")"
    metadata="$(resolve_app_compatibility "${app_id}" "${TARGET_SPLUNK_VERSION}" "${selected_version}")"
    if [[ -z "${metadata}" ]]; then
        if [[ "${app_id}" =~ ^[0-9]+$ ]]; then
            if [[ "${ACCEPT_UNVERIFIED_RELEASE}" != "true" ]]; then
                log "ERROR: Numeric app ID ${app_id} is outside the provenance-bound registry."
                log "Refusing the entire batch before ACS mutation. Pass --accept-unverified-release only after independently reviewing the app identity and release."
                return 1
            fi
            if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" != "true" ]]; then
                log "ERROR: Numeric app ID ${app_id} has no registry platform evidence for Splunk ${TARGET_SPLUNK_VERSION}."
                log "Refusing the entire batch before ACS mutation. After manual compatibility review, pass --accept-unsupported-platform as a separate approval."
                return 1
            fi
            if [[ -z "${selected_version}" ]]; then
                log "ERROR: Unknown Splunkbase app ID ${app_id} requires an explicit --version."
                log "Refusing the entire batch before ACS mutation because a moving latest release cannot be verified exactly."
                return 1
            fi
            log "WARNING: Explicit unverified-ID and manual platform approvals accepted for unknown Splunkbase app ID ${app_id}."
            return 0
        fi
        log "INFO: App ID ${app_id} is not a numeric Splunkbase ID; compatibility must be verified separately."
        return 0
    fi

    IFS='|' read -r status app_name platforms verified release selected_version evidence cloud_compatible \
        install_method_single install_method_distributed verified_evidence_status <<< "${metadata}"
    if [[ "${selected_version}" == "${verified}" && "${verified_evidence_status}" == "historical-review-only-not-currently-reproducible" ]]; then
        if [[ "${ACCEPT_HISTORICAL_REVIEW_ONLY_PIN}" == "true" ]]; then
            log "WARNING: Explicit historical-review-only pin override accepted for ${app_name:-app ID ${app_id}} version ${selected_version}."
            log "WARNING: The current public Splunkbase release API cannot reproduce this reviewed pin's metadata; this is not current source provenance or package-binary checksum verification."
        else
            log "ERROR: ${app_name:-App ID ${app_id}} version ${selected_version} is historical-review-only and cannot be reproduced from the current public Splunkbase release API."
            log "Refusing the entire batch before ACS mutation. Prefer --accept-unverified-release to review public latest, or pass --accept-historical-review-only-pin only after independent package/version approval."
            return 1
        fi
    fi
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
            if [[ "${evidence}" == "historical-review-only" ]]; then
                log "The historical reviewed pin has no reproducible current public release metadata; use --accept-unverified-release to review public latest."
            fi
            log "Refusing the entire batch before ACS mutation. Pass --accept-unsupported-platform only with documented vendor approval."
            return 1
        fi
    else
        log "Compatibility preflight passed: ${app_name:-app ID ${app_id}} version ${selected_version:-unknown} (${evidence}) advertises Splunk ${TARGET_SPLUNK_VERSION}."
    fi

    if [[ -z "${APP_VERSION}" && "${ACCEPT_UNVERIFIED_RELEASE}" != "true" && -n "${verified}" ]]; then
        if [[ "${verified_evidence_status}" == "historical-review-only-not-currently-reproducible" ]]; then
            log "App ID ${app_id}: historical-review-only version ${verified} selected; current public latest is ${release:-unknown}."
        elif [[ -n "${release}" && "${release}" != "${verified}" ]]; then
            log "App ID ${app_id}: using repo-verified version ${verified}; public latest ${release} remains unverified by this repo."
        else
            log "App ID ${app_id}: using repo-verified version ${verified}."
        fi
    elif [[ -z "${APP_VERSION}" && "${ACCEPT_UNVERIFIED_RELEASE}" == "true" ]]; then
        log "WARNING: App ID ${app_id}: registry-recorded public latest ${selected_version} is pinned without repository package-binary verification."
    fi
}

resolve_app_install_version() {
    local app_id="$1"
    if [[ -n "${APP_VERSION}" ]] && is_explicitly_requested_app_id "${app_id}"; then
        printf '%s' "${APP_VERSION}"
        return 0
    fi
    if [[ -f "${REGISTRY_FILE}" ]]; then
        python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == sys.argv[2]:
        field = 'latest_release_version' if sys.argv[3] == 'true' else 'latest_verified_version'
        print(app.get(field, ''), end='')
        break
" "${REGISTRY_FILE}" "${app_id}" "${ACCEPT_UNVERIFIED_RELEASE}" 2>/dev/null || true
    fi
}

is_explicitly_requested_app_id() {
    local target="$1" requested
    for requested in "${REQUESTED_APP_IDS[@]:-}"; do
        [[ "${target}" == "${requested}" ]] && return 0
    done
    return 1
}

ACS_APP_VERIFY_ATTEMPTS="${SPLUNK_ACS_APP_VERIFY_ATTEMPTS:-30}"
ACS_APP_VERIFY_INTERVAL="${SPLUNK_ACS_APP_VERIFY_INTERVAL:-5}"
ACS_STATE_FILE=""
RECOVERY_FILE=""
EXPECTED_VERSIONS=()
PRE_PRESENT=()
PRE_NAMES=()
PRE_VERSIONS=()
PRE_STATUSES=()
NEW_APP_IDS=()
NEW_APP_NAMES=()
NEW_APP_VERSIONS=()

validate_verify_settings() {
    if [[ ! "${ACS_APP_VERIFY_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
        log "ERROR: SPLUNK_ACS_APP_VERIFY_ATTEMPTS must be a positive integer."
        return 1
    fi
    if [[ ! "${ACS_APP_VERIFY_INTERVAL}" =~ ^[0-9]+$ ]]; then
        log "ERROR: SPLUNK_ACS_APP_VERIFY_INTERVAL must be a non-negative integer."
        return 1
    fi
}

cleanup_batch_state_file() {
    [[ -n "${ACS_STATE_FILE}" && -f "${ACS_STATE_FILE}" ]] && rm -f "${ACS_STATE_FILE}"
}
trap cleanup_batch_state_file EXIT

initialize_batch_evidence() {
    local recovery_dir="${SPLUNK_BATCH_RECOVERY_DIR:-${TMPDIR:-/tmp}}"
    if [[ ! -d "${recovery_dir}" || -L "${recovery_dir}" ]]; then
        log "ERROR: Recovery evidence directory must be an existing non-symlink directory: ${recovery_dir}"
        return 1
    fi
    umask 077
    ACS_STATE_FILE="$(mktemp "${recovery_dir%/}/splunk-cloud-batch-state.XXXXXX")" || return 1
    RECOVERY_FILE="$(mktemp "${recovery_dir%/}/splunk-cloud-batch-recovery.XXXXXX")" || return 1
    chmod 600 "${ACS_STATE_FILE}" "${RECOVERY_FILE}"
}

append_recovery_event() {
    local event="$1" app_id="${2:-}" app_name="${3:-}" expected_version="${4:-}"
    local observed_version="${5:-}" observed_status="${6:-}" detail="${7:-}"
    python3 - "${RECOVERY_FILE}" "${event}" "${app_id}" "${app_name}" \
        "${expected_version}" "${observed_version}" "${observed_status}" "${detail}" <<'PY'
import json
import sys
from datetime import datetime, timezone

path, event, app_id, app_name, expected, observed, status, detail = sys.argv[1:]
record = {
    "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "event": event,
    "splunkbase_id": app_id,
    "app_name": app_name,
    "expected_version": expected,
    "observed_version": observed,
    "observed_status": status,
    "detail": detail,
}
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True) + "\n")
PY
}

fetch_strict_acs_state() {
    local output_file="$1" offset=0 count=100 raw payload page_count
    printf '{"apps":[]}' > "${output_file}"
    while true; do
        if ! raw="$(acs_command apps list --splunkbase --count "${count}" --offset "${offset}" 2>/dev/null)"; then
            return 1
        fi
        [[ -n "${raw}" ]] || return 1
        payload="$(printf '%s' "${raw}" | acs_extract_http_response_json)" || return 1
        page_count="$(python3 - "${output_file}" 3<<<"${payload}" <<'PY'
import json
import os
import sys

output_path = sys.argv[1]
try:
    with os.fdopen(3, encoding="utf-8") as page_handle:
        page = json.load(page_handle)
    with open(output_path, encoding="utf-8") as handle:
        aggregate = json.load(handle)
except Exception:
    raise SystemExit(1)
if not isinstance(page, dict) or not isinstance(page.get("apps"), list):
    raise SystemExit(1)
if not isinstance(aggregate, dict) or not isinstance(aggregate.get("apps"), list):
    raise SystemExit(1)
aggregate["apps"].extend(page["apps"])
with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(aggregate, handle)
print(len(page["apps"]), end="")
PY
)" || return 1
        [[ "${page_count}" =~ ^[0-9]+$ ]] || return 1
        (( page_count < count )) && break
        offset=$((offset + count))
    done
}

refresh_acs_state() {
    local next_file="${ACS_STATE_FILE}.next"
    rm -f "${next_file}"
    if ! fetch_strict_acs_state "${next_file}"; then
        rm -f "${next_file}"
        return 1
    fi
    chmod 600 "${next_file}"
    mv -f "${next_file}" "${ACS_STATE_FILE}"
}

acs_identity_for_id() {
    local app_id="$1"
    python3 - "${ACS_STATE_FILE}" "${app_id}" <<'PY'
import json
import sys

path, target = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)

matches = []
for app in payload.get("apps", []):
    if not isinstance(app, dict):
        continue
    spec = app.get("spec") if isinstance(app.get("spec"), dict) else {}
    app_id = (
        app.get("splunkbaseID")
        or app.get("splunkbaseId")
        or app.get("splunkbase_id")
        or spec.get("splunkbaseID")
        or spec.get("splunkbaseId")
        or spec.get("splunkbase_id")
        or ""
    )
    if str(app_id) != target:
        continue
    name = app.get("name") or app.get("appID") or spec.get("name") or ""
    matches.append(str(name))

if not matches:
    raise SystemExit(3)
if len(matches) != 1 or not matches[0] or "\x1f" in matches[0]:
    raise SystemExit(2)
print(matches[0], end="")
PY
}

acs_describe_app_state() {
    local app_name="$1" raw payload
    if ! raw="$(acs_command apps describe "${app_name}" 2>/dev/null)"; then
        return 1
    fi
    payload="$(printf '%s' "${raw}" | acs_extract_http_response_json)" || return 1
    printf '%s' "${payload}" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
if isinstance(data, dict) and isinstance(data.get("app"), dict):
    data = data["app"]
if not isinstance(data, dict):
    raise SystemExit(1)
spec = data.get("spec") if isinstance(data.get("spec"), dict) else {}
name = data.get("name") or data.get("appID") or spec.get("name") or ""
version = data.get("version") or spec.get("version") or ""
status = data.get("status") or spec.get("status") or ""
values = [str(name), str(version), str(status)]
if not all(values) or any("\x1f" in value for value in values):
    raise SystemExit(1)
print("\x1f".join(values), end="")
'
}

is_terminal_app_status() {
    local normalized
    normalized="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
    case "${normalized}" in
        installed|updated|active|completed|complete|ready|enabled|success|succeeded) return 0 ;;
        *) return 1 ;;
    esac
}

lookup_live_app_state() {
    local app_id="$1" identity describe_state rc
    refresh_acs_state || return 1
    set +e
    identity="$(acs_identity_for_id "${app_id}")"
    rc=$?
    set -e
    (( rc == 0 )) || return "${rc}"
    describe_state="$(acs_describe_app_state "${identity}")" || return 1
    printf '%s' "${describe_state}"
}

verify_exact_terminal_app() {
    local app_id="$1" expected_version="$2" attempt=1 state rc
    local observed_name observed_version observed_status

    while (( attempt <= ACS_APP_VERIFY_ATTEMPTS )); do
        set +e
        state="$(lookup_live_app_state "${app_id}")"
        rc=$?
        set -e
        if (( rc == 0 )); then
            IFS=$'\x1f' read -r observed_name observed_version observed_status <<< "${state}"
            if [[ "${observed_version}" == "${expected_version}" ]] && is_terminal_app_status "${observed_status}"; then
                printf '%s' "${state}"
                return 0
            fi
            if is_terminal_app_status "${observed_status}" && [[ "${observed_version}" != "${expected_version}" ]]; then
                log "ERROR: ACS reports ${observed_name} version ${observed_version}, expected ${expected_version}." >&2
                return 1
            fi
            case "$(printf '%s' "${observed_status}" | tr '[:upper:]' '[:lower:]')" in
                pending|installing|updating|processing|queued|in_progress|in-progress) ;;
                *)
                    log "ERROR: ACS reports ambiguous non-terminal status '${observed_status}' for app ID ${app_id}." >&2
                    return 1
                    ;;
            esac
        elif (( rc == 2 )); then
            log "ERROR: ACS app identity for Splunkbase ID ${app_id} is ambiguous." >&2
            return 1
        elif (( rc != 3 )); then
            log "ERROR: ACS state for Splunkbase ID ${app_id} is unavailable." >&2
            return 1
        fi

        if (( attempt < ACS_APP_VERIFY_ATTEMPTS )); then
            (( ACS_APP_VERIFY_INTERVAL > 0 )) && sleep "${ACS_APP_VERIFY_INTERVAL}"
        fi
        attempt=$((attempt + 1))
    done
    log "ERROR: ACS did not prove app ID ${app_id} at exact version ${expected_version} within the verification window." >&2
    return 1
}

verify_app_absent() {
    local app_id="$1" attempt=1 identity rc
    while (( attempt <= ACS_APP_VERIFY_ATTEMPTS )); do
        refresh_acs_state || return 1
        set +e
        identity="$(acs_identity_for_id "${app_id}")"
        rc=$?
        set -e
        if (( rc == 3 )); then
            return 0
        fi
        if (( rc != 0 )); then
            return 1
        fi
        if (( attempt < ACS_APP_VERIFY_ATTEMPTS )); then
            (( ACS_APP_VERIFY_INTERVAL > 0 )) && sleep "${ACS_APP_VERIFY_INTERVAL}"
        fi
        attempt=$((attempt + 1))
    done
    log "ERROR: ACS still lists ${identity:-app ID ${app_id}} after compensating uninstall." >&2
    return 1
}

acs_output_has_status_code() {
    local raw="$1" expected="$2"
    printf '%s' "${raw}" | python3 -c '
import json
import sys

expected = sys.argv[1]
try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
items = data if isinstance(data, list) else [data]
for item in items:
    if not isinstance(item, dict):
        continue
    candidates = [item]
    response = item.get("response")
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except Exception:
            response = {}
    if isinstance(response, dict):
        candidates.append(response)
    for candidate in candidates:
        status = candidate.get("statusCode") or candidate.get("status_code") or candidate.get("status")
        if str(status) == expected:
            raise SystemExit(0)
raise SystemExit(1)
' "${expected}"
}

track_new_install() {
    local app_id="$1" app_name="$2" version="$3" existing i
    for i in "${!NEW_APP_IDS[@]}"; do
        existing="${NEW_APP_IDS[$i]}"
        [[ "${existing}" == "${app_id}" ]] && return 0
    done
    NEW_APP_IDS+=("${app_id}")
    NEW_APP_NAMES+=("${app_name}")
    NEW_APP_VERSIONS+=("${version}")
    append_recovery_event "installed-new" "${app_id}" "${app_name}" "${version}" "${version}" "installed" "eligible for reverse compensation"
}

capture_failed_operation_for_compensation() {
    local app_id="$1" expected_version="$2" state rc name version status
    set +e
    state="$(lookup_live_app_state "${app_id}")"
    rc=$?
    set -e
    (( rc == 0 )) || return 0
    IFS=$'\x1f' read -r name version status <<< "${state}"
    if [[ "${version}" == "${expected_version}" ]]; then
        track_new_install "${app_id}" "${name}" "${version}"
    fi
}

compensate_new_installs() {
    local i app_id app_name version output rc rollback_failures=0
    if (( ${#NEW_APP_IDS[@]} == 0 )); then
        log "No newly installed apps were proven safe for automatic compensation."
        return 0
    fi

    log "Attempting reverse compensating uninstall for newly installed apps..."
    for ((i=${#NEW_APP_IDS[@]} - 1; i>=0; i--)); do
        app_id="${NEW_APP_IDS[$i]}"
        app_name="${NEW_APP_NAMES[$i]}"
        version="${NEW_APP_VERSIONS[$i]}"
        log "  Rolling back ${app_name} (ID ${app_id}, version ${version})..."
        set +e
        if cloud_requires_local_scope; then
            output="$(acs_command apps uninstall "${app_name}" --scope local 2>&1)"
        else
            output="$(acs_command apps uninstall "${app_name}" 2>&1)"
        fi
        rc=$?
        set -e
        if (( rc != 0 )) && ! verify_app_absent "${app_id}"; then
            append_recovery_event "rollback-failed" "${app_id}" "${app_name}" "${version}" "" "" "ACS uninstall rc=${rc}"
            [[ -n "${output}" ]] && log "  ${output}"
            rollback_failures=$((rollback_failures + 1))
            continue
        fi
        if ! verify_app_absent "${app_id}"; then
            append_recovery_event "rollback-failed" "${app_id}" "${app_name}" "${version}" "" "" "absence could not be proven"
            rollback_failures=$((rollback_failures + 1))
            continue
        fi
        append_recovery_event "rollback-verified" "${app_id}" "${app_name}" "${version}" "" "absent" "ACS absence verified"
        log "  Rollback verified for ${app_name}."
    done
    (( rollback_failures == 0 ))
}

capture_initial_acs_snapshot() {
    local i app_id expected_version registry_name identity describe_state rc
    local observed_name observed_version observed_status

    if ! refresh_acs_state; then
        log "ERROR: ACS app inventory is unavailable; refusing the entire batch before mutation."
        return 1
    fi

    for i in "${!APP_IDS[@]}"; do
        app_id="${APP_IDS[$i]}"
        expected_version="$(resolve_app_install_version "${app_id}")"
        registry_name="$(resolve_app_name "${app_id}")"
        EXPECTED_VERSIONS[i]="${expected_version}"

        set +e
        identity="$(acs_identity_for_id "${app_id}")"
        rc=$?
        set -e
        if (( rc == 3 )); then
            PRE_PRESENT[i]="false"
            PRE_NAMES[i]="${registry_name}"
            PRE_VERSIONS[i]=""
            PRE_STATUSES[i]="absent"
            append_recovery_event "snapshot" "${app_id}" "${registry_name}" "${expected_version}" "" "absent" "not installed before batch"
            continue
        fi
        if (( rc != 0 )); then
            log "ERROR: ACS returned ambiguous identity state for Splunkbase ID ${app_id}; refusing mutation."
            return 1
        fi

        if ! describe_state="$(acs_describe_app_state "${identity}")"; then
            log "ERROR: ACS could not describe preexisting app '${identity}'; refusing mutation."
            return 1
        fi
        IFS=$'\x1f' read -r observed_name observed_version observed_status <<< "${describe_state}"
        if [[ "${observed_name}" != "${identity}" ]]; then
            log "ERROR: ACS list/describe identity mismatch for app ID ${app_id}: '${identity}' versus '${observed_name}'."
            return 1
        fi
        PRE_PRESENT[i]="true"
        PRE_NAMES[i]="${observed_name}"
        PRE_VERSIONS[i]="${observed_version}"
        PRE_STATUSES[i]="${observed_status}"
        append_recovery_event "snapshot" "${app_id}" "${observed_name}" "${expected_version}" "${observed_version}" "${observed_status}" "installed before batch"

        if ! is_terminal_app_status "${observed_status}"; then
            log "ERROR: Preexisting app '${observed_name}' has non-terminal or unknown ACS status '${observed_status}'."
            log "Refusing mutation until ACS reports an exact terminal state."
            return 1
        fi
        if [[ "${observed_version}" != "${expected_version}" ]]; then
            log "ERROR: Preexisting app '${observed_name}' is version ${observed_version}; batch requires exact version ${expected_version}."
            log "Refusing mutation. Use the individual app updater for reviewed version transitions."
            return 1
        fi
    done
}

REQUESTED_APP_IDS=("${APP_IDS[@]}")
expanded_output=""
if ! expanded_output="$(expand_dependency_app_ids)"; then
    log "ERROR: Dependency expansion failed; refusing the entire batch before ACS mutation."
    exit 1
fi

expanded_app_ids=()
while IFS= read -r expanded_id || [[ -n "${expanded_id}" ]]; do
    [[ -n "${expanded_id}" ]] || continue
    expanded_app_ids+=("${expanded_id}")
done <<< "${expanded_output}"

if (( ${#expanded_app_ids[@]} == 0 )); then
    log "ERROR: Dependency expansion returned no app IDs; refusing the entire batch before ACS mutation."
    exit 1
fi

APP_IDS=("${expanded_app_ids[@]}")

resolve_target_splunk_version || exit 1
for app_id in "${APP_IDS[@]}"; do
    selected_version="$(resolve_app_install_version "${app_id}")"
    preflight_app_compatibility "${app_id}" || exit 1
    if [[ -z "${selected_version}" ]] || ! validate_app_version "${selected_version}"; then
        log "ERROR: App ID ${app_id} did not resolve to a safe exact install version."
        log "Refusing the entire batch before ACS mutation."
        exit 1
    fi
done

require_registry_provenance || exit 1
acs_prepare_context || exit 1
validate_verify_settings || exit 1
initialize_batch_evidence || exit 1
if ! capture_initial_acs_snapshot; then
    rm -f "${RECOVERY_FILE}"
    RECOVERY_FILE=""
    exit 1
fi

log "=== Cloud Batch Install ==="
for i in "${!APP_IDS[@]}"; do
    log "App ID ${APP_IDS[$i]}: expected=${EXPECTED_VERSIONS[$i]}, preexisting=${PRE_PRESENT[$i]}, name=${PRE_NAMES[$i]:-unresolved}"
done
log ""

failures=0
failed_app_id=""
for i in "${!APP_IDS[@]}"; do
    app_id="${APP_IDS[$i]}"
    install_version="${EXPECTED_VERSIONS[$i]}"
    if [[ "${PRE_PRESENT[$i]}" == "true" ]]; then
        log "Skipping ${PRE_NAMES[$i]} (ID ${app_id}); exact version ${install_version} was already installed before the batch."
        append_recovery_event "already-satisfied" "${app_id}" "${PRE_NAMES[$i]}" "${install_version}" "${PRE_VERSIONS[$i]}" "${PRE_STATUSES[$i]}" "no mutation"
        continue
    fi

    log "Installing Splunkbase app ID ${app_id}..."
    warn_if_role_unsupported_for_app_id "${app_id}"

    license_ack="$(resolve_license_ack "${app_id}")"

    declare -a cmd=(apps install splunkbase --splunkbase-id "${app_id}")
    cmd+=(--version "${install_version}")
    [[ -n "${license_ack}" ]] && cmd+=(--acs-licensing-ack "${license_ack}")
    cloud_requires_local_scope && cmd+=(--scope local)

    set +e
    output=$(acs_command "${cmd[@]}" 2>&1)
    rc=$?
    set -e

    conflict=false
    if (( rc != 0 )); then
        if acs_output_has_status_code "${output}" "409"; then
            conflict=true
            log "  ACS returned 409 for app ID ${app_id}; exact live state must prove the request is already satisfied."
        else
            log "  ERROR: Failed to install app ID ${app_id} (rc=${rc})."
            [[ -n "${output}" ]] && log "  ${output}"
            append_recovery_event "install-failed" "${app_id}" "${PRE_NAMES[$i]}" "${install_version}" "" "" "ACS command rc=${rc}"
            capture_failed_operation_for_compensation "${app_id}" "${install_version}"
            failures=1
            failed_app_id="${app_id}"
            break
        fi
    fi

    if ! verified_state="$(verify_exact_terminal_app "${app_id}" "${install_version}")"; then
        log "  ERROR: Exact terminal ACS verification failed for app ID ${app_id}."
        append_recovery_event "verification-failed" "${app_id}" "${PRE_NAMES[$i]}" "${install_version}" "" "" "exact terminal state not proven"
        if [[ "${conflict}" != "true" ]]; then
            capture_failed_operation_for_compensation "${app_id}" "${install_version}"
        fi
        failures=1
        failed_app_id="${app_id}"
        break
    fi

    IFS=$'\x1f' read -r verified_name verified_version verified_status <<< "${verified_state}"
    if [[ "${conflict}" == "true" ]]; then
        append_recovery_event "conflict-satisfied" "${app_id}" "${verified_name}" "${install_version}" "${verified_version}" "${verified_status}" "409 accepted only after exact proof; not rollback-owned"
        log "  Exact version ${verified_version} is already installed as ${verified_name}; 409 accepted."
    else
        track_new_install "${app_id}" "${verified_name}" "${verified_version}"
        log "  Installed and verified ${verified_name} version ${verified_version} (${verified_status})."
    fi
done

if (( failures > 0 )); then
    log ""
    log "ERROR: Batch stopped at app ID ${failed_app_id}; no later app was mutated and no restart will be attempted."
    if compensate_new_installs; then
        append_recovery_event "batch-failed-compensated" "${failed_app_id}" "" "" "" "" "all rollback-owned installs are absent"
        log "Compensating rollback completed, but the requested batch did not complete."
    else
        append_recovery_event "batch-failed-recovery-required" "${failed_app_id}" "" "" "" "" "automatic compensation incomplete"
        log "ERROR: Automatic compensation was incomplete."
    fi
    log "Recovery evidence retained at ${RECOVERY_FILE} (mode 600)."
    exit 1
fi

if ${RESTART}; then
    log ""
    log "Checking if ACS restart is required..."
    if ! cloud_restart_if_required 900; then
        append_recovery_event "restart-failed" "" "" "" "" "" "all app versions verified before restart; stack readiness not proven"
        log "ERROR: ACS restart/readiness verification failed."
        log "Recovery evidence retained at ${RECOVERY_FILE} (mode 600)."
        exit 1
    fi
    log "Stack is Ready. Re-verifying exact app versions after restart..."
    for i in "${!APP_IDS[@]}"; do
        if ! verify_exact_terminal_app "${APP_IDS[$i]}" "${EXPECTED_VERSIONS[$i]}" >/dev/null; then
            append_recovery_event "post-restart-verification-failed" "${APP_IDS[$i]}" "" "${EXPECTED_VERSIONS[$i]}" "" "" "exact terminal state not proven"
            log "ERROR: Post-restart exact verification failed for app ID ${APP_IDS[$i]}."
            log "Recovery evidence retained at ${RECOVERY_FILE} (mode 600)."
            exit 1
        fi
    done
    log "=== Batch install complete: every requested app is at its exact version and the stack is Ready ==="
else
    log ""
    log "=== Batch app versions verified; restart intentionally deferred by --no-restart ==="
fi

append_recovery_event "batch-complete" "" "" "" "" "verified" "all exact versions proven"
rm -f "${RECOVERY_FILE}"
RECOVERY_FILE=""
