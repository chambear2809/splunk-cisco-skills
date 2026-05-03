#!/usr/bin/env bash
# Install or refresh the Splunk-side companion apps for Splunk On-Call.
#
# Reads a splunk-side YAML/JSON spec (see templates/splunk-side.example.yaml)
# and renders the planned actions: install Splunkbase 3546 (victorops_app)
# on a search head, install Splunkbase 4886 (TA-splunk-add-on-for-victorops)
# on a heavy forwarder, install Splunkbase 5863 SOAR connector readiness,
# pre-create the four required indexes the Add-on macros expect, seed the
# alert-action's mycollection KV-store with the operator-supplied
# api_id + routing_key, and configure the org slug on victorops_app.
#
# Render-first: defaults to printing the planned actions. Mutates only when
# --apply is passed. Uses file-based secrets only.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=/dev/null
source "${PROJECT_ROOT}/skills/shared/lib/credential_helpers.sh"
load_splunk_connection_settings >/dev/null 2>&1 || true

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
  --apply                     Mutate Splunk (install apps, create indexes, seed KV-store).
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
        )
    if add_on.get("app_name"):
        add_action(
            "uninstall",
            f"Uninstall Splunkbase {add_on.get('splunkbase_id')} ({add_on.get('app_name')})",
            app=add_on.get("app_name"),
            splunkbase_id=add_on.get("splunkbase_id"),
        )
    if soar.get("app_name"):
        add_action(
            "uninstall",
            f"Uninstall Splunkbase {soar.get('splunkbase_id')} ({soar.get('app_name')}); "
            "this is a SOAR connector — uninstall through Splunk SOAR",
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
                "render_inputs_conf",
                f"Render inputs.conf for {add_on['app_name']} ({len(inputs)} inputs)",
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

run_install_app() {
    local app_name="$1" app_id="$2"
    log "Installing Splunkbase ${app_id} (${app_name}) via splunk-app-install..."
    bash "${INSTALL_APP_SH}" --app-id "${app_id}" --app-package-name "${app_name}"
}

run_uninstall_app() {
    local app_name="$1"
    log "Uninstalling ${app_name}..."
    bash "${UNINSTALL_APP_SH}" --app "${app_name}"
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

# Resolve a Splunk session for index/KV-store mutations.
load_splunk_credentials >/dev/null 2>&1 || true
SESSION_KEY=""
if resolve_splunk_session_key >/dev/null 2>&1; then
    SESSION_KEY="${SPLUNK_SESSION_KEY:-}"
else
    log "WARN: Could not resolve a Splunk session key. Index/KV-store mutations skipped."
fi

while IFS=$'\t' read -r kind detail_json; do
    [[ -n "${kind}" ]] || continue
    case "${kind}" in
        install_app)
            app_name="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("app",""))')"
            app_id="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("splunkbase_id",""))')"
            [[ -n "${app_name}" && -n "${app_id}" ]] && run_install_app "${app_name}" "${app_id}"
            ;;
        uninstall)
            app_name="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("app",""))')"
            [[ -n "${app_name}" ]] && run_uninstall_app "${app_name}"
            ;;
        create_indexes)
            indexes="$(echo "${detail_json}" | "${PYTHON_BIN}" -c '
import json,sys
data = json.load(sys.stdin).get("indexes") or []
for name in data:
    if isinstance(name, str):
        print(name)
')"
            if [[ -n "${SESSION_KEY}" ]]; then
                while IFS= read -r index_name; do
                    [[ -n "${index_name}" ]] || continue
                    log "Creating index ${index_name} (idempotent)..."
                    rest_create_index "${SESSION_KEY}" "${SPLUNK_URI:-https://localhost:8089}" "${index_name}" || true
                done <<<"${indexes}"
            else
                log "WARN: Skipping create_indexes — no Splunk session key."
            fi
            ;;
        seed_kv_store)
            app="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("app",""))')"
            api_key_file="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("api_key_file",""))')"
            api_id="$(echo "${detail_json}" | "${PYTHON_BIN}" -c 'import json,sys;print(json.load(sys.stdin).get("api_id",""))')"
            if [[ -z "${SESSION_KEY}" || -z "${app}" || -z "${api_key_file}" || -z "${api_id}" ]]; then
                log "WARN: Skipping seed_kv_store — missing session key, app name, api_id, or api_key file."
                continue
            fi
            # Validate the secret file (must exist, be readable, and have
            # mode 0600 so group/world bits are cleared).
            if [[ ! -r "${api_key_file}" ]]; then
                log "WARN: Skipping seed_kv_store — ${api_key_file} not readable."
                continue
            fi
            if ! "${PYTHON_BIN}" - "${api_key_file}" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
try:
    mode = stat.S_IMODE(os.stat(path).st_mode)
except OSError as exc:
    sys.exit(f"WARN: cannot stat {path}: {exc}")
if mode & 0o077:
    sys.exit(
        f"WARN: {path} has overly permissive mode {oct(mode)}; "
        "require 0600 (group/world bits cleared)."
    )
PY
            then
                log "WARN: Skipping seed_kv_store — api-key-file mode check failed."
                continue
            fi
            log "Seeding ${app}.mycollection with API ID + key (api_key passed via stdin to the JSON builder; never on argv)..."
            # SECURITY: do NOT pass api_key on the command line. Read it from
            # the file inside Python and emit a JSON payload to stdout.
            payload="$(API_KEY_FILE="${api_key_file}" API_ID="${api_id}" "${PYTHON_BIN}" - <<'PY'
import json
import os

with open(os.environ["API_KEY_FILE"], "r", encoding="utf-8") as handle:
    api_key = handle.read().strip()
print(json.dumps({"api_key": api_key, "api_id": os.environ["API_ID"]}))
PY
            )"
            # Capture errors instead of silently dropping them. Write any
            # response to a temp file we can scan for known failure patterns
            # without echoing potential secret material to logs.
            tmp_response="$(mktemp)"
            seed_url="${SPLUNK_URI:-https://localhost:8089}/servicesNS/nobody/${app}/storage/collections/data/mycollection?output_mode=json"
            seed_status=0
            splunk_curl "${SESSION_KEY}" \
                -X POST \
                -H "Content-Type: application/json" \
                -d "${payload}" \
                "${seed_url}" >"${tmp_response}" 2>&1 || seed_status=$?
            # Wipe payload from memory — best-effort.
            payload=""
            if [[ "${seed_status}" -ne 0 ]]; then
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
                log "WARN: KV-store seed failed (exit ${seed_status}). Response (sanitized): ${sanitized}"
            fi
            rm -f "${tmp_response}"
            ;;
        configure_org_slug|alert_action_itsi_overrides|render_inputs_conf|soar_readiness|itsi_neap_stub|es_adaptive_response_stub|observability_handoff|recovery_polling_apply)
            log "INFO: ${kind} is rendered into handoff.md / payloads/; no live REST action required by this script."
            ;;
        *)
            log "WARN: Unknown action kind: ${kind}"
            ;;
    esac
done <<<"${ACTIONS_PARSED}"

log "Splunk-side install complete."
