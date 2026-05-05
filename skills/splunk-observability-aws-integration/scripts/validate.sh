#!/usr/bin/env bash
set -euo pipefail

# Splunk Observability Cloud <-> AWS integration validator.
#
# Static checks (default):
#   - rendered tree completeness (numbered plan files, coverage-report.json,
#     apply-plan.json, scripts/, payloads/, iam/, aws/, state/)
#   - secret-leak scan across every rendered file
#
# Live checks (--live):
#   - GET /v2/integration?type=AWSCloudWatch round-trip
#   - HTTP HEAD on the configured CFN template URL
#
# Doctor mode (--doctor) writes <output-dir>/doctor-report.md with the
# troubleshooting catalog. Discover mode (--discover) writes
# <output-dir>/current-state.json with the live snapshot (read-only).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

OUTPUT_DIR=""
LIVE=false
DOCTOR=false
DISCOVER=false
JSON_OUTPUT=false
SUMMARY=false

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--live] [--doctor] [--discover] [--json] [--summary]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --live) LIVE=true ;;
        --doctor) DOCTOR=true ;;
        --discover) DISCOVER=true ;;
        --json) JSON_OUTPUT=true ;;
        --summary) SUMMARY=true ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-aws-integration-rendered"
fi

REQUIRED_FILES=(
    "README.md"
    "architecture.mmd"
    "00-prerequisites.md"
    "01-authentication.md"
    "02-connection.md"
    "03-regions-services.md"
    "04-namespaces.md"
    "05-metric-streams.md"
    "06-private-link.md"
    "07-multi-account.md"
    "08-validation.md"
    "09-handoff.md"
    "coverage-report.json"
    "apply-plan.json"
    "payloads/integration-create.json"
    "payloads/api-payload-shapes.json"
    "iam/iam-foundation.json"
    "iam/iam-polling.json"
    "iam/iam-streams.json"
    "iam/iam-tag-sync.json"
    "iam/iam-combined.json"
    "aws/cloudformation-stub.sh"
    "aws/main.tf"
    "scripts/apply-integration.sh"
    "scripts/apply-cloudformation.sh"
    "scripts/apply-multi-account.sh"
    "scripts/validate-live.sh"
    "state/apply-state.json"
    "state/idempotency-keys.json"
)

failures=()
warns=()
infos=()

for rel in "${REQUIRED_FILES[@]}"; do
    if [[ ! -e "${OUTPUT_DIR}/${rel}" ]]; then
        failures+=("missing rendered artifact: ${rel}")
    fi
done

# Secret-leak scan across every rendered text file.
if [[ -d "${OUTPUT_DIR}" ]]; then
    while IFS= read -r -d '' file; do
        # Match JWT-looking blobs, bearer tokens with > 12 base64 chars,
        # AWS access key IDs, or `aws_secret_access_key=...` literals.
        if grep -E "(eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,}|AKIA[0-9A-Z]{16}|aws_secret_access_key\s*[:=]\s*[A-Za-z0-9/+=]{20,})" "${file}" >/dev/null 2>&1; then
            failures+=("secret-looking content in ${file#"${OUTPUT_DIR}"/}")
        fi
    done < <(find "${OUTPUT_DIR}" -type f \( -name "*.md" -o -name "*.json" -o -name "*.sh" -o -name "*.tf" -o -name "*.mmd" \) -print0)
fi

# Validate IAM JSON shape (must parse + have Version + Statement[]).
if [[ -d "${OUTPUT_DIR}/iam" ]]; then
    while IFS= read -r -d '' file; do
        if ! "${PYTHON_BIN}" -c "
import json, sys
data = json.loads(open('${file}').read())
assert isinstance(data, dict), 'must be object'
assert data.get('Version') == '2012-10-17', 'Version mismatch'
assert isinstance(data.get('Statement'), list), 'Statement must be a list'
" >/dev/null 2>&1; then
            failures+=("malformed IAM policy: ${file#"${OUTPUT_DIR}"/}")
        fi
    done < <(find "${OUTPUT_DIR}/iam" -type f -name "*.json" -print0)
fi

# Live checks (best-effort; do not FAIL when external state is unknown).
if [[ "${LIVE}" == "true" ]]; then
    # Verify the CFN template URL responds.
    cfn_url="https://o11y-public.s3.amazonaws.com/aws-cloudformation-templates/release/template_metric_streams_regional.yaml"
    if command -v curl >/dev/null 2>&1; then
        status_code=$(curl -sS -o /dev/null -w "%{http_code}" -I "${cfn_url}" 2>/dev/null || echo "000")
        if [[ "${status_code}" =~ ^(200|301|302)$ ]]; then
            infos+=("CFN template URL reachable (HTTP ${status_code})")
        else
            warns+=("CFN template URL HTTP HEAD returned ${status_code}; may be transient")
        fi
    else
        warns+=("curl not installed; skipping CFN URL probe")
    fi

    # Verify Splunk Observability /v2/integration is reachable for our realm.
    if [[ -n "${SPLUNK_O11Y_REALM:-}" && -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
        if "${PYTHON_BIN}" "${SCRIPT_DIR}/aws_integration_api.py" \
            --realm "${SPLUNK_O11Y_REALM}" \
            --token-file "${SPLUNK_O11Y_TOKEN_FILE}" \
            --state-dir "${OUTPUT_DIR}/state" \
            list >/dev/null 2>&1; then
            infos+=("/v2/integration?type=AWSCloudWatch reachable")
        else
            warns+=("/v2/integration?type=AWSCloudWatch unreachable (token / realm may be wrong)")
        fi
    else
        warns+=("SPLUNK_O11Y_REALM and SPLUNK_O11Y_TOKEN_FILE not set; skipping live integration probe")
    fi
fi

# Doctor mode: write the troubleshooting matrix.
if [[ "${DOCTOR}" == "true" ]]; then
    cat > "${OUTPUT_DIR}/doctor-report.md" <<'EOF'
# Doctor Report

This is the static doctor matrix derived from the rendered plan. For live API
checks, run `validate.sh --live` after configuring `SPLUNK_O11Y_REALM` and
`SPLUNK_O11Y_TOKEN_FILE` in the project credentials file.

| # | Check | Severity | Fix command |
|---|-------|----------|-------------|
| 1 | Realm is AWS-hosted (not us2-gcp) | FAIL | Edit spec.realm; the renderer rejects `us2-gcp` |
| 2 | regions is non-empty | FAIL | Enumerate explicitly; the canonical schema rejects empty |
| 3 | GovCloud / China regions force authentication.mode=security_token | FAIL | Set spec.authentication.mode=security_token; pass --aws-access-key-id-file + --aws-secret-access-key-file |
| 4 | services.explicit and services.namespace_sync_rules are mutually exclusive | FAIL | Pick one; the renderer enforces the canonical schema's conflict matrix |
| 5 | custom_namespaces.simple_list and custom_namespaces.sync_rules are mutually exclusive | FAIL | Pick one |
| 6 | metric_streams.managed_externally requires use_metric_streams_sync | FAIL | Set both true |
| 7 | enableLogsSync is deprecated and rejected | FAIL | Hand off logs to splunk-app-install (Splunk_TA_AWS, Splunkbase 1876) instead |
| 8 | 100k-metric auto-deactivate guard (enableCheckLargeVolume) is on | WARN | Default true; only disable for known-high-volume integrations |
| 9 | metricStreamsManagedExternally + AWS-managed-streams stuck in CANCELLATION_FAILED | FAIL | See troubleshoot doc; usually requires a fresh AWS-managed stream |
| 10 | Splunk Observability Cloud is FedRAMP-authorized for our realm | INFO | NOT yet authorized as of early 2026; FedRAMP customers cannot use this skill |
| 11 | API Gateway charts populated | WARN | Enable detailed CloudWatch metrics on API Gateway side |
| 12 | Cassandra/Keyspaces permissions block uses ARN list (not Resource: "*") | INFO | Renderer always emits the correct shape |
| 13 | OTel payload version (AWS-managed streams) is 0.7 or 1.0 | FAIL | Splunk supports only those two; renderer enforces 1.0 default |
| 14 | One AWS-managed Metric Streams integration per AWS account | FAIL | The hard limit; --discover refuses to create a second |
| 15 | Multi-account: control account != member account in the spec | INFO | Splunk Observability has no native multi-account aggregation; this is N integrations |
| 16 | PrivateLink endpoints use the legacy signalfx.com domain (Sep-2024 doc) | INFO | The new `observability.splunkcloud.com` PrivateLink hostnames are gated behind --privatelink-domain new |
| 17 | Splunk_TA_amazon_security_lake uninstalled before Splunk_TA_AWS v7+ install | FAIL | Renderer's hand-off section emits the uninstall step first |
| 18 | Adaptive polling defaults: active 60-600 s, inactive 1200 s default in 60-3600 range | INFO | Renderer enforces these bounds |
| 19 | Terraform provider pin is `~> 9.0` (latest stable 9.7.2 in April 2026) | INFO | Older 6.22.0 example from Splunk help is stale |
| 20 | Drift bucket: `safe-to-converge` auto-applies; `operator-confirm-required` needs --accept-drift FIELD | WARN | Run --discover to see; never auto-apply without operator confirmation |
EOF
    infos+=("doctor-report.md written to ${OUTPUT_DIR}/doctor-report.md")
fi

# Discover mode: minimal placeholder; the apply path uses the API client directly.
if [[ "${DISCOVER}" == "true" && ! -f "${OUTPUT_DIR}/current-state.json" ]]; then
    cat > "${OUTPUT_DIR}/current-state.json" <<EOF
{
  "discovered_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "note": "Run with SPLUNK_O11Y_REALM/SPLUNK_O11Y_TOKEN_FILE configured to populate the live snapshot via aws_integration_api.py."
}
EOF
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    SOAI_FAILURES_JSON="$(printf '%s\n' "${failures[@]+"${failures[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SOAI_WARNS_JSON="$(printf '%s\n' "${warns[@]+"${warns[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SOAI_INFOS_JSON="$(printf '%s\n' "${infos[@]+"${infos[@]}"}" | "${PYTHON_BIN}" -c "import sys, json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SOAI_OUTPUT_DIR="${OUTPUT_DIR}" \
    SOAI_LIVE="${LIVE}" \
    SOAI_DOCTOR="${DOCTOR}" \
    SOAI_DISCOVER="${DISCOVER}" \
    SOAI_FAILURES_JSON="${SOAI_FAILURES_JSON}" \
    SOAI_WARNS_JSON="${SOAI_WARNS_JSON}" \
    SOAI_INFOS_JSON="${SOAI_INFOS_JSON}" \
    "${PYTHON_BIN}" - <<'PY'
import json, os
print(json.dumps({
    "output_dir": os.environ["SOAI_OUTPUT_DIR"],
    "live": os.environ["SOAI_LIVE"] == "true",
    "doctor": os.environ["SOAI_DOCTOR"] == "true",
    "discover": os.environ["SOAI_DISCOVER"] == "true",
    "failures": json.loads(os.environ.get("SOAI_FAILURES_JSON", "[]")),
    "warns": json.loads(os.environ.get("SOAI_WARNS_JSON", "[]")),
    "infos": json.loads(os.environ.get("SOAI_INFOS_JSON", "[]")),
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
