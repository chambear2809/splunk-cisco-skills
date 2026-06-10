#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
RENDER_SCRIPT="${SCRIPT_DIR}/render_assets.py"
INSTALL=false; RENDER=false; JSON=false; DRY_RUN=false; ACCEPT_UNSUPPORTED_10_4_TOMCAT=false
INDEX="web"; SYSLOG_INDEX="netproxy"; WINDOWS_INDEX="iis"; PRODUCTS="apache,nginx,iis,tomcat,haproxy,squid,bluecoat,forcepoint,checkpoint,f5,citrix,infoblox"; SERVER_NAME="web01"; LOG_ROOT="/var/log"; SYSLOG_PORT="514"; OUTPUT_DIR=""
SPLUNK_VERSION="10.4"
usage(){ cat >&2 <<EOF
Syslog/Web/Proxy Supported Add-on Setup

Usage: $(basename "$0") [OPTIONS]

Options:
  --render                 Render monitor templates, transport handoffs, plan, validation SPL
  --install                Emit install commands in rendered assets; live install remains through splunk-app-install
  --index INDEX            Local file/web-server event index (default: web)
  --syslog-index INDEX     Appliance/syslog event index (default: netproxy)
  --windows-index INDEX    IIS Windows event index (default: iis)
  --products LIST          Products: apache,nginx,iis,tomcat,haproxy,squid,bluecoat,forcepoint,checkpoint,f5,citrix,infoblox
  --splunk-version VERSION Target Splunk version for compatibility gates (default: 10.4)
  --accept-unsupported-10-4-tomcat
                            Deprecated no-op; Tomcat app 2911 advertises 10.4 support
  --server-name NAME       Host value for local monitor templates
  --log-root DIR           Local Unix log root for monitor templates
  --syslog-port PORT       Syslog handoff port (default: 514)
  --output-dir DIR         Render output directory
  --json                   Emit JSON from render script
  --dry-run                Show render targets without writing files
  --help                   Show this help

This skill does not accept credential values. Product-specific API credentials, where applicable, are handled by each add-on account flow.
EOF
exit "${1:-0}"; }
while [[ $# -gt 0 ]]; do case "$1" in --render) RENDER=true; shift ;; --install) INSTALL=true; shift ;; --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;; --syslog-index) require_arg "$1" $# || exit 1; SYSLOG_INDEX="$2"; shift 2 ;; --windows-index) require_arg "$1" $# || exit 1; WINDOWS_INDEX="$2"; shift 2 ;; --products) require_arg "$1" $# || exit 1; PRODUCTS="$2"; shift 2 ;; --splunk-version) require_arg "$1" $# || exit 1; SPLUNK_VERSION="$2"; shift 2 ;; --accept-unsupported-10-4-tomcat) ACCEPT_UNSUPPORTED_10_4_TOMCAT=true; shift ;; --server-name) require_arg "$1" $# || exit 1; SERVER_NAME="$2"; shift 2 ;; --log-root) require_arg "$1" $# || exit 1; LOG_ROOT="$2"; shift 2 ;; --syslog-port) require_arg "$1" $# || exit 1; SYSLOG_PORT="$2"; shift 2 ;; --output-dir) require_arg "$1" $# || exit 1; OUTPUT_DIR="$2"; shift 2 ;; --json) JSON=true; shift ;; --dry-run) DRY_RUN=true; shift ;; --help|-h) usage ;; *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;; esac; done
[[ "${RENDER}" == "false" && "${INSTALL}" == "false" ]] && RENDER=true
run_render(){ local cmd=(python3 "${RENDER_SCRIPT}" --phase render --index "${INDEX}" --syslog-index "${SYSLOG_INDEX}" --windows-index "${WINDOWS_INDEX}" --products "${PRODUCTS}" --splunk-version "${SPLUNK_VERSION}" --server-name "${SERVER_NAME}" --log-root "${LOG_ROOT}" --syslog-port "${SYSLOG_PORT}"); [[ "${ACCEPT_UNSUPPORTED_10_4_TOMCAT}" == "true" ]] && cmd+=(--accept-unsupported-10-4-tomcat); [[ -n "${OUTPUT_DIR}" ]] && cmd+=(--output-dir "${OUTPUT_DIR}"); [[ "${JSON}" == "true" ]] && cmd+=(--json); [[ "${DRY_RUN}" == "true" ]] && cmd+=(--dry-run); "${cmd[@]}"; }
warn_if_current_skill_role_unsupported
run_render
log "Syslog/web/proxy render complete. Review monitor templates and transport handoffs before applying them."
