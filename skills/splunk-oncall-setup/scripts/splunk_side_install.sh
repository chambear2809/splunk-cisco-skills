#!/usr/bin/env bash
# Install or refresh the Splunk-side companion apps for Splunk On-Call.
#
# Reads a splunk-side YAML/JSON spec (see templates/splunk-side.example.yaml)
# and renders the planned actions: install Splunkbase 3546 (victorops_app)
# on a search head, install Splunkbase 4886 (TA-splunk-add-on-for-victorops)
# on a heavy forwarder, render Splunkbase 5863 SOAR connector readiness,
# pre-create the four required indexes the Add-on macros expect, seed the
# alert-action's mycollection KV Store with the operator-supplied API
# credentials, and configure the org slug on victorops_app.
#
# Render-first: defaults to printing the planned actions. Mutates only when
# --apply is passed. Uses file-based secrets only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_splunk_connection_settings

if [[ -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="${PYTHON:-python3}"
fi

INSTALL_APP_SH="${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh"
UNINSTALL_APP_SH="${PROJECT_ROOT}/skills/splunk-app-install/scripts/uninstall_app.sh"

usage() {
    cat <<'EOF'
Splunk-side install for Splunk On-Call.

Usage:
  bash skills/splunk-oncall-setup/scripts/splunk_side_install.sh \
       --spec PATH [options]

Required:
  --spec PATH                 splunk-side YAML or JSON spec.

Common options:
  --apply                     Mutate Splunk (install apps, create indexes, configure
                              the alert-action app, seed KV Store, and recovery polling).
                              Without --apply the script renders planned actions only.
  --api-id ID                 Splunk On-Call API ID (non-secret) used to seed mycollection.
  --api-key-file PATH         Splunk On-Call API key file (chmod 600).
  --uninstall                 Plan or execute uninstall of the three companion apps.
  --json                      Emit JSON output.

Direct secret flags such as --api-key, --vo-api-key, --integration-key,
--rest-key, and --token are rejected. Use --api-key-file instead.
EOF
}

SPEC=""
APPLY=false
UNINSTALL=false
JSON_OUTPUT=false
ONCALL_API_ID="${SPLUNK_ONCALL_API_ID:-}"
ONCALL_API_KEY_FILE="${SPLUNK_ONCALL_API_KEY_FILE:-}"

if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --spec) require_arg "$1" "$#" || exit 1; SPEC="$2"; shift 2 ;;
        --apply) APPLY=true; shift ;;
        --uninstall) UNINSTALL=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        --api-id) require_arg "$1" "$#" || exit 1; ONCALL_API_ID="$2"; shift 2 ;;
        --api-key-file) require_arg "$1" "$#" || exit 1; ONCALL_API_KEY_FILE="$2"; shift 2 ;;
        --api-key|--vo-api-key|--x-vo-api-key|--oncall-api-key|--on-call-api-key)
            reject_secret_arg "$1" "--api-key-file"; exit 1 ;;
        --api-key=*|--vo-api-key=*|--x-vo-api-key=*|--oncall-api-key=*|--on-call-api-key=*)
            reject_secret_arg "${1%%=*}" "--api-key-file"; exit 1 ;;
        --integration-key|--rest-key)
            reject_secret_arg "$1" "--integration-key-file"; exit 1 ;;
        --integration-key=*|--rest-key=*)
            reject_secret_arg "${1%%=*}" "--integration-key-file"; exit 1 ;;
        --token|--password|--secret)
            reject_secret_arg "$1" "--<*>-file"; exit 1 ;;
        --token=*|--password=*|--secret=*)
            reject_secret_arg "${1%%=*}" "--<*>-file"; exit 1 ;;
        --help|-h) usage; exit 0 ;;
        *) log "ERROR: Unknown option: $1"; usage; exit 1 ;;
    esac
done

if [[ -z "${SPEC}" ]]; then
    log "ERROR: --spec is required."
    exit 1
fi

# Build the plan in Python — much safer than building JSON via printf/%s.
PLAN_JSON="$(
    SPEC_PATH="${SPEC}" \
    APPLY_FLAG="${APPLY}" \
    UNINSTALL_FLAG="${UNINSTALL}" \
    ONCALL_API_ID="${ONCALL_API_ID}" \
    ONCALL_API_KEY_FILE="${ONCALL_API_KEY_FILE}" \
    "${PYTHON_BIN}" - <<'PY'
import json
import os
import sys
from pathlib import Path

spec_path = Path(os.environ["SPEC_PATH"])
text = spec_path.read_text(encoding="utf-8")
if spec_path.suffix.lower() == ".json":
    spec = json.loads(text)
else:
    import yaml

    spec = yaml.safe_load(text)
if not isinstance(spec, dict):
    print(f"ERROR: {spec_path} root must be a mapping/object.", file=sys.stderr)
    sys.exit(1)

splunk_side = spec.get("splunk_side") or {}
if not isinstance(splunk_side, dict):
    print("ERROR: splunk_side must be a mapping.", file=sys.stderr)
    sys.exit(1)

apply = os.environ.get("APPLY_FLAG", "false").lower() == "true"
uninstall = os.environ.get("UNINSTALL_FLAG", "false").lower() == "true"
api_id = os.environ.get("ONCALL_API_ID", "")
api_key_file = os.environ.get("ONCALL_API_KEY_FILE", "")

actions: list[dict] = []


def add_action(kind: str, description: str, **detail) -> None:
    actions.append({"kind": kind, "description": description, "detail": detail})


alert = splunk_side.get("alert_action_app") or {}
add_on = splunk_side.get("add_on") or {}
soar = splunk_side.get("soar_connector") or {}
itsi = splunk_side.get("itsi") or {}
es = splunk_side.get("enterprise_security") or {}
observability = bool(splunk_side.get("observability_handoff"))
recovery = spec.get("recovery_polling") or {}

if uninstall:
    if alert.get("app_name"):
        add_action(
            "uninstall",
            f"Uninstall Splunkbase {alert.get('splunkbase_id')} ({alert.get('app_name')})",
            app=alert.get("app_name"),
            splunkbase_id=alert.get("splunkbase_id"),
            install_target=alert.get("install_target", "search_head"),
        )
    if add_on.get("app_name"):
        add_action(
            "uninstall",
            f"Uninstall Splunkbase {add_on.get('splunkbase_id')} ({add_on.get('app_name')})",
            app=add_on.get("app_name"),
            splunkbase_id=add_on.get("splunkbase_id"),
            install_target=add_on.get("install_target", "heavy_forwarder"),
        )
    if soar.get("app_name"):
        add_action(
            "soar_uninstall_handoff",
            f"Uninstall Splunkbase {soar.get('splunkbase_id')} ({soar.get('app_name')}) "
            "through Splunk SOAR",
            app=soar.get("app_name"),
            splunkbase_id=soar.get("splunkbase_id"),
        )
else:
    if alert.get("app_name") and alert.get("splunkbase_id"):
        add_action(
            "install_app",
            f"Install Splunkbase {alert['splunkbase_id']} ({alert['app_name']}) on "
            f"{alert.get('install_target', 'search_head')}",
            app=alert["app_name"],
            splunkbase_id=alert["splunkbase_id"],
            install_target=alert.get("install_target", "search_head"),
        )
        if alert.get("org_slug"):
            add_action(
                "configure_org_slug",
                f"Set [ui] organization={alert['org_slug']} on {alert['app_name']}",
                app=alert["app_name"],
                org_slug=alert["org_slug"],
            )
        if api_id and api_key_file:
            add_action(
                "seed_kv_store",
                f"Seed mycollection in {alert['app_name']} with API ID + routing key",
                app=alert["app_name"],
                collection="mycollection",
                api_id=api_id,
                api_key_file=api_key_file,
            )
        if alert.get("ea_role") or alert.get("ea_mgr_host"):
            add_action(
                "alert_action_itsi_overrides",
                f"Render [victorops] ITSI overrides ea_role={alert.get('ea_role', '')!r} "
                f"ea_mgr_host={alert.get('ea_mgr_host', '')!r}",
                ea_role=alert.get("ea_role", ""),
                ea_mgr_host=alert.get("ea_mgr_host", ""),
            )
    if add_on.get("app_name") and add_on.get("splunkbase_id"):
        add_action(
            "install_app",
            f"Install Splunkbase {add_on['splunkbase_id']} ({add_on['app_name']}) on heavy_forwarder",
            app=add_on["app_name"],
            splunkbase_id=add_on["splunkbase_id"],
            install_target=add_on.get("install_target", "heavy_forwarder"),
        )
        indexes = add_on.get("indexes") or []
        if indexes:
            add_action(
                "create_indexes",
                "Pre-create the four indexes the Add-on macros expect",
                indexes=list(indexes),
            )
        inputs = add_on.get("inputs") or []
        if inputs:
            add_action(
                "inputs_config_handoff",
                f"Render the reviewed modular-input handoff for {add_on['app_name']} ({len(inputs)} inputs)",
                app=add_on["app_name"],
                input_kinds=[item.get("kind") for item in inputs if isinstance(item, dict)],
            )
    if soar.get("app_name") and soar.get("splunkbase_id"):
        add_action(
            "soar_readiness",
            f"Render Splunkbase {soar['splunkbase_id']} ({soar['app_name']}) "
            "asset-config stub for Splunk SOAR readiness (FIPS-compliant; min Phantom 5.1.0)",
            app=soar["app_name"],
            splunkbase_id=soar["splunkbase_id"],
            asset_label=soar.get("asset_label"),
            integration_url_required="for create_incident and update_incident actions only",
        )
    if itsi.get("enabled"):
        add_action(
            "itsi_neap_stub",
            f"Render ITSI NEAP JSON for Splunk On-Call (ea_role={itsi.get('ea_role') or 'executor'}, "
            f"ea_mgr_host={itsi.get('ea_mgr_host', '')!r})",
            ea_role=itsi.get("ea_role", "executor"),
            ea_mgr_host=itsi.get("ea_mgr_host", ""),
        )
    if es.get("adaptive_response"):
        add_action(
            "es_adaptive_response_stub",
            "Render Splunk ES Adaptive Response action backed by [victorops]",
        )
    if observability:
        add_action(
            "observability_handoff",
            "Render Splunk Observability detector recipient deeplink/handoff",
        )
    if recovery and recovery.get("enabled"):
        add_action(
            "recovery_polling_apply",
            "Toggle enable_recovery + the victorops-alert-recovery scheduled saved search via Splunk REST",
            scheduled_search=recovery.get("scheduled_search", {}),
            alert_actions=recovery.get("alert_actions", []),
        )

print(json.dumps({
    "mode": "uninstall" if uninstall else "install",
    "spec": str(spec_path),
    "apply": apply,
    "actions": actions,
}, indent=2, sort_keys=True))
PY
)"

if [[ $? -ne 0 ]]; then
    log "ERROR: Failed to build the splunk-side plan."
    exit 1
fi

if [[ "${APPLY}" != "true" ]]; then
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        echo "${PLAN_JSON}"
    else
        log "Splunk-side install plan (render-first; pass --apply to mutate):"
        echo "${PLAN_JSON}"
    fi
    exit 0
fi

# --- live apply ---

if [[ ! -f "${INSTALL_APP_SH}" ]]; then
    log "ERROR: Cannot find install_app.sh at ${INSTALL_APP_SH}."
    exit 1
fi
if [[ "${UNINSTALL}" == "true" && ! -f "${UNINSTALL_APP_SH}" ]]; then
    log "ERROR: Cannot find uninstall_app.sh at ${UNINSTALL_APP_SH}."
    exit 1
fi

profile_for_install_target() {
    local target="$1" profile="" role=""
    case "${target}" in
        search_head|search-tier|shc_deployer)
            profile="$(resolve_search_credential_profile 2>/dev/null || true)"
            [[ -n "${profile}" ]] || profile="$(resolve_credential_profile 2>/dev/null || true)"
            ;;
        heavy_forwarder|heavy-forwarder)
            profile="$(resolve_ingest_credential_profile 2>/dev/null || true)"
            if [[ -z "${profile}" ]]; then
                role="$(resolve_splunk_target_role 2>/dev/null || true)"
                if [[ "${role}" != "heavy-forwarder" ]]; then
                    log "ERROR: ${target} installation requires SPLUNK_INGEST_PROFILE pointing to a heavy-forwarder profile."
                    return 1
                fi
                profile="$(resolve_credential_profile 2>/dev/null || true)"
            fi
            ;;
        *)
            log "ERROR: Unsupported install_target '${target}'. Use search_head or heavy_forwarder."
            return 1
            ;;
    esac

    if [[ -n "${profile}" ]]; then
        role="$(deployment_profile_target_role "${profile}" 2>/dev/null || true)"
        case "${target}:${role}" in
            search_head:|search-tier:|shc_deployer:|search_head:search-tier|search-tier:search-tier|shc_deployer:search-tier) ;;
            heavy_forwarder:heavy-forwarder|heavy-forwarder:heavy-forwarder) ;;
            *)
                log "ERROR: Credential profile '${profile}' has target role '${role:-unset}', incompatible with install_target '${target}'."
                return 1
                ;;
        esac
    fi
    printf '%s' "${profile}"
}

run_install_app() {
    local app_name="$1" app_id="$2" target="$3" profile=""
    profile="$(profile_for_install_target "${target}")" || return 1
    log "Installing Splunkbase ${app_id} (${app_name}) on ${target} via splunk-app-install..."
    if [[ -n "${profile}" ]]; then
        SPLUNK_PROFILE="${profile}" SPLUNK_SEARCH_PROFILE='' \
            bash "${INSTALL_APP_SH}" --source splunkbase --app-id "${app_id}" --update
    else
        bash "${INSTALL_APP_SH}" --source splunkbase --app-id "${app_id}" --update
    fi
}

run_uninstall_app() {
    local app_name="$1" target="$2" profile=""
    profile="$(profile_for_install_target "${target}")" || return 1
    log "Uninstalling ${app_name} from ${target}..."
    if [[ -n "${profile}" ]]; then
        SPLUNK_PROFILE="${profile}" SPLUNK_SEARCH_PROFILE='' \
            bash "${UNINSTALL_APP_SH}" --app-name "${app_name}" --yes
    else
        bash "${UNINSTALL_APP_SH}" --app-name "${app_name}" --yes
    fi
}

rest_update_saved_search() {
    local session_key="$1" uri="$2" app="$3" search_name="$4" body="$5"
    local encoded_name response http_code
    encoded_name="$(_urlencode "${search_name}")"
    response="$(splunk_curl_post "${session_key}" "${body}" \
        "${uri}/servicesNS/nobody/${app}/saved/searches/${encoded_name}" \
        -w '\n%{http_code}' 2>/dev/null)" || {
        log "ERROR: Failed to update saved search '${search_name}'."
        return 1
    }
    http_code="$(printf '%s\n' "${response}" | tail -1)"
    case "${http_code}" in
        200|201) return 0 ;;
        *) log "ERROR: Update saved search '${search_name}' failed (HTTP ${http_code:-unknown})."; return 1 ;;
    esac
}

normalize_splunk_bool() {
    case "${1:-}" in
        1|true|True|TRUE) printf '1' ;;
        0|false|False|FALSE) printf '0' ;;
        *) printf '%s' "${1:-}" ;;
    esac
}

validate_api_key_file() {
    local path="$1"
    "${PYTHON_BIN}" - "${path}" <<'PY'
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    mode = stat.S_IMODE(path.stat().st_mode)
except OSError as exc:
    raise SystemExit(f"ERROR: cannot stat API key file {path}: {exc}")
if not path.is_file() or not path.read_bytes().strip():
    raise SystemExit(f"ERROR: API key file is missing or empty: {path}")
if mode & 0o077:
    raise SystemExit(
        f"ERROR: {path} has overly permissive mode {oct(mode)}; "
        "require 0600 or stricter"
    )
PY
}

ACTIONS_PARSED="$(PLAN_JSON="${PLAN_JSON}" "${PYTHON_BIN}" - <<'PY'
import json
import os

plan = json.loads(os.environ["PLAN_JSON"])
for action in plan.get("actions", []):
    detail = action.get("detail") or {}
    print(action.get("kind", ""), json.dumps(detail), sep="\t")
PY
)"

# Validate every target and secret prerequisite before the first mutation so a
# bad later action cannot leave an avoidable partial install.
while IFS=$'\t' read -r preflight_kind preflight_detail; do
    [[ -n "${preflight_kind}" ]] || continue
    case "${preflight_kind}" in
        install_app|uninstall)
            preflight_target="$(echo "${preflight_detail}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("install_target",""))')"
            [[ -n "${preflight_target}" ]] \
                || { log "ERROR: ${preflight_kind} action is missing install_target."; exit 1; }
            profile_for_install_target "${preflight_target}" >/dev/null
            ;;
        seed_kv_store)
            preflight_key_file="$(echo "${preflight_detail}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("api_key_file",""))')"
            preflight_api_id="$(echo "${preflight_detail}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("api_id",""))')"
            [[ -n "${preflight_api_id}" && -n "${preflight_key_file}" ]] \
                || { log "ERROR: seed_kv_store action is missing api_id or api_key_file."; exit 1; }
            validate_api_key_file "${preflight_key_file}"
            ;;
        recovery_polling_apply)
            DETAIL_JSON="${preflight_detail}" "${PYTHON_BIN}" - <<'PY'
import json
import os

detail = json.loads(os.environ["DETAIL_JSON"])
for item in detail.get("alert_actions") or []:
    if not isinstance(item, dict) or not str(item.get("alert_name") or "").strip():
        raise SystemExit("ERROR: every recovery alert action requires alert_name")
    enabled = item.get("enable_recovery", True)
    if not isinstance(enabled, bool) and enabled not in (0, 1):
        raise SystemExit("ERROR: enable_recovery must be a boolean or 0/1")
    if int(item.get("poll_interval", 300)) < 1 or int(item.get("inactive_polls", 1)) < 1:
        raise SystemExit("ERROR: poll_interval and inactive_polls must be positive")
schedule = detail.get("scheduled_search") or {}
if not isinstance(schedule, dict):
    raise SystemExit("ERROR: recovery scheduled_search must be an object")
enabled = schedule.get("enabled", True)
if not isinstance(enabled, bool) and enabled not in (0, 1):
    raise SystemExit("ERROR: scheduled_search.enabled must be a boolean or 0/1")
if int(schedule.get("schedule_window", 60)) < 0:
    raise SystemExit("ERROR: schedule_window cannot be negative")
PY
            ;;
    esac
done <<<"${ACTIONS_PARSED}"

# Resolve the search-tier Splunk session before making any mutation. This
# prevents a missing credential from producing a partial install followed by
# silently skipped configuration.
REQUIRES_SPLUNK_SESSION="$({ printf '%s\n' "${ACTIONS_PARSED}" | cut -f1 | grep -Eq \
    '^(seed_kv_store|configure_org_slug|recovery_polling_apply)$'; } && echo true || echo false)"
REQUIRES_INDEX_APPLY="$({ printf '%s\n' "${ACTIONS_PARSED}" | cut -f1 | grep -Eq \
    '^create_indexes$'; } && echo true || echo false)"
SESSION_KEY=""
if [[ "${REQUIRES_SPLUNK_SESSION}" == "true" ]] \
    || { [[ "${REQUIRES_INDEX_APPLY}" == "true" ]] && ! is_splunk_cloud; }; then
    if ! load_splunk_credentials >/dev/null 2>&1; then
        log "ERROR: Splunk credentials are required for the requested Splunk-side mutations."
        exit 1
    fi
fi
if [[ "${REQUIRES_SPLUNK_SESSION}" == "true" ]] \
    || { [[ "${REQUIRES_INDEX_APPLY}" == "true" ]] && ! is_splunk_cloud; }; then
    if ! SESSION_KEY="$(get_session_key "${SPLUNK_URI:-https://localhost:8089}" 2>/dev/null)" || [[ -z "${SESSION_KEY}" ]]; then
        log "ERROR: Could not resolve a Splunk session key; refusing a partial apply."
        exit 1
    fi
fi

pending_handoffs=()
while IFS=$'\t' read -r kind detail_json; do
    [[ -n "${kind}" ]] || continue
    case "${kind}" in
        install_app)
            app_name="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("app",""))')"
            app_id="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("splunkbase_id",""))')"
            install_target="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("install_target",""))')"
            [[ -n "${app_name}" && -n "${app_id}" && -n "${install_target}" ]] \
                || { log "ERROR: install_app action is missing app, id, or install_target."; exit 1; }
            run_install_app "${app_name}" "${app_id}" "${install_target}"
            ;;
        uninstall)
            app_name="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("app",""))')"
            install_target="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("install_target",""))')"
            [[ -n "${app_name}" && -n "${install_target}" ]] \
                || { log "ERROR: uninstall action is missing app or install_target."; exit 1; }
            run_uninstall_app "${app_name}" "${install_target}"
            ;;
        create_indexes)
            indexes="$(echo "${detail_json}" | "${PYTHON_BIN}" -c '
import json,sys
data = json.load(sys.stdin).get("indexes") or []
for name in data:
    if isinstance(name, str):
        print(name)
')"
            while IFS= read -r index_name; do
                [[ -n "${index_name}" ]] || continue
                log "Creating index ${index_name} through the platform-aware index path (idempotent)..."
                platform_create_index "${SESSION_KEY}" "${SPLUNK_URI:-https://localhost:8089}" "${index_name}"
            done <<<"${indexes}"
            ;;
        seed_kv_store)
            app="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("app",""))')"
            api_key_file="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("api_key_file",""))')"
            api_id="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("api_id",""))')"
            if [[ -z "${SESSION_KEY}" || -z "${app}" || -z "${api_key_file}" || -z "${api_id}" ]]; then
                log "ERROR: seed_kv_store requires a session key, app name, api_id, and api_key file."
                exit 1
            fi
            validate_api_key_file "${api_key_file}"
            log "Seeding ${app}.mycollection with API ID + key from a mode-0600 request file..."
            tmp_payload="$(mktemp)"
            tmp_response="$(mktemp)"
            chmod 600 "${tmp_payload}" "${tmp_response}"
            # SECURITY: the key is written only to a mode-0600 temporary file;
            # neither the value nor the JSON payload appears in process argv.
            if ! API_KEY_FILE="${api_key_file}" API_ID="${api_id}" "${PYTHON_BIN}" - "${tmp_payload}" <<'PY'
import json
import os
import sys
from pathlib import Path

with open(os.environ["API_KEY_FILE"], "r", encoding="utf-8") as handle:
    api_key = handle.read().strip()
if not api_key:
    raise SystemExit("API key file is empty")
Path(sys.argv[1]).write_text(
    json.dumps({"api_key": api_key, "api_id": os.environ["API_ID"]}),
    encoding="utf-8",
)
PY
            then
                rm -f "${tmp_payload}" "${tmp_response}"
                log "ERROR: Failed to build the KV Store request payload."
                exit 1
            fi
            seed_url="${SPLUNK_URI:-https://localhost:8089}/servicesNS/nobody/${app}/storage/collections/data/mycollection?output_mode=json"
            if ! seed_http_code="$(splunk_curl "${SESSION_KEY}" \
                -X POST \
                -H "Content-Type: application/json" \
                --data-binary "@${tmp_payload}" \
                -o "${tmp_response}" -w '%{http_code}' \
                "${seed_url}" 2>/dev/null)"; then
                seed_http_code="000"
            fi
            rm -f "${tmp_payload}"
            case "${seed_http_code}" in
                200|201) ;;
                *)
                # Sanitize the response: strip anything that looks like a
                # repeated API key value before logging.
                sanitized="$("${PYTHON_BIN}" - "${tmp_response}" <<'PY'
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")[:2048]
# Redact api_key occurrences (case-insensitive).
text = re.sub(
    r'(?i)("?api_key"?\s*[:=]\s*"?)[^"\s,}]+',
    r'\1[REDACTED]',
    text,
)
print(text)
PY
                )"
                    rm -f "${tmp_response}"
                    log "ERROR: KV Store seed failed (HTTP ${seed_http_code}). Response (sanitized): ${sanitized}"
                    exit 1
                    ;;
            esac
            rm -f "${tmp_response}"
            ;;
        configure_org_slug)
            app="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("app",""))')"
            org_slug="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("org_slug",""))')"
            [[ -n "${SESSION_KEY}" && -n "${app}" && -n "${org_slug}" ]] \
                || { log "ERROR: configure_org_slug requires a session key, app, and org_slug."; exit 1; }
            org_body="$(form_urlencode_pairs organization "${org_slug}")"
            log "Configuring [ui] organization for ${app}..."
            rest_set_conf "${SESSION_KEY}" "${SPLUNK_URI:-https://localhost:8089}" \
                "${app}" app ui "${org_body}"
            ;;
        recovery_polling_apply)
            app="victorops_app"
            recovery_rows="$(DETAIL_JSON="${detail_json}" "${PYTHON_BIN}" - <<'PY'
import json
import os

def flag(value, field):
    if isinstance(value, bool):
        return "1" if value else "0"
    if value in (0, 1):
        return str(value)
    raise SystemExit(f"ERROR: {field} must be a boolean or 0/1")

detail = json.loads(os.environ["DETAIL_JSON"])
for item in detail.get("alert_actions") or []:
    if not isinstance(item, dict):
        raise SystemExit("ERROR: recovery_polling.alert_actions entries must be objects")
    name = str(item.get("alert_name") or "").replace("\t", " ").replace("\n", " ").strip()
    if not name:
        raise SystemExit("ERROR: recovery_polling.alert_actions[].alert_name is required")
    enabled = flag(item.get("enable_recovery", True), "enable_recovery")
    poll = int(item.get("poll_interval", 300))
    inactive = int(item.get("inactive_polls", 1))
    if poll < 1 or inactive < 1:
        raise SystemExit("ERROR: poll_interval and inactive_polls must be positive")
    print(name, enabled, poll, inactive, sep="\t")
PY
            )"
            while IFS=$'\t' read -r alert_name enable_recovery poll_interval inactive_polls; do
                [[ -n "${alert_name}" ]] || continue
                recovery_body="$(form_urlencode_pairs \
                    action.victorops.param.enable_recovery "${enable_recovery}" \
                    action.victorops.param.poll_interval "${poll_interval}" \
                    action.victorops.param.inactive_polls "${inactive_polls}")"
                log "Configuring recovery parameters for saved search '${alert_name}'..."
                rest_update_saved_search "${SESSION_KEY}" "${SPLUNK_URI:-https://localhost:8089}" \
                    "${app}" "${alert_name}" "${recovery_body}"
                actual_recovery="$(rest_get_saved_search_value "${SESSION_KEY}" \
                    "${SPLUNK_URI:-https://localhost:8089}" "${app}" "${alert_name}" \
                    action.victorops.param.enable_recovery)"
                actual_recovery="$(normalize_splunk_bool "${actual_recovery}")"
                [[ "${actual_recovery}" == "${enable_recovery}" ]] \
                    || { log "ERROR: Recovery setting verification failed for '${alert_name}'."; exit 1; }
            done <<<"${recovery_rows}"
            schedule_values="$(DETAIL_JSON="${detail_json}" "${PYTHON_BIN}" - <<'PY'
import json
import os

schedule = json.loads(os.environ["DETAIL_JSON"]).get("scheduled_search") or {}
raw_enabled = schedule.get("enabled", True)
if not isinstance(raw_enabled, bool) and raw_enabled not in (0, 1):
    raise SystemExit("ERROR: recovery_polling.scheduled_search.enabled must be a boolean or 0/1")
enabled = "0" if bool(raw_enabled) else "1"
cron = str(schedule.get("cron_schedule") or "*/5 * * * *").replace("\t", " ").replace("\n", " ")
window = int(schedule.get("schedule_window", 60))
if window < 0:
    raise SystemExit("ERROR: recovery_polling.scheduled_search.schedule_window cannot be negative")
print(enabled, cron, window, sep="\t")
PY
            )"
            IFS=$'\t' read -r schedule_disabled schedule_cron schedule_window <<<"${schedule_values}"
            schedule_body="$(form_urlencode_pairs disabled "${schedule_disabled}" \
                cron_schedule "${schedule_cron}" schedule_window "${schedule_window}")"
            log "Configuring victorops-alert-recovery schedule..."
            rest_update_saved_search "${SESSION_KEY}" "${SPLUNK_URI:-https://localhost:8089}" \
                "${app}" "victorops-alert-recovery" "${schedule_body}"
            actual_disabled="$(rest_get_saved_search_value "${SESSION_KEY}" \
                "${SPLUNK_URI:-https://localhost:8089}" "${app}" "victorops-alert-recovery" disabled)"
            actual_disabled="$(normalize_splunk_bool "${actual_disabled}")"
            actual_cron="$(rest_get_saved_search_value "${SESSION_KEY}" \
                "${SPLUNK_URI:-https://localhost:8089}" "${app}" "victorops-alert-recovery" cron_schedule)"
            actual_window="$(rest_get_saved_search_value "${SESSION_KEY}" \
                "${SPLUNK_URI:-https://localhost:8089}" "${app}" "victorops-alert-recovery" schedule_window)"
            [[ "${actual_disabled}" == "${schedule_disabled}" \
                && "${actual_cron}" == "${schedule_cron}" \
                && "${actual_window}" == "${schedule_window}" ]] \
                || { log "ERROR: victorops-alert-recovery schedule verification failed."; exit 1; }
            ;;
        soar_uninstall_handoff)
            log "INFO: Splunkbase 5863 is a Splunk SOAR connector; use the rendered SOAR uninstall handoff."
            pending_handoffs+=("${kind}")
            ;;
        alert_action_itsi_overrides|inputs_config_handoff|soar_readiness|itsi_neap_stub|es_adaptive_response_stub|observability_handoff)
            log "INFO: ${kind} remains an explicit operator/child-skill handoff in handoff.md and payloads/splunk_side/splunk-side.json."
            pending_handoffs+=("${kind}")
            ;;
        *)
            log "ERROR: Unknown action kind: ${kind}; refusing to report a partial apply as successful."
            exit 1
            ;;
    esac
done <<<"${ACTIONS_PARSED}"

log "Requested Splunk Platform mutations completed; review every rendered handoff before declaring the full integration complete."
if (( ${#pending_handoffs[@]} > 0 )); then
    log "ERROR: The full Splunk-side request remains incomplete; pending handoffs: ${pending_handoffs[*]}"
    exit 2
fi
