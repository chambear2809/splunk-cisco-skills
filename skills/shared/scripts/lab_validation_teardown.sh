#!/usr/bin/env bash
set -euo pipefail

# Campaign teardown for PROFILE_lab_6890 validation runs.
# Leaves /home/cisco/splunk running; does not restore archived trees.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"

PROFILE="${SPLUNK_PROFILE:-lab_6890}"
export SPLUNK_PROFILE="${PROFILE}"
load_splunk_ssh_credentials

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

ssh_lab() {
  ssh -o BatchMode=yes "${SPLUNK_SSH_USER}@${SPLUNK_SSH_HOST}" "$@"
}

log "Teardown: removing labval collector roots and campaign artifacts on ${SPLUNK_SSH_HOST}"
ssh_lab 'set -euo pipefail
for path in /home/cisco/labval-sc4s /home/cisco/labval-sc4snmp /opt/splunkforwarder; do
  if [ -e "$path" ]; then
    echo "removing $path"
    sudo rm -rf "$path"
  fi
done
if command -v docker >/dev/null 2>&1; then
  docker ps -a --format "{{.Names}}" | grep -E "^labval" | xargs -r docker rm -f || true
fi
if command -v podman >/dev/null 2>&1; then
  podman ps -a --format "{{.Names}}" | grep -E "^labval" | xargs -r podman rm -f || true
fi
rm -f /tmp/labval_admin_pass
'

log "Teardown: removing workstation temp artifacts"
rm -f /tmp/labval_splunk_admin /tmp/labval_splunk_ca.pem

log "Teardown complete; Splunk Enterprise left running at /home/cisco/splunk"
