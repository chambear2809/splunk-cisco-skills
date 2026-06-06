#!/usr/bin/env bash
# Download and unpack a Splunkbase app package for offline package inspection.
#
# This helper is intentionally download-only. It never installs an app into
# Splunk and never writes outside the repo-local splunk-ta cache unless asked.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"

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
    --app-id 3225 --version 4.1.0 \
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
clean_expected_apps=()
for app_name in "${EXPECTED_APP_NAMES[@]}"; do
    app_name="${app_name#"${app_name%%[![:space:]]*}"}"
    app_name="${app_name%"${app_name##*[![:space:]]}"}"
    [[ -n "${app_name}" ]] && clean_expected_apps+=("${app_name}")
done
EXPECTED_APP_NAMES=("${clean_expected_apps[@]}")
[[ "${#EXPECTED_APP_NAMES[@]}" -gt 0 ]] || die "--app-name or --app-names is required"
EXPECTED_APP_KEY="${EXPECTED_APP_NAMES[0]}"

mkdir -p "${TA_DIR}" "${UNPACK_ROOT}"

log "Resolving Splunkbase app ${APP_ID} version ${APP_VERSION}..."
get_splunkbase_release_metadata "${APP_ID}" "${APP_VERSION}" || exit 1

RESOLVED_VERSION="${SB_DOWNLOAD_VERSION:-${APP_VERSION}}"
ARCHIVE_NAME="${SB_DOWNLOAD_FILENAME:-splunkbase_${APP_ID}_${RESOLVED_VERSION}.tgz}"
ARCHIVE_PATH="${TA_DIR}/${ARCHIVE_NAME}"
TARGET_DIR="${UNPACK_ROOT}/${EXPECTED_APP_KEY}-${RESOLVED_VERSION}"

if [[ "${RESOLVED_VERSION}" != "${APP_VERSION}" ]]; then
    die "Resolved version ${RESOLVED_VERSION} did not match requested version ${APP_VERSION}"
fi

if [[ -f "${ARCHIVE_PATH}" ]]; then
    if _is_splunk_package "${ARCHIVE_PATH}"; then
        log "Using cached archive: ${ARCHIVE_PATH}"
    else
        die "Cached file is not a valid Splunk package: ${ARCHIVE_PATH}"
    fi
else
    log "Downloading ${EXPECTED_APP_KEY} ${APP_VERSION} to ${ARCHIVE_PATH}..."
    load_splunkbase_credentials || exit 1
    download_splunkbase_release "${APP_ID}" "${APP_VERSION}" "${ARCHIVE_PATH}" || exit 1
fi

if [[ -d "${TARGET_DIR}" && "${FORCE}" != "true" ]]; then
    log "Using existing extraction: ${TARGET_DIR}"
else
    if [[ -d "${TARGET_DIR}" ]]; then
        rm -rf "${TARGET_DIR}"
    fi
    TMP_EXTRACT="$(mktemp -d "${UNPACK_ROOT}/.${EXPECTED_APP_KEY}-${RESOLVED_VERSION}.XXXXXX")"
    cleanup() {
        rm -rf "${TMP_EXTRACT:-}"
    }
    trap cleanup EXIT
    tar -xf "${ARCHIVE_PATH}" -C "${TMP_EXTRACT}"
    mkdir -p "${TARGET_DIR}"
    shopt -s dotglob nullglob
    extracted=("${TMP_EXTRACT}"/*)
    if [[ "${#extracted[@]}" -eq 0 ]]; then
        die "Package extraction produced no files"
    fi
    mv "${extracted[@]}" "${TARGET_DIR}/"
    shopt -u dotglob nullglob
    cleanup
    trap - EXIT
    log "Extracted to: ${TARGET_DIR}"
fi

python3 - "${TARGET_DIR}" "${APP_VERSION}" "${EXPECTED_APP_NAMES[@]}" <<'PY'
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

log "Package ready."
echo "ARCHIVE_PATH=${ARCHIVE_PATH}"
echo "EXTRACT_DIR=${TARGET_DIR}"
