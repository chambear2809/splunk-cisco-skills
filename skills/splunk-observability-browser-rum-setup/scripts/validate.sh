#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/shared/lib/credential_helpers.sh"

RENDERED_DIR="${PROJECT_ROOT}/../splunk-observability-browser-rum-rendered"
CHECK_URL=""
CHECK_INGEST=false
REALM="${SPLUNK_O11Y_REALM:-us0}"

usage() {
    cat <<'EOF'
Splunk Browser RUM validation

Usage:
  bash skills/splunk-observability-browser-rum-setup/scripts/validate.sh [options]

Options:
  --rendered-dir DIR      Offline rendered asset directory
  --check-url URL         Fetch a deployed page and look for RUM markers
  --check-rum-ingest      Probe rum-ingest.<realm>.observability.splunkcloud.com:443
  --realm REALM           Splunk Observability realm
  --help                  Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rendered-dir) require_arg "$1" "$#" || exit 1; RENDERED_DIR="$2"; shift 2 ;;
        --check-url) require_arg "$1" "$#" || exit 1; CHECK_URL="$2"; shift 2 ;;
        --check-rum-ingest) CHECK_INGEST=true; shift ;;
        --realm) require_arg "$1" "$#" || exit 1; REALM="$2"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

PASS=0
WARN=0
FAIL=0
pass() { log "  PASS: $*"; PASS=$((PASS + 1)); }
warn() { log "  WARN: $*"; WARN=$((WARN + 1)); }
fail() { log "  FAIL: $*"; FAIL=$((FAIL + 1)); }

log "=== Splunk Browser RUM Validation ==="

for file in metadata.json browser-rum-plan.md cdn-snippet.html npm-init.ts source-map-upload.sh csp-header.txt rum-to-apm-validation.md; do
    [[ -f "${RENDERED_DIR}/${file}" ]] && pass "Rendered asset exists: ${file}" || fail "Missing rendered asset: ${RENDERED_DIR}/${file}"
done

if [[ -f "${RENDERED_DIR}/cdn-snippet.html" ]]; then
    grep -q "SplunkRum.init" "${RENDERED_DIR}/cdn-snippet.html" && pass "CDN snippet initializes SplunkRum" || fail "CDN snippet missing SplunkRum.init"
fi

if [[ -n "${CHECK_URL}" ]]; then
    page="$(curl -fsSL "${CHECK_URL}" || true)"
    if grep -Eq 'SplunkRum|splunk-otel-web|rum-ingest' <<<"${page}"; then
        pass "Detected Browser RUM marker at ${CHECK_URL}"
    else
        warn "No Browser RUM marker detected at ${CHECK_URL}"
    fi
    headers="$(curl -fsSI "${CHECK_URL}" || true)"
    if grep -qi 'server-timing:.*traceparent' <<<"${headers}"; then
        pass "Server-Timing traceparent header detected"
    else
        warn "Server-Timing traceparent header not detected"
    fi
fi

if [[ "${CHECK_INGEST}" == "true" ]]; then
    host="rum-ingest.${REALM}.observability.splunkcloud.com"
    if nc -z "${host}" 443 >/dev/null 2>&1; then
        pass "RUM ingest endpoint reachable: ${host}:443"
    else
        warn "Could not reach RUM ingest endpoint: ${host}:443"
    fi
fi

log ""
log "=== Validation Summary ==="
log "  PASS: ${PASS} | WARN: ${WARN} | FAIL: ${FAIL}"
[[ "${FAIL}" -eq 0 ]]
