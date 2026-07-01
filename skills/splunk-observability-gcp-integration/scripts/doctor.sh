#!/usr/bin/env bash
set -euo pipefail

# Doctor for the Splunk Observability Cloud GCP integration.
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
WIF_CONFIG_FILE=""
JSON_OUTPUT=false

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--realm REALM] [--wif-config-file PATH] [--json]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --realm) REALM="$2"; shift ;;
        --wif-config-file) WIF_CONFIG_FILE="$2"; shift ;;
        --json) JSON_OUTPUT=true ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-gcp-integration-rendered"
fi

if [[ -z "${REALM}" && -f "${OUTPUT_DIR}/coverage-report.json" ]]; then
    REALM="$("${PYTHON_BIN}" -c "
import json
print(json.loads(open('${OUTPUT_DIR}/coverage-report.json').read()).get('realm','unknown'))
" 2>/dev/null || echo "unknown")"
fi

fails=()
warns=()
infos=()

# 1. rest/create.json exists and has expected shape.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    if "${PYTHON_BIN}" - "${OUTPUT_DIR}/rest/create.json" <<'PY'
import json, sys
data = json.loads(open(sys.argv[1]).read())
assert data.get('type') == 'GCP', 'type must be GCP'
poll_rate = data.get('pollRate', 0)
assert 60000 <= poll_rate <= 600000, f'pollRate {poll_rate} outside 60000-600000 ms'
auth = data.get('authMethod')
assert auth in ('SERVICE_ACCOUNT_KEY', 'WORKLOAD_IDENTITY_FEDERATION'), 'invalid authMethod'
projects = data.get('projects')
assert isinstance(projects, dict), 'projects must be an object'
assert projects.get('syncMode') in ('ALL', 'SELECTED'), 'projects.syncMode missing or invalid'
project_ids = projects.get('projectIds', [])
assert isinstance(project_ids, list) and all(isinstance(item, str) and item for item in project_ids), 'projects.projectIds must be a string list'
if projects['syncMode'] == 'ALL':
    assert not project_ids, 'projects.projectIds must be empty for ALL'
else:
    assert project_ids, 'projects.projectIds is required for SELECTED'
if auth == 'WORKLOAD_IDENTITY_FEDERATION':
    value = data.get('workloadIdentityFederationConfig')
    assert isinstance(value, str) and value, 'workloadIdentityFederationConfig missing'
    assert 'workloadIdentityPoolId' not in data, 'legacy workloadIdentityPoolId is invalid'
    assert 'workloadIdentityProviderId' not in data, 'legacy workloadIdentityProviderId is invalid'
PY
    then
        infos+=("rest/create.json: type=GCP, pollRate, authMethod, and projects.syncMode are valid")
    else
        fails+=("rest/create.json: shape validation failed (type, pollRate, authMethod, projects.syncMode, or WIF contract)")
    fi
else
    fails+=("rest/create.json not found — run --render first")
fi

# WIF uses only Splunk's official generated configuration document. Validate
# the referenced file without copying its contents into the rendered tree.
auth_method=""
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    auth_method="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/rest/create.json" <<'PY' 2>/dev/null || true
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("authMethod", ""))
PY
)"
fi
if [[ "${auth_method}" == "WORKLOAD_IDENTITY_FEDERATION" ]]; then
    if [[ -z "${WIF_CONFIG_FILE}" && -f "${OUTPUT_DIR}/rest/wif-config-file-manifest.json" ]]; then
        WIF_CONFIG_FILE="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/rest/wif-config-file-manifest.json" <<'PY' 2>/dev/null || true
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("configFile", ""))
PY
)"
    fi
    if "${PYTHON_BIN}" - "${WIF_CONFIG_FILE}" <<'PY'
import json
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1]) if sys.argv[1] else None
assert path is not None, "WIF config path missing"
metadata = path.lstat()
assert path.name == "gcp_wif_config.json", "WIF config filename must be gcp_wif_config.json"
assert stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode), "WIF config must be a regular non-symlink file"
assert stat.S_IMODE(metadata.st_mode) == 0o600, "WIF config must have mode 600"
payload = json.loads(path.read_text(encoding="utf-8"))
assert isinstance(payload, dict) and payload, "WIF config must be a non-empty JSON object"
PY
    then
        infos+=("gcp_wif_config.json: official file reference is present, valid JSON, and mode 600")
    else
        fails+=("gcp_wif_config.json: missing, corrupt, insecure, renamed, or not a regular file")
    fi
fi

# 2. Poll rate check.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    poll_rate_ms="$("${PYTHON_BIN}" -c "
import json
print(json.loads(open('${OUTPUT_DIR}/rest/create.json').read()).get('pollRate', 0))
" 2>/dev/null || echo "0")"
    if (( poll_rate_ms < 300000 )); then
        warns+=("pollRate=${poll_rate_ms}ms is below the recommended 300000ms (300s). Low poll rates increase Cloud Monitoring API quota usage.")
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

# 4. services non-empty when explicit mode.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    services_mode_info="$("${PYTHON_BIN}" -c "
import json
data = json.loads(open('${OUTPUT_DIR}/rest/create.json').read())
svcs = data.get('services') or []
print(f'count={len(svcs)}')
" 2>/dev/null || echo "count=0")"
    if [[ -f "${OUTPUT_DIR}/coverage-report.json" ]]; then
        cov_services_mode="$("${PYTHON_BIN}" -c "
import json
cov = json.loads(open('${OUTPUT_DIR}/coverage-report.json').read())
print(cov.get('coverage', {}).get('services.mode', {}).get('notes', ''))
" 2>/dev/null || echo "")"
        if echo "${cov_services_mode}" | grep -q 'mode=explicit'; then
            if echo "${services_mode_info}" | grep -q 'count=0'; then
                warns+=("services.mode=explicit but no services listed in rest/create.json. Integration will monitor all built-in services; confirm this is intended.")
            fi
        fi
    fi
    infos+=("services ${services_mode_info}")
fi

# 5. Credential hash drift.
if [[ -f "${OUTPUT_DIR}/state/credential-hashes.json" ]]; then
    hash_count="$("${PYTHON_BIN}" -c "
import json
h = json.loads(open('${OUTPUT_DIR}/state/credential-hashes.json').read())
pks = h.get('project_key_sha256', {})
wif = h.get('wif_config_sha256', {})
print(len(pks) + len(wif))
" 2>/dev/null || echo "0")"
    if [[ "${hash_count}" == "0" ]]; then
        warns+=("state/credential-hashes.json has no stored credential hashes. Apply has not been run yet, or hashes were not recorded.")
    else
        infos+=("state/credential-hashes.json: ${hash_count} credential hash(es) recorded from last apply")
    fi
fi

# 6. useMetricSourceProjectForQuota warning.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    quota_flag="$("${PYTHON_BIN}" -c "
import json
print(json.loads(open('${OUTPUT_DIR}/rest/create.json').read()).get('useMetricSourceProjectForQuota', False))
" 2>/dev/null || echo "False")"
    if [[ "${quota_flag}" == "True" ]]; then
        warns+=("useMetricSourceProjectForQuota=true: ensure roles/serviceusage.serviceUsageConsumer is granted on the metric source project SA.")
    fi
fi

# Write doctor-report.md.
cat > "${OUTPUT_DIR}/doctor-report.md" <<EOF
# GCP Integration Doctor Report

Generated at $(date -u +"%Y-%m-%dT%H:%M:%SZ") — realm: ${REALM}

## Troubleshooting catalog

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No metrics in O11y | Wrong SA key or missing IAM roles | Re-apply with fresh key file; verify roles/monitoring.viewer + roles/compute.viewer |
| projectKey drift | SA key rotated | Hash mismatch detected by doctor; re-apply with new key file |
| Services empty (explicit mode) | No services listed | Add services or set services.mode=all_built_in |
| namedToken changed | ForceNew: integration recreated | Expected; old integration stops flowing data immediately |
| Rate limited | Poll rate too fast | Increase poll_rate_seconds (300+ recommended) |
| WIF auth failure | Missing, modified, malformed, or stale generated config | Download a fresh official gcp_wif_config.json from Splunk; store it unchanged with mode 600 and re-apply |
| useMetricSourceProjectForQuota 403 | Missing roles/serviceusage.serviceUsageConsumer | Add the role or set flag to false |
| Custom metric not appearing | Not in customMetricTypeDomains | Add the metric type prefix |
| 401 / token error | Token expired or wrong scope | Admin user API access token required (not org token) |

## Live checks

Failures detected: ${#fails[@]}
Warnings detected: ${#warns[@]}
Infos: ${#infos[@]}

$(for f in "${fails[@]+"${fails[@]}"}"; do echo "- FAIL: ${f}"; done)
$(for w in "${warns[@]+"${warns[@]}"}"; do echo "- WARN: ${w}"; done)
$(for i in "${infos[@]+"${infos[@]}"}"; do echo "- INFO: ${i}"; done)
EOF

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    SGCP_FAILS_JSON="$(printf '%s\n' "${fails[@]+"${fails[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SGCP_WARNS_JSON="$(printf '%s\n' "${warns[@]+"${warns[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SGCP_INFOS_JSON="$(printf '%s\n' "${infos[@]+"${infos[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SGCP_REALM="${REALM}" \
    SGCP_OUTPUT_DIR="${OUTPUT_DIR}" \
    SGCP_FAILS_JSON="${SGCP_FAILS_JSON}" \
    SGCP_WARNS_JSON="${SGCP_WARNS_JSON}" \
    SGCP_INFOS_JSON="${SGCP_INFOS_JSON}" \
    "${PYTHON_BIN}" - <<'PY'
import json, os
print(json.dumps({
    "realm": os.environ.get("SGCP_REALM", ""),
    "output_dir": os.environ["SGCP_OUTPUT_DIR"],
    "failures": json.loads(os.environ.get("SGCP_FAILS_JSON", "[]")),
    "warns": json.loads(os.environ.get("SGCP_WARNS_JSON", "[]")),
    "infos": json.loads(os.environ.get("SGCP_INFOS_JSON", "[]")),
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
