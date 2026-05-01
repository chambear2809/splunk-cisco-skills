#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"

CATALOG_PATH="${SCRIPT_DIR}/../catalog.json"
REGISTRY_PATH="${SCRIPT_DIR}/../../shared/app_registry.json"
RESOLVE_SCRIPT="${SCRIPT_DIR}/resolve_product.sh"
INSTALL_APP_SCRIPT="${SCRIPT_DIR}/../../splunk-app-install/scripts/install_app.sh"

PRODUCT_QUERY=""
DRY_RUN=false
JSON_OUTPUT=false
INSTALL_ONLY=false
CONFIGURE_ONLY=false
VALIDATE_ONLY=false
LIST_PRODUCTS=false
MODE_FLAGS=0

USER_KEYS=()
USER_VALUES=()
SECRET_KEYS=()
SECRET_PATHS=()

TMP_FILES=()
PRODUCT_FILE=""

ROUTE_TYPE=""
AUTOMATION_STATE=""
PRIMARY_SKILL=""
EFFECTIVE_PRODUCT_KEY=""
EFFECTIVE_DEFAULT_NAME=""
EFFECTIVE_DEFAULT_INDEX=""
EFFECTIVE_INPUT_TYPE=""
EFFECTIVE_ACCOUNT_TYPE=""
EFFECTIVE_VARIANT_KEY=""
EFFECTIVE_VARIANT_VALUE=""
EFFECTIVE_DISCOVERED_ORG_ID=""
WRAPPER_SESSION_READY=false
SK=""

EFFECTIVE_REQUIRED_NON_SECRET_KEYS=()
EFFECTIVE_OPTIONAL_NON_SECRET_KEYS=()
EFFECTIVE_ACCEPTED_SECRET_KEYS=()
EFFECTIVE_REQUIRED_SECRET_KEYS=()
EFFECTIVE_DEFAULT_KEYS=()
EFFECTIVE_DEFAULT_VALUES=()

usage() {
    cat >&2 <<EOF
Cisco Product Setup

Usage: $(basename "$0") [OPTIONS]

Required:
  --product NAME            Cisco product name, alias, or ID

Options:
  --set KEY VALUE           Set a non-secret product field (repeatable)
  --secret-file KEY PATH    Read a secret from PATH (repeatable)
  --dry-run                 Show the resolved workflow without changing Splunk
  --json                    Emit machine-readable JSON with --dry-run or --list-products
  --install-only            Install the required Splunk apps only
  --configure-only          Configure the resolved product only
  --validate-only           Run validation only
  --list-products           List catalog products and automation states
  --catalog PATH            Override catalog.json path
  --help                    Show this help

Examples:
  $(basename "$0") --product "Cisco ACI" --dry-run
  $(basename "$0") --product "Nexus 9000" \\
    --set hostname apic1.example.local \\
    --set username splunk \\
    --secret-file password /tmp/nexus_password
  $(basename "$0") --product "Cisco Secure Firewall" \\
    --set variant api \\
    --set fmc_host https://fmc.example.local \\
    --set username api-user \\
    --secret-file password /tmp/sfw_password
EOF
    exit "${1:-0}"
}

cleanup() {
    local path
    for path in "${TMP_FILES[@]:-}"; do
        [[ -n "${path}" && -e "${path}" ]] && rm -f "${path}"
    done
    return 0
}
trap cleanup EXIT

new_tmp_file() {
    local path
    path="$(mktemp)"
    TMP_FILES+=("${path}")
    printf '%s' "${path}"
}

normalize_key() {
    printf '%s' "${1:-}" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/_/g; s/^_+//; s/_+$//; s/_+/_/g'
}

normalize_variant() {
    normalize_key "${1:-}"
}

is_truthy() {
    case "$(normalize_key "${1:-}")" in
        1|true|yes|y|on) return 0 ;;
        *) return 1 ;;
    esac
}

lookup_user_value() {
    local key normalized i
    key="${1:-}"
    normalized="$(normalize_key "${key}")"
    for i in "${!USER_KEYS[@]}"; do
        if [[ "${USER_KEYS[$i]}" == "${normalized}" ]]; then
            printf '%s' "${USER_VALUES[$i]}"
            return 0
        fi
    done
    return 1
}

has_user_value() {
    lookup_user_value "${1:-}" >/dev/null 2>&1
}

append_user_value() {
    local normalized value i
    normalized="$(normalize_key "${1:-}")"
    value="${2:-}"
    for i in "${!USER_KEYS[@]}"; do
        if [[ "${USER_KEYS[$i]}" == "${normalized}" ]]; then
            USER_VALUES[i]="${value}"
            return 0
        fi
    done
    USER_KEYS+=("${normalized}")
    USER_VALUES+=("${value}")
}

lookup_secret_file() {
    local key normalized i
    key="${1:-}"
    normalized="$(normalize_key "${key}")"
    for i in "${!SECRET_KEYS[@]}"; do
        if [[ "${SECRET_KEYS[$i]}" == "${normalized}" ]]; then
            printf '%s' "${SECRET_PATHS[$i]}"
            return 0
        fi
    done
    return 1
}

has_secret_file() {
    lookup_secret_file "${1:-}" >/dev/null 2>&1
}

secret_file_status() {
    local key="$1" path
    if ! path="$(lookup_secret_file "${key}" 2>/dev/null)"; then
        printf '%s' "missing"
        return 0
    fi
    if [[ ! -f "${path}" ]]; then
        printf 'missing: %s' "${path}"
        return 0
    fi
    if [[ ! -r "${path}" ]]; then
        printf 'unreadable: %s' "${path}"
        return 0
    fi
    printf '%s' "ready"
}

append_secret_file() {
    local normalized path i
    normalized="$(normalize_key "${1:-}")"
    path="${2:-}"
    for i in "${!SECRET_KEYS[@]}"; do
        if [[ "${SECRET_KEYS[$i]}" == "${normalized}" ]]; then
            SECRET_PATHS[i]="${path}"
            return 0
        fi
    done
    SECRET_KEYS+=("${normalized}")
    SECRET_PATHS+=("${path}")
}

append_unique_required_non_secret() {
    local value="$1" i
    [[ -n "${value}" ]] || return 0
    for i in "${!EFFECTIVE_REQUIRED_NON_SECRET_KEYS[@]}"; do
        [[ "${EFFECTIVE_REQUIRED_NON_SECRET_KEYS[$i]}" == "${value}" ]] && return 0
    done
    EFFECTIVE_REQUIRED_NON_SECRET_KEYS+=("${value}")
}

append_unique_optional_non_secret() {
    local value="$1" i
    [[ -n "${value}" ]] || return 0
    for i in "${!EFFECTIVE_OPTIONAL_NON_SECRET_KEYS[@]}"; do
        [[ "${EFFECTIVE_OPTIONAL_NON_SECRET_KEYS[$i]}" == "${value}" ]] && return 0
    done
    EFFECTIVE_OPTIONAL_NON_SECRET_KEYS+=("${value}")
}

append_unique_accepted_secret() {
    local value="$1" i
    [[ -n "${value}" ]] || return 0
    for i in "${!EFFECTIVE_ACCEPTED_SECRET_KEYS[@]}"; do
        [[ "${EFFECTIVE_ACCEPTED_SECRET_KEYS[$i]}" == "${value}" ]] && return 0
    done
    EFFECTIVE_ACCEPTED_SECRET_KEYS+=("${value}")
}

append_unique_required_secret() {
    local value="$1" i
    [[ -n "${value}" ]] || return 0
    for i in "${!EFFECTIVE_REQUIRED_SECRET_KEYS[@]}"; do
        [[ "${EFFECTIVE_REQUIRED_SECRET_KEYS[$i]}" == "${value}" ]] && return 0
    done
    EFFECTIVE_REQUIRED_SECRET_KEYS+=("${value}")
}

append_default_pair() {
    local key="$1" value="$2" i
    [[ -n "${key}" ]] || return 0
    for i in "${!EFFECTIVE_DEFAULT_KEYS[@]}"; do
        if [[ "${EFFECTIVE_DEFAULT_KEYS[$i]}" == "${key}" ]]; then
            EFFECTIVE_DEFAULT_VALUES[i]="${value}"
            return 0
        fi
    done
    EFFECTIVE_DEFAULT_KEYS+=("${key}")
    EFFECTIVE_DEFAULT_VALUES+=("${value}")
}

json_path() {
    python3 - "$1" "$2" <<'PY'
import json
import sys

path = [part for part in sys.argv[2].split(".") if part]
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)

current = data
for part in path:
    if isinstance(current, dict):
        current = current.get(part, "")
    elif isinstance(current, list) and part.isdigit():
        idx = int(part)
        current = current[idx] if 0 <= idx < len(current) else ""
    else:
        current = ""
        break

if isinstance(current, bool):
    print("true" if current else "false", end="")
elif current in (None, ""):
    print("", end="")
elif isinstance(current, (dict, list)):
    print(json.dumps(current, sort_keys=True), end="")
else:
    print(str(current), end="")
PY
}

json_lines() {
    python3 - "$1" "$2" <<'PY'
import json
import sys

path = [part for part in sys.argv[2].split(".") if part]
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)

current = data
for part in path:
    if isinstance(current, dict):
        current = current.get(part, [])
    elif isinstance(current, list) and part.isdigit():
        idx = int(part)
        current = current[idx] if 0 <= idx < len(current) else []
    else:
        current = []
        break

if isinstance(current, list):
    for item in current:
        print(item)
PY
}

json_object_pairs() {
    python3 - "$1" "$2" <<'PY'
import json
import sys

path = [part for part in sys.argv[2].split(".") if part]
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)

current = data
for part in path:
    if isinstance(current, dict):
        current = current.get(part, {})
    else:
        current = {}
        break

if isinstance(current, dict):
    for key in sorted(current):
        value = current[key]
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif value is None:
            rendered = ""
        else:
            rendered = str(value)
        print(f"{key}\t{rendered}")
PY
}

json_object_keys() {
    python3 - "$1" "$2" <<'PY'
import json
import sys

path = [part for part in sys.argv[2].split(".") if part]
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)

current = data
for part in path:
    if isinstance(current, dict):
        current = current.get(part, {})
    else:
        current = {}
        break

if isinstance(current, dict):
    for key in sorted(current):
        print(key)
PY
}

json_rule_rows() {
    python3 - "$1" "$2" <<'PY'
import json
import sys

path = [part for part in sys.argv[2].split(".") if part]
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)

current = data
for part in path:
    if isinstance(current, dict):
        current = current.get(part, [])
    elif isinstance(current, list) and part.isdigit():
        idx = int(part)
        current = current[idx] if 0 <= idx < len(current) else []
    else:
        current = []
        break

if isinstance(current, list):
    for item in current:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field", "") or "")
        value = str(item.get("value", "") or "")
        for secret_key in item.get("secret_keys", []) or []:
            print(f"{field}\t{value}\t{secret_key}")
PY
}

product_field() {
    json_path "${PRODUCT_FILE}" "${1:-}"
}

product_list() {
    json_lines "${PRODUCT_FILE}" "${1:-}"
}

product_object_pairs() {
    json_object_pairs "${PRODUCT_FILE}" "${1:-}"
}

product_object_keys() {
    json_object_keys "${PRODUCT_FILE}" "${1:-}"
}

product_rule_rows() {
    json_rule_rows "${PRODUCT_FILE}" "${1:-}"
}

registry_app_info() {
    python3 - "${REGISTRY_PATH}" "${1:-}" <<'PY'
import json
import sys

target = sys.argv[2]
with open(sys.argv[1], encoding="utf-8") as handle:
    registry = json.load(handle)

for app in registry.get("apps", []):
    if app.get("app_name") == target:
        print(
            "\t".join(
                [
                    str(app.get("splunkbase_id", "")),
                    str(app.get("label", "")),
                    str(app.get("skill", "")),
                ]
            ),
            end="",
        )
        raise SystemExit(0)
PY
}

ensure_wrapper_session() {
    if ${WRAPPER_SESSION_READY}; then
        return 0
    fi
    load_splunk_credentials || { log "ERROR: Splunk credentials are required."; exit 1; }
    SK=$(get_session_key "${SPLUNK_URI}") || { log "ERROR: Could not authenticate to Splunk."; exit 1; }
    WRAPPER_SESSION_READY=true
}

ensure_platform_index_exists() {
    local index_name="$1"
    [[ -n "${index_name}" ]] || return 0
    ensure_wrapper_session
    if platform_create_index "${SK}" "${SPLUNK_URI}" "${index_name}" "512000"; then
        log "Ensured index '${index_name}' exists."
    else
        log "ERROR: Failed to ensure index '${index_name}' exists."
        exit 1
    fi
}

update_meraki_macro() {
    local index_name="$1" definition encoded body
    [[ -n "${index_name}" ]] || return 0
    ensure_wrapper_session
    definition="index IN(${index_name})"
    encoded=$(python3 - "${definition}" <<'PY'
import sys
import urllib.parse

print(urllib.parse.quote(sys.argv[1], safe=""), end="")
PY
)
    body="definition=${encoded}&iseval=0"
    if rest_set_conf "${SK}" "${SPLUNK_URI}" "Splunk_TA_cisco_meraki" "macros" "meraki_index" "${body}"; then
        log "Updated meraki_index macro to '${definition}'."
    else
        log "ERROR: Failed to update meraki_index macro."
        exit 1
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --product) [[ $# -ge 2 ]] || usage 1; PRODUCT_QUERY="$2"; shift 2 ;;
            --set)
                [[ $# -ge 3 ]] || usage 1
                append_user_value "$2" "$3"
                shift 3
                ;;
            --secret-file)
                [[ $# -ge 3 ]] || usage 1
                append_secret_file "$2" "$3"
                shift 3
                ;;
            --dry-run) DRY_RUN=true; shift ;;
            --json) JSON_OUTPUT=true; shift ;;
            --install-only) INSTALL_ONLY=true; MODE_FLAGS=$((MODE_FLAGS + 1)); shift ;;
            --configure-only) CONFIGURE_ONLY=true; MODE_FLAGS=$((MODE_FLAGS + 1)); shift ;;
            --validate-only) VALIDATE_ONLY=true; MODE_FLAGS=$((MODE_FLAGS + 1)); shift ;;
            --list-products) LIST_PRODUCTS=true; shift ;;
            --catalog) [[ $# -ge 2 ]] || usage 1; CATALOG_PATH="$2"; shift 2 ;;
            --help) usage ;;
            *) echo "Unknown option: $1" >&2; usage 1 ;;
        esac
    done
}

resolve_product() {
    local resolution_file status
    resolution_file="$(new_tmp_file)"
    set +e
    bash "${RESOLVE_SCRIPT}" --catalog "${CATALOG_PATH}" --json "${PRODUCT_QUERY}" >"${resolution_file}"
    status=$?
    set -e
    if (( status != 0 )); then
        bash "${RESOLVE_SCRIPT}" --catalog "${CATALOG_PATH}" "${PRODUCT_QUERY}" || true
        exit "${status}"
    fi

    PRODUCT_FILE="$(new_tmp_file)"
    python3 - "${resolution_file}" "${PRODUCT_FILE}" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
matches = payload.get("matches", [])
if not matches:
    raise SystemExit("Resolved payload did not include a product match.")
Path(sys.argv[2]).write_text(json.dumps(matches[0], indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

emit_role_warnings() {
    local app_name skill_name
    warn_if_current_skill_role_unsupported
    skill_name="$(product_field primary_skill)"
    [[ -n "${skill_name}" ]] && warn_if_role_unsupported_for_skill "${skill_name}"
    [[ -n "${skill_name}" ]] && warn_if_cloud_pairing_missing_for_skill "${skill_name}"
    while IFS= read -r skill_name || [[ -n "${skill_name}" ]]; do
        [[ -n "${skill_name}" ]] || continue
        warn_if_role_unsupported_for_skill "${skill_name}"
        warn_if_cloud_pairing_missing_for_skill "${skill_name}"
    done < <(product_list companion_skills)

    while IFS= read -r app_name || [[ -n "${app_name}" ]]; do
        [[ -n "${app_name}" ]] || continue
        warn_if_role_unsupported_for_app_name "${app_name}"
    done < <(product_list install_apps)
    return 0
}

validate_known_keys() {
    local key allowed found
    if [[ -n "${USER_KEYS[0]+set}" ]]; then
        for key in "${USER_KEYS[@]}"; do
            found=false
            while IFS= read -r allowed || [[ -n "${allowed}" ]]; do
                if [[ "${allowed}" == "${key}" ]]; then
                    found=true
                    break
                fi
            done < <(product_list accepted_non_secret_keys)
            if ! ${found}; then
                echo "ERROR: Unsupported non-secret key '${key}' for $(product_field display_name)." >&2
                echo "Template paths:" >&2
                while IFS= read -r allowed || [[ -n "${allowed}" ]]; do
                    [[ -n "${allowed}" ]] && echo "  - ${allowed}" >&2
                done < <(product_list template_paths)
                exit 1
            fi
        done
    fi

    if [[ -n "${SECRET_KEYS[0]+set}" ]]; then
        for key in "${SECRET_KEYS[@]}"; do
            found=false
            while IFS= read -r allowed || [[ -n "${allowed}" ]]; do
                if [[ "${allowed}" == "${key}" ]]; then
                    found=true
                    break
                fi
            done < <(product_list secret_keys)
            if ! ${found}; then
                echo "ERROR: Unsupported secret key '${key}' for $(product_field display_name)." >&2
                echo "Template paths:" >&2
                while IFS= read -r allowed || [[ -n "${allowed}" ]]; do
                    [[ -n "${allowed}" ]] && echo "  - ${allowed}" >&2
                done < <(product_list template_paths)
                exit 1
            fi
        done
    fi
    return 0
}

reset_effective_route() {
    ROUTE_TYPE="$(product_field route_type)"
    AUTOMATION_STATE="$(product_field automation_state)"
    PRIMARY_SKILL="$(product_field primary_skill)"
    EFFECTIVE_PRODUCT_KEY=""
    EFFECTIVE_DEFAULT_NAME=""
    EFFECTIVE_DEFAULT_INDEX=""
    EFFECTIVE_INPUT_TYPE=""
    EFFECTIVE_ACCOUNT_TYPE=""
    EFFECTIVE_VARIANT_KEY=""
    EFFECTIVE_VARIANT_VALUE=""
    EFFECTIVE_DISCOVERED_ORG_ID=""
    EFFECTIVE_REQUIRED_NON_SECRET_KEYS=()
    EFFECTIVE_OPTIONAL_NON_SECRET_KEYS=()
    EFFECTIVE_ACCEPTED_SECRET_KEYS=()
    EFFECTIVE_REQUIRED_SECRET_KEYS=()
    EFFECTIVE_DEFAULT_KEYS=()
    EFFECTIVE_DEFAULT_VALUES=()
}

load_effective_lists_from_product() {
    local item
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_required_non_secret "${item}"
    done < <(product_list required_non_secret_keys)
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_optional_non_secret "${item}"
    done < <(product_list optional_non_secret_keys)
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_accepted_secret "${item}"
    done < <(product_list secret_keys)
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_required_secret "${item}"
    done < <(product_list required_secret_keys)
    return 0
}

load_variant_lists() {
    local base_path="$1" item
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_required_non_secret "${item}"
    done < <(product_list "${base_path}.required_non_secret_keys")
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_optional_non_secret "${item}"
    done < <(product_list "${base_path}.optional_non_secret_keys")
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_accepted_secret "${item}"
    done < <(product_list "${base_path}.secret_keys")
    while IFS= read -r item || [[ -n "${item}" ]]; do
        append_unique_required_secret "${item}"
    done < <(product_list "${base_path}.required_secret_keys")
    return 0
}

load_default_pairs() {
    local path="$1" key value
    while IFS=$'\t' read -r key value || [[ -n "${key}" ]]; do
        append_default_pair "${key}" "${value}"
    done < <(product_object_pairs "${path}")
    return 0
}

load_conditional_required_secrets() {
    local path="$1" field expected_value secret_key actual_value
    while IFS=$'\t' read -r field expected_value secret_key || [[ -n "${field}${expected_value}${secret_key}" ]]; do
        [[ -n "${field}" && -n "${expected_value}" && -n "${secret_key}" ]] || continue
        actual_value="$(lookup_user_value "${field}" || true)"
        [[ -n "${actual_value}" ]] || continue
        if [[ "$(normalize_key "${actual_value}")" == "$(normalize_key "${expected_value}")" ]]; then
            append_unique_required_secret "${secret_key}"
        fi
    done < <(product_rule_rows "${path}")
    return 0
}

prepare_effective_route() {
    local variant_path variant_key variant_value

    reset_effective_route
    load_effective_lists_from_product

    case "${ROUTE_TYPE}" in
        security_cloud_product)
            EFFECTIVE_PRODUCT_KEY="$(product_field route.product_key)"
            EFFECTIVE_DEFAULT_NAME="$(product_field route.default_name)"
            load_default_pairs "route.defaults"
            load_conditional_required_secrets "conditional_required_secret_rules"
            ;;
        security_cloud_variant)
            EFFECTIVE_VARIANT_KEY="$(product_field route.variant_key)"
            variant_key="${EFFECTIVE_VARIANT_KEY}"
            variant_value="$(lookup_user_value "${variant_key}" || true)"
            if [[ -z "${variant_value}" ]]; then
                variant_value="$(product_field route.default_variant)"
            fi
            variant_value="$(normalize_variant "${variant_value}")"
            EFFECTIVE_VARIANT_VALUE="${variant_value}"
            if [[ -n "${variant_value}" ]]; then
                variant_path="route.variants.${variant_value}"
                EFFECTIVE_PRODUCT_KEY="$(product_field "${variant_path}.product_key")"
                if [[ -z "${EFFECTIVE_PRODUCT_KEY}" ]]; then
                    echo "ERROR: Invalid value '${variant_value}' for ${variant_key}." >&2
                    echo "Available values:" >&2
                    while IFS= read -r variant_value || [[ -n "${variant_value}" ]]; do
                        [[ -n "${variant_value}" ]] && echo "  - ${variant_value}" >&2
                    done < <(product_object_keys "route.variants")
                    exit 1
                fi
                EFFECTIVE_DEFAULT_NAME="$(product_field "${variant_path}.default_name")"
                load_variant_lists "${variant_path}"
                load_default_pairs "${variant_path}.defaults"
                load_conditional_required_secrets "${variant_path}.conditional_required_secret_rules"
            fi
            ;;
        secure_access)
            append_unique_required_secret "api_key"
            append_unique_required_secret "api_secret"
            if [[ "$(product_field id)" == "cisco_cloudlock" ]] || has_user_value "cloudlock_name"; then
                append_unique_required_secret "cloudlock_token"
            fi
            ;;
        dc_networking)
            EFFECTIVE_ACCOUNT_TYPE="$(product_field route.account_type)"
            EFFECTIVE_DEFAULT_NAME="$(product_field route.default_name)"
            EFFECTIVE_DEFAULT_INDEX="$(product_field route.default_index)"
            EFFECTIVE_INPUT_TYPE="$(product_field route.input_type)"
            append_unique_required_secret "password"
            ;;
        catalyst_stack)
            EFFECTIVE_ACCOUNT_TYPE="$(product_field route.account_type)"
            EFFECTIVE_DEFAULT_NAME="$(product_field route.default_name)"
            EFFECTIVE_DEFAULT_INDEX="$(product_field route.default_index)"
            EFFECTIVE_INPUT_TYPE="$(product_field route.input_type)"
            if [[ "${EFFECTIVE_ACCOUNT_TYPE}" == "cybervision" ]]; then
                append_unique_required_secret "api_token"
            else
                append_unique_required_secret "password"
            fi
            ;;
        meraki)
            EFFECTIVE_DEFAULT_NAME="$(product_field route.default_name)"
            EFFECTIVE_DEFAULT_INDEX="$(product_field route.default_index)"
            append_unique_required_secret "api_key"
            ;;
        intersight)
            EFFECTIVE_DEFAULT_NAME="$(product_field route.default_name)"
            EFFECTIVE_DEFAULT_INDEX="$(product_field route.default_index)"
            append_unique_required_secret "client_secret"
            ;;
        thousandeyes)
            EFFECTIVE_DEFAULT_INDEX="$(product_field route.default_index)"
            EFFECTIVE_INPUT_TYPE="$(product_field route.default_input_type)"
            ;;
        spaces)
            EFFECTIVE_DEFAULT_NAME="$(product_field route.default_name)"
            EFFECTIVE_DEFAULT_INDEX="$(product_field route.default_index)"
            append_unique_required_secret "activation_token"
            ;;
        appdynamics)
            EFFECTIVE_DEFAULT_NAME="$(product_field route.default_name)"
            EFFECTIVE_DEFAULT_INDEX="$(product_field route.default_index)"
            append_unique_required_secret "client_secret"
            ;;
        *)
            ;;
    esac

    if [[ "${ROUTE_TYPE}" == "secure_access" ]] && has_secret_file "cloudlock_token"; then
        append_unique_required_secret "cloudlock_token"
    fi
    return 0
}

effective_name() {
    local value
    value="$(lookup_user_value "name" || true)"
    if [[ -n "${value}" ]]; then
        printf '%s' "${value}"
    else
        printf '%s' "${EFFECTIVE_DEFAULT_NAME}"
    fi
}

effective_meraki_index() {
    local value
    value="$(lookup_user_value "index" || true)"
    if [[ -n "${value}" ]]; then
        printf '%s' "${value}"
    else
        printf '%s' "${EFFECTIVE_DEFAULT_INDEX:-meraki}"
    fi
}

effective_thousandeyes_index() {
    local value
    value="$(lookup_user_value "index" || true)"
    if [[ -n "${value}" ]]; then
        printf '%s' "${value}"
    else
        printf '%s' "${EFFECTIVE_DEFAULT_INDEX:-thousandeyes_metrics}"
    fi
}

effective_appdynamics_index() {
    local value
    value="$(lookup_user_value "index" || true)"
    if [[ -n "${value}" ]]; then
        printf '%s' "${value}"
    else
        printf '%s' "${EFFECTIVE_DEFAULT_INDEX:-appdynamics}"
    fi
}

effective_spaces_index() {
    local value
    value="$(lookup_user_value "index" || true)"
    if [[ -n "${value}" ]]; then
        printf '%s' "${value}"
    else
        printf '%s' "${EFFECTIVE_DEFAULT_INDEX:-cisco_spaces}"
    fi
}

effective_spaces_auto_inputs() {
    local value
    value="$(lookup_user_value "auto_inputs" || true)"
    if [[ -z "${value}" ]]; then
        value="$(product_field route.default_auto_inputs)"
    fi
    is_truthy "${value}"
}

effective_create_inputs() {
    local value
    value="$(lookup_user_value "create_inputs" || true)"
    if [[ -n "${value}" ]]; then
        printf '%s' "${value}"
    else
        printf '%s' "$(product_field route.default_create_inputs)"
    fi
}

effective_create_defaults() {
    local value
    value="$(lookup_user_value "create_defaults" || true)"
    if [[ -z "${value}" ]]; then
        return 1
    fi
    is_truthy "${value}"
}

effective_auto_inputs() {
    local value
    value="$(lookup_user_value "auto_inputs" || true)"
    if [[ -z "${value}" ]]; then
        return 1
    fi
    is_truthy "${value}"
}

check_missing_configuration_inputs() {
    local key secret_key secret_status missing=()

    prepare_effective_route

    if [[ "${ROUTE_TYPE}" == "security_cloud_variant" && -z "${EFFECTIVE_VARIANT_VALUE}" ]]; then
        :
    fi

    if [[ -n "${EFFECTIVE_REQUIRED_NON_SECRET_KEYS[0]+set}" ]]; then
        for key in "${EFFECTIVE_REQUIRED_NON_SECRET_KEYS[@]}"; do
            if [[ "${ROUTE_TYPE}" == "secure_access" && "${key}" == "org_id" ]]; then
                if has_user_value "org_id"; then
                    continue
                fi
                if is_truthy "$(lookup_user_value "discover_org_id" || true)"; then
                    continue
                fi
            fi
            has_user_value "${key}" || missing+=("${key}")
        done
    fi

    if [[ -n "${EFFECTIVE_REQUIRED_SECRET_KEYS[0]+set}" ]]; then
        for secret_key in "${EFFECTIVE_REQUIRED_SECRET_KEYS[@]}"; do
            secret_status="$(secret_file_status "${secret_key}")"
            case "${secret_status}" in
                ready) ;;
                missing) missing+=("${secret_key} (secret-file)") ;;
                *) missing+=("${secret_key} (secret-file ${secret_status})") ;;
            esac
        done
    fi

    if [[ -n "${missing[0]+set}" ]]; then
        printf '%s\n' "${missing[@]}"
    fi
    return 0
}

print_list_or_none() {
    local title="$1" path="$2" item found=false
    echo "${title}:"
    while IFS= read -r item || [[ -n "${item}" ]]; do
        [[ -n "${item}" ]] || continue
        found=true
        echo "  - ${item}"
    done < <(product_list "${path}")
    ${found} || echo "  - none"
    return 0
}

print_variants() {
    # shellcheck disable=SC2034
    local variant option product_key
    echo "Available ${EFFECTIVE_VARIANT_KEY}:"
    while IFS= read -r option || [[ -n "${option}" ]]; do
        [[ -n "${option}" ]] || continue
        product_key="$(product_field "route.variants.${option}.product_key")"
        echo "  - ${option}${product_key:+ -> ${product_key}}"
    done < <(product_object_keys "route.variants")
    return 0
}

print_effective_defaults() {
    local i
    echo "Default field values:"
    if [[ -z "${EFFECTIVE_DEFAULT_KEYS[0]+set}" ]]; then
        echo "  - none"
        return 0
    fi
    for i in "${!EFFECTIVE_DEFAULT_KEYS[@]}"; do
        echo "  - ${EFFECTIVE_DEFAULT_KEYS[$i]}=${EFFECTIVE_DEFAULT_VALUES[$i]}"
    done
}

print_install_apps() {
    local app_name app_id label skill info
    echo "Install apps:"
    while IFS= read -r app_name || [[ -n "${app_name}" ]]; do
        [[ -n "${app_name}" ]] || continue
        info="$(registry_app_info "${app_name}")"
        # shellcheck disable=SC2034
        IFS=$'\t' read -r app_id label skill <<< "${info}"
        if [[ -n "${app_id}" || -n "${label}" ]]; then
            echo "  - ${app_name}${app_id:+ [${app_id}]}${label:+ ${label}}"
        else
            echo "  - ${app_name}"
        fi
    done < <(product_list install_apps)
    return 0
}

print_command_plan() {
    echo "Planned phases:"
    if ${INSTALL_ONLY}; then
        echo "  - install only"
    elif ${CONFIGURE_ONLY}; then
        echo "  - configure only"
    elif ${VALIDATE_ONLY}; then
        echo "  - validate only"
    else
        echo "  - install"
        echo "  - configure"
        echo "  - validate"
    fi

    case "${ROUTE_TYPE}" in
        security_cloud_product|security_cloud_variant)
            echo "Workflow scripts:"
            echo "  - skills/cisco-security-cloud-setup/scripts/configure_product.sh"
            echo "  - skills/cisco-security-cloud-setup/scripts/validate.sh"
            ;;
        secure_access)
            echo "Workflow scripts:"
            echo "  - skills/cisco-secure-access-setup/scripts/configure_account.sh"
            echo "  - skills/cisco-secure-access-setup/scripts/configure_settings.sh"
            echo "  - skills/cisco-secure-access-setup/scripts/validate.sh"
            ;;
        dc_networking)
            echo "Workflow scripts:"
            echo "  - skills/cisco-dc-networking-setup/scripts/setup.sh"
            echo "  - skills/cisco-dc-networking-setup/scripts/configure_account.sh"
            echo "  - skills/cisco-dc-networking-setup/scripts/validate.sh"
            ;;
        catalyst_stack)
            echo "Workflow scripts:"
            echo "  - skills/cisco-catalyst-ta-setup/scripts/setup.sh"
            echo "  - skills/cisco-catalyst-ta-setup/scripts/configure_account.sh"
            echo "  - skills/cisco-enterprise-networking-setup/scripts/setup.sh"
            echo "  - skills/cisco-catalyst-ta-setup/scripts/validate.sh"
            echo "  - skills/cisco-enterprise-networking-setup/scripts/validate.sh"
            ;;
        meraki)
            echo "Workflow scripts:"
            echo "  - skills/cisco-meraki-ta-setup/scripts/setup.sh"
            echo "  - skills/cisco-meraki-ta-setup/scripts/configure_account.sh"
            echo "  - skills/cisco-meraki-ta-setup/scripts/validate.sh"
            echo "  - skills/cisco-enterprise-networking-setup/scripts/setup.sh"
            echo "  - skills/cisco-enterprise-networking-setup/scripts/validate.sh"
            ;;
        intersight)
            echo "Workflow scripts:"
            echo "  - skills/cisco-intersight-setup/scripts/setup.sh"
            echo "  - skills/cisco-intersight-setup/scripts/configure_account.sh"
            echo "  - skills/cisco-intersight-setup/scripts/validate.sh"
            ;;
        thousandeyes)
            echo "Workflow scripts:"
            echo "  - skills/cisco-thousandeyes-setup/scripts/setup.sh"
            echo "  - skills/cisco-thousandeyes-setup/scripts/configure_account.sh"
            echo "  - skills/cisco-thousandeyes-setup/scripts/validate.sh"
            ;;
        appdynamics)
            echo "Workflow scripts:"
            echo "  - skills/cisco-appdynamics-setup/scripts/setup.sh"
            echo "  - skills/cisco-appdynamics-setup/scripts/configure_account.sh"
            echo "  - skills/cisco-appdynamics-setup/scripts/validate.sh"
            ;;
        spaces)
            echo "Workflow scripts:"
            echo "  - skills/cisco-spaces-setup/scripts/setup.sh"
            echo "  - skills/cisco-spaces-setup/scripts/configure_stream.sh"
            echo "  - skills/cisco-spaces-setup/scripts/validate.sh"
            ;;
    esac
}

emit_summary() {
    local item missing found_missing=false

    prepare_effective_route

    echo "Resolved product: $(product_field display_name)"
    echo "Product ID: $(product_field id)"
    echo "Automation state: $(product_field automation_state)"
    echo "Route type: ${ROUTE_TYPE:-none}"
    [[ -n "${PRIMARY_SKILL}" ]] && echo "Primary skill: ${PRIMARY_SKILL}"
    if [[ -n "${EFFECTIVE_PRODUCT_KEY}" ]]; then
        echo "Routed product key: ${EFFECTIVE_PRODUCT_KEY}"
    fi
    if [[ -n "${EFFECTIVE_VARIANT_KEY}" ]]; then
        if [[ -n "${EFFECTIVE_VARIANT_VALUE}" ]]; then
            echo "${EFFECTIVE_VARIANT_KEY}: ${EFFECTIVE_VARIANT_VALUE}"
        else
            echo "${EFFECTIVE_VARIANT_KEY}: required"
        fi
        print_variants
    fi
    if [[ -n "$(product_field notes)" ]]; then
        echo "Notes: $(product_field notes)"
    fi
    if [[ -n "$(product_field manual_gap_reason)" ]]; then
        echo "Reason: $(product_field manual_gap_reason)"
    fi
    print_list_or_none "Dashboards" "dashboards"
    print_list_or_none "Template paths" "template_paths"
    print_install_apps
    echo "Required non-secret keys:"
    if [[ -z "${EFFECTIVE_REQUIRED_NON_SECRET_KEYS[0]+set}" ]]; then
        echo "  - none"
    else
        for item in "${EFFECTIVE_REQUIRED_NON_SECRET_KEYS[@]}"; do
            echo "  - ${item}"
        done
    fi
    echo "Optional non-secret keys:"
    if [[ -z "${EFFECTIVE_OPTIONAL_NON_SECRET_KEYS[0]+set}" ]]; then
        echo "  - none"
    else
        for item in "${EFFECTIVE_OPTIONAL_NON_SECRET_KEYS[@]}"; do
            echo "  - ${item}"
        done
    fi
    echo "Secret-file keys:"
    if [[ -z "${EFFECTIVE_ACCEPTED_SECRET_KEYS[0]+set}" ]]; then
        echo "  - none"
    else
        for item in "${EFFECTIVE_ACCEPTED_SECRET_KEYS[@]}"; do
            echo "  - ${item}"
        done
    fi
    print_effective_defaults
    print_command_plan

    echo "Missing values for configure:"
    if ${INSTALL_ONLY} || ${VALIDATE_ONLY}; then
        echo "  - not checked for this phase"
    else
        while IFS= read -r missing || [[ -n "${missing}" ]]; do
            [[ -n "${missing}" ]] || continue
            found_missing=true
            echo "  - ${missing}"
        done < <(check_missing_configuration_inputs)
        ${found_missing} || echo "  - none"
    fi
    return 0
}

join_json_items() {
    local IFS=$'\037'
    printf '%s' "$*"
}

emit_summary_json() {
    local missing_values=() missing

    prepare_effective_route

    if ! ${INSTALL_ONLY} && ! ${VALIDATE_ONLY}; then
        while IFS= read -r missing || [[ -n "${missing}" ]]; do
            [[ -n "${missing}" ]] || continue
            missing_values+=("${missing}")
        done < <(check_missing_configuration_inputs)
    fi

    JSON_REQUIRED_NON_SECRET="$(join_json_items "${EFFECTIVE_REQUIRED_NON_SECRET_KEYS[@]}")" \
    JSON_OPTIONAL_NON_SECRET="$(join_json_items "${EFFECTIVE_OPTIONAL_NON_SECRET_KEYS[@]}")" \
    JSON_ACCEPTED_SECRET="$(join_json_items "${EFFECTIVE_ACCEPTED_SECRET_KEYS[@]}")" \
    JSON_REQUIRED_SECRET="$(join_json_items "${EFFECTIVE_REQUIRED_SECRET_KEYS[@]}")" \
    JSON_DEFAULT_KEYS="$(join_json_items "${EFFECTIVE_DEFAULT_KEYS[@]}")" \
    JSON_DEFAULT_VALUES="$(join_json_items "${EFFECTIVE_DEFAULT_VALUES[@]}")" \
    JSON_MISSING_VALUES="$(join_json_items "${missing_values[@]}")" \
    JSON_ROUTE_TYPE="${ROUTE_TYPE}" \
    JSON_PRIMARY_SKILL="${PRIMARY_SKILL}" \
    JSON_EFFECTIVE_PRODUCT_KEY="${EFFECTIVE_PRODUCT_KEY}" \
    JSON_EFFECTIVE_ACCOUNT_TYPE="${EFFECTIVE_ACCOUNT_TYPE}" \
    JSON_EFFECTIVE_DEFAULT_NAME="${EFFECTIVE_DEFAULT_NAME}" \
    JSON_EFFECTIVE_DEFAULT_INDEX="${EFFECTIVE_DEFAULT_INDEX}" \
    JSON_EFFECTIVE_INPUT_TYPE="${EFFECTIVE_INPUT_TYPE}" \
    JSON_EFFECTIVE_VARIANT_KEY="${EFFECTIVE_VARIANT_KEY}" \
    JSON_EFFECTIVE_VARIANT_VALUE="${EFFECTIVE_VARIANT_VALUE}" \
    JSON_INSTALL_ONLY="${INSTALL_ONLY}" \
    JSON_CONFIGURE_ONLY="${CONFIGURE_ONLY}" \
    JSON_VALIDATE_ONLY="${VALIDATE_ONLY}" \
    python3 - "${PRODUCT_FILE}" "${REGISTRY_PATH}" <<'PY'
import json
import os
import sys
from pathlib import Path

SEP = "\x1f"


def split_env(name):
    value = os.environ.get(name, "")
    return [] if value == "" else value.split(SEP)


def env_bool(name):
    return os.environ.get(name, "false").lower() == "true"


product = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
registry = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
registry_by_name = {
    str(app.get("app_name", "")): app
    for app in registry.get("apps", [])
    if app.get("app_name")
}

route_type = os.environ.get("JSON_ROUTE_TYPE", "")
default_keys = split_env("JSON_DEFAULT_KEYS")
default_values = split_env("JSON_DEFAULT_VALUES")
defaults = dict(zip(default_keys, default_values))

if env_bool("JSON_INSTALL_ONLY"):
    phases = ["install"]
elif env_bool("JSON_CONFIGURE_ONLY"):
    phases = ["configure"]
elif env_bool("JSON_VALIDATE_ONLY"):
    phases = ["validate"]
else:
    phases = ["install", "configure", "validate"]

workflow_scripts_by_route = {
    "security_cloud_product": [
        "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
        "skills/cisco-security-cloud-setup/scripts/validate.sh",
    ],
    "security_cloud_variant": [
        "skills/cisco-security-cloud-setup/scripts/configure_product.sh",
        "skills/cisco-security-cloud-setup/scripts/validate.sh",
    ],
    "secure_access": [
        "skills/cisco-secure-access-setup/scripts/configure_account.sh",
        "skills/cisco-secure-access-setup/scripts/configure_settings.sh",
        "skills/cisco-secure-access-setup/scripts/validate.sh",
    ],
    "dc_networking": [
        "skills/cisco-dc-networking-setup/scripts/setup.sh",
        "skills/cisco-dc-networking-setup/scripts/configure_account.sh",
        "skills/cisco-dc-networking-setup/scripts/validate.sh",
    ],
    "catalyst_stack": [
        "skills/cisco-catalyst-ta-setup/scripts/setup.sh",
        "skills/cisco-catalyst-ta-setup/scripts/configure_account.sh",
        "skills/cisco-enterprise-networking-setup/scripts/setup.sh",
        "skills/cisco-catalyst-ta-setup/scripts/validate.sh",
        "skills/cisco-enterprise-networking-setup/scripts/validate.sh",
    ],
    "meraki": [
        "skills/cisco-meraki-ta-setup/scripts/setup.sh",
        "skills/cisco-meraki-ta-setup/scripts/configure_account.sh",
        "skills/cisco-meraki-ta-setup/scripts/validate.sh",
        "skills/cisco-enterprise-networking-setup/scripts/setup.sh",
        "skills/cisco-enterprise-networking-setup/scripts/validate.sh",
    ],
    "intersight": [
        "skills/cisco-intersight-setup/scripts/setup.sh",
        "skills/cisco-intersight-setup/scripts/configure_account.sh",
        "skills/cisco-intersight-setup/scripts/validate.sh",
    ],
    "thousandeyes": [
        "skills/cisco-thousandeyes-setup/scripts/setup.sh",
        "skills/cisco-thousandeyes-setup/scripts/configure_account.sh",
        "skills/cisco-thousandeyes-setup/scripts/validate.sh",
    ],
    "appdynamics": [
        "skills/cisco-appdynamics-setup/scripts/setup.sh",
        "skills/cisco-appdynamics-setup/scripts/configure_account.sh",
        "skills/cisco-appdynamics-setup/scripts/validate.sh",
    ],
    "spaces": [
        "skills/cisco-spaces-setup/scripts/setup.sh",
        "skills/cisco-spaces-setup/scripts/configure_stream.sh",
        "skills/cisco-spaces-setup/scripts/validate.sh",
    ],
}

install_apps = []
for app_name in product.get("install_apps", []) or []:
    metadata = registry_by_name.get(str(app_name), {})
    install_apps.append(
        {
            "app_name": app_name,
            "splunkbase_id": metadata.get("splunkbase_id", ""),
            "label": metadata.get("label", ""),
            "skill": metadata.get("skill", ""),
        }
    )

variant_key = os.environ.get("JSON_EFFECTIVE_VARIANT_KEY", "")
variant_value = os.environ.get("JSON_EFFECTIVE_VARIANT_VALUE", "")
variants = {}
if variant_key:
    for key, value in (product.get("route", {}).get("variants", {}) or {}).items():
        variants[key] = value.get("product_key", "") if isinstance(value, dict) else ""

payload = {
    "resolved_product": {
        "id": product.get("id", ""),
        "display_name": product.get("display_name", ""),
        "automation_state": product.get("automation_state", ""),
        "route_type": route_type,
        "primary_skill": os.environ.get("JSON_PRIMARY_SKILL", ""),
        "notes": product.get("notes", ""),
        "manual_gap_reason": product.get("manual_gap_reason", ""),
    },
    "route": {
        "type": route_type,
        "product_key": os.environ.get("JSON_EFFECTIVE_PRODUCT_KEY", ""),
        "account_type": os.environ.get("JSON_EFFECTIVE_ACCOUNT_TYPE", ""),
        "default_name": os.environ.get("JSON_EFFECTIVE_DEFAULT_NAME", ""),
        "default_index": os.environ.get("JSON_EFFECTIVE_DEFAULT_INDEX", ""),
        "input_type": os.environ.get("JSON_EFFECTIVE_INPUT_TYPE", ""),
        "variant_key": variant_key,
        "variant_value": variant_value,
        "variants": variants,
        "defaults": defaults,
    },
    "dashboards": product.get("dashboards", []) or [],
    "template_paths": product.get("template_paths", []) or [],
    "install_apps": install_apps,
    "required_non_secret_keys": split_env("JSON_REQUIRED_NON_SECRET"),
    "optional_non_secret_keys": split_env("JSON_OPTIONAL_NON_SECRET"),
    "secret_file_keys": split_env("JSON_ACCEPTED_SECRET"),
    "required_secret_file_keys": split_env("JSON_REQUIRED_SECRET"),
    "missing_values_for_configure": split_env("JSON_MISSING_VALUES"),
    "planned_phases": phases,
    "workflow_scripts": workflow_scripts_by_route.get(route_type, []),
}

json.dump(payload, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
PY
}

require_configuration_ready() {
    local missing found=false
    while IFS= read -r missing || [[ -n "${missing}" ]]; do
        [[ -n "${missing}" ]] || continue
        if ! ${found}; then
            echo "ERROR: Missing required values for configure:" >&2
            found=true
        fi
        echo "  - ${missing}" >&2
    done < <(check_missing_configuration_inputs)

    if ${found}; then
        echo "Template paths:" >&2
        while IFS= read -r missing || [[ -n "${missing}" ]]; do
            [[ -n "${missing}" ]] && echo "  - ${missing}" >&2
        done < <(product_list template_paths)
        exit 1
    fi
}

install_app_by_name() {
    local app_name="$1" app_id label skill info
    info="$(registry_app_info "${app_name}")"
    # shellcheck disable=SC2034
    IFS=$'\t' read -r app_id label skill <<< "${info}"
    if [[ -z "${app_id}" ]]; then
        log "ERROR: Could not resolve Splunkbase ID for ${app_name} from the app registry."
        exit 1
    fi
    log "Installing ${label:-${app_name}} (${app_name}, app ID ${app_id})..."
    bash "${INSTALL_APP_SCRIPT}" --source splunkbase --app-id "${app_id}" --no-update
}

run_install_phase() {
    local app_name
    while IFS= read -r app_name || [[ -n "${app_name}" ]]; do
        [[ -n "${app_name}" ]] || continue
        install_app_by_name "${app_name}"
    done < <(product_list install_apps)
}

run_security_cloud_configure() {
    local cmd name i key value
    name="$(effective_name)"
    cmd=(bash "${SCRIPT_DIR}/../../cisco-security-cloud-setup/scripts/configure_product.sh" --product "${EFFECTIVE_PRODUCT_KEY}")
    [[ -n "${name}" ]] && cmd+=(--name "${name}")

    for i in "${!EFFECTIVE_DEFAULT_KEYS[@]}"; do
        key="${EFFECTIVE_DEFAULT_KEYS[$i]}"
        value="${EFFECTIVE_DEFAULT_VALUES[$i]}"
        if has_user_value "${key}" || has_secret_file "${key}"; then
            continue
        fi
        cmd+=(--set "${key}" "${value}")
    done

    for i in "${!USER_KEYS[@]}"; do
        key="${USER_KEYS[$i]}"
        value="${USER_VALUES[$i]}"
        [[ "${key}" == "name" ]] && continue
        [[ -n "${EFFECTIVE_VARIANT_KEY}" && "${key}" == "${EFFECTIVE_VARIANT_KEY}" ]] && continue
        cmd+=(--set "${key}" "${value}")
    done

    for i in "${!SECRET_KEYS[@]}"; do
        cmd+=(--secret-file "${SECRET_KEYS[$i]}" "${SECRET_PATHS[$i]}")
    done

    "${cmd[@]}"
}

run_secure_access_configure() {
    local account_cmd settings_cmd tmp_output status effective_org_id
    account_cmd=(bash "${SCRIPT_DIR}/../../cisco-secure-access-setup/scripts/configure_account.sh")
    settings_cmd=(bash "${SCRIPT_DIR}/../../cisco-secure-access-setup/scripts/configure_settings.sh")

    if has_user_value "org_id"; then
        effective_org_id="$(lookup_user_value "org_id")"
        account_cmd+=(--org-id "${effective_org_id}")
    elif is_truthy "$(lookup_user_value "discover_org_id" || true)"; then
        account_cmd+=(--discover-org-id)
    else
        log "ERROR: secure_access requires --set org_id or --set discover_org_id true."
        exit 1
    fi

    account_cmd+=(--base-url "$(lookup_user_value "base_url")")
    account_cmd+=(--timezone "$(lookup_user_value "timezone")")
    account_cmd+=(--storage-region "$(lookup_user_value "storage_region")")
    account_cmd+=(--api-key-file "$(lookup_secret_file "api_key")")
    account_cmd+=(--api-secret-file "$(lookup_secret_file "api_secret")")

    has_user_value "investigate_index" && account_cmd+=(--investigate-index "$(lookup_user_value "investigate_index")")
    has_user_value "privateapp_index" && account_cmd+=(--privateapp-index "$(lookup_user_value "privateapp_index")")
    has_user_value "appdiscovery_index" && account_cmd+=(--appdiscovery-index "$(lookup_user_value "appdiscovery_index")")

    if [[ -z "${effective_org_id}" ]]; then
        tmp_output="$(new_tmp_file)"
        set +e
        "${account_cmd[@]}" >"${tmp_output}" 2>&1
        status=$?
        set -e
        cat "${tmp_output}"
        if (( status != 0 )); then
            exit "${status}"
        fi
        effective_org_id="$(sed -n 's/^.*Discovered org ID: //p' "${tmp_output}" | tail -1)"
        if [[ -z "${effective_org_id}" ]]; then
            log "ERROR: Could not determine the discovered org ID from configure_account.sh output."
            exit 1
        fi
        EFFECTIVE_DISCOVERED_ORG_ID="${effective_org_id}"
    else
        "${account_cmd[@]}"
    fi

    settings_cmd+=(--org-id "${effective_org_id}" --bootstrap-roles --accept-terms --apply-dashboard-defaults)
    has_user_value "search_interval" && settings_cmd+=(--search-interval "$(lookup_user_value "search_interval")")
    has_user_value "refresh_rate" && settings_cmd+=(--refresh-rate "$(lookup_user_value "refresh_rate")")

    if has_user_value "cloudlock_name"; then
        settings_cmd+=(--cloudlock-name "$(lookup_user_value "cloudlock_name")")
        settings_cmd+=(--cloudlock-url "$(lookup_user_value "cloudlock_url")")
        settings_cmd+=(--cloudlock-start-date "$(lookup_user_value "cloudlock_start_date")")
        settings_cmd+=(--cloudlock-token-file "$(lookup_secret_file "cloudlock_token")")
        if has_user_value "cloudlock_show_incident_details"; then
            settings_cmd+=(--cloudlock-incident-details "$(lookup_user_value "cloudlock_show_incident_details")")
        fi
        if has_user_value "cloudlock_show_ueba"; then
            settings_cmd+=(--cloudlock-ueba "$(lookup_user_value "cloudlock_show_ueba")")
        fi
    fi

    has_user_value "dns_index" && settings_cmd+=(--dns-index "$(lookup_user_value "dns_index")")
    has_user_value "proxy_index" && settings_cmd+=(--proxy-index "$(lookup_user_value "proxy_index")")
    has_user_value "firewall_index" && settings_cmd+=(--firewall-index "$(lookup_user_value "firewall_index")")
    has_user_value "dlp_index" && settings_cmd+=(--dlp-index "$(lookup_user_value "dlp_index")")
    has_user_value "ravpn_index" && settings_cmd+=(--ravpn-index "$(lookup_user_value "ravpn_index")")

    "${settings_cmd[@]}"
}

run_dc_networking_configure() {
    local name cmd
    name="$(effective_name)"
    bash "${SCRIPT_DIR}/../../cisco-dc-networking-setup/scripts/setup.sh"

    cmd=(bash "${SCRIPT_DIR}/../../cisco-dc-networking-setup/scripts/configure_account.sh"
        --type "${EFFECTIVE_ACCOUNT_TYPE}"
        --name "${name}"
        --username "$(lookup_user_value "username")"
        --password-file "$(lookup_secret_file "password")")

    if [[ "${EFFECTIVE_ACCOUNT_TYPE}" == "nexus9k" ]]; then
        cmd+=(--device-ip "$(lookup_user_value "device_ip")")
    else
        cmd+=(--hostname "$(lookup_user_value "hostname")")
    fi
    has_user_value "port" && cmd+=(--port "$(lookup_user_value "port")")
    has_user_value "auth_type" && cmd+=(--auth-type "$(lookup_user_value "auth_type")")
    has_user_value "login_domain" && cmd+=(--login-domain "$(lookup_user_value "login_domain")")
    is_truthy "$(lookup_user_value "proxy_enabled" || true)" && cmd+=(--proxy-enabled)
    if has_user_value "verify_ssl"; then
        if is_truthy "$(lookup_user_value "verify_ssl")"; then
            cmd+=(--verify-ssl)
        else
            cmd+=(--no-verify-ssl)
        fi
    fi
    "${cmd[@]}"

    bash "${SCRIPT_DIR}/../../cisco-dc-networking-setup/scripts/setup.sh" \
        --enable-inputs \
        --account "${name}" \
        --index "${EFFECTIVE_DEFAULT_INDEX}" \
        --input-type "${EFFECTIVE_INPUT_TYPE}"
}

run_catalyst_stack_configure() {
    local name cmd
    name="$(effective_name)"
    bash "${SCRIPT_DIR}/../../cisco-catalyst-ta-setup/scripts/setup.sh"

    cmd=(bash "${SCRIPT_DIR}/../../cisco-catalyst-ta-setup/scripts/configure_account.sh"
        --type "${EFFECTIVE_ACCOUNT_TYPE}"
        --name "${name}"
        --host "$(lookup_user_value "host")")

    if [[ "${EFFECTIVE_ACCOUNT_TYPE}" == "cybervision" ]]; then
        cmd+=(--api-token-file "$(lookup_secret_file "api_token")")
    else
        cmd+=(--username "$(lookup_user_value "username")")
        cmd+=(--password-file "$(lookup_secret_file "password")")
    fi
    is_truthy "$(lookup_user_value "use_ca_cert" || true)" && cmd+=(--use-ca-cert)
    if has_user_value "verify_ssl"; then
        if is_truthy "$(lookup_user_value "verify_ssl")"; then
            cmd+=(--verify-ssl)
        else
            cmd+=(--no-verify-ssl)
        fi
    fi
    "${cmd[@]}"

    bash "${SCRIPT_DIR}/../../cisco-catalyst-ta-setup/scripts/setup.sh" \
        --enable-inputs \
        --account "${name}" \
        --index "${EFFECTIVE_DEFAULT_INDEX}" \
        --input-type "${EFFECTIVE_INPUT_TYPE}"

    bash "${SCRIPT_DIR}/../../cisco-enterprise-networking-setup/scripts/setup.sh"
}

run_meraki_configure() {
    local name index cmd
    name="$(effective_name)"
    index="$(effective_meraki_index)"
    bash "${SCRIPT_DIR}/../../cisco-meraki-ta-setup/scripts/setup.sh"

    cmd=(bash "${SCRIPT_DIR}/../../cisco-meraki-ta-setup/scripts/configure_account.sh"
        --name "${name}"
        --org-id "$(lookup_user_value "org_id")"
        --api-key-file "$(lookup_secret_file "api_key")"
        --index "${index}")
    has_user_value "region" && cmd+=(--region "$(lookup_user_value "region")")
    has_user_value "max_api_rate" && cmd+=(--max-api-rate "$(lookup_user_value "max_api_rate")")
    if effective_auto_inputs; then
        cmd+=(--auto-inputs)
    fi
    "${cmd[@]}"

    if [[ "${index}" != "meraki" ]]; then
        ensure_platform_index_exists "${index}"
        update_meraki_macro "${index}"
    fi

    if [[ "$(product_field route.install_companion_app)" == "true" ]]; then
        bash "${SCRIPT_DIR}/../../cisco-enterprise-networking-setup/scripts/setup.sh"
    fi
}

run_intersight_configure() {
    local name cmd
    name="$(effective_name)"
    bash "${SCRIPT_DIR}/../../cisco-intersight-setup/scripts/setup.sh"
    cmd=(bash "${SCRIPT_DIR}/../../cisco-intersight-setup/scripts/configure_account.sh"
        --name "${name}"
        --client-id "$(lookup_user_value "client_id")"
        --client-secret-file "$(lookup_secret_file "client_secret")")
    has_user_value "hostname" && cmd+=(--hostname "$(lookup_user_value "hostname")")
    if effective_create_defaults; then
        cmd+=(--create-defaults)
    fi
    if has_user_value "verify_ssl"; then
        if is_truthy "$(lookup_user_value "verify_ssl")"; then
            cmd+=(--verify-ssl)
        else
            cmd+=(--no-verify-ssl)
        fi
    fi
    "${cmd[@]}"
}

run_thousandeyes_configure() {
    local index input_type hec_token cmd account_output_file actual_account requested_account resolved_account
    index="$(effective_thousandeyes_index)"
    input_type="$(lookup_user_value "input_type" || true)"
    [[ -n "${input_type}" ]] || input_type="${EFFECTIVE_INPUT_TYPE:-all}"
    hec_token="$(lookup_user_value "hec_token" || true)"
    [[ -n "${hec_token}" ]] || hec_token="$(product_field route.default_hec_token)"
    account_output_file="$(new_tmp_file)"

    bash "${SCRIPT_DIR}/../../cisco-thousandeyes-setup/scripts/setup.sh"
    if [[ "${index}" != "thousandeyes_metrics" ]]; then
        ensure_platform_index_exists "${index}"
    fi

    cmd=(bash "${SCRIPT_DIR}/../../cisco-thousandeyes-setup/scripts/configure_account.sh"
        --account-output-file "${account_output_file}")
    has_user_value "poll_interval" && cmd+=(--poll-interval "$(lookup_user_value "poll_interval")")
    has_user_value "poll_timeout" && cmd+=(--poll-timeout "$(lookup_user_value "poll_timeout")")
    "${cmd[@]}"

    requested_account="$(lookup_user_value "account" || true)"
    actual_account="$(tr -d '\r' < "${account_output_file}")"
    if [[ -n "${actual_account}" ]]; then
        resolved_account="${actual_account}"
        if [[ -n "${requested_account}" && "${requested_account}" != "${actual_account}" ]]; then
            echo "WARNING: Requested ThousandEyes account '${requested_account}' does not match authenticated account '${actual_account}'. Using '${actual_account}'." >&2
        fi
    else
        resolved_account="${requested_account}"
    fi
    if [[ -z "${resolved_account}" ]]; then
        echo "ERROR: ThousandEyes account name could not be resolved from the OAuth flow." >&2
        exit 1
    fi

    cmd=(bash "${SCRIPT_DIR}/../../cisco-thousandeyes-setup/scripts/setup.sh"
        --enable-inputs
        --account "${resolved_account}"
        --account-group "$(lookup_user_value "account_group")"
        --index "${index}"
        --input-type "${input_type}"
        --hec-token "${hec_token}")
    has_user_value "pathvis_index" && cmd+=(--pathvis-index "$(lookup_user_value "pathvis_index")")
    has_user_value "pathvis_interval" && cmd+=(--pathvis-interval "$(lookup_user_value "pathvis_interval")")
    if has_user_value "pathvis_enabled" && ! is_truthy "$(lookup_user_value "pathvis_enabled")"; then
        cmd+=(--no-pathvis)
    fi
    "${cmd[@]}"
}

run_appdynamics_configure() {
    local name index create_inputs cmd
    name="$(effective_name)"
    index="$(effective_appdynamics_index)"
    create_inputs="$(effective_create_inputs)"
    bash "${SCRIPT_DIR}/../../cisco-appdynamics-setup/scripts/setup.sh" --index "${index}"
    cmd=(bash "${SCRIPT_DIR}/../../cisco-appdynamics-setup/scripts/configure_account.sh"
        --name "${name}"
        --controller-url "$(lookup_user_value "controller_url")"
        --client-name "$(lookup_user_value "client_name")"
        --client-secret-file "$(lookup_secret_file "client_secret")"
        --index "${index}")
    [[ -n "${create_inputs}" ]] && cmd+=(--create-inputs "${create_inputs}")
    if has_user_value "verify_ssl"; then
        if is_truthy "$(lookup_user_value "verify_ssl")"; then
            cmd+=(--verify-ssl)
        else
            cmd+=(--no-verify-ssl)
        fi
    fi
    "${cmd[@]}"
}

run_spaces_configure() {
    local name index cmd
    name="$(effective_name)"
    index="$(effective_spaces_index)"

    bash "${SCRIPT_DIR}/../../cisco-spaces-setup/scripts/setup.sh" --index "${index}"

    cmd=(bash "${SCRIPT_DIR}/../../cisco-spaces-setup/scripts/configure_stream.sh"
        --name "${name}"
        --token-file "$(lookup_secret_file "activation_token")"
        --region "$(lookup_user_value "region")"
        --index "${index}")

    if has_user_value "location_updates_status" && is_truthy "$(lookup_user_value "location_updates_status")"; then
        cmd+=(--location-updates)
    fi
    if effective_spaces_auto_inputs; then
        cmd+=(--auto-inputs)
    fi

    "${cmd[@]}"
}

run_configure_phase() {
    case "${ROUTE_TYPE}" in
        security_cloud_product|security_cloud_variant) run_security_cloud_configure ;;
        secure_access) run_secure_access_configure ;;
        dc_networking) run_dc_networking_configure ;;
        catalyst_stack) run_catalyst_stack_configure ;;
        meraki) run_meraki_configure ;;
        intersight) run_intersight_configure ;;
        thousandeyes) run_thousandeyes_configure ;;
        appdynamics) run_appdynamics_configure ;;
        spaces) run_spaces_configure ;;
        *)
            log "ERROR: Unsupported route type '${ROUTE_TYPE}'."
            exit 1
            ;;
    esac
}

run_validation_phase() {
    local org_id
    case "${ROUTE_TYPE}" in
        security_cloud_product|security_cloud_variant)
            if [[ -z "${EFFECTIVE_PRODUCT_KEY}" ]]; then
                log "ERROR: ${ROUTE_TYPE} validation requires --set ${EFFECTIVE_VARIANT_KEY} <value>."
                exit 1
            fi
            bash "${SCRIPT_DIR}/../../cisco-security-cloud-setup/scripts/validate.sh" --product "${EFFECTIVE_PRODUCT_KEY}"
            ;;
        secure_access)
            org_id="$(lookup_user_value "org_id" || true)"
            [[ -z "${org_id}" ]] && org_id="${EFFECTIVE_DISCOVERED_ORG_ID}"
            if [[ -n "${org_id}" ]]; then
                bash "${SCRIPT_DIR}/../../cisco-secure-access-setup/scripts/validate.sh" --org-id "${org_id}"
            else
                bash "${SCRIPT_DIR}/../../cisco-secure-access-setup/scripts/validate.sh"
            fi
            ;;
        dc_networking)
            bash "${SCRIPT_DIR}/../../cisco-dc-networking-setup/scripts/validate.sh"
            ;;
        catalyst_stack)
            bash "${SCRIPT_DIR}/../../cisco-catalyst-ta-setup/scripts/validate.sh"
            bash "${SCRIPT_DIR}/../../cisco-enterprise-networking-setup/scripts/validate.sh"
            ;;
        meraki)
            bash "${SCRIPT_DIR}/../../cisco-meraki-ta-setup/scripts/validate.sh"
            if [[ "$(product_field route.install_companion_app)" == "true" ]]; then
                bash "${SCRIPT_DIR}/../../cisco-enterprise-networking-setup/scripts/validate.sh"
            fi
            ;;
        intersight)
            bash "${SCRIPT_DIR}/../../cisco-intersight-setup/scripts/validate.sh"
            ;;
        thousandeyes)
            bash "${SCRIPT_DIR}/../../cisco-thousandeyes-setup/scripts/validate.sh"
            ;;
        appdynamics)
            bash "${SCRIPT_DIR}/../../cisco-appdynamics-setup/scripts/validate.sh"
            ;;
        spaces)
            bash "${SCRIPT_DIR}/../../cisco-spaces-setup/scripts/validate.sh"
            ;;
        *)
            log "ERROR: Unsupported route type '${ROUTE_TYPE}' for validation." >&2
            exit 1
            ;;
    esac
}

main() {
    parse_args "$@"

    if ${LIST_PRODUCTS}; then
        if ${JSON_OUTPUT}; then
            exec bash "${RESOLVE_SCRIPT}" --catalog "${CATALOG_PATH}" --list-products --json
        fi
        exec bash "${RESOLVE_SCRIPT}" --catalog "${CATALOG_PATH}" --list-products
    fi

    [[ -n "${PRODUCT_QUERY}" ]] || usage
    (( MODE_FLAGS <= 1 )) || { echo "ERROR: Choose only one of --install-only, --configure-only, or --validate-only." >&2; exit 1; }
    if ${JSON_OUTPUT} && ! ${DRY_RUN}; then
        echo "ERROR: --json is only supported with --dry-run or --list-products." >&2
        exit 1
    fi

    resolve_product
    validate_known_keys
    prepare_effective_route
    emit_role_warnings
    if [[ "${AUTOMATION_STATE}" != "automated" ]]; then
        if ${JSON_OUTPUT}; then
            emit_summary_json
        else
            emit_summary
        fi
        exit 1
    fi
    if ${JSON_OUTPUT}; then
        emit_summary_json
    else
        emit_summary
    fi

    if ${DRY_RUN}; then
        exit 0
    fi

    if ! ${INSTALL_ONLY} && ! ${VALIDATE_ONLY}; then
        require_configuration_ready
    fi

    if ${INSTALL_ONLY}; then
        run_install_phase
        exit 0
    fi

    if ${CONFIGURE_ONLY}; then
        run_configure_phase
        exit 0
    fi

    if ${VALIDATE_ONLY}; then
        run_validation_phase
        exit 0
    fi

    run_install_phase
    run_configure_phase
    run_validation_phase
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
