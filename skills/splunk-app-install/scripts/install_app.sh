#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
PROJECT_TA_DIR="${SCRIPT_DIR}/../../../splunk-ta"
TA_CACHE="${TA_CACHE:-${PROJECT_TA_DIR}}"

SOURCE=""
APP_FILE=""
APP_URL=""
APP_ID=""
APP_VERSION=""
APP_PACKAGE_NAME=""
UPDATE=false
UPDATE_SET=false

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

is_interactive() { [[ -t 0 ]]; }

safe_read() {
    if ! is_interactive; then
        log "ERROR: Missing required value (would prompt for: $1) but stdin is not a terminal."
        log "Supply all values via flags/env vars for non-interactive use."
        exit 1
    fi
    shift
    read "$@"
}

# Accept flags for non-interactive use; anything missing gets prompted
while [[ $# -gt 0 ]]; do
    case "$1" in
        --source)       SOURCE="$2";      shift 2 ;;
        --file)         APP_FILE="$2";     shift 2 ;;
        --url)          APP_URL="$2";      shift 2 ;;
        --app-id)       APP_ID="$2";       shift 2 ;;
        --app-version)  APP_VERSION="$2";  shift 2 ;;
        --update)       UPDATE=true;  UPDATE_SET=true;  shift ;;
        --no-update)    UPDATE=false; UPDATE_SET=true;  shift ;;
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
  --app-id ID           Splunkbase app ID
  --app-version VER     Splunkbase version
  --update              Upgrade mode
  --no-update           Fresh install (skip upgrade prompt)

Credentials and remote host settings are read from the project-root credentials file automatically.
For remote local-package installs, the script tries REST upload first, then falls back
to SSH staging using SPLUNK_SSH_HOST/SPLUNK_SSH_USER/SPLUNK_SSH_PASS.
Run: bash ${SCRIPT_DIR}/../../shared/scripts/setup_credentials.sh
EOF
            exit 0 ;;
        *) log "Unknown option: $1"; exit 1 ;;
    esac
done

# ── Prompt helpers ──────────────────────────────────────────────────

prompt_source() {
    [[ -n "${SOURCE}" ]] && return
    echo ""
    echo "How do you want to install the app?"
    echo "  1) Local             — .tgz/.spl file on this server or in the project"
    echo "  2) Remote            — download from a remote URL"
    echo "  3) Splunkbase        — download from splunkbase.splunk.com"
    echo ""
    safe_read "--source" -rp "Select source [1/2/3]: " choice
    case "${choice}" in
        1|local)                SOURCE="local" ;;
        2|remote|url)           SOURCE="remote" ;;
        3|splunkbase)           SOURCE="splunkbase" ;;
        *) log "ERROR: Invalid choice '${choice}'"; exit 1 ;;
    esac
}

prompt_local_file() {
    [[ -n "${APP_FILE}" ]] && return
    echo ""

    local files=()
    local search_dirs=()

    [[ -d "${PROJECT_TA_DIR}" ]] && search_dirs+=("${PROJECT_TA_DIR}")
    if [[ "${TA_CACHE}" != "${PROJECT_TA_DIR}" && -d "${TA_CACHE}" ]]; then
        search_dirs+=("${TA_CACHE}")
    fi

    for dir in "${search_dirs[@]}"; do
        while IFS= read -r -d '' f; do
            files+=("$f")
        done < <(find "${dir}" -maxdepth 1 \( -name '*.tgz' -o -name '*.spl' -o -name '*.tar.gz' \) -print0 2>/dev/null | sort -z)
    done

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

    if [[ -z "${APP_VERSION}" ]]; then
        echo ""
        safe_read "--app-version" -rp "App version (leave blank for latest): " APP_VERSION
    fi
}

prompt_update() {
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

resolve_splunkbase_release_metadata() {
    local metadata requested_version

    requested_version="${APP_VERSION}"
    if [[ -z "${requested_version}" ]]; then
        log "Resolving latest version for app ID ${APP_ID}..."
    fi

    metadata=$(curl -sk "https://splunkbase.splunk.com/api/v1/app/${APP_ID}/release/" 2>/dev/null \
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

    local requested_version cached_path
    requested_version="${APP_VERSION}"

    if [[ -n "${APP_PACKAGE_NAME}" ]]; then
        local cached_candidates=("${PROJECT_TA_DIR}/${APP_PACKAGE_NAME}")
        if [[ "${TA_CACHE}" != "${PROJECT_TA_DIR}" ]]; then
            cached_candidates+=("${TA_CACHE}/${APP_PACKAGE_NAME}")
        fi

        for cached_path in "${cached_candidates[@]}"; do
            if [[ -f "${cached_path}" ]] && _is_splunk_package "${cached_path}"; then
                log "Existing package found: ${cached_path}"
                APP_FILE="${cached_path}"
                return
            fi
            if [[ -f "${cached_path}" ]]; then
                log "Ignoring invalid package at: ${cached_path}"
            fi
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
        log "Verify app ID (${APP_ID}), version (${requested_version:-latest}), and splunk.com credentials in your credentials file."
        exit 1
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
    local filename
    filename=$(basename "${APP_URL}" | sed 's/[?#].*//')

    if [[ -z "${filename}" ]] || [[ "${filename}" == "/" ]]; then
        filename="downloaded_app_$(date +%s).tgz"
    fi

    local output_path="${TA_CACHE}/${filename}"

    log "Downloading from: ${APP_URL}"
    local http_code
    http_code=$(curl -skL -w "%{http_code}" \
        -o "${output_path}" \
        "${APP_URL}" 2>/dev/null || echo "000")

    if [[ "${http_code}" -lt 200 ]] || [[ "${http_code}" -ge 400 ]] || [[ ! -s "${output_path}" ]]; then
        rm -f "${output_path}"
        log "ERROR: Download failed (HTTP ${http_code}) from: ${APP_URL}"
        exit 1
    fi

    log "Downloaded to: ${output_path} (HTTP ${http_code})"
    APP_FILE="${output_path}"
}

install_via_rest_upload() {
    local file_path="$1"
    local update_flag="$2"

    splunk_curl "${SK}" \
        -X POST "${SPLUNK_URI}/services/apps/local" \
        -F "name=$(basename "${file_path}")" \
        -F "appfile=@${file_path}" \
        -F "update=${update_flag}" \
        -F "output_mode=json" \
        -w '\n%{http_code}' \
        2>/dev/null || true
}

install_via_server_path() {
    local source_path="$1"
    local update_flag="$2"

    splunk_curl "${SK}" \
        -X POST "${SPLUNK_URI}/services/apps/local" \
        --data-urlencode "name=${source_path}" \
        -d "filename=true" \
        -d "update=${update_flag}" \
        -d "output_mode=json" \
        -w '\n%{http_code}' \
        2>/dev/null || true
}

stage_file_via_ssh() {
    local local_path="$1"
    local remote_path="$2"
    local ssh_target="${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}"
    local pass_file

    if ! command -v sshpass >/dev/null 2>&1; then
        log "ERROR: sshpass is required for SSH password-based staging."
        log "Install sshpass or use a host that supports direct REST upload."
        return 1
    fi

    pass_file="$(mktemp)"
    chmod 600 "${pass_file}"
    printf '%s' "${SPLUNK_SSH_PASS}" > "${pass_file}"

    sshpass -f "${pass_file}" scp \
        -P "${SPLUNK_SSH_PORT}" \
        -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        -o PubkeyAuthentication=no \
        -o PreferredAuthentications=password \
        -q \
        "${local_path}" "${ssh_target}:${remote_path}"
    local rc=$?
    rm -f "${pass_file}"
    return "${rc}"
}

cleanup_remote_stage_file() {
    local remote_path="$1"
    local ssh_target="${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}"
    local pass_file

    [[ -z "${remote_path}" ]] && return 0

    if ! command -v sshpass >/dev/null 2>&1; then
        return 0
    fi

    pass_file="$(mktemp)"
    chmod 600 "${pass_file}"
    printf '%s' "${SPLUNK_SSH_PASS}" > "${pass_file}"

    sshpass -f "${pass_file}" ssh \
        -p "${SPLUNK_SSH_PORT}" \
        -o ConnectTimeout=15 \
        -o StrictHostKeyChecking=accept-new \
        -o PubkeyAuthentication=no \
        -o PreferredAuthentications=password \
        -q \
        "${ssh_target}" "rm -f '${remote_path}'" >/dev/null 2>&1 || true

    rm -f "${pass_file}"
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

    local response http_code body
    local abs_file_path
    abs_file_path="$(cd "$(dirname "${file_path}")" && pwd)/$(basename "${file_path}")"
    local file_dir file_name
    file_dir="$(dirname "${abs_file_path}")"
    file_name="$(basename "${abs_file_path}")"

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
        response=$(install_via_server_path "${abs_file_path}" "${update_flag}")
    else
        # Splunk is remote — try direct REST upload first.
        log "Trying direct REST upload to remote Splunk..."
        response=$(install_via_rest_upload "${abs_file_path}" "${update_flag}")
        http_code=$(echo "${response}" | tail -1)
        body=$(echo "${response}" | sed '$d')

        if [[ "${http_code}" -lt 200 || "${http_code}" -ge 400 ]]; then
            local remote_tmp
            remote_tmp="/tmp/${file_name%.*}.$$.${RANDOM}.$(basename "${file_name}")"

            log "REST upload returned HTTP ${http_code}; falling back to SSH staging."
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
            response=$(install_via_server_path "${remote_tmp}" "${update_flag}")
            cleanup_remote_stage_file "${remote_tmp}"
        fi
    fi

    http_code=$(echo "${response}" | tail -1)
    body=$(echo "${response}" | sed '$d')

    local app_name
    app_name=$(echo "${body}" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    entries = data.get('entry', [])
    if entries:
        print(entries[0].get('name', ''))
    else:
        msgs = data.get('messages', [])
        for m in msgs:
            if m.get('type') == 'ERROR':
                print('ERROR: ' + m.get('text', 'Unknown error'), file=sys.stderr)
                sys.exit(1)
except Exception:
    print('', end='')
" 2>&1 || true)

    if [[ "${app_name}" == ERROR:* ]]; then
        log "${app_name}"
        log "Installation failed (HTTP ${http_code})."
        exit 1
    fi

    if [[ -n "${app_name}" ]]; then
        log "SUCCESS: App '${app_name}' installed (HTTP ${http_code})"

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
    else
        log "WARNING: Install completed (HTTP ${http_code}) but could not parse app name."
        log "Check Splunk: ${SPLUNK_HOME}/etc/apps/"
    fi

    log ""
    log "Note: A Splunk restart may be required to activate the app."
}

# ── Main ────────────────────────────────────────────────────────────

main() {
    echo "=== Splunk App Installer ==="
    echo ""

    mkdir -p "${PROJECT_TA_DIR}"
    mkdir -p "${TA_CACHE}"

    prompt_source

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
            download_from_splunkbase
            ;;
        *)
            log "ERROR: Unknown source '${SOURCE}'"
            exit 1
            ;;
    esac

    prompt_update
    prompt_splunk_creds
    splunk_auth
    install_app "${APP_FILE}"
}

main
