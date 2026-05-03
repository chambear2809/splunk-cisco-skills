#!/usr/bin/env bash
# Offline smoke test for splunk-edge-processor-setup. Renders a Cloud + EP
# plan with multiple destinations and pipelines and asserts every artifact is
# present and well-formed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TMP_OUT="$(mktemp -d)"
trap 'rm -rf "${TMP_OUT}"' EXIT

bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "${TMP_OUT}" \
    --ep-control-plane cloud \
    --ep-tenant-url https://example.scs.splunk.com \
    --ep-name prod-ep \
    --ep-tls-mode tls \
    --ep-tls-server-cert /etc/pki/ep/server.pem \
    --ep-tls-server-key /etc/pki/ep/server.key \
    --ep-instances "ep01.example.com=systemd,ep02.example.com=docker,ep03.example.com=nosystemd" \
    --ep-target-daily-gb 250 \
    --ep-source-types "syslog_router,hec_apps" \
    --ep-destinations "primary=type=s2s;host=idx-cluster.example.com;port=9997;index_routing=specify_for_no_index:summary,archive=type=s3;bucket=splunk-archive;prefix=ep-overflow/;region=us-east-1,hec=type=hec;url=https://hec.example.com:8088;token_file=/tmp/ep_hec_token" \
    --ep-default-destination primary \
    --ep-pipelines "filter_dev=partition=Keep;sourcetype=app:dev;spl2_file=pipelines/filter_dev.spl2;destination=primary,archive_overflow=partition=Remove;sourcetype=app:dev;spl2_file=pipelines/archive.spl2;destination=archive" \
    >/dev/null

required=(
    README.md metadata.json validate.sh
    control-plane/edge-processors/prod-ep.json
    control-plane/source-types/syslog_router.json control-plane/source-types/hec_apps.json
    control-plane/destinations/primary.json control-plane/destinations/archive.json control-plane/destinations/hec.json
    control-plane/pipelines/filter_dev.json control-plane/pipelines/filter_dev.spl2
    control-plane/pipelines/archive_overflow.json control-plane/pipelines/archive_overflow.spl2
    control-plane/apply-objects.sh
    host/ep01.example.com/install-with-systemd.sh host/ep01.example.com/uninstall.sh
    host/ep02.example.com/install-docker.sh host/ep02.example.com/uninstall.sh
    host/ep03.example.com/install-without-systemd.sh host/ep03.example.com/uninstall.sh
    forwarder-templates/outputs.conf
    pipelines/templates/filter.spl2 pipelines/templates/mask.spl2 pipelines/templates/sample.spl2 pipelines/templates/route.spl2
    handoffs/acs-allowlist.json
)
for file in "${required[@]}"; do
    [[ -f "${TMP_OUT}/${file}" ]] || { echo "FAIL: missing ${file}" >&2; exit 1; }
done

# Every shell script must be syntactically valid.
while IFS= read -r script; do
    bash -n "${script}" || { echo "FAIL: shell syntax error in ${script}" >&2; exit 1; }
done < <(find "${TMP_OUT}" -name '*.sh')

# Pipeline JSON must parse.
python3 -c "import json; json.load(open('${TMP_OUT}/control-plane/pipelines/filter_dev.json'))"
python3 -c "import json; json.load(open('${TMP_OUT}/control-plane/destinations/primary.json'))"
python3 -c "import json; json.load(open('${TMP_OUT}/control-plane/destinations/archive.json'))"

# Default-destination guard appears in metadata.
grep -q '"default_destination": "primary"' "${TMP_OUT}/metadata.json"

# ACS allowlist hand-off lists s2s + hec.
grep -q '"s2s"' "${TMP_OUT}/handoffs/acs-allowlist.json"
grep -q '"hec"' "${TMP_OUT}/handoffs/acs-allowlist.json"

# Default-destination guard rejects render when not set.
if bash "${SCRIPT_DIR}/setup.sh" \
    --phase render \
    --output-dir "$(mktemp -d)" \
    --ep-tenant-url https://example.scs.splunk.com \
    --ep-destinations "primary=type=s2s;host=idx;port=9997" \
    >/dev/null 2>&1; then
    echo "FAIL: default-destination guard did not reject missing default" >&2
    exit 1
fi

# Install scripts must NOT use $(cat ${TOKEN_FILE}) in argv (token leak).
if grep -E '\$\(cat .*TOKEN_FILE.*\)' "${TMP_OUT}/host/ep01.example.com/install-with-systemd.sh"; then
    echo "FAIL: install-with-systemd.sh leaks install token via \$(cat) in argv" >&2
    exit 1
fi
# Install scripts must reference EP_INSTALL_CMD_FILE (operator-supplied install command).
grep -q 'EP_INSTALL_CMD_FILE' "${TMP_OUT}/host/ep01.example.com/install-with-systemd.sh" \
    || { echo "FAIL: install-with-systemd.sh must consume EP_INSTALL_CMD_FILE" >&2; exit 1; }

# apply-objects.sh and validate.sh must use configurable EP_API_BASE (no
# hardcoded /api/v1/edge-processor/... that Splunk has not published).
if grep -q '/api/v1/edge-processor/' "${TMP_OUT}/control-plane/apply-objects.sh"; then
    echo "FAIL: apply-objects.sh must use \${EP_API_BASE}, not the invented /api/v1/edge-processor/ path" >&2
    exit 1
fi
grep -q 'EP_API_BASE' "${TMP_OUT}/control-plane/apply-objects.sh" \
    || { echo "FAIL: apply-objects.sh must reference EP_API_BASE" >&2; exit 1; }
grep -q 'manual_fallback' "${TMP_OUT}/control-plane/apply-objects.sh" \
    || { echo "FAIL: apply-objects.sh must include a manual UI fallback when EP_API_BASE is unset" >&2; exit 1; }

# validate.sh must also support offline (no EP_API_BASE) mode and check default destination.
grep -q 'No default destination' "${TMP_OUT}/validate.sh" \
    || { echo "FAIL: validate.sh must enforce default-destination guard" >&2; exit 1; }

echo "PASS: splunk-edge-processor-setup offline smoke OK"
