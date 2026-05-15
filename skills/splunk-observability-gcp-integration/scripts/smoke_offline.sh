#!/usr/bin/env bash
set -euo pipefail

# Offline smoke test for splunk-observability-gcp-integration.
# No live API calls; validates the render pipeline end-to-end.
#
# Asserts:
#   - render produces non-empty rest/create.json
#   - rest/create.json has type=GCP
#   - pollRate is 60000-600000 ms
#   - authMethod is SERVICE_ACCOUNT_KEY
#   - projectKey is the placeholder, not a real value
#   - no secret values in any rendered file
#   - terraform/main.tf contains signalfx_gcp_integration
#   - gcloud-cli/ scripts rendered (when gcloud_cli_render=true)
#   - coverage-report.json has realm=us1
#   - --list-services works
#
# Exit 0 = all assertions passed.
# Exit 1 = at least one assertion failed.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
PYTHON_BIN="python3"
if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
fi

SKILL_DIR="${SCRIPT_DIR}/.."
TEMPLATE="${SKILL_DIR}/template.example"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "${TMPDIR}"' EXIT

failures=()

# Build a minimal valid spec by patching template.example:
# - Replace empty key_file placeholder with a real-looking path (no actual key needed for render)
# - Replace placeholder project_id with a real-looking one
# - Specify realm us1
"${PYTHON_BIN}" - "${TEMPLATE}" "${TMPDIR}/spec.yaml" <<'PY'
import sys

src = open(sys.argv[1]).read()

# Replace empty key_file with a non-empty path (render only; file does not need to exist)
src = src.replace(
    'key_file: ""   # path to GCP SA JSON key file; chmod 600',
    'key_file: "/tmp/fake-gcp-sa-key.json"   # path to GCP SA JSON key file; chmod 600',
)

# Replace placeholder project_id with a real-looking one
src = src.replace(
    'project_id: my-gcp-project',
    'project_id: my-real-gcp-project-123',
)

open(sys.argv[2], 'w').write(src)
PY

# The renderer validates spec at render time; key_file path is only checked on --apply.
# Create a fake key file so the path check does not fail if it runs.
# (The renderer does NOT read the key contents — just stores the path.)

# Run the renderer.
if ! "${PYTHON_BIN}" "${SKILL_DIR}/scripts/render_assets.py" \
    --spec "${TMPDIR}/spec.yaml" \
    --output-dir "${TMPDIR}/rendered" \
    --realm us1 2>&1; then
    failures+=("render_assets.py exited non-zero")
fi

# Assert rest/create.json exists and is non-empty.
if [[ ! -s "${TMPDIR}/rendered/rest/create.json" ]]; then
    failures+=("rest/create.json is missing or empty after render")
else
    # Assert type=GCP.
    if ! "${PYTHON_BIN}" -c "
import json, sys
data = json.loads(open('${TMPDIR}/rendered/rest/create.json').read())
assert data.get('type') == 'GCP', f'type={data.get(\"type\")!r}, expected GCP'
print('type=GCP OK')
"; then
        failures+=("rest/create.json type check failed")
    fi

    # Assert pollRate in range.
    if ! "${PYTHON_BIN}" -c "
import json
data = json.loads(open('${TMPDIR}/rendered/rest/create.json').read())
pr = data.get('pollRate', 0)
assert 60000 <= pr <= 600000, f'pollRate {pr} out of range'
print(f'pollRate={pr}ms OK')
"; then
        failures+=("rest/create.json pollRate validation failed")
    fi

    # Assert authMethod is present.
    if ! "${PYTHON_BIN}" -c "
import json
data = json.loads(open('${TMPDIR}/rendered/rest/create.json').read())
assert 'authMethod' in data, 'authMethod missing'
assert data['authMethod'] == 'SERVICE_ACCOUNT_KEY', f'authMethod={data[\"authMethod\"]!r}'
print(f'authMethod={data[\"authMethod\"]} OK')
"; then
        failures+=("rest/create.json authMethod check failed")
    fi

    # Assert projectKey entries use the placeholder.
    if "${PYTHON_BIN}" -c "
import json
data = json.loads(open('${TMPDIR}/rendered/rest/create.json').read())
psk = data.get('projectServiceKeys', [])
assert psk, 'projectServiceKeys is empty'
for entry in psk:
    pk = entry.get('projectKey', '')
    assert '\${PROJECT_KEY_FROM_FILE}' in pk, f'projectKey should be placeholder, got {pk!r}'
print('projectKey placeholder OK')
" 2>/dev/null; then
        :
    else
        failures+=("rest/create.json projectKey should be placeholder string")
    fi

    # Assert no real secrets present.
    if grep -E '(eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,})' \
        "${TMPDIR}/rendered/rest/create.json" >/dev/null 2>&1; then
        failures+=("rest/create.json contains secret-looking content")
    fi
fi

# Assert terraform/main.tf contains signalfx_gcp_integration.
if [[ ! -f "${TMPDIR}/rendered/terraform/main.tf" ]]; then
    failures+=("terraform/main.tf missing after render")
elif ! grep -q 'signalfx_gcp_integration' "${TMPDIR}/rendered/terraform/main.tf"; then
    failures+=("terraform/main.tf does not contain signalfx_gcp_integration resource")
else
    echo "terraform/main.tf: signalfx_gcp_integration present"
fi

# Assert gcloud-cli/ scripts rendered.
if [[ ! -f "${TMPDIR}/rendered/gcloud-cli/create-sa.sh" ]]; then
    failures+=("gcloud-cli/create-sa.sh missing after render")
else
    echo "gcloud-cli/create-sa.sh: present"
fi

if [[ ! -f "${TMPDIR}/rendered/gcloud-cli/bind-roles.sh" ]]; then
    failures+=("gcloud-cli/bind-roles.sh missing after render")
else
    echo "gcloud-cli/bind-roles.sh: present"
fi

# Assert no secrets in any rendered file.
while IFS= read -r -d '' file; do
    if grep -E '(eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,})' "${file}" >/dev/null 2>&1; then
        failures+=("secret-looking content in rendered file: ${file#"${TMPDIR}/rendered/"}")
    fi
done < <(find "${TMPDIR}/rendered" -type f \( -name "*.json" -o -name "*.sh" -o -name "*.tf" -o -name "*.md" \) -print0)

# Assert coverage-report.json exists and has realm=us1.
if [[ ! -f "${TMPDIR}/rendered/coverage-report.json" ]]; then
    failures+=("coverage-report.json missing after render")
else
    if ! "${PYTHON_BIN}" -c "
import json
data = json.loads(open('${TMPDIR}/rendered/coverage-report.json').read())
assert data.get('realm') == 'us1', f'realm={data.get(\"realm\")!r}'
print('coverage-report.json: realm=us1 OK')
"; then
        failures+=("coverage-report.json realm check failed")
    fi
fi

# Assert --list-services works.
if ! "${PYTHON_BIN}" "${SKILL_DIR}/scripts/render_assets.py" \
    --spec "${TMPDIR}/spec.yaml" \
    --output-dir "${TMPDIR}/rendered" \
    --realm us1 \
    --list-services >/dev/null 2>&1; then
    failures+=("--list-services exited non-zero")
else
    echo "--list-services: OK"
fi

# Assert --list-services returns 32 entries.
service_count="$("${PYTHON_BIN}" "${SKILL_DIR}/scripts/render_assets.py" \
    --spec "${TMPDIR}/spec.yaml" \
    --output-dir "${TMPDIR}/rendered" \
    --realm us1 \
    --list-services 2>/dev/null | wc -l | tr -d ' ')"
if [[ "${service_count}" != "32" ]]; then
    failures+=("--list-services returned ${service_count} entries, expected 32")
else
    echo "--list-services: 32 entries OK"
fi

echo ""
if [[ ${#failures[@]} -eq 0 ]]; then
    echo "smoke_offline: ALL ASSERTIONS PASSED"
    exit 0
else
    echo "smoke_offline: FAILURES:" >&2
    for f in "${failures[@]}"; do
        echo "  FAIL: ${f}" >&2
    done
    exit 1
fi
