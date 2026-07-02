#!/usr/bin/env bash
# Shared Splunk Platform version defaults for shell skills.
# The library normally resolves the skills root from its own location. Set
# SPV_SKILLS_ROOT only when the helper has been copied away from the repo.

spv_skills_root() {
    local helper_root
    if [[ -n "${SPV_SKILLS_ROOT:-}" ]]; then
        printf '%s' "${SPV_SKILLS_ROOT}"
        return 0
    fi
    helper_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    if [[ -f "${helper_root}/shared/references/splunk_platform_versions.json" ]]; then
        printf '%s' "${helper_root}"
        return 0
    fi
    if [[ -n "${SCRIPT_DIR:-}" ]]; then
        printf '%s' "$(cd "${SCRIPT_DIR}/../.." && pwd)"
        return 0
    fi
    echo "ERROR: Could not locate the skills root; set SPV_SKILLS_ROOT." >&2
    return 1
}

spv_json_path() {
    local root
    root="$(spv_skills_root)" || return 1
    printf '%s/references/splunk_platform_versions.json' "${root}/shared"
}

spv_default() {
    local key="${1:-}"
    local json_path
    json_path="$(spv_json_path)" || return 1
    python3 - "${json_path}" "${key}" <<'PY'
import json
import sys

path, key = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
value = (payload.get("defaults") or {}).get(key)
if not isinstance(value, str) or not value.strip():
    raise SystemExit(f"defaults.{key} missing in {path}")
print(value, end="")
PY
}

spv_enterprise_default() {
    spv_default enterprise_version
}

spv_cloud_doc_train_default() {
    spv_default cloud_doc_train
}

spv_cloud_doc_train_previous() {
    spv_default cloud_doc_train_previous
}

spv_classify_enterprise_version() {
    local version="${1:-}"
    local json_path
    json_path="$(spv_json_path)" || return 1
    python3 - "${json_path}" "${version}" <<'PY'
import json
import re
import sys

path, version = sys.argv[1], sys.argv[2]
match = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.\d+)?\s*", version or "")
if not match:
    print("invalid")
    raise SystemExit(0)
train = f"{int(match.group(1))}.{int(match.group(2))}"
with open(path, encoding="utf-8") as handle:
    payload = json.load(handle)
supported = {str(item) for item in payload.get("enterprise_platform_versions", [])}
cloud_only = {str(item) for item in payload.get("enterprise_cloud_only_trains", [])}
not_public = {
    str(item)
    for item in payload.get("enterprise_not_publicly_released_trains", [])
}
if train in supported:
    print("supported")
elif train in cloud_only:
    print("cloud-only")
elif train in not_public:
    print("not-publicly-released")
else:
    print("unsupported")
PY
}

spv_require_supported_enterprise_version() {
    local version="${1:-}"
    local classification
    classification="$(spv_classify_enterprise_version "${version}")" || return 1
    if [[ "${classification}" != "supported" ]]; then
        echo "ERROR: Splunk Enterprise ${version:-<empty>} is ${classification}; it is not a supported public self-managed runtime train." >&2
        return 1
    fi
}

spv_server_info_version() {
    local json_file="${1:-}"
    if [[ -z "${json_file}" || ! -s "${json_file}" ]]; then
        echo "ERROR: server-info JSON file is empty or missing: ${json_file:-<empty>}" >&2
        return 1
    fi
    python3 - "${json_file}" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        payload = json.load(handle)
    entry = (payload.get("entry") or [])[0]
    content = entry.get("content", {}) if isinstance(entry, dict) else {}
    version = str(content.get("version") or "").strip()
except (OSError, ValueError, TypeError, IndexError, AttributeError):
    version = ""
if not version:
    raise SystemExit(1)
print(version)
PY
}

spv_require_supported_enterprise_server_info() {
    local json_file="${1:-}"
    local version
    if ! version="$(spv_server_info_version "${json_file}")"; then
        echo "ERROR: Could not determine Splunk Enterprise version from server-info JSON: ${json_file:-<empty>}" >&2
        return 1
    fi
    spv_require_supported_enterprise_version "${version}" || return 1
    printf '%s\n' "${version}"
}

spv_splunk_home_version() {
    local splunk_home="${1:-}"
    local output
    if [[ -z "${splunk_home}" || ! -x "${splunk_home}/bin/splunk" ]]; then
        echo "ERROR: Splunk CLI is missing or not executable under ${splunk_home:-<empty>}." >&2
        return 1
    fi
    if ! output="$("${splunk_home}/bin/splunk" version 2>&1)"; then
        echo "ERROR: Could not run ${splunk_home}/bin/splunk version." >&2
        return 1
    fi
    python3 - "${output}" <<'PY'
import re
import sys

match = re.search(r"\b(?:Splunk(?: Universal Forwarder)?|Universal Forwarder)\s+(\d+\.\d+(?:\.\d+)?)\b", sys.argv[1])
if not match:
    raise SystemExit(1)
print(match.group(1))
PY
}

spv_require_supported_splunk_home() {
    local splunk_home="${1:-}"
    local version
    if ! version="$(spv_splunk_home_version "${splunk_home}")"; then
        echo "ERROR: Could not determine installed Splunk version under ${splunk_home:-<empty>}." >&2
        return 1
    fi
    spv_require_supported_enterprise_version "${version}" || return 1
    printf '%s\n' "${version}"
}
