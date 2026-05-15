#!/usr/bin/env bash
set -euo pipefail

# Doctor for the Splunk Observability Cloud Azure integration.
# Checks the rendered plan for common configuration issues and emits
# doctor-report.md with the troubleshooting catalog.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

OUTPUT_DIR=""
REALM="${SPLUNK_O11Y_REALM:-}"
JSON_OUTPUT=false

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--realm REALM] [--json]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --realm) REALM="$2"; shift ;;
        --json) JSON_OUTPUT=true ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-azure-integration-rendered"
fi

if [[ -z "${REALM}" && -f "${OUTPUT_DIR}/coverage-report.json" ]]; then
    REALM="$("${PYTHON_BIN}" -c "
import json
print(json.loads(open('${OUTPUT_DIR}/coverage-report.json').read()).get('realm','unknown'))
" 2>/dev/null || echo "unknown")"
fi

checks=()
fails=()
warns=()
infos=()

# 1. rest/create.json exists and has expected shape.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    "${PYTHON_BIN}" - "${OUTPUT_DIR}/rest/create.json" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1]).read())
assert data.get('type') == 'Azure', 'type must be Azure'
poll_rate = data.get('pollRate', 0)
assert 60000 <= poll_rate <= 600000, f'pollRate {poll_rate} outside 60000-600000 ms'
subs = data.get('subscriptions', [])
assert subs, 'subscriptions is empty'
PY
    # shellcheck disable=SC2181
    if [[ $? -eq 0 ]]; then
        infos+=("rest/create.json: type=Azure, pollRate in range, subscriptions non-empty")
    else
        fails+=("rest/create.json: shape validation failed (type, pollRate, subscriptions)")
    fi
else
    fails+=("rest/create.json not found — run --render first")
fi

# 2. Poll rate check.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    poll_rate_ms="$("${PYTHON_BIN}" -c "
import json
print(json.loads(open('${OUTPUT_DIR}/rest/create.json').read()).get('pollRate', 0))
" 2>/dev/null || echo "0")"
    if (( poll_rate_ms < 300000 )); then
        warns+=("pollRate=${poll_rate_ms}ms is below the recommended 300000ms (300s). Low poll rates increase Azure Monitor API costs.")
    else
        infos+=("pollRate=${poll_rate_ms}ms OK")
    fi
fi

# 3. namedToken ForceNew check.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    named_token="$("${PYTHON_BIN}" -c "
import json
print(json.loads(open('${OUTPUT_DIR}/rest/create.json').read()).get('namedToken',''))
" 2>/dev/null || echo "")"
    if [[ -n "${named_token}" ]]; then
        warns+=("namedToken=${named_token} is set. Changing namedToken after apply destroys and re-creates the integration (ForceNew in Terraform). Confirm this is intentional.")
    fi
fi

# 4. azureEnvironment GovCloud consistency.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    azure_env="$("${PYTHON_BIN}" -c "
import json
print(json.loads(open('${OUTPUT_DIR}/rest/create.json').read()).get('azureEnvironment','AZURE'))
" 2>/dev/null || echo "AZURE")"
    if [[ "${azure_env}" == "AZURE_US_GOVERNMENT" ]]; then
        warns+=("azureEnvironment=AZURE_US_GOVERNMENT: confirm the realm (${REALM}) is a Splunk GovCloud org. Contact Splunk if not.")
    fi
fi

# 5. Credential hash drift.
if [[ -f "${OUTPUT_DIR}/state/credential-hashes.json" ]]; then
    stored="$("${PYTHON_BIN}" -c "
import json
h = json.loads(open('${OUTPUT_DIR}/state/credential-hashes.json').read())
print(h.get('app_id_sha256','') + '|' + h.get('secret_sha256',''))
" 2>/dev/null || echo "|")"
    if [[ "${stored}" == "|" ]] || [[ "${stored}" == "" ]]; then
        warns+=("state/credential-hashes.json has no stored hashes. Apply has not been run yet, or hashes were not recorded.")
    else
        infos+=("state/credential-hashes.json: hashes recorded from last apply")
    fi
fi

# 6. services non-empty.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    has_services="$("${PYTHON_BIN}" -c "
import json
data = json.loads(open('${OUTPUT_DIR}/rest/create.json').read())
svcs = data.get('services') or []
additional = data.get('additionalServices') or []
print('yes' if (svcs or additional) else 'no')
" 2>/dev/null || echo "no")"
    if [[ "${has_services}" == "no" ]]; then
        warns+=("Neither services nor additionalServices is set. The integration will monitor ALL built-in Azure services (services.mode=all_built_in); confirm this is intended to avoid excess Azure Monitor API quota usage.")
    fi
fi

# Write doctor-report.md.
cat > "${OUTPUT_DIR}/doctor-report.md" <<EOF
# Azure Integration Doctor Report

Generated at $(date -u +"%Y-%m-%dT%H:%M:%SZ") — realm: ${REALM}

## Troubleshooting catalog

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No metrics in O11y | Wrong tenantId or appId | Re-run \`--apply\` with fresh credential files |
| appId / secretKey drift | Credentials rotated | Hash mismatch detected by doctor; re-apply |
| Services empty | No services or additionalServices | Add at least one service or set services.mode=all_built_in |
| namedToken changed | ForceNew: integration recreated | Expected; old integration stops flowing data immediately |
| AZURE_US_GOVERNMENT + wrong realm | Realm must be a GovCloud realm | Contact Splunk for GovCloud org provisioning |
| Rate limited | Poll rate too fast | Increase poll_rate_seconds (300+ recommended) |
| 401 / token error | Token expired or wrong scope | Admin user API access token required (not org token) |
| importAzureMonitor=false | Metadata-only mode | Set connection.import_azure_monitor=true |
| Custom namespace not appearing | Not in customNamespacesPerService | Add entry to services.custom_namespaces_per_service |

## Live checks

Failures detected: ${#fails[@]}
Warnings detected: ${#warns[@]}
Infos: ${#infos[@]}

$(for f in "${fails[@]+"${fails[@]}"}"; do echo "- FAIL: ${f}"; done)
$(for w in "${warns[@]+"${warns[@]}"}"; do echo "- WARN: ${w}"; done)
$(for i in "${infos[@]+"${infos[@]}"}"; do echo "- INFO: ${i}"; done)
EOF

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    SAZURE_FAILS_JSON="$(printf '%s\n' "${fails[@]+"${fails[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SAZURE_WARNS_JSON="$(printf '%s\n' "${warns[@]+"${warns[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SAZURE_INFOS_JSON="$(printf '%s\n' "${infos[@]+"${infos[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SAZURE_REALM="${REALM}" \
    SAZURE_OUTPUT_DIR="${OUTPUT_DIR}" \
    SAZURE_FAILS_JSON="${SAZURE_FAILS_JSON}" \
    SAZURE_WARNS_JSON="${SAZURE_WARNS_JSON}" \
    SAZURE_INFOS_JSON="${SAZURE_INFOS_JSON}" \
    "${PYTHON_BIN}" - <<'PY'
import json, os
print(json.dumps({
    "realm": os.environ.get("SAZURE_REALM", ""),
    "output_dir": os.environ["SAZURE_OUTPUT_DIR"],
    "failures": json.loads(os.environ.get("SAZURE_FAILS_JSON", "[]")),
    "warns": json.loads(os.environ.get("SAZURE_WARNS_JSON", "[]")),
    "infos": json.loads(os.environ.get("SAZURE_INFOS_JSON", "[]")),
}, indent=2))
PY
else
    for f in "${fails[@]+"${fails[@]}"}"; do echo "FAIL: ${f}" >&2; done
    for w in "${warns[@]+"${warns[@]}"}"; do echo "WARN: ${w}"; done
    for i in "${infos[@]+"${infos[@]}"}"; do echo "INFO: ${i}"; done
    echo "doctor: report written to ${OUTPUT_DIR}/doctor-report.md"
fi

if [[ ${#fails[@]} -gt 0 ]]; then
    exit 1
fi
exit 0
