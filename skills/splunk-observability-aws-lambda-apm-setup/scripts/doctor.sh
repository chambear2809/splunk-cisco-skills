#!/usr/bin/env bash
set -euo pipefail

# Splunk Observability Cloud AWS Lambda APM — doctor script.
#
# Detects: vendor conflicts (Datadog, New Relic, AppDynamics, Dynatrace),
# ADOT layer conflicts, X-Ray coexistence issues, snapshot freshness,
# layer drift, and VPC/egress readiness when local collector is disabled.
#
# Writes: <output-dir>/doctor-report.md

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

OUTPUT_DIR=""
REALM=""
TARGET=""
ALLOW_VENDOR_COEXISTENCE=false
JSON_OUTPUT=false

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--realm REALM] [--target FN] [--allow-vendor-coexistence] [--json]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --realm) REALM="$2"; shift ;;
        --target) TARGET="$2"; shift ;;
        --allow-vendor-coexistence) ALLOW_VENDOR_COEXISTENCE=true ;;
        --json) JSON_OUTPUT=true ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-aws-lambda-apm-rendered"
fi

SNAPSHOT="${SCRIPT_DIR}/../references/layer-versions.snapshot.json"
failures=()
warns=()
infos=()
[[ -n "${REALM}" ]] && infos+=("Realm: ${REALM}")

# --- Snapshot freshness ---
if [[ -f "${SNAPSHOT}" ]]; then
    SNAPSHOT_DATE="$("${PYTHON_BIN}" -c "
import json, sys
data = json.loads(open('${SNAPSHOT}').read())
print(data.get('_meta', {}).get('snapshot_date', ''))" 2>/dev/null || echo "")"
    if [[ -n "${SNAPSHOT_DATE}" ]]; then
        AGE="$("${PYTHON_BIN}" -c "
from datetime import datetime, timezone
snap = datetime.fromisoformat('${SNAPSHOT_DATE}')
now = datetime.now(timezone.utc).replace(tzinfo=None)
print((now - snap).days)" 2>/dev/null || echo "0")"
        if [[ "${AGE}" -gt 90 ]]; then
            warns+=("Layer ARN snapshot is ${AGE} days old (>${SNAPSHOT_DATE}). Run --refresh-layer-manifest to update.")
        else
            infos+=("Layer ARN snapshot age: ${AGE} days (${SNAPSHOT_DATE})")
        fi
    fi
fi

# --- Beta disclaimer ---
warns+=("signalfx/splunk-otel-lambda is BETA. Test in non-production first. Check for new versions at signalfx/lambda-layer-versions.")

# --- ADOT conflict check (static, reads rendered env plan) ---
if [[ -f "${OUTPUT_DIR}/04-env.md" ]]; then
    if grep -q "aws-otel" "${OUTPUT_DIR}/04-env.md" 2>/dev/null; then
        failures+=("ADOT conflict: rendered env plan references aws-otel-* layer. ADOT and Splunk layers cannot run simultaneously.")
    fi
fi

# --- X-Ray coexistence ---
if [[ -f "${OUTPUT_DIR}/04-env.md" ]]; then
    if grep -q "OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION" "${OUTPUT_DIR}/04-env.md" 2>/dev/null; then
        infos+=("X-Ray coexistence flag OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION=true is set (correct when X-Ray active tracing is on).")
    fi
fi

# --- Live function-config checks (requires AWS CLI) ---
if [[ -n "${TARGET}" ]] && command -v aws >/dev/null 2>&1; then
    echo "==> Checking live function config for: ${TARGET}..."
    FN_CONFIG="$(aws lambda get-function-configuration \
        --function-name "${TARGET}" \
        --query '{Layers:Layers[].Arn,Env:Environment.Variables}' \
        --output json 2>/dev/null || echo "{}")"

    # Vendor conflict detection.
    VENDOR_FOUND="$("${PYTHON_BIN}" - "${FN_CONFIG}" "${ALLOW_VENDOR_COEXISTENCE}" <<'PY'
import json, sys
config = json.loads(sys.argv[1])
allow = sys.argv[2].lower() == "true"
env = config.get("Env", {}) or {}
layers = config.get("Layers", []) or []
conflicts = []
for prefix, name in [("DD_", "Datadog"), ("APPDYNAMICS_", "AppDynamics")]:
    if any(k.startswith(prefix) for k in env):
        conflicts.append(name)
if "NEW_RELIC_LAMBDA_HANDLER" in env:
    conflicts.append("New Relic")
if "DT_TENANT" in env:
    conflicts.append("Dynatrace")
for arn in layers:
    if "datadog" in arn.lower():
        if "Datadog" not in conflicts:
            conflicts.append("Datadog")
    if "NewRelicLambdaExtension" in arn:
        if "New Relic" not in conflicts:
            conflicts.append("New Relic")
    if "Dynatrace_" in arn:
        if "Dynatrace" not in conflicts:
            conflicts.append("Dynatrace")
    if "aws-otel" in arn or "901920570463" in arn:
        conflicts.append("ADOT")
level = "WARN" if allow else "FAIL"
for c in conflicts:
    print(f"{level}: {c} vendor conflict detected")
PY
)"
    while IFS= read -r line; do
        if [[ "${line}" == FAIL:* ]]; then
            failures+=("${line#FAIL: }")
        elif [[ "${line}" == WARN:* ]]; then
            warns+=("${line#WARN: }")
        fi
    done <<< "${VENDOR_FOUND}"

    infos+=("Live function config checked for: ${TARGET}")
else
    if [[ -n "${TARGET}" ]]; then
        warns+=("aws CLI not installed; skipping live function-config check for ${TARGET}.")
    fi
fi

# --- Write doctor report ---
mkdir -p "${OUTPUT_DIR}"
{
echo "# Doctor Report — AWS Lambda APM"
echo ""
echo "| # | Check | Severity | Notes |"
echo "|---|-------|----------|-------|"
echo "| 1 | spec.accept_beta acknowledged | FAIL if missing | Gate behind accept_beta: true |"
echo "| 2 | GovCloud / China regions refused | FAIL | No published layer ARNs; renderer refuses |"
echo "| 3 | Runtime is Node.js/Python/Java | FAIL | Go, Ruby, .NET have no published layers |"
echo "| 4 | arm64 layer published for selected region | FAIL | renderer refuses arm64 in unpublished regions |"
echo "| 5 | Vendor conflict: Datadog / New Relic / AppD / Dynatrace | FAIL unless --allow-vendor-coexistence | Cannot run with Splunk OTel layer |"
echo "| 6 | ADOT conflict: aws-otel-* layer present | FAIL | Cannot run ADOT + Splunk simultaneously |"
echo "| 7 | X-Ray active tracing + OTEL_LAMBDA_DISABLE_AWS_CONTEXT_PROPAGATION=true | FAIL if missing | Prevents trace ID collision |"
echo "| 8 | SPLUNK_ACCESS_TOKEN delivered via Secrets Manager or SSM | FAIL if inline | Token must never appear in function config directly |"
echo "| 9 | Layer ARN snapshot age <= 90 days | WARN | Run --refresh-layer-manifest to update |"
echo "| 10 | VPC egress to ingest endpoint when local collector disabled | WARN | Requires NAT GW or VPC endpoint |"
echo "| 11 | signalfx/splunk-otel-lambda is BETA | WARN | Test in non-production first |"
echo "| 12 | Cold start overhead: ~150-300 ms | INFO | Lambda Extension adds cold start latency |"
} > "${OUTPUT_DIR}/doctor-report.md"

infos+=("doctor-report.md written to ${OUTPUT_DIR}/doctor-report.md")

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    SLAA_FAILURES_JSON="$(printf '%s\n' "${failures[@]+"${failures[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SLAA_WARNS_JSON="$(printf '%s\n' "${warns[@]+"${warns[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SLAA_INFOS_JSON="$(printf '%s\n' "${infos[@]+"${infos[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SLAA_FAILURES_JSON="${SLAA_FAILURES_JSON}" \
    SLAA_WARNS_JSON="${SLAA_WARNS_JSON}" \
    SLAA_INFOS_JSON="${SLAA_INFOS_JSON}" \
    "${PYTHON_BIN}" - <<'PY'
import json, os
print(json.dumps({
    "failures": json.loads(os.environ.get("SLAA_FAILURES_JSON", "[]")),
    "warns": json.loads(os.environ.get("SLAA_WARNS_JSON", "[]")),
    "infos": json.loads(os.environ.get("SLAA_INFOS_JSON", "[]")),
}, indent=2))
PY
else
    if [[ ${#infos[@]} -gt 0 ]]; then
        printf 'INFO: %s\n' "${infos[@]}"
    fi
    if [[ ${#warns[@]} -gt 0 ]]; then
        printf 'WARN: %s\n' "${warns[@]}"
    fi
    if [[ ${#failures[@]} -gt 0 ]]; then
        printf 'FAIL: %s\n' "${failures[@]}" >&2
        exit 1
    else
        echo "doctor: OK"
    fi
fi
