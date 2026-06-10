#!/usr/bin/env bash
# Shared Splunk Platform version defaults for shell skills.
# Source after SCRIPT_DIR is set, or pass an explicit repo skills root.

spv_skills_root() {
    if [[ -n "${SPV_SKILLS_ROOT:-}" ]]; then
        printf '%s' "${SPV_SKILLS_ROOT}"
        return 0
    fi
    if [[ -n "${SCRIPT_DIR:-}" ]]; then
        printf '%s' "$(cd "${SCRIPT_DIR}/../.." && pwd)"
        return 0
    fi
    echo "ERROR: spv_skills_root requires SCRIPT_DIR or SPV_SKILLS_ROOT" >&2
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
