#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_OUT_S="$(mktemp -d)"
TMP_OUT_C="$(mktemp -d)"
TMP_OUT_X="$(mktemp -d)"
trap 'rm -rf "${TMP_OUT_S}" "${TMP_OUT_C}" "${TMP_OUT_X}"' EXIT

bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT_S}" \
    --soar-platform onprem-single \
    --soar-home /opt/soar \
    --soar-https-port 8443 \
    --soar-hostname soar01.example.com \
    --soar-tgz /tmp/splunk_soar-unpriv-8.5.0.tgz \
    --automation-broker "runtime=docker,fips=auto,image_source=dockerhub" \
    --splunk-side-apps "app_for_soar=true,app_for_soar_export=true" \
    >/dev/null

bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT_C}" \
    --soar-platform onprem-cluster \
    --soar-home /opt/soar \
    --soar-https-port 8443 \
    --soar-hosts soar01,soar02,soar03 \
    --soar-tgz /tmp/splunk_soar-unpriv-8.5.0.tgz \
    --external-pg "mode=rds,host=soar-db.cluster-xyz.us-east-1.rds.amazonaws.com,port=5432" \
    --external-gluster gluster01,gluster02 \
    --external-es es01,es02,es03 \
    --load-balancer haproxy01 \
    --automation-broker "runtime=podman,fips=auto,image_source=tarball" \
    >/dev/null

bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT_X}" \
    --soar-platform cloud \
    --soar-tenant-url https://example.splunkcloudgc.com/soar \
    --soar-cloud-admin-email cloud-admin@example.com \
    --automation-broker "runtime=docker,fips=auto" \
    --splunk-side-apps "app_for_soar=true,app_for_soar_export=false" \
    >/dev/null

common_required=(
    README.md metadata.json validate.sh
    onprem-single/prepare-system.sh onprem-single/install-soar.sh onprem-single/post-install-checklist.md
    onprem-cluster/make-cluster-node.sh onprem-cluster/backup.sh onprem-cluster/restore.sh
    onprem-cluster/external-services/gluster-volume.sh onprem-cluster/external-services/elasticsearch.yml onprem-cluster/external-services/haproxy.cfg
    cloud/onboarding-checklist.md cloud/jwt-token-helper.sh cloud/ip-allowlist.json cloud/apply-allowlist.sh cloud/automation-user.sh
    handoffs/acs-allowlist.json
)
for dir in "${TMP_OUT_S}" "${TMP_OUT_C}" "${TMP_OUT_X}"; do
    for file in "${common_required[@]}"; do
        [[ -f "${dir}/${file}" ]] || { echo "FAIL: ${dir} missing ${file}" >&2; exit 1; }
    done
done

[[ -f "${TMP_OUT_C}/onprem-cluster/external-services/postgres-rds.tf" ]] || { echo "FAIL: rds tf missing" >&2; exit 1; }
[[ -f "${TMP_OUT_S}/automation-broker/docker-compose.yml" ]] || { echo "FAIL: docker compose missing" >&2; exit 1; }
[[ -f "${TMP_OUT_C}/automation-broker/podman-compose.yml" ]] || { echo "FAIL: podman compose missing" >&2; exit 1; }
[[ -f "${TMP_OUT_S}/splunk-side/install-app-for-soar-export.sh" ]] || { echo "FAIL: SS export script missing in single variant" >&2; exit 1; }
[[ -f "${TMP_OUT_S}/splunk-side/configure-phantom-endpoint.sh" ]] || { echo "FAIL: configure-phantom-endpoint.sh missing" >&2; exit 1; }
[[ -f "${TMP_OUT_S}/splunk-side/es-soar-integration.yaml" ]] || { echo "FAIL: es-soar-integration.yaml missing" >&2; exit 1; }
if [[ -f "${TMP_OUT_X}/splunk-side/install-app-for-soar-export.sh" ]]; then
    echo "FAIL: cloud variant should NOT have install-app-for-soar-export.sh (disabled)" >&2
    exit 1
fi

# install-app-for-soar.sh must reference install_app.sh (not setup.sh) and use --source splunkbase --app-id.
grep -q 'install_app.sh' "${TMP_OUT_S}/splunk-side/install-app-for-soar.sh" || { echo "FAIL: install-app-for-soar.sh must reference install_app.sh" >&2; exit 1; }
grep -q -- '--source splunkbase --app-id' "${TMP_OUT_S}/splunk-side/install-app-for-soar.sh" || { echo "FAIL: install-app-for-soar.sh must use --source splunkbase --app-id" >&2; exit 1; }

# configure-phantom-endpoint.sh must use --spec / --mode preview (not invented --section/--integration flags).
grep -q -- '--spec' "${TMP_OUT_S}/splunk-side/configure-phantom-endpoint.sh" || { echo "FAIL: configure-phantom-endpoint.sh must use --spec" >&2; exit 1; }

# validate.sh must mkdir AUDIT_DIR with proper slash separator.
# shellcheck disable=SC2016
grep -q '${AUDIT_DIR}/${out_name}.json' "${TMP_OUT_S}/validate.sh" || { echo "FAIL: validate.sh path concatenation must include slash" >&2; exit 1; }

while IFS= read -r script; do
    bash -n "${script}" || { echo "FAIL: shell syntax error in ${script}" >&2; exit 1; }
done < <(find "${TMP_OUT_S}" "${TMP_OUT_C}" "${TMP_OUT_X}" -name '*.sh')

grep -q 'example.splunkcloudgc.com' "${TMP_OUT_X}/cloud/onboarding-checklist.md"
python3 -c "import json; json.load(open('${TMP_OUT_S}/cloud/ip-allowlist.json'))"

echo "PASS: splunk-soar-setup offline smoke OK (single + cluster + cloud)"
