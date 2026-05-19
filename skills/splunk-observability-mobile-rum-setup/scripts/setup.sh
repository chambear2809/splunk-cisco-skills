#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_observability_cloud_settings

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-mobile-rum-rendered"
DEFAULT_SPEC="${SKILL_DIR}/template.example"

usage() {
    cat <<'EOF'
Splunk Observability Mobile RUM setup

Usage:
  bash skills/splunk-observability-mobile-rum-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                         Render snippets only (default)
  --render-patches                 Render source patch files, do not apply
  --apply-patches                  Apply rendered source patches; requires --accept-mobile-rum-source-edit
  --validate                       Run validate.sh against the output directory

Core options:
  --spec PATH                      YAML or JSON spec (default: template.example)
  --output-dir DIR                 Rendered output directory
  --source-mode MODE               render-snippets | render-patches | apply-patches
  --realm REALM                    Splunk Observability realm
  --platform PLATFORM              ios | android | react_native | flutter (repeatable)
  --app-root DIR                   App source root for generated patches
  --app-name NAME                  App name for RUM
  --bundle-id ID                   iOS bundle id
  --application-id ID              Android application id
  --deployment-environment ENV     prod | staging | dev | qa ...
  --app-version VERSION            Release version
  --release-name NAME              Release name global attribute
  --build-number VALUE             Release build global attribute
  --validation-url URL             Backend URL for Server-Timing validation (repeatable)
  --webview-url URL                WebView URL that needs Browser RUM handoff (repeatable)

Version pins:
  --ios-agent-version VERSION
  --android-agent-version VERSION
  --android-gradle-plugins-version VERSION
  --react-native-agent-version VERSION
  --react-native-session-replay-version VERSION
  --flutter-agent-version VERSION
  --flutter-session-replay-version VERSION
  --allow-latest-version           Permit latest, +, or otherwise unpinned versions

Session Replay:
  --enable-session-replay
  --accept-session-replay-enterprise
  --session-replay-sampler-ratio FLOAT

Privacy:
  --privacy-ignore-url URL_OR_REGEX
  --privacy-redact-query-strings
  --user-tracking-mode MODE

Credential references:
  --rum-token-file PATH            RUM token file reference for runbooks/snippets
  --o11y-token-file PATH           Org access-token file for dSYM/mapping uploads
  --rum-token-ref NAME             Placeholder/env ref to use in rendered assets
  --allow-loose-token-perms        Warn instead of failing when token files are not mode 600

Source edit gate:
  --accept-mobile-rum-source-edit  Required for --apply-patches

Validation passthrough:
  --check-server-timing URL        validate.sh live Server-Timing check
  --check-server-timing-header TXT validate.sh offline header text check

Common:
  --dry-run
  --json
  --help

Direct token flags such as --rum-token, --access-token, --token, --bearer-token,
--api-token, --o11y-token, --sf-token, --hec-token, --platform-hec-token, and
--api-key are rejected. Use token files or build-time placeholders.
EOF
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

check_secret_file_perms() {
    local label="$1"
    local path="$2"
    local allow_loose="$3"
    [[ -z "${path}" ]] && return 0
    if [[ ! -f "${path}" ]]; then
        log "ERROR: ${label} file not found: ${path}"
        return 1
    fi
    local mode
    mode="$(python3 - "$path" <<'PY'
import os
import stat
import sys
print(oct(stat.S_IMODE(os.stat(sys.argv[1]).st_mode)))
PY
)"
    if [[ "${mode}" != "0o600" && "${mode}" != "0o400" ]]; then
        if [[ "${allow_loose}" == "true" ]]; then
            log "WARNING: ${label} file should be chmod 600 or 400: ${path} (${mode})"
        else
            log "ERROR: ${label} file must be chmod 600 or 400: ${path} (${mode})"
            return 1
        fi
    fi
}

MODE_VALIDATE=false
MODE_APPLY_PATCHES=false
ACCEPT_SOURCE_EDIT=false
ALLOW_LOOSE_TOKEN_PERMS=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
SPEC="${DEFAULT_SPEC}"
RUM_TOKEN_FILE="${SPLUNK_O11Y_RUM_TOKEN_FILE:-}"
O11Y_TOKEN_FILE="${SPLUNK_O11Y_TOKEN_FILE:-}"
RUM_TOKEN_FILE_EXPLICIT=false
O11Y_TOKEN_FILE_EXPLICIT=false

RENDER_ARGS=()
VALIDATE_ARGS=()

pass_arg() { RENDER_ARGS+=("$1" "$2"); }
pass_flag() { RENDER_ARGS+=("$1"); }

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render)
            pass_arg --source-mode "render-snippets"
            shift
            ;;
        --render-patches)
            pass_arg --source-mode "render-patches"
            shift
            ;;
        --apply-patches)
            MODE_APPLY_PATCHES=true
            pass_arg --source-mode "apply-patches"
            shift
            ;;
        --validate)
            MODE_VALIDATE=true
            shift
            ;;
        --source-mode)
            require_arg "$1" "$#" || exit 1
            if [[ "$2" == "apply-patches" ]]; then
                MODE_APPLY_PATCHES=true
            fi
            pass_arg --source-mode "$2"
            shift 2
            ;;
        --accept-mobile-rum-source-edit)
            ACCEPT_SOURCE_EDIT=true
            pass_flag --accept-mobile-rum-source-edit
            shift
            ;;
        --accept-session-replay-enterprise)
            pass_flag --accept-session-replay-enterprise
            shift
            ;;
        --allow-latest-version)
            pass_flag --allow-latest-version
            shift
            ;;
        --allow-lower-android-api)
            pass_flag --allow-lower-android-api
            shift
            ;;
        --allow-loose-token-perms)
            ALLOW_LOOSE_TOKEN_PERMS=true
            shift
            ;;
        --dry-run)
            pass_flag --dry-run
            shift
            ;;
        --json)
            pass_flag --json
            shift
            ;;
        --spec)
            require_arg "$1" "$#" || exit 1
            SPEC="$2"
            shift 2
            ;;
        --output-dir)
            require_arg "$1" "$#" || exit 1
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --rum-token-file)
            require_arg "$1" "$#" || exit 1
            RUM_TOKEN_FILE="$2"
            RUM_TOKEN_FILE_EXPLICIT=true
            pass_arg --rum-token-file "$2"
            shift 2
            ;;
        --o11y-token-file)
            require_arg "$1" "$#" || exit 1
            O11Y_TOKEN_FILE="$2"
            O11Y_TOKEN_FILE_EXPLICIT=true
            pass_arg --o11y-token-file "$2"
            shift 2
            ;;
        --realm|--platform|--app-root|--app-name|--bundle-id|--application-id|--deployment-environment|--app-version|--release-name|--build-number|--validation-url|--webview-url|--ios-agent-version|--android-agent-version|--android-gradle-plugins-version|--react-native-agent-version|--react-native-session-replay-version|--flutter-agent-version|--flutter-session-replay-version|--session-replay-sampler-ratio|--privacy-ignore-url|--user-tracking-mode|--rum-token-ref)
            require_arg "$1" "$#" || exit 1
            pass_arg "$1" "$2"
            shift 2
            ;;
        --enable-session-replay|--privacy-redact-query-strings)
            pass_flag "$1"
            shift
            ;;
        --check-server-timing|--check-server-timing-header)
            require_arg "$1" "$#" || exit 1
            VALIDATE_ARGS+=("$1" "$2")
            shift 2
            ;;
        --rum-token|--access-token|--token|--bearer-token|--api-token|--o11y-token|--sf-token|--hec-token|--platform-hec-token|--api-key)
            log "ERROR: Direct token flag $1 is rejected. Use a token file or placeholder reference."
            exit 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    exec bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}" "${VALIDATE_ARGS[@]}"
fi

if [[ "${MODE_APPLY_PATCHES}" == "true" && "${ACCEPT_SOURCE_EDIT}" != "true" ]]; then
    log "ERROR: --apply-patches requires --accept-mobile-rum-source-edit."
    exit 2
fi

if [[ "${RUM_TOKEN_FILE_EXPLICIT}" == "true" ]]; then
    check_secret_file_perms "RUM token" "${RUM_TOKEN_FILE}" "${ALLOW_LOOSE_TOKEN_PERMS}"
fi
if [[ "${O11Y_TOKEN_FILE_EXPLICIT}" == "true" ]]; then
    check_secret_file_perms "Splunk Observability org access token" "${O11Y_TOKEN_FILE}" "${ALLOW_LOOSE_TOKEN_PERMS}"
fi

PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi

"${PYTHON_BIN}" "${SCRIPT_DIR}/render_assets.py" \
    --spec "${SPEC}" \
    --output-dir "${OUTPUT_DIR}" \
    "${RENDER_ARGS[@]}"

if [[ "${MODE_APPLY_PATCHES}" == "true" ]]; then
    ACCEPT_MOBILE_RUM_SOURCE_EDIT=true "${OUTPUT_DIR}/apply-source-patches.sh"
fi
