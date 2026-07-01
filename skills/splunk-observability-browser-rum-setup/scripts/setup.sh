#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${SKILLS_ROOT}/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

RENDER=false
UPLOAD_SOURCE_MAPS=false
JSON_OUTPUT=false
OUTPUT_DIR="${SKILLS_ROOT}/../splunk-observability-browser-rum-rendered"
ASSETS_DIR=""
TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
APPLICATION_NAME="frontend"
ENVIRONMENT_NAME="prod"
VERSION="1.0.0"
REALM="${SPLUNK_O11Y_REALM:-us0}"
FRAMEWORK="generic"
TOKEN_REFERENCE="\${SPLUNK_RUM_TOKEN}"
ENABLE_SESSION_REPLAY=false
MASK_ALL_TEXT=true
SAMPLE_RATE="0.05"

usage() {
    cat <<'EOF'
Splunk Observability Browser RUM Setup

Usage:
  bash skills/splunk-observability-browser-rum-setup/scripts/setup.sh --render [options]
  bash skills/splunk-observability-browser-rum-setup/scripts/setup.sh --upload-source-maps [options]

Options:
  --render                       Render Browser RUM source/build assets
  --upload-source-maps           Run the reviewed rendered source-map helper
  --json                         Emit JSON render output
  --output-dir DIR               Render output directory
  --assets-dir DIR               Built frontend assets for source-map upload
  --token-file PATH              Observability API token file for source maps
  --application-name NAME        Splunk RUM applicationName
  --environment ENV              Deployment environment
  --version VERSION              App version used for source maps
  --realm REALM                  Splunk Observability realm
  --framework NAME               generic, cdn, npm, next, vite, webpack
  --rum-token-reference VALUE    Build-time/browser token reference, not the token value
  --enable-session-replay        Render Session Replay recorder snippet and privacy plan
  --mask-all-text true|false     Session Replay privacy default
  --sample-rate RATE             Session Replay sample rate placeholder
  --help                         Show this help

Do not pass RUM token values or Observability API tokens on argv. Use a
build-time reference for Browser RUM and SPLUNK_O11Y_TOKEN_FILE for source maps.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --upload-source-maps) UPLOAD_SOURCE_MAPS=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --assets-dir) require_arg "$1" "$#" || exit 1; ASSETS_DIR="$2"; shift 2 ;;
        --token-file) require_arg "$1" "$#" || exit 1; TOKEN_FILE="$2"; shift 2 ;;
        --application-name) require_arg "$1" "$#" || exit 1; APPLICATION_NAME="$2"; shift 2 ;;
        --environment) require_arg "$1" "$#" || exit 1; ENVIRONMENT_NAME="$2"; shift 2 ;;
        --version) require_arg "$1" "$#" || exit 1; VERSION="$2"; shift 2 ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --framework) require_arg "$1" "$#" || exit 1; FRAMEWORK="$2"; shift 2 ;;
        --rum-token-reference) require_arg "$1" "$#" || exit 1; TOKEN_REFERENCE="$2"; shift 2 ;;
        --enable-session-replay) ENABLE_SESSION_REPLAY=true; shift ;;
        --mask-all-text) require_arg "$1" "$#" || exit 1; MASK_ALL_TEXT="$2"; shift 2 ;;
        --sample-rate) require_arg "$1" "$#" || exit 1; SAMPLE_RATE="$2"; shift 2 ;;
        --token|--access-token|--api-token|--o11y-token|--sf-token)
            reject_secret_arg "$1" "SPLUNK_O11Y_TOKEN_FILE or a build-time token reference"
            exit 1
            ;;
        --token=*|--access-token=*|--api-token=*|--o11y-token=*|--sf-token=*)
            reject_secret_arg "${1%%=*}" "SPLUNK_O11Y_TOKEN_FILE or a build-time token reference"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ "${RENDER}" == "true" && "${UPLOAD_SOURCE_MAPS}" == "true" ]]; then
    echo "ERROR: choose either --render or --upload-source-maps." >&2
    exit 2
fi

if [[ "${UPLOAD_SOURCE_MAPS}" == "true" ]]; then
    upload_helper="${OUTPUT_DIR}/source-map-upload.sh"
    [[ -f "${upload_helper}" ]] || {
        echo "ERROR: missing reviewed helper: ${upload_helper}; render and review it first." >&2
        exit 2
    }
    [[ -n "${ASSETS_DIR}" && -d "${ASSETS_DIR}" ]] || {
        echo "ERROR: --assets-dir must name an existing built-asset directory." >&2
        exit 2
    }
    [[ -n "${TOKEN_FILE}" && -f "${TOKEN_FILE}" ]] || {
        echo "ERROR: --token-file (or SPLUNK_O11Y_TOKEN_FILE) must name an existing token file." >&2
        exit 2
    }
    token_mode="$(stat -f '%Lp' "${TOKEN_FILE}" 2>/dev/null || stat -c '%a' "${TOKEN_FILE}" 2>/dev/null || true)"
    [[ "${token_mode}" == "600" || "${token_mode}" == "400" ]] || {
        echo "ERROR: token file permissions must be 0600 or 0400 (found ${token_mode:-unknown})." >&2
        exit 2
    }
    SPLUNK_O11Y_TOKEN_FILE="${TOKEN_FILE}" ASSETS_DIR="${ASSETS_DIR}" bash "${upload_helper}"
    exit 0
fi

if [[ "${RENDER}" == "false" ]]; then
    RENDER=true
fi

args=(
    --output-dir "${OUTPUT_DIR}"
    --application-name "${APPLICATION_NAME}"
    --environment "${ENVIRONMENT_NAME}"
    --version "${VERSION}"
    --realm "${REALM}"
    --framework "${FRAMEWORK}"
    --rum-token-reference "${TOKEN_REFERENCE}"
    --mask-all-text "${MASK_ALL_TEXT}"
    --sample-rate "${SAMPLE_RATE}"
)
[[ "${ENABLE_SESSION_REPLAY}" == "true" ]] && args+=(--enable-session-replay)
[[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
python3 "${SCRIPT_DIR}/render_assets.py" "${args[@]}"
