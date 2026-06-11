#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/galileo-mcp-rendered"

usage() {
    cat <<'EOF'
Galileo MCP Server setup

Usage:
  bash skills/galileo-mcp-server-setup/scripts/setup.sh [mode] [options]

Modes:
  --render                         Render client configs (default)
  --validate                       Validate already-rendered output
  --probe                          Probe live MCP metadata without tenant mutation
  --doctor                         Render, validate, and run no-secret probe
  --dry-run                        Show render plan without writing
  --json                           Emit JSON where supported

Options:
  --client LIST                    Comma-separated clients: cursor,claude,codex,vscode,kiro
                                   Aliases: all, claude-code, vs-code, aws-kiro
                                   (default: cursor,claude,codex,vscode,kiro)
  --spec PATH                      Optional YAML/JSON spec (api_version: galileo-mcp-server-setup/v1)
  --output-dir DIR                 Rendered output directory
  --mcp-url URL                    Explicit Galileo MCP URL
  --galileo-console-url URL        Derive MCP URL from a self-hosted console URL
  --galileo-api-key-file PATH      Optional chmod-600 API key file for read-only auth check
  --accept-galileo-mcp-write-tools Render stronger warnings/enablement guidance for
                                   dataset and prompt creation tools
  --allow-loose-key-perms          Warn instead of failing if key file is not chmod 600
  --help                           Show this help

Direct secret flags such as --galileo-api-key, --api-key, --token, --password,
and --authorization are rejected. There is no --apply mode in v1.
EOF
}

bool_text() {
    if [[ "$1" == "true" ]]; then
        printf 'true'
    else
        printf 'false'
    fi
}

resolve_abs_path() {
    python3 - "$1" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
}

MODE_RENDER=false
MODE_VALIDATE=false
MODE_PROBE=false
DRY_RUN=false
JSON_OUTPUT=false
MODE_GIVEN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
CLIENTS=""
CLIENTS_SET=false
SPEC=""
MCP_URL=""
GALILEO_CONSOLE_URL=""
GALILEO_API_KEY_FILE=""
ACCEPT_WRITE_TOOLS=false
ALLOW_LOOSE_KEY_PERMS=false

if [[ $# -eq 0 ]]; then
    MODE_RENDER=true
    MODE_GIVEN=true
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; MODE_GIVEN=true; shift ;;
        --validate) MODE_VALIDATE=true; MODE_GIVEN=true; shift ;;
        --probe) MODE_PROBE=true; MODE_GIVEN=true; shift ;;
        --doctor)
            MODE_RENDER=true
            MODE_VALIDATE=true
            MODE_PROBE=true
            MODE_GIVEN=true
            shift
            ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --client|--clients) require_arg "$1" "$#" || exit 1; CLIENTS="$2"; CLIENTS_SET=true; shift 2 ;;
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --mcp-url) require_arg "$1" "$#" || exit 1; MCP_URL="$2"; shift 2 ;;
        --galileo-console-url) require_arg "$1" "$#" || exit 1; GALILEO_CONSOLE_URL="$2"; shift 2 ;;
        --galileo-api-key-file) require_arg "$1" "$#" || exit 1; GALILEO_API_KEY_FILE="$2"; shift 2 ;;
        --accept-galileo-mcp-write-tools) ACCEPT_WRITE_TOOLS=true; shift ;;
        --allow-loose-key-perms) ALLOW_LOOSE_KEY_PERMS=true; shift ;;
        --galileo-api-key|--api-key|--token|--password|--authorization|--bearer-token)
            reject_secret_arg "$1" "--galileo-api-key-file"
            exit 1
            ;;
        --galileo-api-key=*|--api-key=*|--token=*|--password=*|--authorization=*|--bearer-token=*)
            reject_secret_arg "${1%%=*}" "--galileo-api-key-file"
            exit 1
            ;;
        --apply)
            log "ERROR: --apply is intentionally not supported for galileo-mcp-server-setup v1."
            log "       Review rendered files and copy/install them manually."
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ "${MODE_GIVEN}" != "true" ]]; then
    MODE_RENDER=true
fi

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"
if [[ -n "${GALILEO_API_KEY_FILE}" ]]; then
    GALILEO_API_KEY_FILE="$(resolve_abs_path "${GALILEO_API_KEY_FILE}")"
fi

_file_perm_octal() {
    local target="$1"
    local mode=""
    if mode="$(stat -f '%A' "${target}" 2>/dev/null)"; then
        printf '%s' "${mode}"
        return 0
    fi
    if mode="$(stat -c '%a' "${target}" 2>/dev/null)"; then
        printf '%s' "${mode}"
        return 0
    fi
    printf ''
}

_check_key_perms() {
    local path="$1"
    [[ -n "${path}" && -r "${path}" ]] || return 0
    local mode
    mode="$(_file_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then
        log "  WARN: Could not stat --galileo-api-key-file (${path}); skipping permission check."
        return 0
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_KEY_PERMS}" == "true" ]]; then
            log "  WARN: --galileo-api-key-file permissions are ${mode}; proceeding because --allow-loose-key-perms is set."
            return 0
        fi
        log "ERROR: --galileo-api-key-file (${path}) is mode ${mode}; expected 600."
        log "       Run 'chmod 600 ${path}' or pass --allow-loose-key-perms for lab-only override."
        return 1
    fi
}

if [[ -n "${GALILEO_API_KEY_FILE}" ]]; then
    if [[ ! -r "${GALILEO_API_KEY_FILE}" ]]; then
        log "ERROR: --galileo-api-key-file is not readable: ${GALILEO_API_KEY_FILE}"
        exit 1
    fi
    _check_key_perms "${GALILEO_API_KEY_FILE}" || exit 1
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --spec "${SPEC}"
    --mcp-url "${MCP_URL}"
    --galileo-console-url "${GALILEO_CONSOLE_URL}"
    --galileo-api-key-file "${GALILEO_API_KEY_FILE}"
    --accept-write-tools "$(bool_text "${ACCEPT_WRITE_TOOLS}")"
)
if [[ "${CLIENTS_SET}" == "true" ]]; then
    RENDER_ARGS+=(--clients "${CLIENTS}")
fi
if [[ "${DRY_RUN}" == "true" ]]; then
    RENDER_ARGS+=(--dry-run)
fi
if [[ "${JSON_OUTPUT}" == "true" ]]; then
    RENDER_ARGS+=(--json)
fi

if [[ "${MODE_RENDER}" == "true" ]]; then
    python3 "${SCRIPT_DIR}/render_assets.py" "${RENDER_ARGS[@]}"
fi

if [[ "${DRY_RUN}" == "true" ]]; then
    exit 0
fi

if [[ "${MODE_VALIDATE}" == "true" ]]; then
    bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
fi

if [[ "${MODE_PROBE}" == "true" ]]; then
    PROBE_ARGS=()
    if [[ -n "${MCP_URL}" ]]; then
        PROBE_ARGS+=(--mcp-url "${MCP_URL}")
    fi
    if [[ -n "${GALILEO_CONSOLE_URL}" ]]; then
        PROBE_ARGS+=(--galileo-console-url "${GALILEO_CONSOLE_URL}")
    fi
    if [[ -n "${GALILEO_API_KEY_FILE}" ]]; then
        PROBE_ARGS+=(--auth-check --galileo-api-key-file "${GALILEO_API_KEY_FILE}")
    fi
    if [[ "${ALLOW_LOOSE_KEY_PERMS}" == "true" ]]; then
        PROBE_ARGS+=(--allow-loose-key-perms)
    fi
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        PROBE_ARGS+=(--json)
    fi
    python3 "${SCRIPT_DIR}/probe_mcp.py" "${PROBE_ARGS[@]}"
fi
