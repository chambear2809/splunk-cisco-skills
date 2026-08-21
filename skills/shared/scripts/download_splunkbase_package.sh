#!/usr/bin/env bash
# Download and unpack a Splunkbase app package for offline package inspection.
#
# This helper is intentionally download-only. It never installs an app into
# Splunk and never writes outside the repo-local splunk-ta cache unless asked.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"
SAFE_EXTRACTOR="${SCRIPT_DIR}/safe_extract_tar.py"

APP_ID=""
APP_VERSION=""
EXPECTED_APP_NAMES=()
TA_DIR="${REPO_ROOT}/splunk-ta"
UNPACK_ROOT="${REPO_ROOT}/splunk-ta/_unpacked"
FORCE=false

usage() {
    cat <<'EOF'
Download and unpack a Splunkbase package for review-only extraction.

Usage:
  bash skills/shared/scripts/download_splunkbase_package.sh \
    --app-id 5556 --version 4.0.0 --app-name Splunk_TA_Google_Workspace

  bash skills/shared/scripts/download_splunkbase_package.sh \
    --app-id 3225 --version 4.1.1 \
    --app-names TA-Exchange-ClientAccess,TA-Exchange-Mailbox,TA-SMTP-Reputation,TA-Windows-Exchange-IIS

Options:
  --app-id ID        Splunkbase numeric app ID (required)
  --version VER      Splunkbase release version to pin (required)
  --app-name NAME    Expected extracted app directory name; repeat for bundles
  --app-names CSV    Comma-separated expected extracted app directory names
  --ta-dir DIR       Archive cache directory (default: splunk-ta)
  --unpack-root DIR  Extraction root (default: splunk-ta/_unpacked)
  --force            Re-extract even when the target directory already exists
  --help             Show this help

The archive is saved under splunk-ta/ and extracted only under the ignored
splunk-ta/_unpacked/<app_name>-<version>/ path.
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

validate_component() {
    local value="$1" label="$2" pattern="$3"
    [[ "${#value}" -le 255 ]] || die "${label} is too long"
    [[ "${value}" =~ ${pattern} ]] || die "${label} contains unsupported characters: ${value}"
    [[ "${value}" != "." && "${value}" != ".." ]] || die "${label} must be a single safe path component"
}

normalize_root() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve(strict=False), end="")
PY
}

contained_path() {
    python3 - "$1" "$2" <<'PY'
import os
from pathlib import Path
import sys

root = Path(sys.argv[1]).expanduser().resolve(strict=False)
candidate_input = Path(sys.argv[2]).expanduser()
if candidate_input.is_symlink():
    raise SystemExit(f"ERROR: refusing symbolic-link target path: {candidate_input}")
candidate = candidate_input.resolve(strict=False)
try:
    common = Path(os.path.commonpath((root, candidate)))
except ValueError as exc:
    raise SystemExit(f"ERROR: path is not below the requested root: {exc}")
if common != root or candidate == root:
    raise SystemExit(f"ERROR: refusing path outside the requested root: {candidate}")
print(candidate, end="")
PY
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --app-id) require_arg "$1" $# || exit 1; APP_ID="$2"; shift 2 ;;
        --version|--app-version) require_arg "$1" $# || exit 1; APP_VERSION="$2"; shift 2 ;;
        --app-name) require_arg "$1" $# || exit 1; EXPECTED_APP_NAMES+=("$2"); shift 2 ;;
        --app-names|--expected-apps) require_arg "$1" $# || exit 1; IFS=',' read -r -a _csv_apps <<< "$2"; EXPECTED_APP_NAMES+=("${_csv_apps[@]}"); shift 2 ;;
        --ta-dir) require_arg "$1" $# || exit 1; TA_DIR="$2"; shift 2 ;;
        --unpack-root) require_arg "$1" $# || exit 1; UNPACK_ROOT="$2"; shift 2 ;;
        --force) FORCE=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1" ;;
    esac
done

[[ -n "${APP_ID}" ]] || die "--app-id is required"
[[ "${APP_ID}" =~ ^[0-9]+$ ]] || die "--app-id must be numeric"
[[ -n "${APP_VERSION}" ]] || die "--version is required"
validate_component "${APP_VERSION}" "--version" '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
clean_expected_apps=()
for app_name in "${EXPECTED_APP_NAMES[@]}"; do
    app_name="${app_name#"${app_name%%[![:space:]]*}"}"
    app_name="${app_name%"${app_name##*[![:space:]]}"}"
    if [[ -n "${app_name}" ]]; then
        validate_component "${app_name}" "--app-name" '^[A-Za-z0-9][A-Za-z0-9_.-]*$'
        clean_expected_apps+=("${app_name}")
    fi
done
EXPECTED_APP_NAMES=("${clean_expected_apps[@]}")
[[ "${#EXPECTED_APP_NAMES[@]}" -gt 0 ]] || die "--app-name or --app-names is required"
EXPECTED_APP_KEY="${EXPECTED_APP_NAMES[0]}"

[[ -f "${SAFE_EXTRACTOR}" && -r "${SAFE_EXTRACTOR}" ]] || die "Safe archive extractor is missing: ${SAFE_EXTRACTOR}"
TA_DIR="$(normalize_root "${TA_DIR}")"
UNPACK_ROOT="$(normalize_root "${UNPACK_ROOT}")"
mkdir -p "${TA_DIR}" "${UNPACK_ROOT}"
TA_DIR="$(normalize_root "${TA_DIR}")"
UNPACK_ROOT="$(normalize_root "${UNPACK_ROOT}")"

log "Resolving Splunkbase app ${APP_ID} version ${APP_VERSION}..."
get_splunkbase_release_metadata "${APP_ID}" "${APP_VERSION}" || exit 1

RESOLVED_VERSION="${SB_DOWNLOAD_VERSION:-${APP_VERSION}}"
ARCHIVE_NAME="${SB_DOWNLOAD_FILENAME:-splunkbase_${APP_ID}_${RESOLVED_VERSION}.tgz}"

if [[ "${RESOLVED_VERSION}" != "${APP_VERSION}" ]]; then
    die "Resolved version ${RESOLVED_VERSION} did not match requested version ${APP_VERSION}"
fi
validate_component "${RESOLVED_VERSION}" "resolved Splunkbase version" '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
validate_component "${ARCHIVE_NAME}" "Splunkbase metadata filename" '^[A-Za-z0-9][A-Za-z0-9._+-]*$'
case "${ARCHIVE_NAME}" in
    *.tgz|*.tar.gz|*.tar|*.spl) ;;
    *) die "Splunkbase metadata filename must end in .tgz, .tar.gz, .tar, or .spl" ;;
esac

ARCHIVE_PATH="$(contained_path "${TA_DIR}" "${TA_DIR}/${ARCHIVE_NAME}")"
TARGET_DIR="$(contained_path "${UNPACK_ROOT}" "${UNPACK_ROOT}/${EXPECTED_APP_KEY}-${RESOLVED_VERSION}")"

if [[ -f "${ARCHIVE_PATH}" ]]; then
    [[ ! -L "${ARCHIVE_PATH}" ]] || die "Cached archive must not be a symbolic link: ${ARCHIVE_PATH}"
    if _is_splunk_package "${ARCHIVE_PATH}"; then
        log "Using cached archive: ${ARCHIVE_PATH}"
    else
        die "Cached file is not a valid Splunk package: ${ARCHIVE_PATH}"
    fi
else
    log "Downloading ${EXPECTED_APP_KEY} ${APP_VERSION} to ${ARCHIVE_PATH}..."
    load_splunkbase_credentials || exit 1
    ARCHIVE_PATH="$(contained_path "${TA_DIR}" "${ARCHIVE_PATH}")"
    download_splunkbase_release "${APP_ID}" "${APP_VERSION}" "${ARCHIVE_PATH}" || exit 1
fi
[[ -f "${ARCHIVE_PATH}" && ! -L "${ARCHIVE_PATH}" ]] || die "Downloaded archive is not a non-symlink regular file: ${ARCHIVE_PATH}"

VALIDATE_DIR="${TARGET_DIR}"
if [[ -d "${TARGET_DIR}" && "${FORCE}" != "true" ]]; then
    log "Using existing extraction: ${TARGET_DIR}"
else
    TMP_PARENT="$(mktemp -d "${UNPACK_ROOT}/.${EXPECTED_APP_KEY}-${RESOLVED_VERSION}.XXXXXX")"
    TMP_PARENT="$(contained_path "${UNPACK_ROOT}" "${TMP_PARENT}")"
    TMP_EXTRACT="$(contained_path "${TMP_PARENT}" "${TMP_PARENT}/extracted")"
    cleanup() {
        if [[ -n "${TMP_PARENT:-}" ]]; then
            local safe_tmp
            safe_tmp="$(contained_path "${UNPACK_ROOT}" "${TMP_PARENT}")" || return
            rm -rf -- "${safe_tmp}"
        fi
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    extract_args=()
    for app_name in "${EXPECTED_APP_NAMES[@]}"; do
        extract_args+=(--expected-root "${app_name}")
    done
    python3 "${SAFE_EXTRACTOR}" \
        --containment-root "${TMP_PARENT}" \
        "${extract_args[@]}" \
        "${ARCHIVE_PATH}" \
        "${TMP_EXTRACT}"
    VALIDATE_DIR="${TMP_EXTRACT}"
fi

python3 - "${VALIDATE_DIR}" "${APP_VERSION}" "${EXPECTED_APP_NAMES[@]}" <<'PY'
import configparser
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
expected_version = sys.argv[2]
expected_apps = sys.argv[3:]

if not expected_apps:
    raise SystemExit("ERROR: no expected app directories supplied")

candidates = [
    p for p in target.iterdir()
    if p.is_dir() and ((p / "default" / "app.conf").is_file() or (p / "app.manifest").is_file())
]
candidate_names = {p.name: p for p in candidates}

for expected_app in expected_apps:
    app_dir = target / expected_app
    if not app_dir.is_dir():
        names = ", ".join(sorted(candidate_names)) or "<none>"
        raise SystemExit(f"ERROR: expected extracted app directory {expected_app!r}; found {names}")

    versions = []
    version_file = app_dir / "VERSION"
    if version_file.is_file():
        text = version_file.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            versions.append(("VERSION", text.splitlines()[0].strip()))

    app_conf = app_dir / "default" / "app.conf"
    if app_conf.is_file():
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read(app_conf, encoding="utf-8")
        if parser.has_option("launcher", "version"):
            versions.append(("default/app.conf [launcher] version", parser.get("launcher", "version").strip()))
        if parser.has_option("install", "version"):
            versions.append(("default/app.conf [install] version", parser.get("install", "version").strip()))

    manifest = app_dir / "app.manifest"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        info = data.get("info") if isinstance(data, dict) else {}
        if isinstance(info, dict) and str(info.get("id", {}).get("version", "")).strip():
            versions.append(("app.manifest info.id.version", str(info["id"]["version"]).strip()))

    matching = [value for _, value in versions if value == expected_version]
    if not matching:
        rendered = ", ".join(f"{source}={value}" for source, value in versions) or "<no version metadata found>"
        raise SystemExit(f"ERROR: extracted version metadata for {expected_app} did not match {expected_version}: {rendered}")

    print(f"OK: {expected_app} {expected_version} verified at {app_dir}")
PY

if [[ "${VALIDATE_DIR}" != "${TARGET_DIR}" ]]; then
    safe_target="$(contained_path "${UNPACK_ROOT}" "${TARGET_DIR}")"
    if [[ -e "${safe_target}" || -L "${safe_target}" ]]; then
        [[ "${FORCE}" == "true" ]] || die "Extraction target already exists: ${safe_target}"
        rm -rf -- "${safe_target}"
    fi
    mv -- "${TMP_EXTRACT}" "${safe_target}"
    VALIDATE_DIR="${safe_target}"
    cleanup
    trap - EXIT INT TERM
    log "Extracted to: ${safe_target}"
fi

log "Package ready."
echo "ARCHIVE_PATH=${ARCHIVE_PATH}"
echo "EXTRACT_DIR=${TARGET_DIR}"
