#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP="${SCRIPT_DIR}/setup.sh"

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Supported Add-ons Setup Validation

Usage: $(basename "$0") [OPTIONS]

Options:
  --help    Show this help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

tmpdir="$(mktemp -d)"
cleanup() {
    rm -rf "${tmpdir}"
}
trap cleanup EXIT

bash "${SETUP}" --phase list --json >/dev/null
bash "${SETUP}" --phase coverage --json >/dev/null
bash "${SETUP}" --phase resolve --profile Splunk_TA_nix --json >/dev/null
bash "${SETUP}" --phase resolve --profile collectd --json >/dev/null
bash "${SETUP}" --phase resolve --profile "Microsoft Windows" --json >/dev/null
bash "${SETUP}" --phase resolve --profile "Cisco ISE" --json >/dev/null
bash "${SETUP}" --phase install-command --profile 833 --json >/dev/null
bash "${SETUP}" --phase install-command --profile "Apache Web Server" --json >/dev/null
bash "${SETUP}" --phase render --profile unix-linux --output-dir "${tmpdir}" >/dev/null
bash "${SETUP}" --phase render --profile linux-collectd --output-dir "${tmpdir}" >/dev/null
bash "${SETUP}" --phase render --profile "Apache Web Server" --output-dir "${tmpdir}" >/dev/null

test -f "${tmpdir}/unix-linux-os-scripts/profile-plan.md"
test -f "${tmpdir}/unix-linux-os-scripts/inputs.local.conf.template"
test -f "${tmpdir}/linux-collectd-auditd/profile-plan.md"
test -f "${tmpdir}/linux-collectd-auditd/collectd-write-http.conf.template"
test -f "${tmpdir}/apache-web-server/handoff-plan.md"
test -f "${tmpdir}/apache-web-server/install-commands.sh"

printf 'PASS: Splunk Supported Add-ons catalog and render assets validated\n'
