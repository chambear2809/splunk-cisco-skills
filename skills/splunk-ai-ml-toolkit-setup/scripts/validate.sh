#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck disable=SC1091
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"

RENDERED_DIR=""
EXPECT_AI_TOOLKIT=""
EXPECT_DSDL=""
PSC_TARGET="linux64"

PASS=0
WARN=0
FAIL=0
SK=""

pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

usage() {
    cat <<'EOF'
Splunk AI/ML Toolkit Validation

Usage:
  validate.sh [OPTIONS]

Options:
  --rendered-dir DIR                 Validate rendered coverage artifacts
  --psc-target TARGET                PSC target for live validation
  --expect-ai-toolkit true|false
  --expect-dsdl true|false
  --help
EOF
}

normalize_boolean() {
    case "${1:-}" in
        true|TRUE|True|1|yes|YES|on|ON) printf '%s' "true" ;;
        false|FALSE|False|0|no|NO|off|OFF) printf '%s' "false" ;;
        *)
            log "ERROR: Expected boolean true or false, got '${1:-}'."
            exit 1
            ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) require_arg "$1" "$#" || exit 1; RENDERED_DIR="$2"; shift 2 ;;
        --psc-target) require_arg "$1" "$#" || exit 1; PSC_TARGET="$2"; shift 2 ;;
        --expect-ai-toolkit) require_arg "$1" "$#" || exit 1; EXPECT_AI_TOOLKIT="$(normalize_boolean "$2")"; shift 2 ;;
        --expect-dsdl) require_arg "$1" "$#" || exit 1; EXPECT_DSDL="$(normalize_boolean "$2")"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *)
            log "ERROR: Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [[ -n "${RENDERED_DIR}" ]]; then
    python3 - "${RENDERED_DIR}" <<'PY'
import json
import sys
from pathlib import Path

rendered = Path(sys.argv[1])
required = [
    "coverage-report.json",
    "coverage-report.md",
    "apply-plan.json",
    "doctor-report.md",
    "dsdl-runtime-handoff.md",
    "legacy-anomaly-migration.md",
]
missing = [name for name in required if not (rendered / name).is_file()]
if missing:
    print("Missing rendered files: " + ", ".join(missing), file=sys.stderr)
    raise SystemExit(1)

payload = json.loads((rendered / "coverage-report.json").read_text(encoding="utf-8"))
coverage = payload.get("coverage", [])
if not coverage:
    print("coverage-report.json has no coverage entries", file=sys.stderr)
    raise SystemExit(1)
bad = []
for entry in coverage:
    if entry.get("status") == "unknown":
        bad.append(f"{entry.get('key')}: unknown")
    if not entry.get("source_url"):
        bad.append(f"{entry.get('key')}: missing source_url")
if bad:
    print("Invalid coverage: " + "; ".join(bad), file=sys.stderr)
    raise SystemExit(1)
plan = json.loads((rendered / "apply-plan.json").read_text(encoding="utf-8"))
commands = plan.get("steps", [])
if not any(step.get("section") == "ai-toolkit" for step in commands):
    print("apply-plan.json is missing the ai-toolkit install step", file=sys.stderr)
    raise SystemExit(1)
for step in commands:
    command = step.get("command") or []
    if "--app-version" in command:
        print("apply-plan.json pins --app-version; latest compatible Splunkbase installs must not be pinned", file=sys.stderr)
        raise SystemExit(1)
    forbidden = {"--token", "--access-token", "--api-token", "--password", "--client-secret", "--llm-api-key"}
    leaked = forbidden.intersection(command)
    if leaked:
        print(f"apply-plan.json contains forbidden direct-secret flags: {', '.join(sorted(leaked))}", file=sys.stderr)
        raise SystemExit(1)
print(f"Rendered validation passed for {rendered}")
PY
    exit $?
fi

load_splunk_credentials || {
    log "ERROR: Splunk credentials are required for live validation."
    exit 1
}
SK="$(get_session_key "${SPLUNK_URI}")" || {
    log "ERROR: Could not authenticate to Splunk."
    exit 1
}

app_json() {
    local app_name="$1"
    splunk_curl "${SK}" "${SPLUNK_URI}/services/apps/local/${app_name}?output_mode=json" 2>/dev/null || true
}

app_installed() {
    local app_name="$1"
    local payload
    payload="$(app_json "${app_name}")"
    python3 - "${payload}" <<'PY'
import json
import sys
try:
    payload = json.loads(sys.argv[1])
    raise SystemExit(0 if payload.get("entry") else 1)
except Exception:
    raise SystemExit(1)
PY
}

psc_app_name() {
    case "${PSC_TARGET}" in
        linux64|linux|auto) printf '%s' "Splunk_SA_Scientific_Python_linux_x86_64" ;;
        windows64|win64|windows) printf '%s' "Splunk_SA_Scientific_Python_windows_x86_64" ;;
        mac-intel|macos|mac) printf '%s' "Splunk_SA_Scientific_Python_darwin_x86_64" ;;
        mac-arm|mac-arm64|darwin-arm64) printf '%s' "Splunk_SA_Scientific_Python_darwin_arm64" ;;
        linux32) printf '%s' "Splunk_SA_Scientific_Python_linux_x86" ;;
        *)
            log "ERROR: Unknown PSC target ${PSC_TARGET}."
            exit 1
            ;;
    esac
}

log "Validating Splunk AI/ML Toolkit live state..."

if app_installed "$(psc_app_name)"; then
    pass "PSC target ${PSC_TARGET} is installed."
else
    fail "PSC target ${PSC_TARGET} is not installed."
fi

if app_installed "Splunk_ML_Toolkit"; then
    pass "Splunk AI Toolkit / MLTK is installed."
    if [[ "${EXPECT_AI_TOOLKIT}" == "false" ]]; then
        fail "Splunk AI Toolkit is installed but --expect-ai-toolkit false was set."
    fi
else
    if [[ "${EXPECT_AI_TOOLKIT}" == "true" ]]; then
        fail "Splunk AI Toolkit is not installed."
    else
        warn "Splunk AI Toolkit is not installed."
    fi
fi

if app_installed "mltk-container"; then
    pass "DSDL app is installed."
    if [[ "${EXPECT_DSDL}" == "false" ]]; then
        fail "DSDL is installed but --expect-dsdl false was set."
    fi
else
    if [[ "${EXPECT_DSDL}" == "true" ]]; then
        fail "DSDL app is not installed."
    else
        warn "DSDL app is not installed."
    fi
fi

if app_installed "Splunk_SA_Scientific_Python_linux_x86"; then
    warn "Legacy PSC Linux 32-bit is installed; migrate away from this runtime."
fi

log ""
log "Validation summary: PASS=${PASS} WARN=${WARN} FAIL=${FAIL}"
if [[ "${FAIL}" -gt 0 ]]; then
    exit 1
fi
