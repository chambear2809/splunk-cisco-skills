#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

OUTPUT_DIR="${PROJECT_ROOT}/splunk-db-connect-rendered"
LIVE=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk DB Connect Rendered Asset Validation

Usage: $(basename "$0") --output-dir PATH [--live]

Options:
  --output-dir PATH        Directory passed to setup.sh --output-dir
  --live                   Also run rendered preflight.sh on this host
  --help
EOF
    exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --output-dir requires a value." >&2
                exit 1
            fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --live) LIVE=true; shift ;;
        --help) usage 0 ;;
        *) echo "ERROR: Unknown option: $1" >&2; usage 1 ;;
    esac
done

if [[ -f "${OUTPUT_DIR}/metadata.json" ]]; then
    ROOT="${OUTPUT_DIR}"
elif [[ -f "${OUTPUT_DIR}/splunk-db-connect/metadata.json" ]]; then
    ROOT="${OUTPUT_DIR}/splunk-db-connect"
else
    echo "ERROR: Could not find metadata.json under ${OUTPUT_DIR}." >&2
    exit 1
fi

required_files=(
    "README.md"
    "metadata.json"
    "coverage.json"
    "preflight.sh"
    "install/install-apps.sh"
    "java/java-preflight.sh"
    "drivers/driver-inventory.json"
    "drivers/custom-driver-app/default/app.conf"
    "drivers/custom-driver-app/default/db_connection_types.conf"
    "drivers/custom-driver-app/lib/dbxdrivers/README.md"
    "topology/shc-deployer.md"
    "topology/hf-ha-etcd-plan.md"
    "operations/upgrade-backup-health.md"
    "operations/federated-search.md"
    "indexes/indexes.conf"
    "hec/handoff-hec-service.sh"
    "dbx/dbx_settings.conf.preview"
    "dbx/db_connections.conf.preview"
    "dbx/db_inputs.conf.preview"
    "dbx/db_outputs.conf.preview"
    "dbx/db_lookups.conf.preview"
    "validation/validation.spl"
    "validation/rest-checks.sh"
    "validation/btool-checks.sh"
    "security/guardrails.md"
    "security/auth-handoffs.md"
    "security/fips-plan.md"
    "security/client-cert-plan.md"
    "troubleshooting/runbook.md"
)

missing=0
for rel in "${required_files[@]}"; do
    if [[ ! -f "${ROOT}/${rel}" ]]; then
        echo "ERROR: Missing rendered file: ${rel}" >&2
        missing=$((missing + 1))
    fi
done
if (( missing > 0 )); then
    exit 1
fi

python3 -m json.tool "${ROOT}/metadata.json" >/dev/null
python3 -m json.tool "${ROOT}/coverage.json" >/dev/null
python3 -m json.tool "${ROOT}/drivers/driver-inventory.json" >/dev/null

for script in \
    "${ROOT}/preflight.sh" \
    "${ROOT}/install/install-apps.sh" \
    "${ROOT}/java/java-preflight.sh" \
    "${ROOT}/hec/handoff-hec-service.sh" \
    "${ROOT}/validation/rest-checks.sh" \
    "${ROOT}/validation/btool-checks.sh"; do
    bash -n "${script}"
done

# shellcheck disable=SC2016 # literal $7$ marker is intentional.
if grep -R -n -E '(\$7\$|password *= *[^<[:space:]]|secret *= *[^<[:space:]]|token *= *[^<[:space:]])' "${ROOT}" >/tmp/splunk_db_connect_secret_scan.$$ 2>/dev/null; then
    cat /tmp/splunk_db_connect_secret_scan.$$ >&2
    rm -f /tmp/splunk_db_connect_secret_scan.$$
    echo "ERROR: Rendered output appears to contain secret material." >&2
    exit 1
fi
rm -f /tmp/splunk_db_connect_secret_scan.$$

if [[ "${LIVE}" == true ]]; then
    bash "${ROOT}/preflight.sh"
fi

echo "OK: Splunk DB Connect rendered assets validated at ${ROOT}"
