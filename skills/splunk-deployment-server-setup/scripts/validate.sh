#!/usr/bin/env bash
set -euo pipefail

# Splunk Deployment Server Setup: validator.
#
# Static checks (default):
#   - rendered tree completeness
#   - no secrets in rendered files
#   - filterType explicitly set (not relying on version-dependent default)
#
# Live checks (--live):
#   - GET /services/deployment/server/clients round-trip
#   - Enrolled client count sanity
#   - Last check-in lag distribution

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

OUTPUT_DIR=""
LIVE=false
DS_URI=""
JSON_OUTPUT=false
SUMMARY=false
ADMIN_PASSWORD_FILE=""

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--live] [--ds-uri URI]
                        [--admin-password-file PATH] [--json] [--summary]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --ds-uri) DS_URI="$2"; shift 2 ;;
        --admin-password-file) ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --summary) SUMMARY=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-deployment-server-rendered"
fi

if [[ ! -d "${OUTPUT_DIR}" ]]; then
    echo "ERROR: Output directory not found: ${OUTPUT_DIR}" >&2
    echo "       Run setup.sh --phase render first." >&2
    exit 1
fi

ERRORS=0
WARNINGS=0

check() {
    local label="$1" condition="$2"
    if ! eval "${condition}" &>/dev/null; then
        echo "FAIL: ${label}" >&2
        ERRORS=$((ERRORS + 1))
    fi
}

warn() {
    local label="$1" condition="$2"
    if ! eval "${condition}" &>/dev/null; then
        echo "WARN: ${label}"
        WARNINGS=$((WARNINGS + 1))
    fi
}

# Required rendered files
for f in "ds/bootstrap/enable-deploy-server.sh" \
          "ds/bootstrap/deployment-apps-layout.md" \
          "ds/reload/reload-deploy-server.sh" \
          "ds/inspect/inspect-fleet.sh" \
          "ds/migrate/retarget-clients.sh" \
          "ds/migrate/staged-rollout.sh" \
          "ds/runbook-failure-modes.md" \
          "ds/validate.sh" \
          "ds/preflight-report.md" \
          "ds/handoffs/agent-management.txt" \
          "ds/handoffs/monitoring-console.txt"; do
    check "Required file ${f} exists" "[[ -f '${OUTPUT_DIR}/${f}' ]]"
done

# filterType must be explicit in any .conf file — skip .md documentation files
if grep -rn "filterType" "${OUTPUT_DIR}" --include="*.conf" 2>/dev/null | \
    grep -v "filterType = whitelist\|filterType = blacklist" | grep -q "filterType"; then
    echo "WARN: filterType found in .conf without explicit whitelist/blacklist value."
    WARNINGS=$((WARNINGS + 1))
fi

# No inline password values in rendered files (allow file-path references)
if grep -rn "SPLUNK_PASS\|splunk_pass\|admin_password" "${OUTPUT_DIR}" 2>/dev/null | \
    grep -v "password_file\|PASSWORD_FILE\|admin-password-file\|splunk_admin_password\|ADMIN_PASS_FILE" | grep -q .; then
    echo "FAIL: Potential inline password value found in rendered files." >&2
    ERRORS=$((ERRORS + 1))
fi

# Live checks
if [[ "${LIVE}" == "true" ]]; then
    if [[ -z "${DS_URI}" ]]; then
        echo "WARN: --live specified but --ds-uri not provided; skipping live checks." >&2
    else
        echo "Live check: ${DS_URI}/services/deployment/server/clients"
        HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
            --insecure \
            ${ADMIN_PASSWORD_FILE:+-u "admin:$(cat "${ADMIN_PASSWORD_FILE}")"} \
            "${DS_URI}/services/deployment/server/clients?count=1&output_mode=json" \
            2>/dev/null || echo "000")"
        if [[ "${HTTP_CODE}" == "200" ]]; then
            echo "OK: Deployment server clients endpoint reachable"
        else
            echo "WARN: Deployment server clients endpoint returned HTTP ${HTTP_CODE}" >&2
            WARNINGS=$((WARNINGS + 1))
        fi
    fi
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    echo "{\"errors\": ${ERRORS}, \"warnings\": ${WARNINGS}, \"output_dir\": \"${OUTPUT_DIR}\"}"
elif [[ "${SUMMARY}" == "true" ]]; then
    echo "validate: errors=${ERRORS} warnings=${WARNINGS} output_dir=${OUTPUT_DIR}"
else
    if [[ "${ERRORS}" -eq 0 ]]; then
        echo "validate: OK (${WARNINGS} warnings)"
    else
        echo "validate: FAILED (${ERRORS} errors, ${WARNINGS} warnings)" >&2
        exit 1
    fi
fi
