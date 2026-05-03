#!/usr/bin/env bash
# Offline smoke test for splunk-license-manager-setup. Exercises the renderer
# against the example worksheet shape and asserts every rendered artifact is
# present and well-formed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_OUT="$(mktemp -d)"
trap 'rm -rf "${TMP_OUT}"' EXIT

bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT}" \
    --license-manager-uri https://lm01.example.com:8089 \
    --license-manager-host lm01.example.com \
    --license-files /etc/splunk/enterprise.lic \
    --license-group Enterprise \
    --pool-spec name=ent_main,stack_id=enterprise,quota=MAX \
    --pool-spec name=ent_dev,stack_id=enterprise,quota=10737418240,description=Dev \
    --peer-hosts idx01.example.com,idx02.example.com \
    --colocated-with cluster-manager \
    >/dev/null

render_dir="${TMP_OUT}/license"
required=(
    README.md metadata.json validate.sh
    manager/install-licenses.sh manager/activate-group.sh manager/apply-pools.sh
    manager/pools/ent_main.json manager/pools/ent_dev.json
    peers/idx01.example.com/peer-server.conf
    peers/idx01.example.com/configure-peer.sh
    peers/idx02.example.com/peer-server.conf
    peers/idx02.example.com/configure-peer.sh
)
for file in "${required[@]}"; do
    [[ -f "${render_dir}/${file}" ]] || { echo "FAIL: missing ${file}" >&2; exit 1; }
done

# Every shell script must be syntactically valid.
while IFS= read -r script; do
    bash -n "${script}" || { echo "FAIL: shell syntax error in ${script}" >&2; exit 1; }
done < <(find "${render_dir}" -name '*.sh')

# Pool JSON must parse and contain expected fields.
python3 - "${render_dir}/manager/pools/ent_main.json" <<'PY'
import json, sys
pool = json.load(open(sys.argv[1]))
assert pool["name"] == "ent_main"
assert pool["stack_id"] == "enterprise"
assert pool["quota"] == "MAX"
assert pool["slaves"] == "*"
PY

python3 - "${render_dir}/manager/pools/ent_dev.json" <<'PY'
import json, sys
pool = json.load(open(sys.argv[1]))
assert pool["quota"] == "10737418240"
assert pool["description"] == "Dev"
PY

# Peer server.conf must contain manager_uri stanza.
grep -q 'manager_uri = https://lm01.example.com:8089' "${render_dir}/peers/idx01.example.com/peer-server.conf"

# Rendered manager scripts must source credential_helpers.sh (for log()) AND
# license_helpers.sh (for the secure REST helpers). We assert both rather
# than the previous "must use %{http_code}" check, because the HTTP-status
# pool-existence logic now lives in license_helpers.sh::license_pool_apply
# rather than inline in the rendered script.
for script in apply-pools.sh activate-group.sh install-licenses.sh; do
    target="${render_dir}/manager/${script}"
    grep -q 'source.*credential_helpers.sh' "${target}" \
        || { echo "FAIL: ${script} must source credential_helpers.sh for log()" >&2; exit 1; }
    grep -q 'source.*license_helpers.sh' "${target}" \
        || { echo "FAIL: ${script} must source license_helpers.sh for the secure REST helpers" >&2; exit 1; }
done

# apply-pools.sh must call license_pool_apply (the helper that uses HTTP
# status to distinguish 200/404 strictly and refuses to fall back to a
# blind create on auth/server errors). The actual %{http_code} usage is
# verified by inspecting license_helpers.sh.
grep -q 'license_pool_apply' "${render_dir}/manager/apply-pools.sh" \
    || { echo "FAIL: apply-pools.sh must call license_pool_apply" >&2; exit 1; }
grep -q '%{http_code}' "$(cd "${SCRIPT_DIR}/../../../skills/shared/lib" && pwd)/license_helpers.sh" \
    || { echo "FAIL: license_helpers.sh must use HTTP status code for pool existence check" >&2; exit 1; }

# Repository-wide rule (codified): rendered scripts must NEVER place admin
# credentials on argv via curl -u or splunk -auth. This catches regressions
# that would otherwise re-introduce the secrets-in-argv pattern.
if grep -rE 'curl[^|]*-u[[:space:]]+["'"'"']?\$\{?(AUTH_USER|admin)' "${render_dir}" >/dev/null 2>&1; then
    echo "FAIL: rendered scripts must not pass admin credentials via 'curl -u'" >&2
    grep -rnE 'curl[^|]*-u[[:space:]]+["'"'"']?\$\{?(AUTH_USER|admin)' "${render_dir}" >&2
    exit 1
fi
if grep -rE 'splunk[^|]*-auth[[:space:]]+["'"'"']?\$\{?(AUTH_USER|admin)' "${render_dir}" >/dev/null 2>&1; then
    echo "FAIL: rendered scripts must not pass admin credentials via 'splunk -auth'" >&2
    grep -rnE 'splunk[^|]*-auth[[:space:]]+["'"'"']?\$\{?(AUTH_USER|admin)' "${render_dir}" >&2
    exit 1
fi

echo "PASS: splunk-license-manager-setup offline smoke OK"
