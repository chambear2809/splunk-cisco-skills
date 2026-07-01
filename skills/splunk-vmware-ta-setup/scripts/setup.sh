#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
source "${PROJECT_ROOT}/shared/lib/credential_helpers.sh"

RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
APP_INSTALL_SCRIPT="${APP_INSTALL_SCRIPT:-${PROJECT_ROOT}/splunk-app-install/scripts/install_app.sh}"

RENDER=false
JSON_OUTPUT=false
OUTPUT_DIR="${PROJECT_ROOT}/../splunk-vmware-ta-rendered"
EVENT_INDEX="vmware"
ESXI_INDEX="vmware_esxi"
METRICS_INDEX="vmware_metrics"
VCENTER_ACCOUNT="vc_prod"
VCENTER_HOST=""
INSTALL_PACKAGES=()

usage() {
    cat <<'EOF'
Splunk VMware TA Setup

Usage:
  bash skills/splunk-vmware-ta-setup/scripts/setup.sh [options]

Options:
  --render                    Render VMware setup assets
  --json                      Emit JSON for render output
  --output-dir DIR            Render output directory
  --event-index INDEX         vCenter event/inventory index (default: vmware)
  --esxi-index INDEX          ESXi syslog index (default: vmware_esxi)
  --metrics-index INDEX       VMware metrics index (default: vmware_metrics)
  --vcenter-account NAME      vCenter account stanza name (default: vc_prod)
  --vcenter-host HOST         Optional vCenter hostname for runbooks
  --install-package PATH      Install a local VMware app/add-on package; repeatable
  --help                      Show this help

Credential values are never accepted on argv. Configure vCenter credentials
through the selected VMware add-on account workflow using local secret files.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --render) RENDER=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --output-dir) require_arg "$1" "$#" || exit 1; OUTPUT_DIR="$2"; shift 2 ;;
        --event-index|--index) require_arg "$1" "$#" || exit 1; EVENT_INDEX="$2"; shift 2 ;;
        --esxi-index) require_arg "$1" "$#" || exit 1; ESXI_INDEX="$2"; shift 2 ;;
        --metrics-index) require_arg "$1" "$#" || exit 1; METRICS_INDEX="$2"; shift 2 ;;
        --vcenter-account) require_arg "$1" "$#" || exit 1; VCENTER_ACCOUNT="$2"; shift 2 ;;
        --vcenter-host) require_arg "$1" "$#" || exit 1; VCENTER_HOST="$2"; shift 2 ;;
        --install-package) require_arg "$1" "$#" || exit 1; INSTALL_PACKAGES+=("$2"); shift 2 ;;
        --password|--secret|--token|--api-token|--client-secret)
            reject_secret_arg "$1" "the VMware add-on account UI or a local secret file"
            exit 1
            ;;
        --password=*|--secret=*|--token=*|--api-token=*|--client-secret=*)
            reject_secret_arg "${1%%=*}" "the VMware add-on account UI or a local secret file"
            exit 1
            ;;
        --help|-h) usage; exit 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done
validate_splunk_index_name "${EVENT_INDEX}" || exit 1
validate_splunk_index_name "${ESXI_INDEX}" || exit 1
validate_splunk_index_name "${METRICS_INDEX}" || exit 1

if [[ "${RENDER}" == "false" && "${#INSTALL_PACKAGES[@]}" -eq 0 ]]; then
    RENDER=true
fi
if [[ "${JSON_OUTPUT}" == "true" && "${#INSTALL_PACKAGES[@]}" -gt 0 ]]; then
    echo "ERROR: --json cannot be combined with --install-package." >&2
    exit 1
fi
if [[ "${#INSTALL_PACKAGES[@]}" -gt 0 ]]; then
    require_current_skill_role_supported
    require_splunk_management_target_role
fi

for package in "${INSTALL_PACKAGES[@]}"; do
    bash "${APP_INSTALL_SCRIPT}" --source local --file "${package}" --no-update
done

if [[ "${RENDER}" == "true" ]]; then
    args=(
        --event-index "${EVENT_INDEX}"
        --esxi-index "${ESXI_INDEX}"
        --metrics-index "${METRICS_INDEX}"
        --vcenter-account "${VCENTER_ACCOUNT}"
        --output-dir "${OUTPUT_DIR}"
    )
    [[ -n "${VCENTER_HOST}" ]] && args+=(--vcenter-host "${VCENTER_HOST}")
    [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
    python3 "${RENDER_SCRIPT}" "${args[@]}"
fi
