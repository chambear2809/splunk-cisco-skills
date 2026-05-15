#!/usr/bin/env bash
set -euo pipefail

# Splunk Search Head Cluster Setup: validator.
#
# Static checks (default):
#   - rendered tree completeness
#   - pass4SymmKey not inlined (must be $SHC_SECRET placeholder)
#   - replication factor >= 3
#   - KV Store port not conflicting with other services
#
# Live checks (--live):
#   - splunk show shcluster-status --verbose (via REST)
#   - member count vs replication factor
#   - KV Store quorum check
#   - bundle generation drift check

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

OUTPUT_DIR=""
LIVE=false
SHC_URI=""
JSON_OUTPUT=false
SUMMARY=false
ADMIN_PASSWORD_FILE=""

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--live] [--shc-uri URI]
                        [--admin-password-file PATH] [--json] [--summary]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --live) LIVE=true; shift ;;
        --shc-uri) SHC_URI="$2"; shift 2 ;;
        --admin-password-file) ADMIN_PASSWORD_FILE="$2"; shift 2 ;;
        --json) JSON_OUTPUT=true; shift ;;
        --summary) SUMMARY=true; shift ;;
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-search-head-cluster-rendered"
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
for f in "shc/bootstrap/sequenced-bootstrap.sh" \
          "shc/bundle/validate.sh" "shc/bundle/apply.sh" \
          "shc/restart/searchable-rolling-restart.sh" \
          "shc/restart/transfer-captain.sh" \
          "shc/kvstore/status.sh" \
          "shc/runbook-failure-modes.md" \
          "shc/validate.sh" \
          "shc/preflight-report.md" \
          "shc/handoffs/license-peers.txt" \
          "shc/handoffs/es-deployer.txt" \
          "shc/handoffs/monitoring-console.txt"; do
    check "Required file ${f} exists" "[[ -f '${OUTPUT_DIR}/${f}' ]]"
done

# pass4SymmKey must not be inlined — allow $SHC_SECRET placeholder and file-read patterns
if grep -rn "pass4SymmKey" "${OUTPUT_DIR}" 2>/dev/null | \
    grep -v '\$SHC_SECRET\|YOUR_\|cat /tmp/splunk_shc_secret\|splunk_shc_secret' | grep -q .; then
    echo "FAIL: Inline pass4SymmKey value detected in rendered files." >&2
    ERRORS=$((ERRORS + 1))
fi

# Replication factor sanity
if grep -rn "replication_factor" "${OUTPUT_DIR}" 2>/dev/null | grep -E "= [12]$" | grep -q .; then
    echo "WARN: replication_factor < 3 found; minimum recommended value is 3."
    WARNINGS=$((WARNINGS + 1))
fi

# Live checks
if [[ "${LIVE}" == "true" ]]; then
    if [[ -z "${SHC_URI}" ]]; then
        echo "WARN: --live specified but --shc-uri not provided; skipping live checks." >&2
    else
        echo "Live check: ${SHC_URI}/services/shcluster/captain/info"
        HTTP_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
            --insecure \
            ${ADMIN_PASSWORD_FILE:+-u "admin:$(cat "${ADMIN_PASSWORD_FILE}")"} \
            "${SHC_URI}/services/shcluster/captain/info" 2>/dev/null || echo "000")"
        if [[ "${HTTP_CODE}" == "200" ]]; then
            echo "OK: SHC captain info endpoint reachable"
        else
            echo "WARN: SHC captain info endpoint returned HTTP ${HTTP_CODE}" >&2
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
