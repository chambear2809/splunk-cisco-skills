#!/usr/bin/env bash
# Shared app-registry and deployment-role helpers.
# Sourced by credential_helpers.sh; not intended for direct use.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_REGISTRY_HELPERS_LOADED:-}" ]] && return 0
_REGISTRY_HELPERS_LOADED=true

REGISTRY_FILE="${REGISTRY_FILE:-${_PROJECT_ROOT}/skills/shared/app_registry.json}"

_registry_lookup_value() {
    local section="${1:-}"
    local match_field="${2:-}"
    local match_value="${3:-}"
    local target_path="${4:-}"

    [[ -f "${REGISTRY_FILE}" ]] || return 0

    python3 - "${REGISTRY_FILE}" "${section}" "${match_field}" "${match_value}" "${target_path}" <<'PY'
import json
import sys

registry_path, section, match_field, match_value, target_path = sys.argv[1:6]

try:
    with open(registry_path, encoding="utf-8") as handle:
        registry = json.load(handle)
except json.JSONDecodeError as exc:
    # Surface a one-line diagnostic so a corrupt registry does not silently
    # turn every role-aware check into "no metadata found". The caller still
    # gets exit 0 + empty stdout, preserving existing best-effort behavior.
    print(
        f"WARNING: registry_helpers: failed to parse {registry_path}: "
        f"{exc.msg} (line {exc.lineno}, col {exc.colno})",
        file=sys.stderr,
    )
    raise SystemExit(0)
except OSError as exc:
    print(
        f"WARNING: registry_helpers: could not read {registry_path}: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(0)

entries = registry.get(section, [])
for entry in entries:
    if str(entry.get(match_field, "")) != match_value:
        continue

    value = entry
    for part in target_path.split("."):
        if not part:
            continue
        if not isinstance(value, dict):
            value = ""
            break
        value = value.get(part, "")

    if isinstance(value, bool):
        print("true" if value else "false", end="")
    elif isinstance(value, (dict, list)):
        print(json.dumps(value, sort_keys=True), end="")
    else:
        print(str(value), end="")
    raise SystemExit(0)
PY
}

shared_registry_app_label_by_id() {
    _registry_lookup_value "apps" "splunkbase_id" "${1:-}" "label"
}

shared_registry_app_label_by_name() {
    _registry_lookup_value "apps" "app_name" "${1:-}" "label"
}

shared_registry_app_role_support_by_id() {
    _registry_lookup_value "apps" "splunkbase_id" "${1:-}" "role_support.${2:-}"
}

shared_registry_app_role_support_by_name() {
    _registry_lookup_value "apps" "app_name" "${1:-}" "role_support.${2:-}"
}

shared_registry_skill_role_support_by_skill() {
    _registry_lookup_value "skill_topologies" "skill" "${1:-}" "role_support.${2:-}"
}

shared_registry_app_capabilities_json_by_id() {
    _registry_lookup_value "apps" "splunkbase_id" "${1:-}" "capabilities"
}

shared_registry_app_capabilities_json_by_name() {
    _registry_lookup_value "apps" "app_name" "${1:-}" "capabilities"
}

shared_registry_skill_notes_by_skill() {
    _registry_lookup_value "skill_topologies" "skill" "${1:-}" "notes"
}

shared_registry_skill_cloud_pairing_json_by_skill() {
    _registry_lookup_value "skill_topologies" "skill" "${1:-}" "cloud_pairing"
}

_registry_capability_summary() {
    local capabilities_json="${1:-}"
    local role="${2:-}"

    [[ -n "${capabilities_json}" ]] || return 0

    python3 - "${capabilities_json}" "${role}" <<'PY'
import json
import sys

try:
    capabilities = json.loads(sys.argv[1])
except json.JSONDecodeError as exc:
    # Internal helper: capabilities_json is built from registry data, so a
    # decode error here is a real bug. Surface it without crashing callers.
    print(
        f"WARNING: registry_helpers: invalid capabilities JSON ({exc.msg}); "
        "treating as no capabilities.",
        file=sys.stderr,
    )
    raise SystemExit(0)

role = sys.argv[2]
reasons = []

if capabilities.get("needs_custom_rest"):
    reasons.append("custom REST handlers")
if capabilities.get("needs_search_time_objects"):
    reasons.append("search-time knowledge objects")
if capabilities.get("needs_kvstore"):
    reasons.append("KV Store content")
if capabilities.get("needs_python_runtime"):
    reasons.append("the full Splunk Python runtime")
if capabilities.get("needs_packet_capture"):
    reasons.append("packet capture or streamfwd support")
if role == "universal-forwarder" and not capabilities.get("uf_safe", False):
    reasons.append("it is not marked UF-safe")

if not reasons:
    raise SystemExit(0)

if len(reasons) == 1:
    print(reasons[0], end="")
elif len(reasons) == 2:
    print(f"{reasons[0]} and {reasons[1]}", end="")
else:
    print(f"{', '.join(reasons[:-1])}, and {reasons[-1]}", end="")
PY
}

_warn_role_metadata_missing() {
    local subject="${1:-this target}"

    log "INFO: No deployment-role metadata found for ${subject}. Continuing without role-aware checks."
}

_warn_role_unsupported() {
    local subject="${1:-This target}"
    local role="${2:-}"
    local reasons="${3:-}"

    log "WARNING: ${subject} is not modeled for role '${role}'."
    if [[ -n "${reasons}" ]]; then
        log "         Relevant capabilities: ${reasons}."
    fi
    log "         Continuing because deployment-role checks are warning-only."
}

_registry_role_list_summary() {
    local roles_json="${1:-}"

    [[ -n "${roles_json}" ]] || return 0

    python3 - "${roles_json}" <<'PY'
import json
import sys

try:
    roles = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(0)

if not isinstance(roles, list):
    raise SystemExit(0)

roles = [str(role) for role in roles if str(role)]
if not roles:
    raise SystemExit(0)
if len(roles) == 1:
    print(roles[0], end="")
elif len(roles) == 2:
    print(f"{roles[0]} or {roles[1]}", end="")
else:
    print(f"{', '.join(roles[:-1])}, or {roles[-1]}", end="")
PY
}

_cloud_pairing_is_satisfied() {
    local pairing_json="${1:-}"
    local primary_role="${2:-}"
    local paired_role="${3:-}"

    [[ -n "${pairing_json}" ]] || return 1

    python3 - "${pairing_json}" "${primary_role}" "${paired_role}" <<'PY'
import json
import sys

try:
    pairings = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(1)

declared = {value for value in sys.argv[2:] if value}
if not isinstance(pairings, list):
    raise SystemExit(1)

for role in pairings:
    if str(role) in declared:
        raise SystemExit(0)

raise SystemExit(1)
PY
}

warn_if_cloud_pairing_missing_for_skill() {
    local skill_name="${1:-}"
    local declared_roles pairing_json primary_role paired_role pairing_summary platform_hint

    [[ -n "${skill_name}" ]] || return 0
    platform_hint="$(_resolve_target_role_platform_hint 2>/dev/null || true)"
    [[ "${platform_hint}" == "cloud" ]] || return 0

    pairing_json="$(shared_registry_skill_cloud_pairing_json_by_skill "${skill_name}")"
    [[ -n "${pairing_json}" && "${pairing_json}" != "[]" ]] || return 0

    primary_role="$(resolve_primary_splunk_target_role)"
    paired_role="$(resolve_search_splunk_target_role)"

    if _cloud_pairing_is_satisfied "${pairing_json}" "${primary_role}" "${paired_role}"; then
        return 0
    fi

    pairing_summary="$(_registry_role_list_summary "${pairing_json}")"
    log "WARNING: Skill '${skill_name}' expects a paired Cloud runtime role: ${pairing_summary:-declared in the registry}."
    if [[ -n "${primary_role}" || -n "${paired_role}" ]]; then
        declared_roles="primary='${primary_role:-unknown}'"
        if [[ -n "${paired_role}" ]]; then
            declared_roles+=", paired='${paired_role}'"
        fi
        log "         Declared roles: ${declared_roles}."
    else
        log "         No runtime roles are declared for the paired side of this Cloud workflow."
    fi
    log "         Continuing, but manage or validate the paired runtime separately."
}

warn_if_role_unsupported_for_app_id() {
    local app_id="${1:-}"
    local role support label reasons subject

    [[ -n "${app_id}" ]] || return 0

    role="$(resolve_splunk_target_role)"
    [[ -n "${role}" ]] || return 0

    support="$(shared_registry_app_role_support_by_id "${app_id}" "${role}")"
    if [[ -z "${support}" ]]; then
        _warn_role_metadata_missing "app ID ${app_id}"
        return 0
    fi
    [[ "${support}" != "none" ]] || {
        label="$(shared_registry_app_label_by_id "${app_id}")"
        subject="${label:-App ID ${app_id}}"
        reasons="$(_registry_capability_summary "$(shared_registry_app_capabilities_json_by_id "${app_id}")" "${role}")"
        _warn_role_unsupported "${subject}" "${role}" "${reasons}"
        return 0
    }

    return 0
}

warn_if_role_unsupported_for_app_name() {
    local app_name="${1:-}"
    local role support label reasons subject

    [[ -n "${app_name}" ]] || return 0

    role="$(resolve_splunk_target_role)"
    [[ -n "${role}" ]] || return 0

    support="$(shared_registry_app_role_support_by_name "${app_name}" "${role}")"
    if [[ -z "${support}" ]]; then
        _warn_role_metadata_missing "app '${app_name}'"
        return 0
    fi
    [[ "${support}" != "none" ]] || {
        label="$(shared_registry_app_label_by_name "${app_name}")"
        if [[ -n "${label}" ]]; then
            subject="${label}"
        else
            subject="App '${app_name}'"
        fi
        reasons="$(_registry_capability_summary "$(shared_registry_app_capabilities_json_by_name "${app_name}")" "${role}")"
        _warn_role_unsupported "${subject}" "${role}" "${reasons}"
        return 0
    }

    return 0
}

warn_if_role_unsupported_for_skill() {
    local skill_name="${1:-}"
    local role support notes subject

    [[ -n "${skill_name}" ]] || return 0

    role="$(resolve_splunk_target_role)"
    [[ -n "${role}" ]] || return 0

    support="$(shared_registry_skill_role_support_by_skill "${skill_name}" "${role}")"
    if [[ -z "${support}" ]]; then
        _warn_role_metadata_missing "skill '${skill_name}'"
        return 0
    fi
    [[ "${support}" != "none" ]] || {
        subject="Skill '${skill_name}'"
        notes="$(shared_registry_skill_notes_by_skill "${skill_name}")"
        _warn_role_unsupported "${subject}" "${role}" "${notes}"
        return 0
    }

    return 0
}

current_skill_name_from_script_dir() {
    local skill_dir

    [[ -n "${SCRIPT_DIR:-}" ]] || return 0
    skill_dir="$(cd "${SCRIPT_DIR}/.." 2>/dev/null && pwd)"
    [[ -n "${skill_dir}" ]] || return 0

    case "${skill_dir}" in
        "${_PROJECT_ROOT}/skills/"*)
            printf '%s' "${skill_dir##*/}"
            ;;
    esac
}

warn_if_current_skill_role_unsupported() {
    local skill_name

    skill_name="$(current_skill_name_from_script_dir)"
    [[ -n "${skill_name}" ]] || return 0

    warn_if_role_unsupported_for_skill "${skill_name}"
    warn_if_cloud_pairing_missing_for_skill "${skill_name}"
}
