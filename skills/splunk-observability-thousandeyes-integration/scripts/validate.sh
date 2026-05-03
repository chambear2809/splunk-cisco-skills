#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-thousandeyes-rendered"
LIVE=false

usage() {
    cat <<'EOF'
Splunk Observability ThousandEyes Integration validation

Usage:
  bash skills/splunk-observability-thousandeyes-integration/scripts/validate.sh [options]

Options:
  --output-dir DIR   Rendered output directory
  --live             Probe ingest.<realm>.signalfx.com and api.thousandeyes.com
  --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

check_file() {
    local path="$1"
    [[ -f "${path}" ]] || { log "ERROR: Missing ${path}"; exit 1; }
}

check_file "${OUTPUT_DIR}/metadata.json"

# Token-scrub: no real secret-shaped strings in any rendered file.
# Allowed tokens are placeholders ${O11Y_INGEST_TOKEN}, ${O11Y_API_TOKEN}, ${TE_TOKEN}, etc.
if grep -rEq -- '"X-SF-Token"[[:space:]]*:[[:space:]]*"[A-Za-z0-9._-]{20,}"' "${OUTPUT_DIR}" 2>/dev/null; then
    if ! grep -rEq -- '"X-SF-Token"[[:space:]]*:[[:space:]]*"\$\{O11Y_(INGEST|API)_TOKEN\}"' "${OUTPUT_DIR}" 2>/dev/null; then
        log "ERROR: A rendered file appears to contain an inline X-SF-Token value."
        exit 1
    fi
fi

# Stream payload sanity check (when present).
if [[ -f "${OUTPUT_DIR}/te-payloads/stream.json" ]]; then
    python3 - "${OUTPUT_DIR}/te-payloads/stream.json" <<'PY' || { log "ERROR: stream.json is not valid JSON."; exit 1; }
import json, sys
data = json.load(open(sys.argv[1]))
required = {"type", "signal", "endpointType", "streamEndpointUrl", "dataModelVersion", "customHeaders"}
missing = required - set(data.keys())
assert not missing, f"stream.json missing required keys: {missing}"
assert data["type"] == "opentelemetry"
assert data["customHeaders"]["X-SF-Token"].startswith("${"), "X-SF-Token must be a placeholder"
PY
fi

# APM artefacts sanity check.
if [[ -f "${OUTPUT_DIR}/te-payloads/connector.json" ]]; then
    python3 - "${OUTPUT_DIR}/te-payloads/connector.json" <<'PY' || { log "ERROR: connector.json invalid."; exit 1; }
import json, sys
data = json.load(open(sys.argv[1]))
assert data["type"] == "generic"
headers = {h["name"]: h["value"] for h in data.get("headers", [])}
assert headers.get("X-SF-Token", "").startswith("${"), "Connector X-SF-Token must be a placeholder"
PY
fi
if [[ -f "${OUTPUT_DIR}/te-payloads/apm-operation.json" ]]; then
    python3 - "${OUTPUT_DIR}/te-payloads/apm-operation.json" <<'PY' || { log "ERROR: apm-operation.json invalid."; exit 1; }
import json, sys
data = json.load(open(sys.argv[1]))
assert data["type"] == "splunk-observability-apm"
PY
fi

# Tests index sanity check.
if [[ -f "${OUTPUT_DIR}/te-payloads/tests/_index.json" ]]; then
    python3 - "${OUTPUT_DIR}/te-payloads/tests/_index.json" <<'PY' || { log "ERROR: tests/_index.json invalid."; exit 1; }
import json, sys
items = json.load(open(sys.argv[1]))
for item in items:
    assert "slug" in item and "type" in item and "file" in item
PY
fi

# Templates sanity check: every template body must use Handlebars placeholders
# for credentials. The renderer enforces this; the validate path is a second
# defense in depth so a hand-edited file in te-payloads/templates/ is caught.
if [[ -d "${OUTPUT_DIR}/te-payloads/templates" ]]; then
    for tmpl in "${OUTPUT_DIR}/te-payloads/templates"/*.json; do
        [[ -f "${tmpl}" ]] || continue
        python3 - "${tmpl}" <<'PY' || { log "ERROR: ${tmpl} contains plain-text credentials (use Handlebars)."; exit 1; }
import json, re, sys
data = json.load(open(sys.argv[1]))
def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")
            if normalized in {"password", "secret", "token", "api_key", "client_secret", "bearer", "authorization"}:
                if isinstance(v, str) and v and not (v.startswith("{{") and v.endswith("}}")):
                    raise SystemExit(f"plain-text credential at {path}.{k}: TE API rejects with HTTP 400")
            walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            walk(item, f"{path}[{i}]")
walk(data)
PY
    done
fi

log "Splunk Observability ThousandEyes Integration rendered assets passed static validation."

if [[ "${LIVE}" == "true" ]]; then
    log "  --live: probing https://api.thousandeyes.com/v7/account-groups (expect 401 without auth)..."
    if command -v curl >/dev/null 2>&1; then
        local_status="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 'https://api.thousandeyes.com/v7/account-groups' || echo 000)"
        log "  status: ${local_status}"
    fi
fi
