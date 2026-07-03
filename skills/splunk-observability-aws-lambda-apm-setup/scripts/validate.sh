#!/usr/bin/env bash
set -euo pipefail

# Splunk Observability Cloud AWS Lambda APM — static + optional live validator.
#
# Static checks (default):
#   - rendered tree completeness
#   - secret-leak scan across every rendered file
#   - IAM JSON shape when iam-ingest-egress.json is present
#   - AWS CLI plan contains no inline token values
#
# Optional live check (--live):
#   - unauthenticated reachability-only probe of the O11y ingest endpoint
#   - does NOT validate Lambda configuration, token authorization, span export,
#     or APM data arrival

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

OUTPUT_DIR=""
LIVE=false
JSON_OUTPUT=false
SUMMARY=false

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--live] [--json] [--summary]

  --live  Run an unauthenticated ingest-endpoint reachability probe only.
          This is not configured-state or telemetry acceptance validation.
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --live) LIVE=true ;;
        --json) JSON_OUTPUT=true ;;
        --summary) SUMMARY=true ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-aws-lambda-apm-rendered"
fi

REQUIRED_FILES=(
    "README.md"
    "01-overview.md"
    "02-targets.md"
    "03-layers.md"
    "04-env.md"
    "05-validation.md"
    "coverage-report.json"
    "aws-cli/apply-plan.sh"
    "terraform/main.tf"
    "cloudformation/snippets.yaml"
    "scripts/write-splunk-token.sh"
    "scripts/handoffs.sh"
)

failures=()
warns=()
infos=()

for rel in "${REQUIRED_FILES[@]}"; do
    if [[ ! -e "${OUTPUT_DIR}/${rel}" ]]; then
        failures+=("missing rendered artifact: ${rel}")
    fi
done

# Secret-leak scan: JWT blobs, bearer tokens, AWS access key IDs, raw token patterns.
if [[ -d "${OUTPUT_DIR}" ]]; then
    while IFS= read -r -d '' file; do
        if grep -E "(eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,}|AKIA[0-9A-Z]{16}|aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{20,})" "${file}" >/dev/null 2>&1; then
            failures+=("secret-looking content in ${file#"${OUTPUT_DIR}"/}")
        fi
    done < <(find "${OUTPUT_DIR}" -type f \( -name "*.md" -o -name "*.json" -o -name "*.sh" -o -name "*.tf" -o -name "*.yaml" \) -print0)
fi

# IAM JSON shape when present.
if [[ -f "${OUTPUT_DIR}/iam/iam-ingest-egress.json" ]]; then
    if ! "${PYTHON_BIN}" - "${OUTPUT_DIR}/iam/iam-ingest-egress.json" >/dev/null 2>&1 <<'PY'; then
import json
import sys

data = json.loads(open(sys.argv[1], encoding="utf-8").read())
assert isinstance(data, dict)
assert data.get('Version') == '2012-10-17'
assert isinstance(data.get('Statement'), list)
PY
        failures+=("malformed IAM policy: iam/iam-ingest-egress.json")
    fi
fi

# Coverage report must parse.
if [[ -f "${OUTPUT_DIR}/coverage-report.json" ]]; then
    if ! "${PYTHON_BIN}" - "${OUTPUT_DIR}/coverage-report.json" >/dev/null 2>&1 <<'PY'; then
import json
import sys

data = json.loads(open(sys.argv[1], encoding="utf-8").read())
assert 'total' in data
assert data['total'] > 0
PY
        failures+=("malformed coverage-report.json")
    fi
fi

# Live checks.
if [[ "${LIVE}" == "true" ]]; then
    if [[ -n "${SPLUNK_O11Y_REALM:-}" ]]; then
        realm_supported=true
        case "${SPLUNK_O11Y_REALM}" in
            us0|us1|us2|us3|eu0|eu1|eu2|au0|jp0|sg0) ;;
            *)
                realm_supported=false
                failures+=("SPLUNK_O11Y_REALM is unsupported for the reachability-only probe")
                ;;
        esac
        if [[ "${realm_supported}" == "true" ]] && command -v curl >/dev/null 2>&1; then
            ingest_url="https://ingest.${SPLUNK_O11Y_REALM}.observability.splunkcloud.com/v2/trace/otlp"
            status_code=$(curl -q --proto '=https' --tlsv1.2 -sS \
                --connect-timeout 10 --max-time 60 \
                -o /dev/null -w "%{http_code}" -I "${ingest_url}" 2>/dev/null || echo "000")
            # Any HTTP response proves DNS/TCP/TLS/HTTP reachability. The probe
            # is intentionally unauthenticated, so authorization or method
            # statuses must not be interpreted as configured-state failures.
            if [[ "${status_code}" =~ ^[1-5][0-9][0-9]$ ]]; then
                infos+=("reachability-only ingest endpoint probe succeeded (HTTP ${status_code}); Lambda configuration and telemetry were not validated")
            else
                failures+=("reachability-only ingest endpoint probe returned HTTP ${status_code}; realm or network reachability failed")
            fi
        elif [[ "${realm_supported}" == "true" ]]; then
            failures+=("curl not installed; cannot run ingest endpoint probe")
        fi
    else
        failures+=("SPLUNK_O11Y_REALM is required for --live")
    fi
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    SLAA_FAILURES_JSON="$(printf '%s\n' "${failures[@]+"${failures[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SLAA_WARNS_JSON="$(printf '%s\n' "${warns[@]+"${warns[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SLAA_INFOS_JSON="$(printf '%s\n' "${infos[@]+"${infos[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SLAA_OUTPUT_DIR="${OUTPUT_DIR}" \
    SLAA_LIVE="${LIVE}" \
    SLAA_FAILURES_JSON="${SLAA_FAILURES_JSON}" \
    SLAA_WARNS_JSON="${SLAA_WARNS_JSON}" \
    SLAA_INFOS_JSON="${SLAA_INFOS_JSON}" \
    "${PYTHON_BIN}" - <<'PY'
import json, os
print(json.dumps({
    "output_dir": os.environ["SLAA_OUTPUT_DIR"],
    "live": os.environ["SLAA_LIVE"] == "true",
    "live_scope": "ingest_endpoint_reachability_only" if os.environ["SLAA_LIVE"] == "true" else None,
    "failures": json.loads(os.environ.get("SLAA_FAILURES_JSON", "[]")),
    "warns": json.loads(os.environ.get("SLAA_WARNS_JSON", "[]")),
    "infos": json.loads(os.environ.get("SLAA_INFOS_JSON", "[]")),
}, indent=2))
PY
elif [[ "${SUMMARY}" == "true" ]]; then
    echo "Validate summary: failures=${#failures[@]} warns=${#warns[@]} infos=${#infos[@]}"
else
    if [[ ${#infos[@]} -gt 0 ]]; then
        printf 'INFO: %s\n' "${infos[@]}"
    fi
    if [[ ${#warns[@]} -gt 0 ]]; then
        printf 'WARN: %s\n' "${warns[@]}"
    fi
    if [[ ${#failures[@]} -gt 0 ]]; then
        printf 'FAIL: %s\n' "${failures[@]}" >&2
    else
        echo "validate: OK (${OUTPUT_DIR})"
    fi
fi

if [[ ${#failures[@]} -gt 0 ]]; then
    exit 1
fi
exit 0
