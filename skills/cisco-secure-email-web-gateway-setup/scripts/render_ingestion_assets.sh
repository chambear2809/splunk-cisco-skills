#!/usr/bin/env bash
set -euo pipefail

PRODUCT="both"
OUTPUT_DIR="./cisco-secure-email-web-gateway-rendered"
ESA_HOST_FILTER="^esa-"
WSA_HOST_FILTER="^wsa-"
ESA_INDEX="email"
WSA_INDEX="netproxy"

usage() {
    cat >&2 <<EOF
Render SC4S and file-monitor handoff snippets for Cisco ESA/WSA.

Usage: $(basename "$0") [OPTIONS]

Options:
  --product esa|wsa|both
  --output-dir DIR
  --esa-host-filter REGEX
  --wsa-host-filter REGEX
  --esa-index INDEX
  --wsa-index INDEX
  --help
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --product) [[ $# -ge 2 ]] || usage 1; PRODUCT="$2"; shift 2 ;;
        --output-dir) [[ $# -ge 2 ]] || usage 1; OUTPUT_DIR="$2"; shift 2 ;;
        --esa-host-filter) [[ $# -ge 2 ]] || usage 1; ESA_HOST_FILTER="$2"; shift 2 ;;
        --wsa-host-filter) [[ $# -ge 2 ]] || usage 1; WSA_HOST_FILTER="$2"; shift 2 ;;
        --esa-index) [[ $# -ge 2 ]] || usage 1; ESA_INDEX="$2"; shift 2 ;;
        --wsa-index) [[ $# -ge 2 ]] || usage 1; WSA_INDEX="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

case "${PRODUCT}" in
    esa|wsa|both) ;;
    *) echo "ERROR: --product must be esa, wsa, or both." >&2; exit 1 ;;
esac

want_esa() { [[ "${PRODUCT}" == "esa" || "${PRODUCT}" == "both" ]]; }
want_wsa() { [[ "${PRODUCT}" == "wsa" || "${PRODUCT}" == "both" ]]; }

mkdir -p "${OUTPUT_DIR}"

if want_esa; then
    cat >"${OUTPUT_DIR}/app-vps-cisco_esa.conf" <<EOF
# Suggested SC4S parser override for Cisco ESA.
# Place under /opt/sc4s/local/config/app-parsers/ and restart SC4S.
application app-vps-cisco_esa[sc4s-vps] {
  filter {
    host("${ESA_HOST_FILTER}");
  };
  parser {
    p_set_netsource_fields(
      vendor('cisco')
      product('esa')
    );
  };
};
EOF
    cat >"${OUTPUT_DIR}/inputs-cisco-esa.conf" <<EOF
# Optional direct Splunk file-monitor example for ESA logs.
# Prefer SC4S for syslog collection when possible.
[monitor:///var/log/cisco/esa/*.log]
disabled = 0
index = ${ESA_INDEX}
sourcetype = cisco:esa
EOF
fi

if want_wsa; then
    cat >"${OUTPUT_DIR}/app-vps-cisco_wsa.conf" <<EOF
# Suggested SC4S parser override for Cisco WSA.
# Place under /opt/sc4s/local/config/app-parsers/ and restart SC4S.
application app-vps-cisco_wsa[sc4s-vps] {
  filter {
    host("${WSA_HOST_FILTER}");
  };
  parser {
    p_set_netsource_fields(
      vendor('cisco')
      product('wsa')
    );
  };
};
EOF
    cat >"${OUTPUT_DIR}/inputs-cisco-wsa.conf" <<EOF
# Optional direct Splunk file-monitor example for WSA logs.
# Prefer SC4S for syslog collection when possible.
[monitor:///var/log/cisco/wsa/*.log]
disabled = 0
index = ${WSA_INDEX}
sourcetype = cisco:wsa:syslog
EOF
fi

cat >"${OUTPUT_DIR}/README.txt" <<EOF
Cisco ESA/WSA ingestion handoff

Generated snippets:
- app-vps-cisco_esa.conf / app-vps-cisco_wsa.conf: SC4S parser hints.
- inputs-cisco-*.conf: optional direct file-monitor examples.

Use skills/splunk-connect-for-syslog-setup for SC4S runtime deployment,
HEC token preparation, and host/Kubernetes rendering.
EOF

echo "Rendered ingestion handoff assets in ${OUTPUT_DIR}"
