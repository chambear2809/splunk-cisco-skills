#!/usr/bin/env bash
# Wave 2 host validation for lab_6890 / amd-halo — premium apps + TA completion gates.
set -euo pipefail

REPO="${REPO:-/home/cisco/code/splunk-cisco-skills}"
LOG="${LOG:-/tmp/labval-wave2-$(date +%Y%m%dT%H%M%S).log}"
SPLUNK_HOME="${SPLUNK_HOME:-/opt/splunk}"
RESULTS_DIR="${RESULTS_DIR:-/tmp/labval-wave2-results}"
export SPLUNK_HOME
export SPLUNK_PROFILE="${SPLUNK_PROFILE:-lab_6890}"
export SPLUNK_NONINTERACTIVE=1
export SPLUNK_SKILLS_LIVE_VALIDATION=1

exec > >(tee -a "${LOG}") 2>&1

section() { echo ""; echo "===== $* ====="; }

export_lab_rest_auth() {
  if [[ ! -f /tmp/labval_splunk_admin ]]; then
    echo "WARN: /tmp/labval_splunk_admin missing"
    return 1
  fi
  sudo cp /tmp/labval_splunk_admin /tmp/labval_splunk_admin.splunk
  sudo chown splunk:splunk /tmp/labval_splunk_admin.splunk
  sudo chmod 600 /tmp/labval_splunk_admin.splunk
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

prepare_splunk_admin_file() {
  [[ -f /tmp/labval_splunk_admin ]] || return 1
  sudo cp /tmp/labval_splunk_admin /tmp/labval_splunk_admin.splunk
  sudo chown splunk:splunk /tmp/labval_splunk_admin.splunk
  sudo chmod 600 /tmp/labval_splunk_admin.splunk
}

run_validate() {
  local skill="$1"
  local out="${RESULTS_DIR}/${skill}.log"
  shift
  mkdir -p "${RESULTS_DIR}"
  echo "VALIDATE ${skill}: $*"
  set +e
  bash "${REPO}/skills/${skill}/scripts/validate.sh" "$@" >"${out}" 2>&1
  local rc=$?
  set -e
  echo "RC=${rc}"
  tail -8 "${out}" || true
  echo "${rc}" >"${RESULTS_DIR}/${skill}.rc"
  return 0
}

create_index_rest() {
  local idx="$1"
  local sk
  # shellcheck disable=SC1091
  source "${REPO}/skills/shared/lib/credential_helpers.sh"
  export_lab_rest_auth
  load_splunk_credentials || return 1
  sk=$(get_session_key "${SPLUNK_URI}") || return 1
  if platform_create_index "${sk}" "${SPLUNK_URI}" "${idx}" "512000"; then
    echo "Created/verified index ${idx}"
  else
    echo "WARN: index ${idx} create failed"
  fi
}

inject_oneshot() {
  local index="$1" sourcetype="$2" payload="$3"
  local f="/tmp/labval-sample-${index}.log"
  prepare_splunk_admin_file || return 1
  echo "${payload}" | sudo tee "${f}" >/dev/null
  sudo chown splunk:splunk "${f}"
  sudo -u splunk env SPLUNK_HOME="${SPLUNK_HOME}" \
    "${SPLUNK_HOME}/bin/splunk" add oneshot "${f}" -index "${index}" -sourcetype "${sourcetype}" \
    -auth "admin:$(sudo cat /tmp/labval_splunk_admin.splunk)" 2>&1 | tail -1 \
    || echo "WARN: oneshot failed ${index}/${sourcetype}"
}

inject_sc4s_asa_sample() {
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
        print(f"Injected ASA syslog via {kind}")
    except OSError as exc:
        print(f"WARN: syslog {kind}: {exc}")
PY
}

init_itsi_kpi_template() {
  # shellcheck disable=SC1091
  source "${REPO}/skills/shared/lib/credential_helpers.sh"
  export_lab_rest_auth
  load_splunk_credentials || return 1
  local sk
  sk=$(get_session_key "${SPLUNK_URI}") || return 1
  local body='{"name":"labval_kpi_template_seed","title":"Lab KPI Template Seed","description":"Wave 2 lab validation seed"}'
  local code
  code=$(splunk_curl_post "${sk}" "${body}" \
    "${SPLUNK_URI}/servicesNS/nobody/SA-ITOA/storage/collections/data/itsi_kpi_template" \
    -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
  echo "itsi_kpi_template seed POST HTTP ${code}"
}

dashboard_probe() {
  local app="$1" label="$2"
  # shellcheck disable=SC1091
  source "${REPO}/skills/shared/lib/credential_helpers.sh"
  export_lab_rest_auth
  load_splunk_credentials || return 1
  local sk
  sk=$(get_session_key "${SPLUNK_URI}") || return 1
  local views count
  views=$(splunk_curl "${sk}" \
    "${SPLUNK_URI}/servicesNS/-/${app}/data/ui/views?count=0&output_mode=json" 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("entry",[])))' 2>/dev/null || echo 0)
  echo "DASHBOARD ${label}: app=${app} views=${views}"
}

event_count() {
  local query="$1"
  # shellcheck disable=SC1091
  source "${REPO}/skills/shared/lib/credential_helpers.sh"
  export_lab_rest_auth
  load_splunk_credentials || return 1
  local sk
  sk=$(get_session_key "${SPLUNK_URI}") || return 1
  rest_oneshot_search "${sk}" "${SPLUNK_URI}" "${query}" "count" 2>/dev/null || echo 0
}

section "ENV"
hostname
date -u
test -d "${REPO}" || { echo "ERROR: repo missing"; exit 1; }
cd "${REPO}"
mkdir -p "${RESULTS_DIR}"
export_lab_rest_auth || true
splunk_login_local || true
sudo -u splunk "${SPLUNK_HOME}/bin/splunk" version | head -1

section "INDEX BOOTSTRAP"
for idx in aws msexchange ontap vmware vmware_esxi vmware_metrics cisco_asa catalyst ise sdwan; do
  create_index_rest "${idx}" || true
done

section "SAMPLE INGEST (ONESHOT + SYSLOG)"
inject_oneshot aws aws:cloudtrail '{"eventVersion":"1.08","eventSource":"signin.amazonaws.com","eventName":"ConsoleLogin"}'
inject_oneshot msexchange 'MSExchange:2013:MessageTracking' "2026-09-09T20:00:00Z,lab@example.com,user@example.com,labval-wave2"
inject_oneshot ontap ontap:syslog "Sep  9 20:00:00 ontap-lab labval ONTAP syslog sample"
inject_oneshot vmware vmware:vclog "labval vCenter log sample"
inject_oneshot vmware_esxi vmware:esxlog "labval ESXi log sample"
inject_oneshot cisco_asa cisco:asa "%ASA-6-302013: Built outbound TCP connection 99999 for outside:192.0.2.10/443 to inside:10.1.1.5/50123"
inject_sc4s_asa_sample
sleep 25

section "ITSI KV INIT"
init_itsi_kpi_template || true

section "CISCO TA INSTALL (if missing)"
# shellcheck disable=SC1091
source "${REPO}/skills/shared/lib/credential_helpers.sh"
export_lab_rest_auth
load_splunk_credentials || true
SK=$(get_session_key "${SPLUNK_URI}" 2>/dev/null || echo "")
if [[ -n "${SK}" ]]; then
  install_as_splunk() {
    local pkg="$1"
    sudo cp "${pkg}" /tmp/labval-install.spl
    sudo chown splunk:splunk /tmp/labval-install.spl
    sudo -u splunk env SPLUNK_HOME="${SPLUNK_HOME}" \
      "${SPLUNK_HOME}/bin/splunk" install app /tmp/labval-install.spl \
      -auth "admin:${SPLUNK_PASS}" -update 1 2>&1 | tail -3
  }
  if ! rest_check_app "${SK}" "${SPLUNK_URI}" "Splunk_TA_cisco-asa" 2>/dev/null; then
    install_as_splunk "${REPO}/splunk-ta/splunk-add-on-for-cisco-asa_612.spl" || echo "WARN: ASA TA install failed"
  else
    echo "Splunk_TA_cisco-asa already installed"
  fi
  if ! rest_check_app "${SK}" "${SPLUNK_URI}" "TA_cisco_catalyst" 2>/dev/null; then
    install_as_splunk "${REPO}/splunk-ta/cisco-enterprise-networking-add-on-for-splunk_3244.tgz" || echo "WARN: Catalyst TA install failed"
  else
    echo "TA_cisco_catalyst already installed"
  fi
fi

section "TIER A: ES INSTALL"
run_validate splunk-enterprise-security-install --completion

section "TIER A: ES CONFIG"
run_validate splunk-enterprise-security-config --completion

section "TIER A: ITSI SETUP"
run_validate splunk-itsi-setup --completion

section "TIER A: ITSI CONFIG (catalog only)"
bash skills/splunk-security-portfolio-setup/scripts/validate.sh 2>&1 | tail -5 || true
echo "ITSI config requires --workflow/--spec; standalone SH: not-applicable for live topology apply"

section "TIER B: AWS TA"
run_validate splunk-aws-ta-setup --completion

section "TIER B: EXCHANGE TA"
run_validate splunk-microsoft-exchange-ta-setup || true
# Live gate via search evidence
cnt=$(event_count "index=msexchange earliest=-1h | stats count")
echo "INGEST msexchange events=${cnt}"
dashboard_probe "TA-Exchange-Mailbox" "Exchange"

section "TIER B: ONTAP TA"
run_validate splunk-netapp-ontap-ta-setup || true
cnt=$(event_count "index=ontap earliest=-1h | stats count")
echo "INGEST ontap events=${cnt}"
dashboard_probe "Splunk_TA_ontap" "ONTAP"

section "TIER B: VMWARE TA"
run_validate splunk-vmware-ta-setup --live 2>/dev/null || run_validate splunk-vmware-ta-setup || true
cnt=$(event_count "index=vmware OR index=vmware_esxi earliest=-1h | stats count")
echo "INGEST vmware events=${cnt}"
dashboard_probe "Splunk_TA_vmware" "VMware"

section "TIER B: APPDYNAMICS VERIFY"
run_validate cisco-appdynamics-setup --completion --strict || true
cnt=$(event_count "index=appdynamics earliest=-24h | stats count")
echo "INGEST appdynamics events=${cnt}"

section "TIER C: CISCO ASA"
run_validate cisco-asa-ta-setup --live --completion || true
cnt=$(event_count "| tstats count where index=cisco_asa sourcetype=\"cisco:asa\"")
echo "INGEST cisco_asa tstats=${cnt}"
dashboard_probe "Splunk_TA_cisco-asa" "ASA"

section "TIER C: CISCO CATALYST"
run_validate cisco-catalyst-ta-setup --live --completion 2>/dev/null || run_validate cisco-catalyst-ta-setup --live || true
dashboard_probe "TA_cisco_catalyst" "Catalyst"

section "TIER D: SECURITY PORTFOLIO"
run_validate splunk-security-essentials-setup --completion || true
run_validate splunk-security-content-update-setup --live 2>/dev/null || true
bash skills/splunk-security-portfolio-setup/scripts/validate.sh 2>&1 | tail -10 || true

section "DASHBOARD / MACRO SPOT CHECKS"
dashboard_probe "SplunkEnterpriseSecuritySuite" "ES"
dashboard_probe "itsi" "ITSI"
dashboard_probe "Splunk_TA_aws" "AWS"
cnt=$(event_count "| tstats count from datamodel=Network_Traffic earliest=-24h")
echo "CIM Network_Traffic tstats=${cnt}"

section "DONE"
echo "Log: ${LOG}"
echo "Results: ${RESULTS_DIR}"
ls -la "${RESULTS_DIR}" || true
