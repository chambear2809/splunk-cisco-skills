#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR=""
KEEP_OUTPUT=false
OFFLINE_DOCS=false
SKIP_LIVE=false
JSON_OUTPUT=false
TEMP_OUTPUT=false
LOOSE_KEY=""
EMPTY_KEY=""
EXPECTED_FAILURE_OUT="/tmp/galileo-mcp-expected-failure.out"

cleanup() {
    rm -f "${EXPECTED_FAILURE_OUT}"
    if [[ -n "${LOOSE_KEY}" ]]; then
        rm -f "${LOOSE_KEY}"
    fi
    if [[ -n "${EMPTY_KEY}" ]]; then
        rm -f "${EMPTY_KEY}"
    fi
    if [[ "${TEMP_OUTPUT}" == "true" && "${KEEP_OUTPUT}" != "true" && -n "${OUTPUT_DIR}" ]]; then
        rm -rf "${OUTPUT_DIR}"
        rm -rf "${OUTPUT_DIR}-spec"
    fi
}
trap cleanup EXIT

usage() {
    cat <<'EOF'
Galileo MCP Server deep audit

Usage:
  bash skills/galileo-mcp-server-setup/scripts/deep_audit.sh [options]

Options:
  --output-dir DIR       Use a specific rendered output directory
  --keep-output          Do not remove temporary rendered output
  --offline-docs         Use embedded docs markers instead of live llms-full.txt
  --skip-live            Skip live Galileo MCP and docs-index checks
  --json                 Emit JSON for live probe/product audit where supported
  --help                 Show this help

This is a validation gate, not an installer. It renders into a temporary
directory by default and never writes client configuration files.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --keep-output) KEEP_OUTPUT=true; shift ;;
        --offline-docs) OFFLINE_DOCS=true; shift ;;
        --skip-live) SKIP_LIVE=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="$(mktemp -d /tmp/galileo-mcp-deep-audit.XXXXXX)"
    TEMP_OUTPUT=true
else
    OUTPUT_DIR="$(python3 - "$OUTPUT_DIR" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve(), end="")
PY
)"
    mkdir -p "${OUTPUT_DIR}"
fi

run_step() {
    log "deep-audit: $*"
    "$@"
}

expect_failure() {
    local description="$1"
    shift
    log "deep-audit: expecting failure: ${description}"
    if "$@" >"${EXPECTED_FAILURE_OUT}" 2>&1; then
        cat "${EXPECTED_FAILURE_OUT}" >&2
        log "ERROR: Expected failure did not occur: ${description}"
        exit 1
    fi
}

run_step python3 -m py_compile \
    "${SCRIPT_DIR}/render_assets.py" \
    "${SCRIPT_DIR}/probe_mcp.py" \
    "${SCRIPT_DIR}/audit_product_coverage.py"

if command -v ruff >/dev/null 2>&1; then
    run_step ruff check \
        "${SCRIPT_DIR}/render_assets.py" \
        "${SCRIPT_DIR}/probe_mcp.py" \
        "${SCRIPT_DIR}/audit_product_coverage.py"
else
    log "deep-audit: ruff not found; skipping Python lint."
fi

run_step bash -n \
    "${SCRIPT_DIR}/setup.sh" \
    "${SCRIPT_DIR}/validate.sh" \
    "${SCRIPT_DIR}/deep_audit.sh"

if command -v shellcheck >/dev/null 2>&1; then
    run_step shellcheck \
        "${SCRIPT_DIR}/setup.sh" \
        "${SCRIPT_DIR}/validate.sh" \
        "${SCRIPT_DIR}/deep_audit.sh"
else
    log "deep-audit: shellcheck not found; skipping shell lint."
fi

run_step bash "${SCRIPT_DIR}/setup.sh" \
    --dry-run \
    --json \
    --client all

run_step bash "${SCRIPT_DIR}/setup.sh" \
    --render \
    --validate \
    --client cursor,claude,codex,vscode,kiro \
    --output-dir "${OUTPUT_DIR}"

run_step bash "${SCRIPT_DIR}/setup.sh" \
    --render \
    --validate \
    --spec "${SKILL_DIR}/template.example" \
    --output-dir "${OUTPUT_DIR}-spec"

if command -v node >/dev/null 2>&1; then
    run_step node --check "${OUTPUT_DIR}/mcp/run-galileo-mcp.js"
else
    log "deep-audit: node not found; skipping generated JS check."
fi

run_step bash -n \
    "${OUTPUT_DIR}/mcp/run-galileo-mcp.sh" \
    "${OUTPUT_DIR}/mcp/codex-register-galileo-mcp.sh"

if command -v shellcheck >/dev/null 2>&1; then
    run_step shellcheck \
        "${OUTPUT_DIR}/mcp/run-galileo-mcp.sh" \
        "${OUTPUT_DIR}/mcp/codex-register-galileo-mcp.sh"
fi

run_step python3 - "${OUTPUT_DIR}" <<'PY'
from pathlib import Path
import json
import re
import sys

root = Path(sys.argv[1])
for cfg in ["cursor.mcp.json", "vscode.mcp.json", "claude.mcp.json", "kiro.mcp.json"]:
    json.loads((root / "mcp" / cfg).read_text(encoding="utf-8"))

metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
catalog = json.loads((root / "coverage/tool-catalog.json").read_text(encoding="utf-8"))
gap = json.loads((root / "coverage/product-gap-matrix.json").read_text(encoding="utf-8"))

if metadata["expected_tool_count"] != catalog["tool_count"]:
    raise SystemExit("metadata/tool-catalog tool counts differ")
if len(gap.get("product_gap_matrix") or []) < 18:
    raise SystemExit("product gap matrix is unexpectedly narrow")
for tool in catalog["tools"]:
    if len(tool["schema_sha256"]) != 64:
        raise SystemExit(f"invalid schema hash for {tool['name']}")

text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in root.rglob("*") if p.is_file())
checks = [
    ("placeholder YOUR-API-KEY", "YOUR-API-KEY" in text),
    ("inline bearer token-like value", re.search(r"Bearer [A-Za-z0-9._-]{12,}", text)),
    (
        "inline Galileo-API-Key header value",
        re.search(r'"Galileo-API-Key"\s*:\s*"(?!\$\{)[^"]{8,}"', text),
    ),
]
for reason, matched in checks:
    if matched:
        raise SystemExit(reason)
print("Generated artifact deep audit passed.")
PY

expect_failure "direct secret flag rejection" \
    bash "${SCRIPT_DIR}/setup.sh" --authorization=secret-value

LOOSE_KEY="$(mktemp /tmp/galileo-mcp-loose-key.XXXXXX)"
EMPTY_KEY="$(mktemp /tmp/galileo-mcp-empty-key.XXXXXX)"
printf 'dummy' >"${LOOSE_KEY}"
chmod 0644 "${LOOSE_KEY}"
chmod 0600 "${EMPTY_KEY}"

expect_failure "loose key file rejection" \
    python3 "${SCRIPT_DIR}/probe_mcp.py" \
        --auth-check \
        --galileo-api-key-file "${LOOSE_KEY}"

expect_failure "empty key file rejection" \
    python3 "${SCRIPT_DIR}/probe_mcp.py" \
        --auth-check \
        --galileo-api-key-file "${EMPTY_KEY}"

if [[ "${SKIP_LIVE}" != "true" ]]; then
    PROBE_ARGS=(--fail-on-drift)
    PRODUCT_ARGS=()
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        PROBE_ARGS+=(--json)
        PRODUCT_ARGS+=(--json)
    fi
    if [[ "${OFFLINE_DOCS}" == "true" ]]; then
        PRODUCT_ARGS+=(--offline)
    fi
    run_step python3 "${SCRIPT_DIR}/probe_mcp.py" "${PROBE_ARGS[@]}"
    run_step python3 "${SCRIPT_DIR}/audit_product_coverage.py" "${PRODUCT_ARGS[@]}"
else
    run_step python3 "${SCRIPT_DIR}/audit_product_coverage.py" --offline
fi

log "deep-audit: Galileo MCP Server skill passed."
if [[ "${KEEP_OUTPUT}" == "true" ]]; then
    log "deep-audit: kept rendered output at ${OUTPUT_DIR}"
fi
