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
#   - exact enabled AWSCloudWatch integration match for rendered identity/scope
#   - Splunk-side credential validation for the matched integration ID
#   - HTTP HEAD on the configured CFN template URL only when rendered for use
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
ALLOW_LOOSE_TOKEN_PERMS=false

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
        --allow-loose-token-perms) ALLOW_LOOSE_TOKEN_PERMS=true ;;
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
        if ! "${PYTHON_BIN}" - "${file}" >/dev/null 2>&1 <<'PY'; then
import json, sys
data = json.loads(open(sys.argv[1]).read())
assert isinstance(data, dict), 'must be object'
assert data.get('Version') == '2012-10-17', 'Version mismatch'
assert isinstance(data.get('Statement'), list), 'Statement must be a list'
PY
            failures+=("malformed IAM policy: ${file#"${OUTPUT_DIR}"/}")
        fi
    done < <(find "${OUTPUT_DIR}/iam" -type f -name "*.json" -print0)
fi

# Live checks are an explicit production-readiness request. Missing tools,
# credentials, or failed endpoints are failures; callers that only want the
# render audit should omit --live.
if [[ "${LIVE}" == "true" ]]; then
    if cfn_probe_metadata="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/apply-plan.json" <<'PY'
import json
import sys
import urllib.parse

plan = json.load(open(sys.argv[1], encoding="utf-8"))
rows = [row for row in (plan.get("ordered_steps") or []) if row.get("step") == "metric_streams.cfn"]
if len(rows) != 1:
    raise SystemExit("rendered apply plan must contain exactly one metric_streams.cfn step")
url = rows[0].get("template_url")
parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None
if (
    parsed is None
    or parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.query
    or parsed.fragment
    or not parsed.path.endswith((".yaml", ".yml"))
    or any(character.isspace() or ord(character) < 0x20 for character in url)
):
    raise SystemExit("rendered metric_streams.cfn template_url is missing or invalid")
required = "true" if rows[0].get("coverage") not in {"not_applicable", "handoff"} else "false"
print(f"{required}\t{url}")
PY
)"; then
        IFS=$'\t' read -r cfn_probe_required cfn_url <<< "${cfn_probe_metadata}"
        if [[ "${cfn_probe_required}" == "true" ]]; then
            if command -v curl >/dev/null 2>&1; then
                status_code=$(curl -q --proto '=https' --tlsv1.2 -sS \
                    --connect-timeout 10 --max-time 60 \
                    -o /dev/null -w "%{http_code}" -I "${cfn_url}" 2>/dev/null || echo "000")
                if [[ "${status_code}" == "200" ]]; then
                    infos+=("CFN template URL reachable (HTTP ${status_code})")
                else
                    failures+=("CFN template URL HTTP HEAD returned ${status_code}")
                fi
            else
                failures+=("curl not installed; cannot run required CFN URL probe")
            fi
        else
            infos+=("CFN template URL probe not applicable to this rendered packet")
        fi
    else
        failures+=("could not determine whether the rendered CFN URL probe is required")
    fi

    # Require one enabled live integration matching the freshly rendered name,
    # account, authentication method, regions, and metric-stream state.
    if [[ -n "${SPLUNK_O11Y_REALM:-}" && -n "${SPLUNK_O11Y_TOKEN_FILE:-}" ]]; then
        expected_account_id="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/apply-plan.json" <<'PY'
import json
import re
import sys

plan = json.load(open(sys.argv[1], encoding="utf-8"))
values = []
for row in plan.get("ordered_steps") or []:
    key = str(row.get("idempotency_key") or "")
    if key.startswith("iam-trust:") and re.fullmatch(r"[0-9]{12}", key.removeprefix("iam-trust:")):
        values.append(key.removeprefix("iam-trust:"))
if len(set(values)) != 1:
    raise SystemExit("rendered apply plan does not identify exactly one AWS account")
print(values[0])
PY
)" || expected_account_id=""
        live_secret_args=()
        [[ "${ALLOW_LOOSE_TOKEN_PERMS}" == "true" ]] && live_secret_args+=(--allow-loose-token-perms)
        if "${PYTHON_BIN}" "${SCRIPT_DIR}/aws_integration_api.py" \
            --realm "${SPLUNK_O11Y_REALM}" \
            --token-file "${SPLUNK_O11Y_TOKEN_FILE}" \
            --state-dir "${OUTPUT_DIR}/state" \
            --payload-file "${OUTPUT_DIR}/payloads/integration-create.json" \
            --expected-aws-account-id "${expected_account_id}" \
            "${live_secret_args[@]}" \
            validate >/dev/null 2>&1; then
            infos+=("live AWSCloudWatch integration matches rendered identity and scope")
        else
            failures+=("live AWSCloudWatch integration is unreachable, absent, disabled, duplicated, or does not match rendered identity/scope")
        fi
    else
        failures+=("SPLUNK_O11Y_REALM and SPLUNK_O11Y_TOKEN_FILE are required for --live")
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
