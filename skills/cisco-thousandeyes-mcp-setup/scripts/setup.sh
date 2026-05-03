#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

DEFAULT_OUTPUT_DIR="${PROJECT_ROOT}/cisco-thousandeyes-mcp-rendered"

usage() {
    cat <<'EOF'
Cisco ThousandEyes MCP Server setup

Usage:
  bash skills/cisco-thousandeyes-mcp-setup/scripts/setup.sh [mode] --client CLIENT[,CLIENT...] [options]

Modes:
  --render                Render client configurations (default if no mode given)
  --apply                 Render then write configurations into actual client config locations
  --validate              Run static validation against an already-rendered output directory
  --dry-run               Show the plan without writing
  --json                  Emit JSON dry-run output

Required:
  --client LIST           Comma-separated client names. Valid: cursor, claude, codex, vscode, kiro

Options:
  --auth bearer|oauth2    Authentication flow (default: bearer)
  --te-token-file PATH    ThousandEyes API token file (Bearer flow). chmod 600 required.
  --allow-loose-token-perms  Skip the chmod-600 token-permission preflight (warns instead)
  --accept-te-mcp-write-tools
                          Enable Create/Update/Delete Synthetic Test, Run Instant Test, Deploy Template
                          tools in clients that support per-tool gating. Default: write tools NOT enabled.
  --cursor-scope user|workspace
                          Cursor config target scope (default: user)
  --cursor-marketplace-link true|false (default: true)
  --claude-connector-name NAME (default: "ThousandEyes MCP Server")
  --claude-auto-allow-read-only true|false (default: true)
  --codex-server-name NAME (default: thousandeyes)
  --codex-replace-existing true|false (default: true)
  --vscode-use-input-prompt true|false (default: true)
  --kiro-use-oauth2 true|false (default: false)
  --output-dir DIR        Rendered output directory
  --explain               Print plan in plain English (no API calls or writes)
  --help                  Show this help

Direct token flags such as --te-token, --access-token, --token, --bearer-token, --api-token are rejected.
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

MODE_RENDER=true
MODE_APPLY=false
MODE_VALIDATE=false
DRY_RUN=false
JSON_OUTPUT=false
EXPLAIN=false

OUTPUT_DIR="${DEFAULT_OUTPUT_DIR}"
CLIENTS=""
AUTH="bearer"
TE_TOKEN_FILE=""
ALLOW_LOOSE_TOKEN_PERMS=false
ACCEPT_WRITE_TOOLS=false
CURSOR_SCOPE="user"
CURSOR_MARKETPLACE_LINK="true"
CLAUDE_CONNECTOR_NAME="ThousandEyes MCP Server"
CLAUDE_AUTO_ALLOW_READ_ONLY="true"
CODEX_SERVER_NAME="thousandeyes"
CODEX_REPLACE_EXISTING="true"
VSCODE_USE_INPUT_PROMPT="true"
KIRO_USE_OAUTH2="false"

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

# Mode flags toggle the corresponding action; default render-only when none
# of --render/--apply/--validate is specified explicitly. We don't auto-imply
# render from --apply because the apply path always renders first and needs
# the same artifacts on disk.
while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) MODE_RENDER=true; shift ;;
        --apply) MODE_APPLY=true; MODE_RENDER=true; shift ;;
        --validate) MODE_VALIDATE=true; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --explain) EXPLAIN=true; shift ;;
        --client|--clients) require_arg "$1" "$#" || exit 1; CLIENTS="$2"; shift 2 ;;
        --auth) require_arg "$1" "$#" || exit 1; AUTH="$2"; shift 2 ;;
        --te-token-file) require_arg "$1" "$#" || exit 1; TE_TOKEN_FILE="$2"; shift 2 ;;
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true; shift ;;
        --accept-te-mcp-write-tools) ACCEPT_WRITE_TOOLS=true; shift ;;
        --cursor-scope) require_arg "$1" "$#" || exit 1; CURSOR_SCOPE="$2"; shift 2 ;;
        --cursor-marketplace-link) require_arg "$1" "$#" || exit 1; CURSOR_MARKETPLACE_LINK="$2"; shift 2 ;;
        --claude-connector-name) require_arg "$1" "$#" || exit 1; CLAUDE_CONNECTOR_NAME="$2"; shift 2 ;;
        --claude-auto-allow-read-only) require_arg "$1" "$#" || exit 1; CLAUDE_AUTO_ALLOW_READ_ONLY="$2"; shift 2 ;;
        --codex-server-name) require_arg "$1" "$#" || exit 1; CODEX_SERVER_NAME="$2"; shift 2 ;;
        --codex-replace-existing) require_arg "$1" "$#" || exit 1; CODEX_REPLACE_EXISTING="$2"; shift 2 ;;
        --vscode-use-input-prompt) require_arg "$1" "$#" || exit 1; VSCODE_USE_INPUT_PROMPT="$2"; shift 2 ;;
        --kiro-use-oauth2) require_arg "$1" "$#" || exit 1; KIRO_USE_OAUTH2="$2"; shift 2 ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --te-token|--access-token|--token|--bearer-token|--api-token)
            reject_secret_arg "$1" "--te-token-file"
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

OUTPUT_DIR="$(resolve_abs_path "${OUTPUT_DIR}")"

if [[ -z "${CLIENTS}" ]]; then
    log "ERROR: --client is required (comma-separated; valid: cursor, claude, codex, vscode, kiro)."
    exit 1
fi

case "${AUTH}" in
    bearer|oauth2) ;;
    *)
        log "ERROR: --auth must be bearer or oauth2."
        exit 1
        ;;
esac

case "${CURSOR_SCOPE}" in
    user|workspace) ;;
    *)
        log "ERROR: --cursor-scope must be user or workspace."
        exit 1
        ;;
esac

# Token-permission preflight (mirrors splunk-observability-otel-collector-setup
# lines 441-484). The file is never read by the renderer; this guard ensures
# the operator has not left it world-readable on disk.
_token_perm_octal() {
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

_check_token_perms() {
    local label="$1" path="$2"
    [[ -n "${path}" && -r "${path}" ]] || return 0
    local mode
    mode="$(_token_perm_octal "${path}")"
    if [[ -z "${mode}" ]]; then
        log "  WARN: Could not stat ${label} (${path}) for permission check; skipping."
        return 0
    fi
    if [[ "${mode}" != "600" && "${mode}" != "0600" ]]; then
        if [[ "${ALLOW_LOOSE_TOKEN_PERMS:-false}" == "true" ]]; then
            log "  WARN: ${label} permissions are ${mode}; --allow-loose-token-perms is set, proceeding."
            return 0
        fi
        log "ERROR: ${label} (${path}) is mode ${mode}; tokens must be mode 600."
        log "       Run 'chmod 600 ${path}' to fix, or pass --allow-loose-token-perms to override."
        return 1
    fi
    return 0
}

if [[ "${AUTH}" == "bearer" && -n "${TE_TOKEN_FILE}" ]]; then
    _check_token_perms "--te-token-file" "${TE_TOKEN_FILE}" || exit 1
fi

if [[ "${MODE_APPLY}" == "true" && "${AUTH}" == "bearer" ]]; then
    if [[ -z "${TE_TOKEN_FILE}" || ! -r "${TE_TOKEN_FILE}" ]]; then
        log "ERROR: --apply with --auth bearer requires a readable --te-token-file."
        exit 1
    fi
fi

if [[ "${EXPLAIN}" == "true" ]]; then
    cat <<EXPLAIN
ThousandEyes MCP Server Setup — execution plan
==============================================
  Output directory: ${OUTPUT_DIR}
  Clients:          ${CLIENTS}
  Auth flow:        ${AUTH}
  Token file:       ${TE_TOKEN_FILE:-<none, OAuth2 or env-var path>}
  Write tools enabled: $(bool_text "${ACCEPT_WRITE_TOOLS}")
  Mode: render=$(bool_text "${MODE_RENDER}") apply=$(bool_text "${MODE_APPLY}") validate=$(bool_text "${MODE_VALIDATE}")

  This will:
  1. Render mcp/<client>.mcp.json (or mcp/codex-register-te-mcp.sh) for each
     selected client under ${OUTPUT_DIR}.
  2. Render mcp/README.md and metadata.json.
$(if [[ "${MODE_APPLY}" == "true" ]]; then echo "  3. Apply: copy each rendered config into the user's actual client config"; echo "     directory (after a confirmation prompt)."; fi)
EXPLAIN
    exit 0
fi

RENDER_ARGS=(
    --output-dir "${OUTPUT_DIR}"
    --clients "${CLIENTS}"
    --auth "${AUTH}"
    --te-token-file "${TE_TOKEN_FILE}"
    --cursor-scope "${CURSOR_SCOPE}"
    --cursor-marketplace-link "${CURSOR_MARKETPLACE_LINK}"
    --claude-connector-name "${CLAUDE_CONNECTOR_NAME}"
    --claude-auto-allow-read-only "${CLAUDE_AUTO_ALLOW_READ_ONLY}"
    --codex-server-name "${CODEX_SERVER_NAME}"
    --codex-replace-existing "${CODEX_REPLACE_EXISTING}"
    --vscode-use-input-prompt "${VSCODE_USE_INPUT_PROMPT}"
    --kiro-use-oauth2 "${KIRO_USE_OAUTH2}"
    --accept-write-tools "$(bool_text "${ACCEPT_WRITE_TOOLS}")"
)
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

if [[ "${MODE_APPLY}" == "true" ]]; then
    log "Apply: copy rendered configs into client config locations."
    log "  Cursor user scope:  cp ${OUTPUT_DIR}/mcp/cursor.mcp.json ~/.cursor/mcp.json"
    log "  Claude:             open Settings > Connectors > Add custom connector"
    log "  Codex:              bash ${OUTPUT_DIR}/mcp/codex-register-te-mcp.sh"
    log "  VS Code:            cp ${OUTPUT_DIR}/mcp/vscode.mcp.json <vscode-mcp-config>"
    log "  AWS Kiro:           cp ${OUTPUT_DIR}/mcp/kiro.mcp.json ~/.kiro/settings/mcp.json"
    log "These commands are NOT executed automatically; review the rendered files first."
fi
