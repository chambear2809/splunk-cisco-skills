#!/usr/bin/env bash
# Wave 1 host validation for lab_6890 / amd-halo.
# Run on amd-halo as cisco; Splunk commands run as splunk where required.
set -euo pipefail

REPO="${REPO:-/home/cisco/code/splunk-cisco-skills}"
LOG="${LOG:-/tmp/labval-wave1-$(date +%Y%m%dT%H%M%S).log}"
SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
LABVAL_HEC="${LABVAL_HEC:-/tmp/labval-hec}"
LABVAL_MC="${LABVAL_MC:-/tmp/labval-mc}"
LABVAL_KV="${LABVAL_KV:-/tmp/labval-kv}"
export SPLUNK_HOME
export SPLUNK_PROFILE="${SPLUNK_PROFILE:-lab_6890}"
export SPLUNK_NONINTERACTIVE=1
export SPLUNK_SKILLS_LIVE_VALIDATION=1

exec > >(tee -a "${LOG}") 2>&1

section() { echo ""; echo "===== $* ====="; }

sync_labval_bundle() {
  local src="$1" dest="$2"
  if [[ ! -d "${src}" ]]; then
    echo "WARN: bundle source missing: ${src}"
    return 1
  fi
  sudo rm -rf "${dest}"
  sudo cp -a "${src}/." "${dest}/"
  sudo chown -R splunk:splunk "${dest}"
  sudo find "${dest}" -type f -name '*.sh' -exec chmod 755 {} +
  echo "Synced ${src} -> ${dest}"
}

run_spv_script() {
  local dir="$1" script="$2"
  shift 2
  if [[ ! -x "${dir}/${script}" ]]; then
    echo "WARN: missing script ${dir}/${script}"
    return 1
  fi
  sudo -u splunk env SPV_SKILLS_ROOT="${dir}/.spv-bundle" bash -lc "cd '${dir}' && ./${script} $*"
}

prepare_splunk_admin_file() {
  if [[ ! -f /tmp/labval_splunk_admin ]]; then
    echo "WARN: /tmp/labval_splunk_admin missing"
    return 1
  fi
  sudo cp /tmp/labval_splunk_admin /tmp/labval_splunk_admin.splunk
  sudo chown splunk:splunk /tmp/labval_splunk_admin.splunk
  sudo chmod 600 /tmp/labval_splunk_admin.splunk
}

export_lab_rest_auth() {
  prepare_splunk_admin_file || return 1
  export SPLUNK_URI="https://127.0.0.1:8089"
  export SPLUNK_USER="${SPLUNK_USER:-admin}"
  export SPLUNK_PASS
  SPLUNK_PASS="$(sudo cat /tmp/labval_splunk_admin.splunk)"
  export SPLUNK_PASS
  export SPLUNK_SEARCH_API_URI="${SPLUNK_URI}"
  export SPLUNK_VERIFY_SSL=false
}

splunk_login_local() {
  prepare_splunk_admin_file || return 1
  sudo -u splunk env SPLUNK_HOME="${SPLUNK_HOME}" \
    "${SPLUNK_HOME}/bin/splunk" login -auth "admin:$(sudo cat /tmp/labval_splunk_admin.splunk)" -owner admin >/dev/null 2>&1 || true
}

inject_sc4s_asa_sample() {
  local msg='<134>%ASA-6-302013: Built outbound TCP connection 12345 for outside:192.0.2.10/443 (192.0.2.10/443) to inside:10.1.1.5/50123 (10.1.1.5/50123)'
  python3 - <<'PY' || true
import socket
msg = b"<134>%ASA-6-302013: Built outbound TCP connection 12345 for outside:192.0.2.10/443 (192.0.2.10/443) to inside:10.1.1.5/50123 (10.1.1.5/50123)\n"
for kind, socktype in (("udp", socket.SOCK_DGRAM), ("tcp", socket.SOCK_STREAM)):
    try:
        s = socket.socket(socket.AF_INET, socktype)
        s.settimeout(2)
        if socktype == socket.SOCK_STREAM:
            s.connect(("127.0.0.1", 514))
            s.sendall(msg)
        else:
            s.sendto(msg, ("127.0.0.1", 514))
        s.close()
        print(f"Injected ASA-style syslog sample via {kind} to 127.0.0.1:514")
    except OSError as exc:
        print(f"WARN: syslog {kind} injection failed: {exc}")
PY
}

section "ENV"
hostname
date -u
id
test -d "${REPO}" || { echo "ERROR: repo missing at ${REPO}"; exit 1; }
cd "${REPO}"
source skills/shared/lib/credential_helpers.sh
load_splunk_credentials || true
export_lab_rest_auth || true
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" version | head -1

section "SPV BUNDLE SYNC"
sync_labval_bundle "${REPO}/splunk-hec-service-rendered-lab6890/hec-service" "${LABVAL_HEC}" || true
sync_labval_bundle "${REPO}/splunk-monitoring-console-rendered-lab6890/monitoring-console" "${LABVAL_MC}" || true
sync_labval_bundle "${REPO}/splunk-kvstore-admin-rendered-lab6890/kvstore" "${LABVAL_KV}" || true

section "COLLECTOR: HEC"
if [[ -x "${LABVAL_HEC}/status-enterprise.sh" ]]; then
  run_spv_script "${LABVAL_HEC}" status-enterprise.sh || true
else
  echo "WARN: hec render missing at ${LABVAL_HEC}"
fi
splunk_login_local || true
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" search 'index=* sourcetype=httpevent earliest=-24h | stats count by index,sourcetype' -maxout 0 2>/dev/null | head -10 || true

section "COLLECTOR: SC4S"
inject_sc4s_asa_sample
sleep 20
bash skills/splunk-connect-for-syslog-setup/scripts/validate.sh --check-host --runtime podman 2>&1 || true
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" search 'index=sc4s earliest=-1h | stats count by sourcetype' -maxout 0 2>/dev/null | head -10 || true

section "COLLECTOR: SC4SNMP"
bash skills/splunk-connect-for-snmp-setup/scripts/validate.sh --check-compose --compose-runtime podman 2>&1 || true
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" search 'index=snmp earliest=-24h | stats count' -maxout 0 2>/dev/null | head -5 || true

section "COLLECTOR: OTLP"
if [[ -d splunk-connect-for-otlp-rendered ]]; then
  bash skills/splunk-connect-for-otlp-setup/scripts/validate.sh --output-dir splunk-connect-for-otlp-rendered 2>&1 || true
fi
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" btool apps list 2>/dev/null | grep -i otlp || true

section "COLLECTOR: STREAM"
bash skills/splunk-stream-setup/scripts/validate.sh 2>&1 || true

section "COLLECTOR: UF"
bash skills/splunk-universal-forwarder-setup/scripts/validate.sh --phase status --execution ssh 2>&1 || \
  /opt/splunkforwarder/bin/splunk version 2>&1 | head -1 || true

section "INGEST ACTIONS"
if [[ ! -f /tmp/labval_s3_access_key ]]; then
  printf '%s\n' 'AKIALABVALPLACEHOLDER' | sudo tee /tmp/labval_s3_access_key >/dev/null
  printf '%s\n' 'labval-placeholder-secret-key-not-real' | sudo tee /tmp/labval_s3_secret_key >/dev/null
  sudo chmod 600 /tmp/labval_s3_access_key /tmp/labval_s3_secret_key
  sudo chown splunk:splunk /tmp/labval_s3_access_key /tmp/labval_s3_secret_key
  echo "Created lab placeholder S3 key files for route validation"
fi
bash skills/splunk-ingest-actions-setup/scripts/setup.sh --phase apply \
  --output-dir splunk-ingest-actions-rendered-lab6890 \
  --ruleset-sourcetype syslog --ruleset-name labval_s3_route --rule-type route-s3 \
  --s3-destination-name labval_archive --s3-path s3://labval-placeholder-bucket/syslog \
  --s3-auth-region us-east-1 \
  --s3-access-key-file /tmp/labval_s3_access_key \
  --s3-secret-key-file /tmp/labval_s3_secret_key \
  --accept-irreversible-ingest 2>&1 || true
bash skills/splunk-ingest-actions-setup/scripts/validate.sh \
  --output-dir splunk-ingest-actions-rendered-lab6890 --live --json 2>&1 || true

section "MCP SERVER"
if [[ ! -f /tmp/splunk_mcp_token ]]; then
  echo "WARN: /tmp/splunk_mcp_token missing"
fi
bash skills/splunk-mcp-server-setup/scripts/validate.sh \
  --completion \
  --accept-nonproduction-package \
  --mcp-bearer-token-file /tmp/splunk_mcp_token 2>&1 || true

section "ADMIN DOCTOR"
bash skills/splunk-admin-doctor/scripts/setup.sh --phase doctor --platform enterprise 2>&1 || true
python3 skills/splunk-admin-doctor/scripts/live_validate_all.py --once --json 2>&1 | tail -40 || true

section "MONITORING CONSOLE"
if [[ -x "${LABVAL_MC}/status.sh" ]]; then
  run_spv_script "${LABVAL_MC}" status.sh || true
else
  echo "WARN: monitoring console render missing at ${LABVAL_MC}"
fi
bash skills/splunk-monitoring-console-setup/scripts/validate.sh --live 2>&1 || \
  bash skills/splunk-monitoring-console-setup/scripts/validate.sh 2>&1 || true

section "CIM DATA MODEL"
bash skills/splunk-cim-data-model-setup/scripts/validate.sh \
  --output-dir splunk-cim-data-model-rendered-lab6890 --live 2>&1 || true
splunk_login_local || true
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" search '| tstats count from datamodel=Network_Traffic | head 5' -maxout 0 2>/dev/null | head -10 || true
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" search '| tstats count where index=* by index' -maxout 0 2>/dev/null | head -10 || true

section "KV STORE ADMIN"
if [[ -x "${LABVAL_KV}/backup.sh" ]]; then
  splunk_login_local || true
  run_spv_script "${LABVAL_KV}" backup.sh || true
  run_spv_script "${LABVAL_KV}" status.sh || true
  latest_archive="$(sudo -u splunk bash -lc 'ls -1t "${SPLUNK_HOME:-/opt/splunk}/var/lib/splunk/kvstorebackup"/*.tar.gz 2>/dev/null | head -1' || true)"
  if [[ -n "${latest_archive}" ]]; then
    archive_name="$(basename "${latest_archive}")"
    bash skills/splunk-kvstore-admin-setup/scripts/setup.sh --phase apply --operation restore \
      --output-dir splunk-kvstore-admin-rendered-lab6890 \
      --backup-archive-name "${archive_name}" --dry-run 2>&1 || true
  else
    echo "WARN: no KV backup archive found for restore dry-run"
  fi
else
  echo "WARN: kvstore render missing at ${LABVAL_KV}"
fi

section "WLM PRODUCTION CUTOVER"
if [[ -d splunk-workload-management-rendered-lab6890/workload-management ]]; then
  WLM=splunk-workload-management-rendered-lab6890/workload-management
  MEMMAX="$("${WLM}/systemd/calculate-memory-max.sh" 90 | awk '/^MemoryMax=/ {print $1}')"
  echo "Calculated ${MEMMAX}"
  sudo mkdir -p /etc/systemd/system/Splunkd.service.d
  sudo cp "${WLM}/systemd/Splunkd.service.d/99-wlm-production.conf.example" \
    /etc/systemd/system/Splunkd.service.d/99-wlm-production.conf
  sudo sed -i "s/^MemoryMax=.*/${MEMMAX}/" /etc/systemd/system/Splunkd.service.d/99-wlm-production.conf
  sudo systemctl daemon-reload
  sudo systemctl restart Splunkd.service
  sleep 15
  (cd "${WLM}" && sudo -u splunk ./status.sh) 2>&1 || true
fi

section "DONE"
echo "Log: ${LOG}"
