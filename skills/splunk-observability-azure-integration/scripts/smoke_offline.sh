#!/usr/bin/env bash
set -euo pipefail

# Offline smoke test for splunk-observability-azure-integration.
# No live API calls; validates the render pipeline end-to-end.
#
# Asserts:
#   - render produces non-empty rest/create.json
#   - rest/create.json has type=Azure
#   - pollRate is 60000-600000 ms
#   - no secret values in any rendered file
#   - terraform/main.tf contains signalfx_azure_integration
#   - azure-cli/ scripts rendered (when azure_cli_render=true)
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
# - Replace placeholder tenant_id with a real-looking UUID
# - Replace placeholder subscription with a real-looking UUID
# - Specify realm us1
"${PYTHON_BIN}" - "${TEMPLATE}" "${TMPDIR}/spec.yaml" <<'PY'
import re, sys

src = open(sys.argv[1]).read()
# Replace placeholder tenant_id
src = src.replace(
    '"00000000-0000-0000-0000-000000000000"',
    '"12345678-1234-1234-1234-123456789abc"',
    1,  # only first occurrence (tenant_id)
)
# Replace placeholder subscription
src = src.replace(
    '"00000000-0000-0000-0000-000000000000"',
    '"abcdef01-abcd-abcd-abcd-abcdef012345"',
)
open(sys.argv[2], 'w').write(src)
PY

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
    # Assert type=Azure.
    if ! "${PYTHON_BIN}" -c "
import json, sys
data = json.loads(open('${TMPDIR}/rendered/rest/create.json').read())
assert data.get('type') == 'Azure', f'type={data.get(\"type\")!r}, expected Azure'
print('type=Azure OK')
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

    # Assert no real secrets present (look for anything that isn't a placeholder).
    if grep -E '(eyJ[A-Za-z0-9._-]{20,}|Bearer\s+[A-Za-z0-9._-]{12,})' \
        "${TMPDIR}/rendered/rest/create.json" >/dev/null 2>&1; then
        failures+=("rest/create.json contains secret-looking content")
    fi

    # Assert appId is the placeholder, not a real value.
    if "${PYTHON_BIN}" -c "
import json
data = json.loads(open('${TMPDIR}/rendered/rest/create.json').read())
app_id = data.get('appId', '')
assert '\${APP_ID_FROM_FILE}' in app_id or app_id == '\${APP_ID_FROM_FILE}', f'appId should be placeholder, got {app_id!r}'
print('appId placeholder OK')
" 2>/dev/null; then
        :
    else
        failures+=("rest/create.json appId should be placeholder string")
    fi
fi

# Assert terraform/main.tf contains signalfx_azure_integration.
if [[ ! -f "${TMPDIR}/rendered/terraform/main.tf" ]]; then
    failures+=("terraform/main.tf missing after render")
elif ! grep -q 'signalfx_azure_integration' "${TMPDIR}/rendered/terraform/main.tf"; then
    failures+=("terraform/main.tf does not contain signalfx_azure_integration resource")
else
    echo "terraform/main.tf: signalfx_azure_integration present"
fi

# Assert azure-cli/ scripts rendered.
if [[ ! -f "${TMPDIR}/rendered/azure-cli/create-sp.sh" ]]; then
    failures+=("azure-cli/create-sp.sh missing after render")
else
    echo "azure-cli/create-sp.sh: present"
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
