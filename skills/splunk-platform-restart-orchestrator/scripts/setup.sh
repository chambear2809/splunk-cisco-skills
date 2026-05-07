#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=../../shared/lib/credential_helpers.sh
source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"

MODE="plan"
OPERATION="changes"
TARGET_ROLE="${SPLUNK_TARGET_ROLE:-standalone}"
RESTART_MODE="${PLATFORM_RESTART_MODE:-auto}"
EXPECTED_PORTS=""
TIMEOUT="${PLATFORM_RESTART_DEFAULT_TIMEOUT:-600}"
JSON_OUTPUT=false
DRY_RUN=false
ACCEPT_RESTART=false
RELOAD_HINT=""
AUDIT_OUTPUT_DIR="${REPO_ROOT}/splunk-platform-restart-rendered"

usage() {
    cat <<'EOF'
Usage:
  setup.sh --plan-restart [--operation TEXT] [--target-role ROLE] [--json]
  setup.sh --restart --accept-restart [--operation TEXT]
  setup.sh --reload ENDPOINT_OR_HINT
  setup.sh --audit-repo [--json]
  setup.sh --validate-restart-path [--json]

Options:
  --restart-mode auto|acs|systemd|cli|rest|idxc|shc|handoff|none
  --allow-rest-fallback
  --expected-port PORT[,PORT]
  --timeout SECONDS
  --dry-run
  --json
EOF
}

json_string() {
    python3 -c 'import json, sys; print(json.dumps(sys.argv[1]), end="")' "${1:-}"
}

emit_plan_json() {
    local plan_text="$1"
    PLAN_TEXT="${plan_text}" EXPECTED_PORTS="${EXPECTED_PORTS}" python3 - <<'PY'
import json
import os

data = {}
for line in os.environ["PLAN_TEXT"].splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        data[key] = value
data["expected_ports"] = [p for p in os.environ.get("EXPECTED_PORTS", "").split(",") if p]
data["secrets"] = "not-rendered"
print(json.dumps({"restart_plan": data}, indent=2, sort_keys=True))
PY
}

emit_plan() {
    local plan_text
    load_splunk_connection_settings
    SPLUNK_TARGET_ROLE="${TARGET_ROLE}"
    PLATFORM_RESTART_MODE="${RESTART_MODE}"
    PLATFORM_RESTART_DEFAULT_TIMEOUT="${TIMEOUT}"
    plan_text="$(platform_restart_plan "${OPERATION}" "${TARGET_ROLE}" "${RESTART_MODE}")"
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        emit_plan_json "${plan_text}"
    else
        printf '%s\n' "${plan_text}"
        if [[ -n "${EXPECTED_PORTS}" ]]; then
            printf 'expected_ports=%s\n' "${EXPECTED_PORTS}"
        fi
    fi
}

run_reload() {
    local hint="$1" endpoint body sk
    load_splunk_connection_settings
    case "${hint}" in
        deploy-server|deployment-server|serverclass|serverclass.conf)
            "${SPLUNK_HOME:-/opt/splunk}/bin/splunk" reload deploy-server
            ;;
        workload|workload-pools|workload_rules|workload-rules)
            "${SPLUNK_HOME:-/opt/splunk}/bin/splunk" _internal call /services/workloads/pools/_reload >/dev/null 2>&1 || true
            "${SPLUNK_HOME:-/opt/splunk}/bin/splunk" _internal call /servicesNS/nobody/search/workloads/rules/_reload >/dev/null 2>&1 || true
            ;;
        /services*)
            sk="$(get_session_key "${SPLUNK_URI}")"
            endpoint="${hint%/}"
            case "${endpoint}" in
                */_reload) ;;
                *) endpoint="${endpoint}/_reload" ;;
            esac
            body="$(form_urlencode_pairs output_mode json)" || return 1
            splunk_curl_post "${sk}" "${body}" "${SPLUNK_URI}${endpoint}" >/dev/null
            ;;
        *)
            log "ERROR: Unknown reload hint '${hint}'. Use deploy-server, workload, or /services/... endpoint."
            return 1
            ;;
    esac
}

run_restart() {
    local sk
    load_splunk_connection_settings
    SPLUNK_TARGET_ROLE="${TARGET_ROLE}"
    PLATFORM_RESTART_MODE="${RESTART_MODE}"
    PLATFORM_RESTART_DEFAULT_TIMEOUT="${TIMEOUT}"
    if [[ "${DRY_RUN}" == "true" ]]; then
        emit_plan
        return 0
    fi
    if [[ "${ACCEPT_RESTART}" != "true" ]]; then
        log "ERROR: --restart requires --accept-restart."
        return 1
    fi
    sk="$(get_session_key "${SPLUNK_URI}")"
    platform_restart_or_exit "${sk}" "${SPLUNK_URI}" "${OPERATION}" \
        "Restart manually before relying on ${OPERATION}."
}

while (( $# > 0 )); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --plan-restart) MODE="plan"; shift ;;
        --restart) MODE="restart"; shift ;;
        --accept-restart) ACCEPT_RESTART=true; shift ;;
        --reload) require_arg "$1" $# || exit 1; MODE="reload"; RELOAD_HINT="$2"; shift 2 ;;
        --audit-repo) MODE="audit"; shift ;;
        --validate-restart-path) MODE="validate"; shift ;;
        --operation) require_arg "$1" $# || exit 1; OPERATION="$2"; shift 2 ;;
        --target-role) require_arg "$1" $# || exit 1; TARGET_ROLE="$2"; shift 2 ;;
        --restart-mode) require_arg "$1" $# || exit 1; RESTART_MODE="$2"; shift 2 ;;
        --allow-rest-fallback) PLATFORM_RESTART_ALLOW_REST_FALLBACK=true; export PLATFORM_RESTART_ALLOW_REST_FALLBACK; shift ;;
        --expected-port|--expected-ports) require_arg "$1" $# || exit 1; EXPECTED_PORTS="$2"; shift 2 ;;
        --timeout) require_arg "$1" $# || exit 1; TIMEOUT="$2"; shift 2 ;;
        --output-dir) require_arg "$1" $# || exit 1; AUDIT_OUTPUT_DIR="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --json) JSON_OUTPUT=true; shift ;;
        *) log "ERROR: Unknown option '$1'"; usage; exit 1 ;;
    esac
done

case "${RESTART_MODE}" in
    auto|acs|systemd|cli|rest|idxc|shc|handoff|none) ;;
    *) log "ERROR: --restart-mode must be auto|acs|systemd|cli|rest|idxc|shc|handoff|none"; exit 1 ;;
esac

case "${MODE}" in
    plan) emit_plan ;;
    validate) emit_plan ;;
    restart) run_restart ;;
    reload) run_reload "${RELOAD_HINT}" ;;
    audit)
        args=(--output-dir "${AUDIT_OUTPUT_DIR}")
        [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
        python3 "${SCRIPT_DIR}/repo_audit.py" "${args[@]}"
        ;;
    *) log "ERROR: Unsupported mode '${MODE}'"; exit 1 ;;
esac
