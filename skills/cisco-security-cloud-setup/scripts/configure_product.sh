#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIGURE_INPUT_SCRIPT="${SCRIPT_DIR}/configure_input.sh"
PRODUCTS_FILE="${SCRIPT_DIR}/../products.json"

PRODUCT=""
INPUT_NAME=""
DISABLE_INPUT=false
CREATE_INDEX=true
LIST_PRODUCTS=false

USER_KEYS=()
USER_VALUES=()
USER_SECRET_KEYS=()
USER_SECRET_PATHS=()

require_value() {
    if [[ "$2" -lt 2 ]]; then
        echo "ERROR: Option '$1' requires a value."
        exit 1
    fi
}

usage() {
    cat <<EOF
Cisco Security Cloud Product Setup

Usage: $(basename "$0") [OPTIONS]

Required:
  --product NAME             Product key from --list-products

Options:
  --name NAME                Override the default stanza name
  --set KEY VALUE            Set a non-secret field (repeatable)
  --secret-file KEY PATH     Read a secret field value from PATH (repeatable)
  --disable                  Create or update the stanza as disabled
  --no-create-index          Do not auto-create the target index
  --list-products            Show the available product keys
  --help                     Show this help

Example:
  $(basename "$0") \\
    --product xdr \\
    --set region us \\
    --set auth_method client_id \\
    --set client_id example-client-id \\
    --set xdr_import_time_range "7 days ago" \\
    --secret-file refresh_token /tmp/xdr_refresh_token
EOF
    exit 0
}

append_kv() {
    local key="$1" value="$2" i
    for i in "${!USER_KEYS[@]}"; do
        if [[ "${USER_KEYS[$i]}" == "${key}" ]]; then
            USER_VALUES[i]="${value}"
            return 0
        fi
    done
    USER_KEYS+=("${key}")
    USER_VALUES+=("${value}")
}

append_secret() {
    local key="$1" path="$2" i
    for i in "${!USER_SECRET_KEYS[@]}"; do
        if [[ "${USER_SECRET_KEYS[$i]}" == "${key}" ]]; then
            USER_SECRET_PATHS[i]="${path}"
            return 0
        fi
    done
    USER_SECRET_KEYS+=("${key}")
    USER_SECRET_PATHS+=("${path}")
}

has_user_key() {
    local key="$1" i
    for i in "${!USER_KEYS[@]}"; do
        if [[ "${USER_KEYS[$i]}" == "${key}" ]]; then
            return 0
        fi
    done
    for i in "${!USER_SECRET_KEYS[@]}"; do
        if [[ "${USER_SECRET_KEYS[$i]}" == "${key}" ]]; then
            return 0
        fi
    done
    return 1
}

list_products() {
    python3 - "${PRODUCTS_FILE}" <<'PY'
import json
import sys
from pathlib import Path

products = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for key in sorted(products):
    entry = products[key]
    print(f"{key}\t{entry['title']}\t{entry['input_type']}")
PY
}

read_product_metadata() {
    python3 - "$PRODUCT" "$PRODUCTS_FILE" <<'PY'
import json
import sys
from pathlib import Path

product = sys.argv[1]
products = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
entry = products.get(product)
if not entry:
    raise SystemExit(1)

print(entry["input_type"])
print(entry["title"])
print(entry["default_name"])
for key, value in entry.get("defaults", {}).items():
    print(f"{key}={value}")
PY
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --product) require_value "$1" $#; PRODUCT="$2"; shift 2 ;;
        --name) require_value "$1" $#; INPUT_NAME="$2"; shift 2 ;;
        --set)
            if [[ $# -lt 3 ]]; then
                echo "ERROR: Option '--set' requires KEY and VALUE."
                exit 1
            fi
            append_kv "$2" "$3"
            shift 3
            ;;
        --secret-file)
            if [[ $# -lt 3 ]]; then
                echo "ERROR: Option '--secret-file' requires KEY and PATH."
                exit 1
            fi
            append_secret "$2" "$3"
            shift 3
            ;;
        --disable) DISABLE_INPUT=true; shift ;;
        --no-create-index) CREATE_INDEX=false; shift ;;
        --list-products) LIST_PRODUCTS=true; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

if ${LIST_PRODUCTS}; then
    list_products
    exit 0
fi

[[ -n "${PRODUCT}" ]] || { echo "ERROR: --product is required."; exit 1; }

metadata_lines=()
while IFS= read -r line || [[ -n "${line}" ]]; do
    metadata_lines+=("${line}")
done < <(read_product_metadata) || {
    echo "ERROR: Unknown product '${PRODUCT}'. Use --list-products."
    exit 1
}

INPUT_TYPE="${metadata_lines[0]}"
PRODUCT_TITLE="${metadata_lines[1]}"
DEFAULT_NAME="${metadata_lines[2]}"
[[ -n "${INPUT_NAME}" ]] || INPUT_NAME="${DEFAULT_NAME}"

cmd=(bash "${CONFIGURE_INPUT_SCRIPT}" --input-type "${INPUT_TYPE}" --name "${INPUT_NAME}")
if ! ${CREATE_INDEX}; then
    cmd+=(--no-create-index)
fi
if ${DISABLE_INPUT}; then
    cmd+=(--disable)
fi

for kv in "${metadata_lines[@]:3}"; do
    key="${kv%%=*}"
    value="${kv#*=}"
    if ! has_user_key "${key}"; then
        cmd+=(--set "${key}" "${value}")
    fi
done

for i in "${!USER_KEYS[@]}"; do
    cmd+=(--set "${USER_KEYS[$i]}" "${USER_VALUES[$i]}")
done
for i in "${!USER_SECRET_KEYS[@]}"; do
    cmd+=(--secret-file "${USER_SECRET_KEYS[$i]}" "${USER_SECRET_PATHS[$i]}")
done

printf 'Configuring %s via %s (input type: %s, stanza: %s)\n' \
    "${PRODUCT_TITLE}" "${PRODUCT}" "${INPUT_TYPE}" "${INPUT_NAME}"
"${cmd[@]}"
