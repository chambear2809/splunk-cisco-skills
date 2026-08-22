#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/platform_version_helpers.sh"

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
PROJECT_TA_DIR="${SCRIPT_DIR}/../../../splunk-ta"
TA_CACHE="${TA_CACHE:-${PROJECT_TA_DIR}}"

SOURCE=""
APP_FILE=""
APP_URL=""
APP_ID=""
APP_VERSION=""
APP_PACKAGE_NAME=""
LICENSE_ACK_URL=""
EXPECTED_SHA256=""
UPDATE=false
UPDATE_SET=false
RESTART_SPLUNK=true
PRE_VETTED=false
TARGET_SPLUNK_VERSION="${SPLUNK_TARGET_VERSION:-}"
ACCEPT_UNSUPPORTED_PLATFORM="${SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM:-false}"
ACCEPT_UNVERIFIED_RELEASE="${SPLUNK_ACCEPT_UNVERIFIED_RELEASE:-false}"
ACCEPT_HISTORICAL_REVIEW_ONLY_PIN="${SPLUNK_ACCEPT_HISTORICAL_REVIEW_ONLY_PIN:-false}"
ACCEPT_NONPRODUCTION_PACKAGE="${SPLUNK_ACCEPT_NONPRODUCTION_PACKAGE:-false}"
CLOUD_APP_NAME=""
CLOUD_APP_VERSION=""
CLOUD_APP_STATUS=""

REGISTRY_FILE="${REGISTRY_FILE:-${SCRIPT_DIR}/../../../skills/shared/app_registry.json}"
REGISTRY_AUDIT="${SCRIPT_DIR}/../../shared/scripts/audit_splunkbase_registry.py"

is_interactive() { [[ -t 0 ]]; }

require_registry_provenance() {
    local audit_output
    if [[ ! -f "${REGISTRY_FILE}" ]]; then
        log "ERROR: Refusing installation before mutation: app registry is missing at ${REGISTRY_FILE}."
        return 1
    fi
    if [[ ! -x "${REGISTRY_AUDIT}" ]]; then
        log "ERROR: Refusing installation before mutation: registry provenance verifier is unavailable."
        return 1
    fi
    if ! audit_output="$(python3 "${REGISTRY_AUDIT}" --registry "${REGISTRY_FILE}" 2>&1)"; then
        log "ERROR: Refusing installation before mutation: Splunkbase registry provenance validation failed."
        [[ -n "${audit_output}" ]] && printf '%s\n' "${audit_output}" >&2
        return 1
    fi
}

validate_splunkbase_id() {
    local app_id="${1:-}"
    [[ "${app_id}" =~ ^[1-9][0-9]*$ ]]
}

validate_app_version() {
    local version="${1:-}"
    (( ${#version} <= 128 )) || return 1
    [[ "${version}" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]]
}

validate_expected_sha256() {
    [[ "${1:-}" =~ ^[A-Fa-f0-9]{64}$ ]]
}

list_package_files() {
    python3 - "$@" <<'PY'
import sys
from pathlib import Path

paths = []
seen = set()
for raw_dir in sys.argv[1:]:
    directory = Path(raw_dir)
    if not directory.is_dir():
        continue
    for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_file():
            continue
        name = child.name.lower()
        if not (name.endswith(".tgz") or name.endswith(".spl") or name.endswith(".tar.gz")):
            continue
        resolved = str(child.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        paths.append(resolved)

for path in paths:
    sys.stdout.buffer.write(path.encode("utf-8"))
    sys.stdout.buffer.write(b"\0")
PY
}

safe_read() {
    if ! is_interactive; then
        log "ERROR: Missing required value (would prompt for: $1) but stdin is not a terminal."
        log "Supply all values via flags/env vars for non-interactive use."
        exit 1
    fi
    shift
    read -r "$@"
}

cloud_known_splunkbase_metadata_from_package() {
    local package_name
    package_name="$(basename "${1:-}" | tr '[:upper:]' '[:lower:]')"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import json, sys, fnmatch

pkg = sys.argv[1]
with open(sys.argv[2]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    for pat in app.get('package_patterns', []):
        for ext in ('*.tar.gz', '*.tgz', '*.spl'):
            if fnmatch.fnmatch(pkg, pat.rstrip('*') + ext):
                sid = app.get('splunkbase_id', '')
                lic = app.get('license_ack_url', '')
                if sid:
                    print(f'{sid}|{lic}', end='')
                    raise SystemExit(0)
" "${package_name}" "${REGISTRY_FILE}" 2>/dev/null || true
}

cloud_known_license_ack_url_by_app_id() {
    local app_id="${1:-}"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import json, sys
target = sys.argv[1]
with open(sys.argv[2]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == target:
        print(app.get('license_ack_url', ''), end='')
        break
" "${app_id}" "${REGISTRY_FILE}" 2>/dev/null || true
}

registry_app_field_by_app_id() {
    local app_id="${1:-}"
    local field_name="${2:-}"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import json, sys
target = sys.argv[1]
field_name = sys.argv[2]
with open(sys.argv[3]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == target:
        value = app.get(field_name, '')
        if isinstance(value, list):
            print('\\n'.join(str(item) for item in value if str(item)), end='')
        else:
            print(str(value), end='')
        break
" "${app_id}" "${field_name}" "${REGISTRY_FILE}" 2>/dev/null || true
}

registry_install_requires_by_app_id() {
    registry_app_field_by_app_id "${1:-}" "install_requires"
}

registry_install_requires_by_package() {
    local package_name
    package_name="$(basename "${1:-}" | tr '[:upper:]' '[:lower:]')"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import json, sys, fnmatch
pkg = sys.argv[1]
with open(sys.argv[2]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    patterns = [str(p).lower() for p in app.get('package_patterns', [])]
    if any(fnmatch.fnmatch(pkg, pattern) for pattern in patterns):
        print('\\n'.join(str(item) for item in app.get('install_requires', []) if str(item)), end='')
        break
" "${package_name}" "${REGISTRY_FILE}" 2>/dev/null || true
}

registry_app_id_by_package() {
    local package_name
    package_name="$(basename "${1:-}" | tr '[:upper:]' '[:lower:]')"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import json, sys, fnmatch
pkg = sys.argv[1]
with open(sys.argv[2]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    patterns = [str(p).lower() for p in app.get('package_patterns', [])]
    if any(fnmatch.fnmatch(pkg, pattern) for pattern in patterns):
        print(str(app.get('splunkbase_id', '')), end='')
        break
" "${package_name}" "${REGISTRY_FILE}" 2>/dev/null || true
}

registry_app_name_by_app_id() {
    registry_app_field_by_app_id "${1:-}" "app_name"
}

registry_app_name_by_package() {
    local package_name
    package_name="$(basename "${1:-}" | tr '[:upper:]' '[:lower:]')"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import json, sys, fnmatch
pkg = sys.argv[1]
with open(sys.argv[2]) as f:
    registry = json.load(f)
for app in registry.get('apps', []):
    patterns = [str(p).lower() for p in app.get('package_patterns', [])]
    if any(fnmatch.fnmatch(pkg, pattern) for pattern in patterns):
        print(str(app.get('app_name', '')), end='')
        break
" "${package_name}" "${REGISTRY_FILE}" 2>/dev/null || true
}

registry_app_label_by_app_id() {
    registry_app_field_by_app_id "${1:-}" "label"
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
        if is_splunk_cloud; then
            raw="$(spv_cloud_doc_train_default)"
        else
            raw="$(spv_enterprise_default)"
        fi
    fi
    if ! TARGET_SPLUNK_VERSION="$(normalize_splunk_minor_version "${raw}")"; then
        log "ERROR: Target Splunk version '${raw}' must use MAJOR.MINOR or MAJOR.MINOR.PATCH."
        return 1
    fi
    export SPLUNK_TARGET_VERSION="${TARGET_SPLUNK_VERSION}"
    export SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM="${ACCEPT_UNSUPPORTED_PLATFORM}"
    export SPLUNK_ACCEPT_UNVERIFIED_RELEASE="${ACCEPT_UNVERIFIED_RELEASE}"
    export SPLUNK_ACCEPT_HISTORICAL_REVIEW_ONLY_PIN="${ACCEPT_HISTORICAL_REVIEW_ONLY_PIN}"
}

registry_app_compatibility_by_app_id() {
    local app_id="${1:-}"
    local target="${2:-}"
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
    status = "supported" if target_version in platforms else "unsupported"
    fields = (
        status,
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

apply_registry_verified_version_default() {
    local verified release evidence_status
    [[ "${SOURCE}" == "splunkbase" ]] || return 0
    [[ -n "${APP_ID}" && -z "${APP_VERSION}" ]] || return 0
    verified="$(registry_app_field_by_app_id "${APP_ID}" "latest_verified_version")"
    release="$(registry_app_field_by_app_id "${APP_ID}" "latest_release_version")"
    evidence_status="$(registry_app_field_by_app_id "${APP_ID}" "verified_release_evidence_status")"
    if [[ "${ACCEPT_UNVERIFIED_RELEASE}" == "true" && -n "${release}" ]]; then
        APP_VERSION="${release}"
        log "WARNING: Pinned registry-recorded public latest ${release} for app ID ${APP_ID}; repository evidence covers release metadata, not package-binary contents."
        return 0
    fi
    if [[ "${ACCEPT_UNVERIFIED_RELEASE}" == "true" ]]; then
        log "WARNING: Unknown app ID ${APP_ID} has no registry public-latest pin; an explicit --app-version is required."
        return 0
    fi
    if [[ -n "${verified}" ]]; then
        APP_VERSION="${verified}"
        if [[ "${evidence_status}" == "historical-review-only-not-currently-reproducible" ]]; then
            log "Selected historical-review-only version ${verified} for app ID ${APP_ID}; current public release API metadata cannot reproduce this pin."
        elif [[ -n "${release}" && "${release}" != "${verified}" ]]; then
            log "Using repo-verified version ${verified} for app ID ${APP_ID}; public latest ${release} remains unverified by this repo."
        else
            log "Using repo-verified version ${verified} for app ID ${APP_ID}."
        fi
    fi
}

preflight_current_install_target_compatibility() {
    local target_app_id metadata status app_name platforms verified release
    local selected_version evidence
    local cloud_compatible install_method_single install_method_distributed
    local verified_evidence_status production_status

    resolve_target_splunk_version || exit 1
    target_app_id="$(registry_target_app_id)"
    if [[ -z "${target_app_id}" ]]; then
        log "INFO: No registry app ID resolved; package compatibility with Splunk ${TARGET_SPLUNK_VERSION} must be verified separately."
        return 0
    fi

    selected_version="${APP_VERSION}"
    if [[ "${SOURCE}" != "splunkbase" && -z "${selected_version}" && "${TARGET_SPLUNK_VERSION}" == "10.5" ]]; then
        selected_version="__unknown_local_package__"
    fi
    metadata="$(registry_app_compatibility_by_app_id "${target_app_id}" "${TARGET_SPLUNK_VERSION}" "${selected_version}")"
    if [[ -z "${metadata}" ]]; then
        if [[ "${target_app_id}" =~ ^[0-9]+$ ]]; then
            if [[ "${ACCEPT_UNVERIFIED_RELEASE}" != "true" ]]; then
                log "ERROR: Numeric app ID ${target_app_id} is outside the provenance-bound registry."
                log "Refusing installation before mutation. Pass --accept-unverified-release only after independently reviewing the app identity and release."
                exit 1
            fi
            if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" != "true" ]]; then
                log "ERROR: Numeric app ID ${target_app_id} has no registry platform evidence for Splunk ${TARGET_SPLUNK_VERSION}."
                log "Refusing installation before mutation. After manual compatibility review, pass --accept-unsupported-platform as a separate approval."
                exit 1
            fi
            if [[ -z "${selected_version}" ]]; then
                log "ERROR: Unknown Splunkbase app ID ${target_app_id} requires an explicit --app-version."
                log "Refusing installation before mutation because a moving latest release cannot be verified exactly."
                exit 1
            fi
            log "WARNING: Explicit unverified-ID and manual platform approvals accepted for unknown Splunkbase app ID ${target_app_id}."
            return 0
        fi
        log "INFO: App ID ${target_app_id} is not a numeric Splunkbase ID; compatibility must be verified separately."
        return 0
    fi
    IFS='|' read -r status app_name platforms verified release selected_version evidence cloud_compatible \
        install_method_single install_method_distributed verified_evidence_status <<< "${metadata}"
    production_status="$(registry_app_field_by_app_id "${target_app_id}" "production_status")"
    if [[ "${production_status}" == "blocked" ]]; then
        if [[ "${ACCEPT_NONPRODUCTION_PACKAGE}" != "true" ]]; then
            log "ERROR: ${app_name:-App ID ${target_app_id}} is review-blocked for production use."
            log "Refusing installation before mutation. For isolated evaluation only, pass --accept-nonproduction-package."
            exit 1
        fi
        log "WARNING: Explicit nonproduction package approval accepted for ${app_name:-App ID ${target_app_id}}."
    fi
    if [[ "${selected_version}" == "${verified}" && "${verified_evidence_status}" == "historical-review-only-not-currently-reproducible" ]]; then
        if [[ "${ACCEPT_HISTORICAL_REVIEW_ONLY_PIN}" == "true" ]]; then
            log "WARNING: Explicit historical-review-only pin override accepted for ${app_name:-app ID ${target_app_id}} version ${selected_version}."
            log "WARNING: The current public Splunkbase release API cannot reproduce this reviewed pin's metadata; this is not current source provenance or package-binary checksum verification."
        else
            log "ERROR: ${app_name:-App ID ${target_app_id}} version ${selected_version} is historical-review-only and cannot be reproduced from the current public Splunkbase release API."
            log "Refusing installation before mutation. Prefer --accept-unverified-release to review public latest, or pass --accept-historical-review-only-pin only after independent package/version approval."
            exit 1
        fi
    fi
    if is_splunk_cloud && [[ "${cloud_compatible}" == "false" ]]; then
        if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" == "true" ]]; then
            log "WARNING: Explicit Cloud-placement override accepted for ${app_name:-app ID ${target_app_id}} even though Splunkbase marks cloud_compatible=false (single=${install_method_single:-unknown}, distributed=${install_method_distributed:-unknown})."
            log "WARNING: Proceed only with documented Splunk Support/vendor approval for this exact package and topology."
            export SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM=true
        else
            log "ERROR: ${app_name:-App ID ${target_app_id}} is explicitly cloud_compatible=false on Splunkbase."
            log "Cloud install methods: single=${install_method_single:-unknown}, distributed=${install_method_distributed:-unknown}."
            log "Refusing installation before Cloud mutation. Use a customer-managed runtime or pass --accept-unsupported-platform only with documented Splunk Support/vendor approval."
            exit 1
        fi
    fi
    if [[ "${status}" == "supported" ]]; then
        log "Compatibility preflight passed: ${app_name:-app ID ${target_app_id}} version ${selected_version:-unknown} (${evidence}) advertises Splunk ${TARGET_SPLUNK_VERSION}."
        return 0
    fi

    if [[ "${ACCEPT_UNSUPPORTED_PLATFORM}" == "true" ]]; then
        log "WARNING: Explicit override accepted for ${app_name:-app ID ${target_app_id}} version ${selected_version:-unknown} (${evidence}) on Splunk ${TARGET_SPLUNK_VERSION}; advertised versions: ${platforms:-none}."
        export SPLUNK_ACCEPT_UNSUPPORTED_PLATFORM=true
        return 0
    fi

    log "ERROR: ${app_name:-App ID ${target_app_id}} version ${selected_version:-unknown} (${evidence}) does not advertise Splunk ${TARGET_SPLUNK_VERSION} compatibility."
    log "Selected-release platform versions: ${platforms:-none}."
    if [[ "${evidence}" == "historical-review-only" ]]; then
        log "The historical reviewed pin has no reproducible current public release metadata; review public latest with --accept-unverified-release."
    elif [[ "${evidence}" == "unregistered-version" ]]; then
        log "Supply a registry-known --app-version or document an explicit compatibility exception."
    fi
    log "Refusing installation. Use a supported package/workflow, or pass --accept-unsupported-platform only with documented vendor approval."
    exit 1
}

guess_app_name_from_package() {
    local package_path="${1:-}"
    local app_id=""
    local app_name=""

    app_name="$(registry_app_name_by_package "${package_path}")"
    if [[ -n "${app_name}" ]]; then
        printf '%s' "${app_name}"
        return 0
    fi

    app_id="$(registry_app_id_by_package "${package_path}")"
    if [[ -n "${app_id}" ]]; then
        app_name="$(registry_app_name_by_app_id "${app_id}")"
        if [[ -n "${app_name}" ]]; then
            printf '%s' "${app_name}"
            return 0
        fi
    fi

    python3 - "${package_path}" <<'PY'
import sys
import tarfile

path = sys.argv[1]
try:
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            name = (member.name or "").lstrip("./")
            if not name:
                continue
            top_level = name.split("/", 1)[0]
            if top_level:
                print(top_level, end="")
                break
except Exception:
    pass
PY
}

PACKAGE_INSPECTED_NAME=""
PACKAGE_INSPECTED_VERSION=""

inspect_package_contract() {
    local package_path="$1" expected_name="${2:-}" expected_version="${3:-}" result
    if ! result="$(python3 - "${package_path}" "${expected_name}" "${expected_version}" <<'PY'
import configparser
import io
import re
import sys
import tarfile
from pathlib import PurePosixPath

archive_path, expected_name, expected_version = sys.argv[1:]
safe_name = re.compile(r"^[A-Za-z0-9_.-]+$")
safe_version = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")

try:
    archive = tarfile.open(archive_path, "r:*")
except Exception as exc:
    print(f"ERROR: Package is not a readable tar archive: {exc}", file=sys.stderr)
    raise SystemExit(1)

with archive:
    top_levels = set()
    app_conf_members = {}
    for member in archive.getmembers():
        raw_name = member.name or ""
        if not raw_name or "\x00" in raw_name or raw_name.startswith("/"):
            print("ERROR: Package contains an empty, absolute, or NUL-bearing path.", file=sys.stderr)
            raise SystemExit(1)
        normalized_name = raw_name
        while normalized_name.startswith("./"):
            normalized_name = normalized_name[2:]
        normalized_name = normalized_name.rstrip("/")
        raw_parts = normalized_name.split("/") if normalized_name else []
        path = PurePosixPath(normalized_name)
        if not raw_parts or any(part in ("", ".", "..") for part in raw_parts):
            print(f"ERROR: Package contains an unsafe path: {raw_name!r}", file=sys.stderr)
            raise SystemExit(1)
        top = path.parts[0]
        if top in {"__MACOSX", "pax_global_header"} or path.name == "@PaxHeader":
            continue
        top_levels.add(top)
        if member.issym() or member.islnk():
            link = PurePosixPath(member.linkname or "")
            if not member.linkname or member.linkname.startswith("/") or ".." in link.parts:
                print(f"ERROR: Package contains an unsafe link target: {member.linkname!r}", file=sys.stderr)
                raise SystemExit(1)
        if len(path.parts) == 3 and path.parts[1] in ("default", "local") and path.parts[2] == "app.conf":
            if not member.isfile() or member.size > 1024 * 1024:
                print("ERROR: Package app.conf must be a regular file no larger than 1 MiB.", file=sys.stderr)
                raise SystemExit(1)
            extracted = archive.extractfile(member)
            if extracted is None:
                print("ERROR: Package app.conf could not be read.", file=sys.stderr)
                raise SystemExit(1)
            app_conf_members[path.parts[1]] = extracted.read().decode("utf-8", errors="strict")

if len(top_levels) != 1:
    print(f"ERROR: Package must contain exactly one top-level Splunk app directory; found {sorted(top_levels)!r}.", file=sys.stderr)
    raise SystemExit(1)

top_level = next(iter(top_levels))
if not safe_name.fullmatch(top_level):
    print(f"ERROR: Package top-level app directory is unsafe: {top_level!r}.", file=sys.stderr)
    raise SystemExit(1)
if expected_name and top_level != expected_name:
    print(f"ERROR: Package app identity {top_level!r} does not match expected {expected_name!r}.", file=sys.stderr)
    raise SystemExit(1)
if "default" not in app_conf_members:
    print("ERROR: Package is missing default/app.conf.", file=sys.stderr)
    raise SystemExit(1)

parsed = {}
for layer in ("default", "local"):
    text = app_conf_members.get(layer)
    if text is None:
        continue
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str.lower
    try:
        parser.read_file(io.StringIO(text))
    except Exception as exc:
        print(f"ERROR: Package {layer}/app.conf is invalid: {exc}", file=sys.stderr)
        raise SystemExit(1)
    package_id = parser.get("package", "id", fallback="").strip()
    version = parser.get("launcher", "version", fallback="").strip()
    if package_id:
        parsed["package_id"] = package_id
    if version:
        parsed["version"] = version

package_id = parsed.get("package_id", "")
version = parsed.get("version", "")
if package_id and (not safe_name.fullmatch(package_id) or package_id != top_level):
    print(f"ERROR: Package [package] id {package_id!r} does not match top-level app directory {top_level!r}.", file=sys.stderr)
    raise SystemExit(1)
if not version or not safe_version.fullmatch(version):
    print("ERROR: Package must declare a safe [launcher] version in app.conf.", file=sys.stderr)
    raise SystemExit(1)
if expected_version and version != expected_version:
    print(f"ERROR: Package version {version!r} does not match expected {expected_version!r}.", file=sys.stderr)
    raise SystemExit(1)

print("\x1f".join((top_level, version)), end="")
PY
)"; then
        log "ERROR: Package identity/version inspection failed for ${package_path}."
        return 1
    fi
    IFS=$'\x1f' read -r PACKAGE_INSPECTED_NAME PACKAGE_INSPECTED_VERSION <<< "${result}"
    if [[ -z "${PACKAGE_INSPECTED_NAME}" || -z "${PACKAGE_INSPECTED_VERSION}" ]]; then
        log "ERROR: Package inspection did not return an exact app identity and version."
        return 1
    fi
    log "Verified package contract: ${PACKAGE_INSPECTED_NAME} version ${PACKAGE_INSPECTED_VERSION}."
}

prepare_exact_package_contract() {
    local target_app_id expected_name
    [[ -n "${APP_FILE}" && -f "${APP_FILE}" ]] || {
        log "ERROR: Package file is unavailable for pre-install identity/version inspection."
        return 1
    }
    target_app_id="$(registry_target_app_id)"
    expected_name=""
    if [[ -n "${target_app_id}" ]]; then
        expected_name="$(registry_app_name_by_app_id "${target_app_id}")"
    fi
    inspect_package_contract "${APP_FILE}" "${expected_name}" "${APP_VERSION}" || return 1
    if [[ -n "${EXPECTED_SHA256}" ]]; then
        local actual_sha expected_sha
        actual_sha="$(hbs_sha256_file "${APP_FILE}")"
        expected_sha="$(printf '%s' "${EXPECTED_SHA256}" | tr '[:upper:]' '[:lower:]')"
        if [[ "${actual_sha}" != "${expected_sha}" ]]; then
            log "ERROR: SHA-256 mismatch for local package ${APP_FILE}."
            log "       expected: ${expected_sha}"
            log "       actual:   ${actual_sha:-<could not compute>}"
            return 1
        fi
        log "Verified operator-provided SHA-256 ${actual_sha} for local package."
    fi
    APP_VERSION="${PACKAGE_INSPECTED_VERSION}"
    if [[ -z "${APP_ID}" && -n "${target_app_id}" ]]; then
        APP_ID="${target_app_id}"
    fi
}

preflight_unknown_explicit_app_id() {
    [[ -n "${APP_ID}" ]] || return 0
    [[ -z "$(registry_app_name_by_app_id "${APP_ID}")" ]] || return 0
    preflight_current_install_target_compatibility
}

registry_local_package_for_app_id() {
    local app_id="${1:-}"
    [[ -f "${REGISTRY_FILE}" ]] || return 0
    python3 -c "
import fnmatch
import json
import re
import sys
from pathlib import Path

registry_path = sys.argv[1]
target = sys.argv[2]
search_dirs = [Path(raw) for raw in sys.argv[3:] if raw]

def package_version(name):
    lowered = name.lower()
    for suffix in ('.tar.gz', '.tgz', '.spl'):
        if lowered.endswith(suffix):
            name = name[:-len(suffix)]
            break
    matches = re.findall(r'\d+(?:\.\d+)+', name)
    if not matches:
        return None
    return tuple(int(part) for part in matches[-1].split('.'))

with open(registry_path) as f:
    registry = json.load(f)

patterns = []
for app in registry.get('apps', []):
    if str(app.get('splunkbase_id', '')) == target:
        patterns = [str(p).lower() for p in app.get('package_patterns', [])]
        break

if not patterns:
    raise SystemExit(0)

candidates = []
for directory in search_dirs:
    if not directory.is_dir():
        continue
    for child in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_file():
            continue
        name = child.name.lower()
        if not (name.endswith('.tgz') or name.endswith('.spl') or name.endswith('.tar.gz')):
            continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
            version = package_version(child.name)
            candidates.append(
                (
                    version is not None,
                    version or (),
                    child.stat().st_mtime_ns,
                    child.name.lower(),
                    str(child.resolve()),
                )
            )

if not candidates:
    raise SystemExit(0)

print(max(candidates)[-1], end='')
" "${REGISTRY_FILE}" "${app_id}" "${PROJECT_TA_DIR}" "${TA_CACHE}" 2>/dev/null || true
}

registry_target_app_id() {
    if [[ -n "${APP_ID}" ]]; then
        printf '%s' "${APP_ID}"
        return 0
    fi
    if [[ -n "${APP_FILE}" ]]; then
        registry_app_id_by_package "${APP_FILE}"
    fi
}

registry_dependency_app_ids_for_current_target() {
    if [[ -n "${APP_ID}" ]]; then
        registry_install_requires_by_app_id "${APP_ID}"
        return 0
    fi
    if [[ -n "${APP_FILE}" ]]; then
        registry_install_requires_by_package "${APP_FILE}"
    fi
}

warn_for_current_install_target_role() {
    local target_app_id

    target_app_id="$(registry_target_app_id)"
    if [[ -n "${target_app_id}" ]]; then
        warn_if_role_unsupported_for_app_id "${target_app_id}"
    elif [[ -n "$(resolve_splunk_target_role)" ]]; then
        log "INFO: No deployment-role metadata found for the requested package. Continuing without role-aware checks."
    fi
}

dependency_install_chain_contains() {
    local app_id="${1:-}"
    case ",${SPLUNK_INSTALL_CHAIN:-}," in
        *",${app_id},"*) return 0 ;;
        *) return 1 ;;
    esac
}

install_dependency_with_current_script() {
    local dep_id="${1:-}"
    local dep_name dep_label dep_package current_target_id chain
    local -a cmd

    [[ -n "${dep_id}" ]] || return 0

    dep_name="$(registry_app_name_by_app_id "${dep_id}")"
    dep_label="$(registry_app_label_by_app_id "${dep_id}")"
    [[ -z "${dep_label}" ]] && dep_label="${dep_name:-Splunkbase app ID ${dep_id}}"

    warn_if_role_unsupported_for_app_id "${dep_id}"

    if dependency_install_chain_contains "${dep_id}"; then
        log "Skipping required companion app ${dep_label} (${dep_id}) because it is already in the install chain."
        return 0
    fi

    if is_splunk_cloud; then
        if [[ -n "$(cloud_resolve_splunkbase_app_name "${dep_id}" || true)" ]]; then
            log "Required companion app ${dep_label} (${dep_id}) is already installed."
            return 0
        fi
    else
        if [[ -n "${dep_name}" ]] && rest_check_app "$SK" "$SPLUNK_URI" "${dep_name}" 2>/dev/null; then
            log "Required companion app ${dep_label} (${dep_id}) is already installed."
            return 0
        fi
    fi

    dep_package="$(registry_local_package_for_app_id "${dep_id}")"
    cmd=(bash "$0")
    if [[ -n "${dep_package}" ]]; then
        log "Installing required companion app ${dep_label} from ${dep_package} before continuing."
        cmd+=(--source local --file "${dep_package}")
    else
        log "Installing required companion app ${dep_label} from Splunkbase (app ID ${dep_id}) before continuing."
        cmd+=(--source splunkbase --app-id "${dep_id}")
    fi

    cmd+=(--no-update --no-restart)

    current_target_id="$(registry_target_app_id)"
    chain="${SPLUNK_INSTALL_CHAIN:-}"
    if [[ -n "${current_target_id}" ]] && ! dependency_install_chain_contains "${current_target_id}"; then
        chain="${chain:+${chain},}${current_target_id}"
    fi
    chain="${chain:+${chain},}${dep_id}"

    if ! SPLUNK_INSTALL_CHAIN="${chain}" "${cmd[@]}"; then
        log "ERROR: Failed to install required companion app ${dep_label} (${dep_id})."
        exit 1
    fi
}

install_required_dependencies() {
    local dep_id
    while IFS= read -r dep_id || [[ -n "${dep_id}" ]]; do
        [[ -n "${dep_id}" ]] || continue
        install_dependency_with_current_script "${dep_id}"
    done < <(registry_dependency_app_ids_for_current_target)
}

cloud_apply_known_splunkbase_defaults() {
    local default_license
    default_license="$(cloud_known_license_ack_url_by_app_id "${APP_ID}")"
    if [[ -z "${LICENSE_ACK_URL}" && -n "${default_license}" ]]; then
        LICENSE_ACK_URL="${default_license}"
    fi
}

cloud_prefer_splunkbase_for_known_package() {
    local package_path="$1"
    local metadata known_app_id default_license

    metadata="$(cloud_known_splunkbase_metadata_from_package "${package_path}")"
    [[ -n "${metadata}" ]] || return 0

    if [[ -n "${EXPECTED_SHA256}" ]]; then
        log "Checksum-pinned local package detected for Splunk Cloud; preserving the exact verified archive."
        return 0
    fi

    IFS='|' read -r known_app_id default_license <<< "${metadata}"
    APP_ID="${known_app_id}"
    [[ -z "${LICENSE_ACK_URL}" ]] && LICENSE_ACK_URL="${default_license}"
    APP_FILE=""
    APP_URL=""
    SOURCE="splunkbase"

    if [[ -n "${APP_VERSION}" ]]; then
        log "Known Splunkbase package detected for Splunk Cloud; switching to ACS Splunkbase install for app ID ${APP_ID} version ${APP_VERSION}."
    else
        log "Known Splunkbase package detected for Splunk Cloud; switching to ACS Splunkbase install for the registry-selected version (app ID ${APP_ID})."
    fi
}

# Accept flags for non-interactive use; anything missing gets prompted
while [[ $# -gt 0 ]]; do
    case "$1" in
        --source) require_arg "$1" $# || exit 1;       SOURCE="$2";      shift 2 ;;
        --file) require_arg "$1" $# || exit 1;         APP_FILE="$2";     shift 2 ;;
        --url) require_arg "$1" $# || exit 1;          APP_URL="$2";      shift 2 ;;
        --expected-sha256) require_arg "$1" $# || exit 1; EXPECTED_SHA256="$2"; shift 2 ;;
        --app-id) require_arg "$1" $# || exit 1;       APP_ID="$2";       shift 2 ;;
        --app-version) require_arg "$1" $# || exit 1;  APP_VERSION="$2";  shift 2 ;;
        --license-ack-url) require_arg "$1" $# || exit 1; LICENSE_ACK_URL="$2"; shift 2 ;;
        --update)       UPDATE=true;  UPDATE_SET=true;  shift ;;
        --no-update)    UPDATE=false; UPDATE_SET=true;  shift ;;
        --no-restart)   RESTART_SPLUNK=false; shift ;;
        --pre-vetted)   PRE_VETTED=true; shift ;;
        --target-splunk-version) require_arg "$1" $# || exit 1; TARGET_SPLUNK_VERSION="$2"; shift 2 ;;
        --accept-unsupported-platform) ACCEPT_UNSUPPORTED_PLATFORM=true; shift ;;
        --accept-unverified-release) ACCEPT_UNVERIFIED_RELEASE=true; shift ;;
        --accept-historical-review-only-pin) ACCEPT_HISTORICAL_REVIEW_ONLY_PIN=true; shift ;;
        --accept-nonproduction-package) ACCEPT_NONPRODUCTION_PACKAGE=true; shift ;;
        --help)
            cat <<EOF
Splunk App Installer (interactive)

Usage: $(basename "$0") [OPTIONS]

All values are prompted interactively when not supplied via flags or env vars.
When stdin is not a terminal, all required values must be provided via flags/env.

Optional flags (skip the corresponding prompt):
  --source local|remote|splunkbase
  --file PATH           Local app file path
  --url URL             Remote download URL
  --expected-sha256 HEX 64-char package SHA-256; required for URL downloads and
                        required before a cached Splunkbase archive may be reused.
  --app-id ID           Splunkbase app ID
  --app-version VER     Pin a specific Splunkbase version (default: repo-verified
                        version for known apps)
  --license-ack-url URL Third-party Splunkbase license URL for ACS installs
  --update              Upgrade mode
  --no-update           Fresh install (skip upgrade prompt)
  --no-restart          Skip the automatic restart after install
  --pre-vetted          Skip ACS app inspection for pre-vetted private apps
  --target-splunk-version VER
                        Compatibility target (MAJOR.MINOR[.PATCH]); defaults to the
                        shared Cloud or Enterprise platform contract.
  --accept-unsupported-platform
                        Override a known registry incompatibility only with documented
                        vendor/operator approval.
  --accept-unverified-release
                        For a known app, pin the registry-recorded public latest instead of
                        the repo-verified version. For an unknown numeric ID, acknowledge
                        independent identity/release review; --app-version is also required.
  --accept-historical-review-only-pin
                        Permit a reviewed older pin that the current public release API no
                        longer returns. Requires independent package/version approval and
                        does not verify package-binary contents or checksums.
  --accept-nonproduction-package
                        Permit a registry review-blocked package for isolated evaluation only.

Credentials and remote host settings are read from the project-root credentials file automatically.
For Splunk Cloud installs, configure ACS access. If one credentials file contains
both Cloud and Enterprise targets, interactive runs will prompt when needed, or
you can override with SPLUNK_PLATFORM=cloud or SPLUNK_PLATFORM=enterprise.
For Enterprise search-tier REST access, set SPLUNK_SEARCH_API_URI when targeting
non-localhost (legacy alias: SPLUNK_URI).
For remote Enterprise local-package installs, the script stages the package over
SSH and then installs it through the management API using filename=true.
Configure SPLUNK_SSH_HOST/SPLUNK_SSH_USER/SPLUNK_SSH_PASS for remote installs.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
            exit 0 ;;
        *) log "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -n "${APP_VERSION}" ]] && ! validate_app_version "${APP_VERSION}"; then
    log "ERROR: --app-version must be 1-128 characters using only letters, digits, '.', '_', '+', or '-'."
    exit 1
fi
if [[ -n "${APP_ID}" ]]; then
    if [[ "${APP_ID}" =~ splunkbase\.splunk\.com/app/([0-9]+) ]]; then
        APP_ID="${BASH_REMATCH[1]}"
    fi
    if ! validate_splunkbase_id "${APP_ID}"; then
        log "ERROR: --app-id must be a positive numeric Splunkbase ID or a Splunkbase app URL."
        exit 1
    fi
fi
if [[ -n "${EXPECTED_SHA256}" ]] && ! validate_expected_sha256 "${EXPECTED_SHA256}"; then
    log "ERROR: --expected-sha256 must be a 64-character hexadecimal SHA-256 digest."
    exit 1
fi

# ── Prompt helpers ──────────────────────────────────────────────────

prompt_source() {
    local choice=""
    [[ -n "${SOURCE}" ]] && return
    if ! is_interactive; then
        SOURCE="splunkbase"
        return
    fi
    echo ""
    echo "How do you want to install the app?"
    echo "  1) Splunkbase        — use the repo-verified release for known apps (default)"
    echo "  2) Local             — .tgz/.spl file on this server or in the project"
    echo "  3) Remote            — download from a remote URL"
    echo ""
    safe_read "--source" -rp "Select source [1/2/3] (default: 1): " choice
    case "${choice}" in
        ""|1|splunkbase)        SOURCE="splunkbase" ;;
        2|local)                SOURCE="local" ;;
        3|remote|url)           SOURCE="remote" ;;
        *) log "ERROR: Invalid choice '${choice}'"; exit 1 ;;
    esac
}

prompt_local_file() {
    local choice=""
    [[ -n "${APP_FILE}" ]] && return
    echo ""

    local files=()
    local search_dirs=()

    [[ -d "${PROJECT_TA_DIR}" ]] && search_dirs+=("${PROJECT_TA_DIR}")
    if [[ "${TA_CACHE}" != "${PROJECT_TA_DIR}" && -d "${TA_CACHE}" ]]; then
        search_dirs+=("${TA_CACHE}")
    fi

    while IFS= read -r -d '' f; do
        files+=("$f")
    done < <(list_package_files "${search_dirs[@]}")

    if [[ ${#files[@]} -gt 0 ]]; then
        echo "Available packages:"
        for i in "${!files[@]}"; do
            local fname size src_label
            fname=$(basename "${files[$i]}")
            size=$(stat -c%s "${files[$i]}" 2>/dev/null || stat -f%z "${files[$i]}" 2>/dev/null || echo "?")
            src_label=$(dirname "${files[$i]}")
            printf "  %d) %s  (%s bytes)  [%s]\n" $((i + 1)) "${fname}" "${size}" "${src_label}"
        done
        echo ""
        safe_read "--file" -rp "Select a number, or enter a full file path: " choice

        if [[ "${choice}" =~ ^[0-9]+$ ]] && [[ "${choice}" -ge 1 ]] && [[ "${choice}" -le ${#files[@]} ]]; then
            APP_FILE="${files[$((choice - 1))]}"
        else
            APP_FILE="${choice}"
        fi
    else
        echo "No .tgz/.spl files found in the project splunk-ta/ directory"
        if [[ "${TA_CACHE}" != "${PROJECT_TA_DIR}" ]]; then
            echo "or the configured TA cache: ${TA_CACHE}/"
        fi
        safe_read "--file" -rp "Enter full path to the app package: " APP_FILE
    fi

    if [[ -z "${APP_FILE}" ]]; then
        log "ERROR: No file specified"
        exit 1
    fi
}

prompt_url() {
    [[ -n "${APP_URL}" ]] && return
    echo ""
    safe_read "--url" -rp "Enter the download URL: " APP_URL
    if [[ -z "${APP_URL}" ]]; then
        log "ERROR: No URL specified"
        exit 1
    fi
}

prompt_splunkbase() {
    if [[ -z "${APP_ID}" ]]; then
        echo ""
        echo "Find the app ID in the Splunkbase URL: https://splunkbase.splunk.com/app/<ID>"
        safe_read "--app-id" -rp "Splunkbase app ID or full URL: " APP_ID
        if [[ -z "${APP_ID}" ]]; then
            log "ERROR: No app ID specified"
            exit 1
        fi
    fi
    # Allow full Splunkbase URL: extract numeric app ID (e.g. 7777 from .../app/7777 or .../app/7777/)
    if [[ "${APP_ID}" =~ splunkbase\.splunk\.com/app/([0-9]+) ]]; then
        APP_ID="${BASH_REMATCH[1]}"
        log "Using app ID: ${APP_ID}"
    fi

    if ! validate_splunkbase_id "${APP_ID}"; then
        log "ERROR: Splunkbase app ID '${APP_ID}' must be a positive numeric ID."
        exit 1
    fi

    cloud_apply_known_splunkbase_defaults
}

prompt_update() {
    local yn=""
    $UPDATE_SET && return
    echo ""
    safe_read "--update or --no-update" -rp "Is this an upgrade of an existing app? [y/N]: " yn
    case "${yn}" in
        [yY]|[yY][eE][sS]) UPDATE=true ;;
        *) UPDATE=false ;;
    esac
}

prompt_splunk_creds() {
    load_splunk_credentials
}

prompt_splunkbase_creds() {
    load_splunkbase_credentials
}

# ── Core functions ──────────────────────────────────────────────────

splunk_auth() {
    if [[ -n "${SPLUNK_SESSION_KEY:-}" ]]; then
        SK="${SPLUNK_SESSION_KEY}"
        log "Authenticated to Splunk REST API with provided session key"
        return 0
    fi
    SK=$(get_session_key "${SPLUNK_URI}")
    log "Authenticated to Splunk REST API"
}

splunkbase_auth() {
    if ! get_splunkbase_session; then
        log "ERROR: Failed to authenticate to Splunkbase. Check your splunk.com credentials."
        log "Hint: Use your splunk.com username (email) and password."
        exit 1
    fi
    log "Authenticated to Splunkbase"
}

restart_splunk_or_exit() {
    : "${RESTART_SPLUNK}"  # Consumed by app_restart_splunk_or_exit.
    app_restart_splunk_or_exit "${SK}" "${SPLUNK_URI}" "$1" \
        "Restart manually before using the updated app." || exit 1
}

cloud_restart_or_exit() {
    : "${RESTART_SPLUNK}"  # Consumed by cloud_app_restart_or_exit.
    cloud_app_restart_or_exit "$1" \
        "Run 'acs status current-stack' and restart if required before using the updated app." || exit 1
}

cloud_resolve_splunkbase_app_name() {
    local splunkbase_id="$1"
    acs_prepare_context || return 1
    acs_apps_list_all_json --splunkbase \
        | acs_extract_http_response_json \
        | python3 -c "
import json, sys
target = str(sys.argv[1])
try:
    data = json.load(sys.stdin)
    for app in data.get('apps', []):
        if str(app.get('splunkbaseID', '')) == target:
            print(app.get('name', ''), end='')
            break
except Exception:
    pass
" "${splunkbase_id}"
}

cloud_install_private_app() {
    local file_path="$1"
    local -a cmd=(apps install private --acs-legal-ack Y --app-package "${file_path}")
    local response app_name version status rc

    acs_prepare_context || exit 1
    ${PRE_VETTED} && cmd+=(--pre-vetted)
    cloud_requires_local_scope && cmd+=(--scope local)

    log "Installing private app package $(basename "${file_path}") to Splunk Cloud via ACS..."
    set +e
    response=$(acs_command "${cmd[@]}" 2>&1)
    rc=$?
    set -e
    if (( rc != 0 )); then
        if [[ "${response}" == *"App id conflict with Splunkbase App id"* ]]; then
            log "ERROR: ACS rejected this package because it maps to a Splunkbase app. Use --source splunkbase or let the installer auto-switch for known packages."
        else
            log "ERROR: ACS private app install failed."
        fi
        [[ -n "${response}" ]] && printf '%s\n' "${response}"
        exit 1
    fi

    IFS='|' read -r app_name version status <<< "$(printf '%s' "${response}" \
        | acs_extract_http_response_json \
        | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print('|'.join(str(value or '') for value in (
        data.get('name') or data.get('appID', ''),
        data.get('version', ''),
        data.get('status', ''),
    )))
except Exception:
    print('||')
")"

    CLOUD_APP_NAME="${app_name}"
    CLOUD_APP_VERSION="${version}"
    CLOUD_APP_STATUS="${status}"
    if [[ -n "${app_name}" ]]; then
        log "ACS accepted the private app install request for '${app_name}'."
    else
        log "ACS accepted the private app install request."
    fi
}

cloud_install_splunkbase_app() {
    local -a cmd
    local response app_name version status installed_name rc

    acs_prepare_context || exit 1
    cloud_apply_known_splunkbase_defaults

    if ${UPDATE}; then
        installed_name="$(cloud_resolve_splunkbase_app_name "${APP_ID}" || true)"
        if [[ -n "${installed_name}" ]]; then
            cmd=(apps update "${installed_name}")
            [[ -n "${APP_VERSION}" ]] && cmd+=(--version "${APP_VERSION}")
            [[ -n "${LICENSE_ACK_URL}" ]] && cmd+=(--acs-licensing-ack "${LICENSE_ACK_URL}")
            log "Updating Splunkbase app ${installed_name} (Splunkbase ID ${APP_ID}) via ACS..."
        else
            log "No installed Splunkbase app found for ID ${APP_ID}; performing a fresh install instead."
            cmd=(apps install splunkbase --splunkbase-id "${APP_ID}")
            [[ -n "${APP_VERSION}" ]] && cmd+=(--version "${APP_VERSION}")
            [[ -n "${LICENSE_ACK_URL}" ]] && cmd+=(--acs-licensing-ack "${LICENSE_ACK_URL}")
            cloud_requires_local_scope && cmd+=(--scope local)
            log "Installing Splunkbase app ID ${APP_ID} via ACS..."
        fi
    else
        cmd=(apps install splunkbase --splunkbase-id "${APP_ID}")
        [[ -n "${APP_VERSION}" ]] && cmd+=(--version "${APP_VERSION}")
        [[ -n "${LICENSE_ACK_URL}" ]] && cmd+=(--acs-licensing-ack "${LICENSE_ACK_URL}")
        cloud_requires_local_scope && cmd+=(--scope local)
        log "Installing Splunkbase app ID ${APP_ID} via ACS..."
    fi

    set +e
    response=$(acs_command "${cmd[@]}" 2>&1)
    rc=$?
    set -e
    if (( rc != 0 )); then
        log "ERROR: ACS Splunkbase app operation failed."
        [[ -n "${response}" ]] && printf '%s\n' "${response}"
        exit 1
    fi

    IFS='|' read -r app_name version status <<< "$(printf '%s' "${response}" \
        | acs_extract_http_response_json \
        | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    print('|'.join(str(value or '') for value in (
        data.get('name') or data.get('appID', ''),
        data.get('version', ''),
        data.get('status', ''),
    )))
except Exception:
    print('||')
")"

    if [[ -z "${app_name}" ]]; then
        app_name="$(cloud_resolve_splunkbase_app_name "${APP_ID}" || true)"
    fi
    CLOUD_APP_NAME="${app_name}"
    CLOUD_APP_VERSION="${version}"
    CLOUD_APP_STATUS="${status}"
    if [[ -n "${app_name}" ]]; then
        log "ACS accepted the Splunkbase app operation for '${app_name}'."
    else
        log "ACS accepted the Splunkbase app operation."
    fi
}

cloud_verify_exact_app_state() {
    local app_name="$1" expected_version="$2"
    local attempts="${SPLUNK_ACS_APP_VERIFY_ATTEMPTS:-30}"
    local interval="${SPLUNK_ACS_APP_VERIFY_INTERVAL:-5}"
    local attempt=1 raw describe_json metadata name version status normalized

    [[ "${attempts}" =~ ^[1-9][0-9]*$ ]] || {
        log "ERROR: SPLUNK_ACS_APP_VERIFY_ATTEMPTS must be a positive integer."
        return 1
    }
    [[ "${interval}" =~ ^[0-9]+$ ]] || {
        log "ERROR: SPLUNK_ACS_APP_VERIFY_INTERVAL must be a non-negative integer."
        return 1
    }
    [[ -n "${expected_version}" ]] || {
        log "ERROR: Exact expected version is required for Cloud post-install verification."
        return 1
    }

    while (( attempt <= attempts )); do
        raw="$(acs_command apps describe "${app_name}" 2>/dev/null || true)"
        describe_json="$(printf '%s' "${raw}" | acs_extract_http_response_json)"
        metadata="$(printf '%s' "${describe_json}" | python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
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
' 2>/dev/null || true)"
        if [[ -n "${metadata}" ]]; then
            IFS=$'\x1f' read -r name version status <<< "${metadata}"
            normalized="$(printf '%s' "${status}" | tr '[:upper:]' '[:lower:]')"
            case "${normalized}" in
                installed|updated|active|completed|complete|ready|enabled|success|succeeded)
                    if [[ "${version}" != "${expected_version}" ]]; then
                        log "ERROR: ACS reports app '${name}' at version '${version}', expected exact version '${expected_version}'."
                        return 1
                    fi
                    printf '%s' "${metadata}"
                    return 0
                    ;;
                pending|installing|updating|processing|queued|in_progress|in-progress) ;;
                *)
                    log "ERROR: ACS reports ambiguous status '${status}' for '${name}'."
                    return 1
                    ;;
            esac
        fi
        if (( attempt < attempts )); then
            (( interval > 0 )) && sleep "${interval}"
        fi
        attempt=$((attempt + 1))
    done
    log "ERROR: ACS did not prove '${app_name}' at exact version '${expected_version}' in a terminal state."
    return 1
}

cloud_install_app() {
    local metadata verified_name verified_version verified_status
    case "${SOURCE}" in
        local|remote|url)
            if [[ ! -f "${APP_FILE}" ]]; then
                log "ERROR: File not found: ${APP_FILE}"
                exit 1
            fi
            cloud_install_private_app "${APP_FILE}"
            ;;
        splunkbase)
            cloud_install_splunkbase_app
            ;;
        *)
            log "ERROR: Unknown source '${SOURCE}'"
            exit 1
            ;;
    esac

    cloud_restart_or_exit "app installation"
    if [[ -z "${CLOUD_APP_NAME}" ]]; then
        log "ERROR: ACS accepted the app operation, but the installed app name could not be resolved for verification."
        log "HANDOFF: Run 'acs apps list' and verify the expected package/version before treating the install as complete."
        return 1
    fi
    if ! metadata="$(cloud_verify_exact_app_state "${CLOUD_APP_NAME}" "${APP_VERSION}")"; then
        log "ERROR: ACS accepted the app operation, but exact terminal state could not be verified afterward."
        log "HANDOFF: Run 'acs apps describe ${CLOUD_APP_NAME}' and verify exact version ${APP_VERSION:-<missing>}."
        return 1
    fi
    IFS=$'\x1f' read -r verified_name verified_version verified_status <<< "${metadata}"
    CLOUD_APP_NAME="${verified_name}"
    CLOUD_APP_VERSION="${verified_version:-${CLOUD_APP_VERSION}}"
    CLOUD_APP_STATUS="${verified_status:-${CLOUD_APP_STATUS}}"
    log "SUCCESS: Splunk Cloud verified app '${CLOUD_APP_NAME}'${CLOUD_APP_VERSION:+ (version ${CLOUD_APP_VERSION})}${CLOUD_APP_STATUS:+ [${CLOUD_APP_STATUS}]}"
}

resolve_splunkbase_release_metadata() {
    local metadata requested_version

    requested_version="${APP_VERSION}"
    if [[ -z "${requested_version}" ]]; then
        log "Resolving latest version for app ID ${APP_ID}..."
    fi

    if ! _set_splunkbase_curl_tls_args; then
        log "ERROR: Could not configure Splunkbase TLS settings for release metadata lookup."
        log "Check SPLUNKBASE_CA_CERT (must be a readable file) or unset it to use system roots."
        return 1
    fi

    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_splunkbase_curl_tls_args.
    metadata=$(curl -q -sS --connect-timeout 30 --max-time 120 \
        --proto '=https' --proto-redir '=https' --max-redirs 0 --globoff \
        ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
        "https://splunkbase.splunk.com/api/v1/app/${APP_ID}/release/" 2>/dev/null \
        | python3 -c "
import json
import sys

requested_version = sys.argv[1]

try:
    releases = json.load(sys.stdin)
except Exception:
    sys.exit(1)

if isinstance(releases, dict):
    releases = releases.get('releases', [])

if not isinstance(releases, list) or not releases:
    sys.exit(1)

release = None
if requested_version:
    for candidate in releases:
        version = candidate.get('name') or candidate.get('title') or candidate.get('version') or ''
        if version == requested_version:
            release = candidate
            break
else:
    release = releases[0]

if release is None:
    sys.exit(1)

version = release.get('name') or release.get('title') or release.get('version') or ''
filename = release.get('filename') or ''
if not version or not filename:
    sys.exit(1)

print(f'{version}\\t{filename}')
" "${requested_version}" 2>/dev/null) || true

    if [[ -n "${metadata}" ]]; then
        IFS=$'\t' read -r APP_VERSION APP_PACKAGE_NAME <<< "${metadata}"
        log "Resolved version: ${APP_VERSION}"
        log "Resolved package filename: ${APP_PACKAGE_NAME}"
    else
        if [[ -n "${requested_version}" ]]; then
            log "Could not resolve Splunkbase release metadata for app ID ${APP_ID} version ${requested_version}."
        else
            log "Could not pre-resolve the latest Splunkbase release metadata."
        fi
    fi
}

download_from_splunkbase() {
    resolve_splunkbase_release_metadata

    local requested_version cached_path cached_sha expected_lower actual_sha actual_lower
    requested_version="${APP_VERSION}"

    if [[ -n "${APP_PACKAGE_NAME}" ]]; then
        local cached_candidates=("${PROJECT_TA_DIR}/${APP_PACKAGE_NAME}")
        if [[ "${TA_CACHE}" != "${PROJECT_TA_DIR}" ]]; then
            cached_candidates+=("${TA_CACHE}/${APP_PACKAGE_NAME}")
        fi

        for cached_path in "${cached_candidates[@]}"; do
            [[ -f "${cached_path}" ]] || continue
            if [[ -z "${EXPECTED_SHA256}" ]]; then
                log "Ignoring unverified cached package and redownloading exact Splunkbase release: ${cached_path}"
                continue
            fi
            cached_sha="$(hbs_sha256_file "${cached_path}")"
            expected_lower="$(printf '%s' "${EXPECTED_SHA256}" | tr '[:upper:]' '[:lower:]')"
            actual_lower="$(printf '%s' "${cached_sha}" | tr '[:upper:]' '[:lower:]')"
            if [[ -n "${cached_sha}" && "${actual_lower}" == "${expected_lower}" ]] && _is_splunk_package "${cached_path}"; then
                log "Using SHA-256-verified cached package: ${cached_path}"
                APP_FILE="${cached_path}"
                return
            fi
            log "Ignoring cached package whose bytes do not match the operator-provided SHA-256: ${cached_path}"
        done
    fi

    prompt_splunkbase_creds
    splunkbase_auth

    local temp_path
    temp_path="$(mktemp "${TA_CACHE}/splunkbase_${APP_ID}.XXXXXX")"

    if [[ -n "${requested_version}" ]]; then
        log "Downloading app ${APP_ID} v${requested_version} from Splunkbase..."
    else
        log "Downloading latest release for app ${APP_ID} from Splunkbase..."
    fi

    if ! download_splunkbase_release "${APP_ID}" "${requested_version}" "${temp_path}"; then
        rm -f "${temp_path}"
        log "ERROR: Splunkbase download failed."
        if [[ -n "${SB_DOWNLOAD_ERROR_HINT:-}" ]]; then
            log "${SB_DOWNLOAD_ERROR_HINT}"
        else
            log "Verify app ID (${APP_ID}), version (${requested_version:-latest}), and splunk.com credentials in your credentials file."
        fi
        exit 1
    fi

    if [[ -n "${EXPECTED_SHA256}" ]]; then
        actual_sha="$(hbs_sha256_file "${temp_path}")"
        actual_lower="$(printf '%s' "${actual_sha}" | tr '[:upper:]' '[:lower:]')"
        expected_lower="$(printf '%s' "${EXPECTED_SHA256}" | tr '[:upper:]' '[:lower:]')"
        if [[ -z "${actual_sha}" || "${actual_lower}" != "${expected_lower}" ]]; then
            rm -f "${temp_path}"
            log "ERROR: SHA-256 mismatch for the exact Splunkbase package."
            log "       expected: ${expected_lower}"
            log "       actual:   ${actual_sha:-<could not compute>}"
            exit 1
        fi
        log "Verified operator-provided SHA-256 ${actual_sha} for the Splunkbase package."
    else
        log "NOTICE: Splunkbase supplied the package over authenticated HTTPS, but no publisher/operator package checksum was provided."
        log "NOTICE: Registry provenance verifies release metadata only; these package bytes are not repository checksum evidence."
    fi

    local resolved_version output_filename output_path
    resolved_version="${SB_DOWNLOAD_VERSION:-${requested_version:-latest}}"
    output_filename="${APP_PACKAGE_NAME:-${SB_DOWNLOAD_FILENAME:-splunkbase_${APP_ID}_v${resolved_version}.tgz}}"
    output_path="${TA_CACHE}/${output_filename}"
    mv -f "${temp_path}" "${output_path}"

    [[ -n "${SB_DOWNLOAD_SOURCE_URL:-}" ]] && log "Source URL: ${SB_DOWNLOAD_SOURCE_URL}"
    if [[ -n "${SB_DOWNLOAD_EFFECTIVE_URL:-}" && "${SB_DOWNLOAD_EFFECTIVE_URL}" != "${SB_DOWNLOAD_SOURCE_URL:-}" ]]; then
        log "Resolved URL: ${SB_DOWNLOAD_EFFECTIVE_URL}"
    fi

    APP_VERSION="${resolved_version}"
    APP_PACKAGE_NAME="${output_filename}"
    log "Downloaded to: ${output_path}"
    APP_FILE="${output_path}"
}

download_from_url() {
    local filename safe_source_url
    filename=$(basename "${APP_URL}" | sed 's/[?#].*//')

    if [[ -z "${filename}" ]] || [[ "${filename}" == "/" ]]; then
        filename="downloaded_app_$(date +%s).tgz"
    fi

    local output_path="${TA_CACHE}/${filename}"

    if [[ -z "${EXPECTED_SHA256}" ]]; then
        log "ERROR: --expected-sha256 is required for --url downloads (supply the publisher's"
        log "       SHA-256 of the package). Without an integrity check a compromised or swapped"
        log "       mirror could ship a malicious app package. Pass --expected-sha256 <hex> or"
        log "       use --source splunkbase for an authenticated exact-release download."
        exit 1
    fi
    if ! [[ "${EXPECTED_SHA256}" =~ ^[A-Fa-f0-9]{64}$ ]]; then
        log "ERROR: --expected-sha256 must be a 64-character hexadecimal SHA-256 digest."
        exit 1
    fi

    if ! credential_curl_validate_url "${APP_URL}" false; then
        log "ERROR: --url must be an absolute credential-free HTTPS URL without whitespace or a fragment."
        exit 1
    fi
    safe_source_url="$(python3 - "${APP_URL}" <<'PY'
import sys
from urllib.parse import urlsplit, urlunsplit

parsed = urlsplit(sys.argv[1])
print(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "[REDACTED]" if parsed.query else "", "")), end="")
PY
)"
    log "Downloading from: ${safe_source_url}"
    local http_code effective_url download_meta temp_path
    _set_app_download_curl_tls_args || exit 1
    temp_path="$(mktemp "${TA_CACHE}/remote-app-download.XXXXXX")"
    hbs_append_cleanup_trap "rm -f $(printf '%q' "${temp_path}") 2>/dev/null || true" EXIT INT TERM
    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_app_download_curl_tls_args.
    download_meta=$(curl -q -sS --location --max-redirs 3 \
        --proto '=https' --proto-redir '=https' --globoff \
        --connect-timeout 30 --max-time 300 \
        ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
        -w $'%{http_code}\t%{url_effective}' \
        -o "${temp_path}" \
        "${APP_URL}" 2>/dev/null || printf '000\t')
    http_code="${download_meta%%$'\t'*}"
    effective_url="${download_meta#*$'\t'}"

    if [[ ! "${http_code}" =~ ^[0-9]{3}$ ]] || (( 10#${http_code} < 200 || 10#${http_code} >= 400 )) || [[ ! -s "${temp_path}" ]]; then
        rm -f "${temp_path}"
        log "ERROR: Download failed (HTTP ${http_code:-unknown}) from: ${safe_source_url}"
        exit 1
    fi
    if ! credential_curl_validate_url "${effective_url}" false; then
        rm -f "${temp_path}"
        log "ERROR: Download resolved to an invalid or non-HTTPS effective URL."
        exit 1
    fi

    local actual_sha actual_lower expected_lower
    actual_sha="$(hbs_sha256_file "${temp_path}")"
    actual_lower="$(printf '%s' "${actual_sha}" | tr '[:upper:]' '[:lower:]')"
    expected_lower="$(printf '%s' "${EXPECTED_SHA256}" | tr '[:upper:]' '[:lower:]')"
    if [[ -z "${actual_sha}" || "${actual_lower}" != "${expected_lower}" ]]; then
        rm -f "${temp_path}"
        log "ERROR: SHA-256 mismatch for downloaded package."
        log "       expected: ${expected_lower}"
        log "       actual:   ${actual_sha:-<could not compute>}"
        log "       Refusing to install a package whose integrity could not be verified."
        exit 1
    fi
    log "Verified SHA-256 ${actual_sha} for ${filename}."

    mv -f "${temp_path}" "${output_path}"

    log "Downloaded to: ${output_path} (HTTP ${http_code})"
    APP_FILE="${output_path}"
}

install_via_server_path() {
    local source_path="$1"
    local update_flag="$2"

    splunk_curl "${SK}" --connect-timeout 10 --max-time 180 \
        -X POST "${SPLUNK_URI}/services/apps/local" \
        --data-urlencode "name=${source_path}" \
        -d "filename=true" \
        -d "update=${update_flag}" \
        -d "output_mode=json" \
        -w '\n%{http_code}' \
        2>/dev/null || true
}

app_lookup_http_code() {
    local sk="$1" uri="$2" app="$3"
    splunk_curl "${sk}" --connect-timeout 5 --max-time 15 -o /dev/null -w "%{http_code}" \
        "${uri}/services/apps/local/${app}?output_mode=json" 2>/dev/null || echo "000"
}

INSTALL_HTTP_CODE=""
INSTALL_BODY=""
INSTALL_INCOMPLETE_BUT_PRESENT=false

install_via_server_path_with_verification() {
    local source_path="$1"
    local update_flag="$2"
    local expected_app_name="${3:-}"
    local response install_rc http_code body post_install_check

    INSTALL_HTTP_CODE=""
    INSTALL_BODY=""
    INSTALL_INCOMPLETE_BUT_PRESENT=false

    response=""
    install_rc=0
    set +e
    response=$(install_via_server_path "${source_path}" "${update_flag}")
    install_rc=$?
    set -e

    http_code=$(printf '%s\n' "${response}" | tail -1)
    body=$(printf '%s\n' "${response}" | sed '$d')

    if [[ -z "${http_code}" ]] || (( install_rc != 0 )) || [[ "${http_code}" == "000" ]]; then
        if [[ -n "${expected_app_name}" ]]; then
            post_install_check="$(app_lookup_http_code "${SK}" "${SPLUNK_URI}" "${expected_app_name}")"
            if [[ "${post_install_check}" == "200" ]]; then
                INSTALL_INCOMPLETE_BUT_PRESENT=true
                http_code="200"
                body=""
            fi
        fi
        if [[ -z "${http_code}" ]]; then
            http_code="000"
        fi
    fi

    INSTALL_HTTP_CODE="${http_code}"
    INSTALL_BODY="${body}"
}

stage_file_via_ssh() {
    local local_path="$1"
    local remote_path="$2"
    local ssh_target="${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}"
    local remote_dir remote_name scp_target rc

    if ! command -v sshpass >/dev/null 2>&1; then
        log "ERROR: sshpass is required for SSH password-based staging."
        log "Install sshpass or stage the package on the Splunk host before installing it."
        return 1
    fi

    remote_dir="$(dirname "${remote_path}")"
    remote_name="$(basename "${remote_path}")"
    if [[ "${remote_path}" != "${remote_dir%/}/${remote_name}" ]]; then
        log "ERROR: SSH staging path is not a normalized absolute remote path: ${remote_path}"
        return 1
    fi
    hbs_validate_remote_stage_path "${remote_dir}" "${remote_name}" || return 1
    hbs_prepare_ssh_trust || return 1
    scp_target="${ssh_target}:${remote_path}"
    if [[ "${SPLUNK_SSH_HOST}" == *:* ]]; then
        scp_target="${SPLUNK_SSH_USER}@[${SPLUNK_SSH_HOST}]:${remote_path}"
    fi

    if env -u SPLUNK_SSH_PASS -u SSHPASS sshpass -d 3 scp \
        -P "${SPLUNK_SSH_PORT}" \
        -o ConnectTimeout=15 \
        ${HBS_SSH_TRUST_ARGS[@]+"${HBS_SSH_TRUST_ARGS[@]}"} \
        -o PubkeyAuthentication=no \
        -o PreferredAuthentications=password \
        -o NumberOfPasswordPrompts=1 \
        -q \
        "${local_path}" "${scp_target}" 3<<<"${SPLUNK_SSH_PASS}"; then
        rc=0
    else
        rc=$?
    fi
    hbs_cleanup_ssh_trust
    return "${rc}"
}

cleanup_remote_stage_file() {
    local remote_path="$1"

    [[ -z "${remote_path}" ]] && return 0

    if ! command -v sshpass >/dev/null 2>&1; then
        return 0
    fi

    hbs_run_target_cmd ssh "$(hbs_shell_join rm -f "${remote_path}")" >/dev/null 2>&1 || true
}

install_app() {
    local file_path="$1"

    if [[ ! -f "${file_path}" ]]; then
        log "ERROR: File not found: ${file_path}"
        exit 1
    fi

    local file_size
    file_size=$(stat -c%s "${file_path}" 2>/dev/null || stat -f%z "${file_path}" 2>/dev/null || echo "unknown")
    log "Installing: $(basename "${file_path}") (${file_size} bytes)"

    local update_flag="false"
    if $UPDATE; then
        update_flag="true"
        log "Mode: upgrade (update=true)"
    else
        log "Mode: fresh install"
    fi

    local http_code body expected_app_name
    local abs_file_path
    abs_file_path="$(cd "$(dirname "${file_path}")" && pwd)/$(basename "${file_path}")"
    local file_name
    file_name="$(basename "${abs_file_path}")"
    expected_app_name="$(guess_app_name_from_package "${abs_file_path}")"
    if [[ -n "${expected_app_name}" && ! "${expected_app_name}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
        log "ERROR: Package top-level app directory '${expected_app_name}' is not a safe Splunk app ID."
        exit 1
    fi

    if deployment_should_use_bundle_for_current_target; then
        local bundle_kind
        bundle_kind="$(deployment_bundle_kind_for_current_target)"
        case "${bundle_kind}" in
            shc)
                log "Installing via search-head-cluster deployer bundle delivery..."
                ;;
            idxc)
                log "Installing via indexer-cluster manager bundle delivery..."
                ;;
            *)
                log "Installing via bundle delivery..."
                ;;
        esac

        if ! deployment_install_app_via_bundle "${abs_file_path}" "${expected_app_name}"; then
            log "ERROR: Bundle-managed app installation failed."
            exit 1
        fi

        if [[ -n "${expected_app_name}" ]]; then
            if ! deployment_bundle_app_exists_for_current_target "${expected_app_name}"; then
                log "ERROR: Bundle-managed app installation could not be verified on the control plane for '${expected_app_name}'."
                exit 1
            fi
            http_code="$(app_lookup_http_code "${SK}" "${SPLUNK_URI}" "${expected_app_name}")"
            if [[ "${http_code}" != "200" ]]; then
                log "WARNING: Bundle delivery completed, but current-target REST verification returned HTTP ${http_code} for '${expected_app_name}'."
                log "WARNING: The bundle may still be propagating through the clustered deployment plane."
            fi
        else
            log "ERROR: Bundle delivery completed, but the app name could not be inferred for post-apply verification."
            log "HANDOFF: Inspect the bundle app directory and verify the deployed app ID before treating installation as complete."
            exit 1
        fi

        INSTALL_HTTP_CODE="200"
        INSTALL_BODY=""
        INSTALL_INCOMPLETE_BUT_PRESENT=false
        http_code="${INSTALL_HTTP_CODE}"
        body="${INSTALL_BODY}"
    else
    log "Installing to ${SPLUNK_URI} ..."

    # Detect whether Splunk is local or remote.
    local splunk_host
    splunk_host=$(echo "${SPLUNK_URI}" | sed -E 's|https?://([^:/]+).*|\1|')
    local is_local=false
    if [[ "${splunk_host}" == "localhost" || "${splunk_host}" == "127.0.0.1" ]]; then
        is_local=true
    fi

    if $is_local; then
        # Splunk is local — install directly from the filesystem path.
        log "Installing from local path: ${abs_file_path}"
        install_via_server_path_with_verification "${abs_file_path}" "${update_flag}" "${expected_app_name}"
    else
        local remote_tmp
        remote_tmp="/tmp/${file_name%.*}.$$.${RANDOM}.$(basename "${file_name}")"

        log "Remote package installs require staging on the Splunk host."
        if ! load_splunk_ssh_credentials; then
            log "ERROR: SSH staging requested but SSH credentials are unavailable."
            exit 1
        fi

        log "Copying package to ${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}:${remote_tmp} ..."
        if ! stage_file_via_ssh "${abs_file_path}" "${remote_tmp}"; then
            log "ERROR: SSH copy failed."
            exit 1
        fi

        log "Installing staged package from ${remote_tmp} ..."
        install_via_server_path_with_verification "${remote_tmp}" "${update_flag}" "${expected_app_name}"
        cleanup_remote_stage_file "${remote_tmp}"
    fi

        http_code="${INSTALL_HTTP_CODE:-000}"
        body="${INSTALL_BODY:-}"
    fi

    local app_name error_msg post_install_check verification_incomplete=false
    app_name=$(echo "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get('entry', [])
    if entries:
        print(entries[0].get('name', ''))
except Exception:
    print('', end='')
" 2>/dev/null || true)

    error_msg=$(echo "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    msgs = data.get('messages', [])
    for m in msgs:
        if m.get('type') == 'ERROR':
            print(m.get('text', 'Unknown error'), end='')
            break
except Exception:
    print('', end='')
" 2>/dev/null || true)

    if [[ -z "${app_name}" && -n "${expected_app_name}" && ( "${http_code}" == "200" || "${http_code}" == "201" ) ]]; then
        app_name="${expected_app_name}"
    fi

    if ${INSTALL_INCOMPLETE_BUT_PRESENT}; then
        log "ERROR: Install request did not finish cleanly; the app is present, but this does not prove the requested install/update completed."
        verification_incomplete=true
    fi

    case "${http_code}" in
        200|201)
            ;;
        *)
            if [[ -n "${error_msg}" ]]; then
                log "ERROR: ${error_msg}"
            else
                log "ERROR: Installation failed (HTTP ${http_code})."
                [[ -n "${body}" ]] && sanitize_response "${body}" 5 >&2
            fi
            exit 1
            ;;
    esac

    if [[ -n "${app_name}" ]]; then
        post_install_check="$(app_lookup_http_code "${SK}" "${SPLUNK_URI}" "${app_name}")"
        if [[ "${post_install_check}" != "200" ]]; then
            log "ERROR: App '${app_name}' could not be read back after the install request (HTTP ${post_install_check})."
            verification_incomplete=true
        else
            log "SUCCESS: App '${app_name}' is present after the install request (HTTP ${http_code})"
        fi

        local version
        version=$(splunk_curl "${SK}" \
            "${SPLUNK_URI}/services/apps/local/${app_name}?output_mode=json" 2>/dev/null \
            | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    e = data.get('entry', [{}])[0].get('content', {})
    print(e.get('version', 'unknown'))
except Exception:
    print('unknown')
" 2>/dev/null || echo "unknown")
        log "Installed path: ${SPLUNK_HOME}/etc/apps/${app_name}/"
        log "Version: ${version}"
        if [[ -n "${APP_VERSION}" && "${version}" != "${APP_VERSION}" ]]; then
            log "ERROR: Installed app '${app_name}' reports version '${version}', expected pinned version '${APP_VERSION}'."
            verification_incomplete=true
        fi
    else
        log "ERROR: Install was accepted (HTTP ${http_code}) but the app name could not be resolved for verification."
        log "Check Splunk: ${SPLUNK_HOME}/etc/apps/"
        verification_incomplete=true
    fi

    restart_splunk_or_exit "app installation"
    if ${verification_incomplete}; then
        log "HANDOFF: Verify the expected app ID and version with list_apps.sh before treating installation as complete."
        return 1
    fi
}

# ── Main ────────────────────────────────────────────────────────────

main() {
    echo "=== Splunk App Installer ==="
    echo ""

    require_registry_provenance || exit 1

    mkdir -p "${PROJECT_TA_DIR}"
    mkdir -p "${TA_CACHE}"

    prompt_source

    if is_splunk_cloud; then
        case "${SOURCE}" in
            local)
                prompt_local_file
                cloud_prefer_splunkbase_for_known_package "${APP_FILE}"
                ;;
            remote|url)
                prompt_url
                download_from_url
                cloud_prefer_splunkbase_for_known_package "${APP_FILE}"
                ;;
            splunkbase)
                prompt_splunkbase
                ;;
            *)
                log "ERROR: Unknown source '${SOURCE}'"
                exit 1
                ;;
        esac

        if [[ "${SOURCE}" != "splunkbase" ]]; then
            preflight_unknown_explicit_app_id
            prepare_exact_package_contract
        fi
        prompt_update
        apply_registry_verified_version_default
        preflight_current_install_target_compatibility
        warn_for_current_install_target_role
        require_registry_provenance || exit 1
        install_required_dependencies
        cloud_install_app
        exit 0
    fi

    case "${SOURCE}" in
        local)
            prompt_local_file
            ;;
        remote|url)
            prompt_url
            download_from_url
            ;;
        splunkbase)
            prompt_splunkbase
            apply_registry_verified_version_default
            preflight_current_install_target_compatibility
            download_from_splunkbase
            ;;
        *)
            log "ERROR: Unknown source '${SOURCE}'"
            exit 1
            ;;
    esac

    preflight_unknown_explicit_app_id
    prepare_exact_package_contract
    prompt_update
    # Bind compatibility to the exact version read from the downloaded archive
    # immediately before any dependency or target mutation.
    preflight_current_install_target_compatibility
    warn_for_current_install_target_role
    require_registry_provenance || exit 1
    prompt_splunk_creds
    splunk_auth
    install_required_dependencies
    install_app "${APP_FILE}"
}

main
