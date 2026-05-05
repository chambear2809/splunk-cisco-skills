#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

APP_NAME="Splunk_TA_cisco-ucs"
NAME=""
DESCRIPTION=""
INTERVAL="300"
SOURCETYPE="cisco:ucs"
INDEX="cisco_ucs"
SERVERS=""
TEMPLATES=""

usage() {
    cat >&2 <<EOF
Configure a Cisco UCS cisco_ucs_task input.

Usage: $(basename "$0") [OPTIONS]

Required:
  --name NAME
  --servers LIST        Comma/pipe list; bare names are prefixed as Splunk_TA_cisco-ucs:<name>
  --templates LIST      Comma/pipe list; bare names are prefixed as Splunk_TA_cisco-ucs:<name>

Optional:
  --description TEXT
  --interval SECONDS    Default: 300
  --sourcetype TYPE     Default: cisco:ucs
  --index INDEX         Default: cisco_ucs
  --help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name) require_arg "$1" $# || exit 1; NAME="$2"; shift 2 ;;
        --description) require_arg "$1" $# || exit 1; DESCRIPTION="$2"; shift 2 ;;
        --interval) require_arg "$1" $# || exit 1; INTERVAL="$2"; shift 2 ;;
        --sourcetype) require_arg "$1" $# || exit 1; SOURCETYPE="$2"; shift 2 ;;
        --index) require_arg "$1" $# || exit 1; INDEX="$2"; shift 2 ;;
        --servers) require_arg "$1" $# || exit 1; SERVERS="$2"; shift 2 ;;
        --templates) require_arg "$1" $# || exit 1; TEMPLATES="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

[[ -n "${NAME}" && -n "${SERVERS}" && -n "${TEMPLATES}" ]] || {
    log "ERROR: --name, --servers, and --templates are required."
    exit 1
}

normalize_refs() {
    local raw="$1"
    python3 - "$raw" <<'PY'
import sys
raw = sys.argv[1].replace("|", ",")
items = [x.strip() for x in raw.split(",") if x.strip()]
out = []
for item in items:
    out.append(item if ":" in item else f"Splunk_TA_cisco-ucs:{item}")
print(" | ".join(out), end="")
PY
}

SERVERS="$(normalize_refs "${SERVERS}")"
TEMPLATES="$(normalize_refs "${TEMPLATES}")"

load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }

body=$(form_urlencode_pairs \
    description "${DESCRIPTION}" \
    interval "${INTERVAL}" \
    sourcetype "${SOURCETYPE}" \
    index "${INDEX}" \
    servers "${SERVERS}" \
    templates "${TEMPLATES}" \
    disabled "0") || exit 1

if rest_create_input "${SK}" "${SPLUNK_URI}" "${APP_NAME}" "cisco_ucs_task" "${NAME}" "${body}"; then
    log "Configured cisco_ucs_task://${NAME} -> index=${INDEX}, servers=${SERVERS}, templates=${TEMPLATES}"
else
    log "ERROR: Failed to configure cisco_ucs_task://${NAME}."
    exit 1
fi
