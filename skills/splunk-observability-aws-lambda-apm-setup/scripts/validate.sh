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
# Live checks (--live):
#   - probe the Splunk Observability Cloud ingest endpoint

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
    if ! "${PYTHON_BIN}" -c "
import json, sys
data = json.loads(open('${OUTPUT_DIR}/iam/iam-ingest-egress.json').read())
assert isinstance(data, dict)
assert data.get('Version') == '2012-10-17'
assert isinstance(data.get('Statement'), list)
" >/dev/null 2>&1; then
        failures+=("malformed IAM policy: iam/iam-ingest-egress.json")
    fi
fi

# Coverage report must parse.
if [[ -f "${OUTPUT_DIR}/coverage-report.json" ]]; then
    if ! "${PYTHON_BIN}" -c "
import json, sys
data = json.loads(open('${OUTPUT_DIR}/coverage-report.json').read())
assert 'total' in data
assert data['total'] > 0
" >/dev/null 2>&1; then
        failures+=("malformed coverage-report.json")
    fi
fi

# Live checks.
if [[ "${LIVE}" == "true" ]]; then
    if [[ -n "${SPLUNK_O11Y_REALM:-}" ]]; then
        ingest_url="https://ingest.${SPLUNK_O11Y_REALM}.observability.splunkcloud.com/v2/trace/otlp"
        if command -v curl >/dev/null 2>&1; then
            status_code=$(curl -sS -o /dev/null -w "%{http_code}" -I "${ingest_url}" 2>/dev/null || echo "000")
            if [[ "${status_code}" =~ ^(200|405|415)$ ]]; then
                infos+=("Splunk ingest endpoint reachable (HTTP ${status_code})")
            else
                warns+=("Splunk ingest endpoint HTTP ${status_code}; may be transient or realm mismatch")
            fi
        else
            warns+=("curl not installed; skipping ingest endpoint probe")
        fi
    else
        warns+=("SPLUNK_O11Y_REALM not set; skipping ingest endpoint probe")
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
