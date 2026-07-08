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
UNSAFE_SECRET_FIXTURE=""
EXPECTED_FAILURE_OUT="/tmp/galileo-mcp-expected-failure.out"

cleanup() {
    rm -f "${EXPECTED_FAILURE_OUT}"
    if [[ -n "${LOOSE_KEY}" ]]; then
        rm -f "${LOOSE_KEY}"
    fi
    if [[ -n "${EMPTY_KEY}" ]]; then
        rm -f "${EMPTY_KEY}"
    fi
    if [[ -n "${UNSAFE_SECRET_FIXTURE}" ]]; then
        rm -f "${UNSAFE_SECRET_FIXTURE}"
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

run_step python3 - "${SCRIPT_DIR}" <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, str(Path(sys.argv[1])))
import probe_mcp  # noqa: E402
import render_assets  # noqa: E402

expected = "https://api.galileo.ai/mcp/http/mcp"
for module in (probe_mcp, render_assets):
    actual = module.derive_mcp_url("", "https://app.galileo.ai")
    if actual != expected:
        raise SystemExit(f"{module.__name__} app URL derivation returned {actual!r}")
    loopback = module.derive_mcp_url("http://127.0.0.1:43199/mcp/http/mcp", "")
    if loopback != "http://127.0.0.1:43199/mcp/http/mcp":
        raise SystemExit(f"{module.__name__} rejected loopback HTTP validation")
    try:
        module.derive_mcp_url("http://api.galileo.ai/mcp/http/mcp", "")
    except ValueError:
        pass
    else:
        raise SystemExit(f"{module.__name__} accepted non-loopback cleartext HTTP")

clean_report = {
    "server_drift": [],
    "unknown_tools": [],
    "missing_tools": [],
    "schema_drift": [],
    "prompts_count": 0,
    "resources_count": 0,
}
if probe_mcp.report_has_drift(clean_report):
    raise SystemExit("clean MCP report was classified as drift")
server_drift_report = {**clean_report, "server_drift": [{"field": "version"}]}
if not probe_mcp.report_has_drift(server_drift_report):
    raise SystemExit("server identity/version drift was not classified as drift")
print("MCP URL derivation and drift classification checks passed.")
PY

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
    run_step node --check "${SKILL_DIR}/assets/stdio_streamable_http_bridge.js"
    run_step node --check "${OUTPUT_DIR}/mcp/run-galileo-mcp.js"
else
    log "deep-audit: node not found; skipping generated JS check."
fi

if grep -R -n 'mcp-remote' \
    "${OUTPUT_DIR}/mcp/run-galileo-mcp.js" \
    "${OUTPUT_DIR}/mcp/run-galileo-mcp.sh"; then
    log "ERROR: rendered bridge unexpectedly depends on mcp-remote."
    exit 1
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
if metadata.get("expected_server") != {
    "name": "EvalsInIDEServer",
    "version_observed": "1.28.1",
}:
    raise SystemExit("metadata server identity/version is stale")
if metadata.get("tool_catalog_reviewed") != "2026-07-08":
    raise SystemExit("metadata catalog review date is stale")
if catalog.get("observed_server") != {
    "name": "EvalsInIDEServer",
    "version": "1.28.1",
}:
    raise SystemExit("tool catalog server identity/version is stale")
if catalog.get("reviewed_on") != "2026-07-08":
    raise SystemExit("tool catalog review date is stale")
if catalog.get("tool_count") != 9:
    raise SystemExit("observed MCP tool count changed")
if len(gap.get("product_gap_matrix") or []) < 32:
    raise SystemExit("product gap matrix is unexpectedly narrow")
for tool in catalog["tools"]:
    if len(tool["schema_sha256"]) != 64:
        raise SystemExit(f"invalid schema hash for {tool['name']}")

readme = (root / "mcp" / "README.md").read_text(encoding="utf-8")
for marker in [
    "July 7, 2026 product boundaries",
    "AI Assistant beta",
    "Global dashboards",
    "Generic alert webhooks",
    "Python SDK >=2.2.0",
    "Large-dataset Playground",
    "galileo-platform-setup",
]:
    if marker not in readme:
        raise SystemExit(f"generated README missing boundary marker: {marker}")

text = "\n".join(
    p.read_text(encoding="utf-8", errors="ignore")
    for p in root.rglob("*")
    if p.is_file()
)
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

UNSAFE_SECRET_FIXTURE="${OUTPUT_DIR}/mcp/unsafe-inline-secret.txt"
printf 'GALILEO_API_KEY=definitely-inline-secret\n' >"${UNSAFE_SECRET_FIXTURE}"
expect_failure "inline API key assignment rejection" \
    bash "${SCRIPT_DIR}/validate.sh" --output-dir "${OUTPUT_DIR}"
rm -f "${UNSAFE_SECRET_FIXTURE}"
UNSAFE_SECRET_FIXTURE=""

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
    if command -v node >/dev/null 2>&1; then
        run_step python3 - "${OUTPUT_DIR}" <<'PY'
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
messages = [
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "galileo-skill-deep-audit", "version": "1"},
        },
    },
    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    {"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}},
    {"jsonrpc": "2.0", "id": 4, "method": "resources/list", "params": {}},
]
env = dict(os.environ)
env.update(
    GALILEO_MCP_URL=metadata["mcp_url"],
    GALILEO_API_KEY="non-secret-catalog-probe",
    GALILEO_MCP_TIMEOUT_MS="20000",
)
result = subprocess.run(
    ["node", str(root / "mcp/run-galileo-mcp.js")],
    input="".join(json.dumps(message) + "\n" for message in messages),
    text=True,
    capture_output=True,
    env=env,
    timeout=40,
    check=False,
)
if result.returncode != 0:
    raise SystemExit("rendered stdio bridge live probe exited nonzero")
responses = {
    message.get("id"): message
    for line in result.stdout.splitlines()
    if (message := json.loads(line)).get("id") is not None
}
server = responses.get(1, {}).get("result", {}).get("serverInfo", {})
if server != {"name": "EvalsInIDEServer", "version": "1.28.1"}:
    raise SystemExit(f"rendered bridge server identity drift: {server!r}")
if len(responses.get(2, {}).get("result", {}).get("tools", [])) != 9:
    raise SystemExit("rendered bridge live tools/list count changed")
if responses.get(3, {}).get("result", {}).get("prompts") != []:
    raise SystemExit("rendered bridge live prompts/list changed")
if responses.get(4, {}).get("result", {}).get("resources") != []:
    raise SystemExit("rendered bridge live resources/list changed")
print("Rendered stdio bridge live initialize/catalog probe passed.")
PY
    else
        log "deep-audit: node not found; skipping rendered bridge live probe."
    fi
    run_step python3 "${SCRIPT_DIR}/audit_product_coverage.py" "${PRODUCT_ARGS[@]}"
else
    run_step python3 "${SCRIPT_DIR}/audit_product_coverage.py" --offline
fi

log "deep-audit: Galileo MCP Server skill passed."
if [[ "${KEEP_OUTPUT}" == "true" ]]; then
    log "deep-audit: kept rendered output at ${OUTPUT_DIR}"
fi
