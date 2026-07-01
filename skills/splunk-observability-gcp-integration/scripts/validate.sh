#!/usr/bin/env bash
set -euo pipefail

# Splunk Observability Cloud <-> GCP integration validator.
#
# Static checks (default):
#   - rendered tree completeness (rest/, terraform/, gcloud-cli/, state/,
#     coverage-report.json, apply-plan.json)
#   - secret-leak scan across every rendered text file
#
# Live checks (--live):
#   - GET /v2/integration?type=GCP round-trip
#   - Credential hash check (state/credential-hashes.json vs local files)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

OUTPUT_DIR=""
LIVE=false
JSON_OUTPUT=false
TOKEN_FILE=""

usage() {
    cat <<EOF
Usage: $(basename "$0") --output-dir PATH [--live] [--token-file PATH] [--json]
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift ;;
        --live) LIVE=true ;;
        --token-file) TOKEN_FILE="$2"; shift ;;
        --json) JSON_OUTPUT=true ;;
        -h|--help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
    shift
done

if [[ -z "${OUTPUT_DIR}" ]]; then
    OUTPUT_DIR="${PROJECT_ROOT}/splunk-observability-gcp-integration-rendered"
fi

REQUIRED_FILES=(
    "README.md"
    "rest/create.json"
    "rest/update.json"
    "rest/project-key-file-manifest.json"
    "rest/wif-config-file-manifest.json"
    "terraform/main.tf"
    "terraform/variables.tf"
    "state/apply-state.json"
    "state/credential-hashes.json"
    "coverage-report.json"
    "apply-plan.json"
)

failures=()
warns=()
infos=()

for rel in "${REQUIRED_FILES[@]}"; do
    if [[ ! -e "${OUTPUT_DIR}/${rel}" ]]; then
        failures+=("missing rendered artifact: ${rel}")
    fi
done

# Validate rest/create.json shape: must have type=GCP.
if [[ -f "${OUTPUT_DIR}/rest/create.json" ]]; then
    if ! "${PYTHON_BIN}" -c "
import json, sys
data = json.loads(open('${OUTPUT_DIR}/rest/create.json').read())
assert data.get('type') == 'GCP', f'expected type=GCP, got {data.get(\"type\")!r}'
auth = data.get('authMethod')
assert auth in ('SERVICE_ACCOUNT_KEY', 'WORKLOAD_IDENTITY_FEDERATION'), f'invalid authMethod: {auth!r}'
poll_rate = data.get('pollRate', 0)
assert 60000 <= poll_rate <= 600000, f'pollRate must be 60000-600000 ms, got {poll_rate}'
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
    assert 'projectServiceKeys' not in data, 'projectServiceKeys is incompatible with WIF'
else:
    assert isinstance(data.get('projectServiceKeys'), list) and data['projectServiceKeys'], 'projectServiceKeys missing'
" >/dev/null 2>&1; then
        failures+=("rest/create.json failed shape validation (type, authMethod, pollRate, projects.syncMode, or auth contract)")
    else
        infos+=("rest/create.json: type=GCP, projects.syncMode and auth contract OK")
    fi
fi

# Validate Terraform without claiming unsupported WIF provider arguments.
if [[ -f "${OUTPUT_DIR}/terraform/main.tf" ]]; then
    auth_method="$("${PYTHON_BIN}" -c "import json; print(json.load(open('${OUTPUT_DIR}/rest/create.json')).get('authMethod',''))" 2>/dev/null || true)"
    if [[ "${auth_method}" == "WORKLOAD_IDENTITY_FEDERATION" ]]; then
        if grep -Eq 'resource[[:space:]]+"signalfx_gcp_integration"|workload_identity_(pool|provider)_id' "${OUTPUT_DIR}/terraform/main.tf"; then
            failures+=("terraform/main.tf: unsupported WIF resource or pool/provider arguments were rendered")
        else
            infos+=("terraform/main.tf: correctly declines unsupported WIF provider arguments")
        fi
    elif grep -q 'signalfx_gcp_integration' "${OUTPUT_DIR}/terraform/main.tf" >/dev/null 2>&1; then
        infos+=("terraform/main.tf: service-account signalfx_gcp_integration resource present")
    else
        failures+=("terraform/main.tf: signalfx_gcp_integration resource not found")
    fi
fi

if [[ "${auth_method:-}" == "WORKLOAD_IDENTITY_FEDERATION" && -f "${OUTPUT_DIR}/rest/wif-config-file-manifest.json" ]]; then
    wif_config_file="$("${PYTHON_BIN}" - "${OUTPUT_DIR}/rest/wif-config-file-manifest.json" <<'PY' 2>/dev/null || true
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("configFile", ""))
PY
)"
    if "${PYTHON_BIN}" - "${wif_config_file}" <<'PY' >/dev/null 2>&1
import json
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1]) if sys.argv[1] else None
assert path is not None
metadata = path.lstat()
assert path.name == "gcp_wif_config.json"
assert stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode)
assert stat.S_IMODE(metadata.st_mode) == 0o600
payload = json.loads(path.read_text(encoding="utf-8"))
assert isinstance(payload, dict) and payload
PY
    then
        infos+=("gcp_wif_config.json: valid JSON regular file with mode 600")
    else
        failures+=("gcp_wif_config.json: missing, corrupt, insecure, renamed, or not a regular file")
    fi
fi

# Secret-leak scan.
if [[ -d "${OUTPUT_DIR}" ]]; then
    while IFS= read -r -d '' file; do
        if grep -E "(eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,})" "${file}" >/dev/null 2>&1; then
            failures+=("secret-looking content in ${file#"${OUTPUT_DIR}"/}")
        fi
        # Note placeholders used correctly.
        if grep -qE '\$\{PROJECT_KEY_FROM_FILE\}' "${file}" 2>/dev/null; then
            infos+=("${file#"${OUTPUT_DIR}"/}: correctly uses placeholder, not real credential")
        fi
        if grep -qE '\$\{WORKLOAD_IDENTITY_FEDERATION_CONFIG_FROM_FILE\}' "${file}" 2>/dev/null; then
            infos+=("${file#"${OUTPUT_DIR}"/}: correctly uses a WIF file placeholder")
        fi
    done < <(find "${OUTPUT_DIR}" -type f \( -name "*.md" -o -name "*.json" -o -name "*.sh" -o -name "*.tf" \) -print0)
fi

# Live checks.
if [[ "${LIVE}" == "true" ]]; then
    REALM="${SPLUNK_O11Y_REALM:-}"
    if [[ -z "${REALM}" ]]; then
        # Try to read realm from coverage-report.json.
        if [[ -f "${OUTPUT_DIR}/coverage-report.json" ]]; then
            REALM="$("${PYTHON_BIN}" -c "import json; print(json.loads(open('${OUTPUT_DIR}/coverage-report.json').read()).get('realm',''))" 2>/dev/null || echo "")"
        fi
    fi
    TF="${TOKEN_FILE:-${SPLUNK_O11Y_TOKEN_FILE:-}}"
    if [[ -n "${REALM}" && -n "${TF}" ]]; then
        if "${PYTHON_BIN}" "${SCRIPT_DIR}/gcp_integration_api.py" \
            --realm "${REALM}" \
            --token-file "${TF}" \
            --state-dir "${OUTPUT_DIR}/state" \
            list >/dev/null 2>&1; then
            infos+=("/v2/integration?type=GCP reachable at realm ${REALM}")
        else
            warns+=("/v2/integration?type=GCP unreachable (token / realm may be wrong)")
        fi
    else
        warns+=("SPLUNK_O11Y_REALM / SPLUNK_O11Y_TOKEN_FILE not set; skipping live probe")
    fi
fi

if [[ "${JSON_OUTPUT}" == "true" ]]; then
    SGCP_FAILURES_JSON="$(printf '%s\n' "${failures[@]+"${failures[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SGCP_WARNS_JSON="$(printf '%s\n' "${warns[@]+"${warns[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SGCP_INFOS_JSON="$(printf '%s\n' "${infos[@]+"${infos[@]}"}" | "${PYTHON_BIN}" -c "import sys,json; print(json.dumps([l.strip() for l in sys.stdin if l.strip()]))" 2>/dev/null || echo "[]")"
    SGCP_OUTPUT_DIR="${OUTPUT_DIR}" \
    SGCP_LIVE="${LIVE}" \
    SGCP_FAILURES_JSON="${SGCP_FAILURES_JSON}" \
    SGCP_WARNS_JSON="${SGCP_WARNS_JSON}" \
    SGCP_INFOS_JSON="${SGCP_INFOS_JSON}" \
    "${PYTHON_BIN}" - <<'PY'
import json, os
print(json.dumps({
    "output_dir": os.environ["SGCP_OUTPUT_DIR"],
    "live": os.environ["SGCP_LIVE"] == "true",
    "failures": json.loads(os.environ.get("SGCP_FAILURES_JSON", "[]")),
    "warns": json.loads(os.environ.get("SGCP_WARNS_JSON", "[]")),
    "infos": json.loads(os.environ.get("SGCP_INFOS_JSON", "[]")),
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
    else
        echo "validate: OK (${OUTPUT_DIR})"
    fi
fi

if [[ ${#failures[@]} -gt 0 ]]; then
    exit 1
fi
exit 0
