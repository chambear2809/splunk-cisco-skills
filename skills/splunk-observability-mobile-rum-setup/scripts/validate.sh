#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-mobile-rum-rendered"
CHECK_SERVER_TIMING_URL=""
CHECK_SERVER_TIMING_HEADER=""
LIVE=false

usage() {
    cat <<'EOF'
Splunk Observability Mobile RUM validation

Usage:
  bash skills/splunk-observability-mobile-rum-setup/scripts/validate.sh [options]

Options:
  --output-dir DIR                  Rendered output directory
  --check-server-timing URL         Live curl HEAD check for Server-Timing traceparent
  --check-server-timing-header TXT  Offline header text check
  --live                            Permit live HTTP probes
  --help                            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            require_arg "$1" "$#" || exit 1
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --check-server-timing)
            require_arg "$1" "$#" || exit 1
            CHECK_SERVER_TIMING_URL="$2"
            LIVE=true
            shift 2
            ;;
        --check-server-timing-header)
            require_arg "$1" "$#" || exit 1
            CHECK_SERVER_TIMING_HEADER="$2"
            shift 2
            ;;
        --live)
            LIVE=true
            shift
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

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    log "ERROR: Rendered output directory not found: ${OUTPUT_DIR}"
    exit 1
fi

for required in metadata.json preflight-report.md runbook.md version-lock.json; do
    if [[ ! -f "${OUTPUT_DIR}/${required}" ]]; then
        log "ERROR: Missing ${OUTPUT_DIR}/${required}"
        exit 1
    fi
done

PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python3"
if [[ ! -x "${PYTHON_BIN}" ]]; then
    PYTHON_BIN="$(command -v python3)"
fi

log "Static: validating rendered Mobile RUM assets."
"${PYTHON_BIN}" - "${OUTPUT_DIR}" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
errors = []
warnings = []

version_re = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
token_literal_re = re.compile(
    r"(?i)(?:"
    r"bearer\s+[A-Za-z0-9_./+=-]{20,}|"
    r"(?:token|api[_-]?key|secret)\s*[:=]\s*(?!providers\.|System\.getenv|os\.environ)[A-Za-z0-9_./+=-]{24,}|"
    r"[A-Za-z0-9_-]{32,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"
    r")"
)

if metadata.get("api_version") != "splunk-observability-mobile-rum-setup/v1":
    errors.append("metadata.json has the wrong api_version.")

if not metadata.get("allow_latest_version"):
    for key, value in (metadata.get("versions") or {}).items():
        if not version_re.match(str(value)):
            errors.append(f"versions.{key} is not pinned: {value!r}")

files = [p for p in root.rglob("*") if p.is_file()]
for path in files:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".sh":
        result = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            errors.append(f"{path.relative_to(root)} failed bash -n: {result.stderr.strip()}")
    for match in token_literal_re.finditer(text):
        snippet = match.group(0)
        # Ignore documented placeholders and hashes in metadata.
        if "RUM_TOKEN_FROM_BUILD_CONFIG" in snippet or "MobileRumConfig" in snippet:
            continue
        if path.name == "metadata.json" and len(snippet) == 64:
            continue
        errors.append(f"{path.relative_to(root)} contains a token-shaped literal: {snippet[:12]}...")

corpus = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)
platforms = {entry["platform"] for entry in metadata.get("platforms") or []}
if "ios" in platforms and "SplunkAgent" not in corpus:
    errors.append("iOS output is missing SplunkAgent references.")
if "android" in platforms and "com.splunk:splunk-otel-android" not in corpus:
    errors.append("Android output is missing com.splunk:splunk-otel-android.")
if "android" in platforms and "com.splunk:rum-mapping-file-plugin" not in corpus:
    errors.append("Android output is missing mapping plugin artifact coordinates.")
if "react_native" in platforms and "@splunk/otel-react-native" not in corpus:
    errors.append("React Native output is missing @splunk/otel-react-native.")
if "flutter" in platforms and "splunk_otel_flutter" not in corpus:
    errors.append("Flutter output is missing splunk_otel_flutter.")

for path in files:
    if "react_native" not in path.relative_to(root).as_posix():
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    if "splunk-rum sourcemaps" in text or "sourcemaps upload" in text:
        errors.append("React Native output includes Browser/JS source-map upload commands.")

if errors:
    print("Static validation: FAIL")
    for error in errors:
        print(f"  FAIL: {error}")
    for warning in warnings:
        print(f"  WARN: {warning}")
    raise SystemExit(2)

print("Static validation: OK")
for warning in warnings:
    print(f"  WARN: {warning}")
PY

validate_header() {
    local header_text="$1"
    local url_note="${2:-}"
    "${PYTHON_BIN}" - "${SCRIPT_DIR}/render_assets.py" "${header_text}" "${OUTPUT_DIR}" "${url_note}" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
headers = sys.argv[2]
output_dir = Path(sys.argv[3])
url_note = sys.argv[4]
spec = importlib.util.spec_from_file_location("mobile_rum_render_assets", module_path)
if spec is None or spec.loader is None:
    raise SystemExit("ERROR: unable to import render_assets.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
status = module.server_timing_traceparent_status(headers)
print(json.dumps(status, indent=2))
if status["status"] != "valid":
    handoff = output_dir / "handoff-auto-instrumentation.sh"
    handoff.write_text(module.render_auto_instrumentation_handoff(url_note), encoding="utf-8")
    handoff.chmod(0o755)
    raise SystemExit(2)
PY
}

if [[ -n "${CHECK_SERVER_TIMING_HEADER}" ]]; then
    validate_header "${CHECK_SERVER_TIMING_HEADER}" "offline-header"
fi

if [[ -n "${CHECK_SERVER_TIMING_URL}" ]]; then
    if [[ "${LIVE}" != "true" ]]; then
        log "ERROR: --check-server-timing requires --live."
        exit 1
    fi
    if ! command -v curl >/dev/null 2>&1; then
        log "ERROR: curl is required for live Server-Timing validation."
        exit 1
    fi
    headers="$(curl -fsSIL "${CHECK_SERVER_TIMING_URL}" || true)"
    validate_header "${headers}" "${CHECK_SERVER_TIMING_URL}"
fi

log "Mobile RUM validation passed."
