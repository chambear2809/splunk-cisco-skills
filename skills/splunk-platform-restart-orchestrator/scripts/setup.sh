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

build_plan() {
    load_splunk_connection_settings
    SPLUNK_TARGET_ROLE="${TARGET_ROLE}"
    PLATFORM_RESTART_MODE="${RESTART_MODE}"
    PLATFORM_RESTART_DEFAULT_TIMEOUT="${TIMEOUT}"
    platform_restart_plan "${OPERATION}" "${TARGET_ROLE}" "${RESTART_MODE}"
}

print_plan() {
    local plan_text="$1"
    if [[ "${JSON_OUTPUT}" == "true" ]]; then
        emit_plan_json "${plan_text}"
    else
        printf '%s\n' "${plan_text}"
        if [[ -n "${EXPECTED_PORTS}" ]]; then
            printf 'expected_ports=%s\n' "${EXPECTED_PORTS}"
        fi
    fi
}

emit_plan() {
    local plan_text
    plan_text="$(build_plan)"
    print_plan "${plan_text}"
}

plan_decision() {
    sed -n 's/^decision=//p' <<< "$1" | head -n 1
}

plan_value() {
    local key="$1"
    sed -n "s/^${key}=//p" <<< "$2" | head -n 1
}

decision_is_actionable() {
    local decision="$1"
    case "${decision}" in
        acs|systemd-cli|cli|rest-explicit|rest-explicit-fallback) return 0 ;;
        *) return 1 ;;
    esac
}

plan_path_is_executable() {
    local plan_text="$1" decision execution_mode splunk_home
    decision="$(plan_decision "${plan_text}")"
    if [[ "${RESTART_MODE}" == "systemd" && "${decision}" != "systemd-cli" ]]; then
        return 1
    fi
    case "${decision}" in
        acs)
            acs_prepare_context >/dev/null 2>&1
            ;;
        systemd-cli|cli)
            execution_mode="$(plan_value execution_mode "${plan_text}")"
            splunk_home="$(plan_value splunk_home "${plan_text}")"
            [[ -n "${execution_mode}" && -n "${splunk_home}" ]] || return 1
            _platform_restart_capture "${execution_mode}" \
                "$(hbs_shell_join test -x "${splunk_home%/}/bin/splunk")" >/dev/null 2>&1
            ;;
        *) return 0 ;;
    esac
}

emit_incomplete_handoff() {
    local decision="$1"
    case "${decision}" in
        delegate-splunk-indexer-cluster-setup)
            log "HANDOFF: Use the indexer-cluster workflow for peer health checks and a cluster-aware rolling restart."
            ;;
        shc-rolling-restart)
            log "HANDOFF: From the SHC captain, run 'splunk rolling-restart shcluster-members -searchable true' after cluster health checks."
            ;;
        handoff-systemd-privilege)
            log "HANDOFF: Grant a supported noninteractive systemd restart path or run the rendered command manually, then verify /services/server/info."
            ;;
        invalid-enterprise-acs)
            log "HANDOFF: ACS restart is Cloud-only; choose --restart-mode systemd, cli, or an explicitly accepted REST fallback for Enterprise."
            ;;
        *)
            log "HANDOFF: No safe executable restart path was detected. Run --plan-restart, perform the reported restart manually, then verify /services/server/info."
            ;;
    esac
    log "ERROR: Restart request remains incomplete (decision=${decision:-unknown})."
}

validate_restart_path() {
    local plan_text decision
    plan_text="$(build_plan)"
    decision="$(plan_decision "${plan_text}")"
    print_plan "${plan_text}"
    if [[ "${RESTART_MODE}" == "none" || "${RESTART_MODE}" == "handoff" || "${RESTART_MODE}" == "idxc" || "${RESTART_MODE}" == "shc" ]] \
        || ! decision_is_actionable "${decision}" \
        || ! plan_path_is_executable "${plan_text}"; then
        emit_incomplete_handoff "${decision}"
        return 1
    fi
}

validate_expected_ports_after_restart() {
    local plan_text="$1" execution_mode splunk_home port probe_code raw_cmd
    [[ -n "${EXPECTED_PORTS}" ]] || return 0
    execution_mode="$(plan_value execution_mode "${plan_text}")"
    splunk_home="$(plan_value splunk_home "${plan_text}")"
    [[ -n "${execution_mode}" && -n "${splunk_home}" ]] || {
        log "ERROR: Cannot validate expected listener ports without an executable target mode."
        return 1
    }
    probe_code='import socket, sys; s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5); s.close()'
    IFS=',' read -r -a expected_port_array <<< "${EXPECTED_PORTS}"
    for port in "${expected_port_array[@]}"; do
        raw_cmd="$(hbs_shell_join "${splunk_home%/}/bin/splunk" cmd python3 -c "${probe_code}" "${port}")"
        if ! _platform_restart_capture "${execution_mode}" "${raw_cmd}" >/dev/null 2>&1; then
            log "ERROR: Expected listener port ${port} is not reachable on target loopback after restart."
            return 1
        fi
        log "Verified expected target listener port ${port}."
    done
}

run_reload() {
    local hint="$1" endpoint body sk execution_mode splunk_home stdin_content command
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would execute reload hint '${hint}' through the configured local/SSH/REST target path."
        return 0
    fi
    load_splunk_connection_settings
    execution_mode="$(platform_restart_execution_mode)"
    splunk_home="${SPLUNK_HOME:-/opt/splunk}"
    stdin_content="$(_platform_restart_stdin_auth)"
    case "${hint}" in
        deploy-server|deployment-server|serverclass|serverclass.conf)
            command="$(hbs_shell_join "${splunk_home}/bin/splunk" reload deploy-server)"
            _platform_restart_run "${execution_mode}" "${command}" "${stdin_content}"
            ;;
        workload|workload-pools|workload_rules|workload-rules)
            command="$(hbs_shell_join "${splunk_home}/bin/splunk" _internal call /services/workloads/pools/_reload)"
            _platform_restart_run "${execution_mode}" "${command}" "${stdin_content}" >/dev/null
            command="$(hbs_shell_join "${splunk_home}/bin/splunk" _internal call /servicesNS/nobody/search/workloads/rules/_reload)"
            _platform_restart_run "${execution_mode}" "${command}" "${stdin_content}" >/dev/null
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
    local sk plan_text decision
    if [[ "${DRY_RUN}" == "true" ]]; then
        emit_plan
        return 0
    fi
    if [[ "${ACCEPT_RESTART}" != "true" ]]; then
        log "ERROR: --restart requires --accept-restart."
        return 1
    fi
    plan_text="$(build_plan)"
    decision="$(plan_decision "${plan_text}")"
    if [[ "${RESTART_MODE}" == "none" || "${RESTART_MODE}" == "handoff" || "${RESTART_MODE}" == "idxc" || "${RESTART_MODE}" == "shc" ]] \
        || ! decision_is_actionable "${decision}" \
        || ! plan_path_is_executable "${plan_text}"; then
        print_plan "${plan_text}"
        emit_incomplete_handoff "${decision}"
        return 1
    fi
    if [[ -n "${EXPECTED_PORTS}" ]] && is_splunk_cloud 2>/dev/null; then
        print_plan "${plan_text}"
        log "ERROR: --expected-port cannot be verified through the Cloud ACS restart path."
        log "HANDOFF: Use a supported external service probe after ACS reports Ready, or omit this option."
        return 1
    fi
    sk="$(get_session_key "${SPLUNK_URI}")"
    if ! platform_restart_or_exit "${sk}" "${SPLUNK_URI}" "${OPERATION}" \
        "Restart manually before relying on ${OPERATION}."; then
        return 1
    fi
    plan_text="$(build_plan)"
    decision="$(plan_decision "${plan_text}")"
    if ! decision_is_actionable "${decision}" || ! plan_path_is_executable "${plan_text}"; then
        print_plan "${plan_text}"
        emit_incomplete_handoff "${decision}"
        return 1
    fi
    validate_expected_ports_after_restart "${plan_text}"
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

if [[ ! "${TIMEOUT}" =~ ^[1-9][0-9]*$ ]]; then
    log "ERROR: --timeout must be a positive integer number of seconds."
    exit 1
fi
if [[ -n "${EXPECTED_PORTS}" ]]; then
    if [[ "${MODE}" == "reload" || "${MODE}" == "audit" ]]; then
        log "ERROR: --expected-port is supported only for restart planning, path validation, or live restart."
        exit 1
    fi
    if [[ "${EXPECTED_PORTS}" == ,* || "${EXPECTED_PORTS}" == *, || "${EXPECTED_PORTS}" == *,,* ]]; then
        log "ERROR: --expected-port contains an empty port value."
        exit 1
    fi
    IFS=',' read -r -a expected_port_array <<< "${EXPECTED_PORTS}"
    for expected_port in "${expected_port_array[@]}"; do
        if [[ ! "${expected_port}" =~ ^[0-9]+$ ]] || (( expected_port < 1 || expected_port > 65535 )); then
            log "ERROR: Invalid expected TCP port '${expected_port}'."
            exit 1
        fi
    done
fi

case "${MODE}" in
    plan) emit_plan ;;
    validate) validate_restart_path ;;
    restart) run_restart ;;
    reload) run_reload "${RELOAD_HINT}" ;;
    audit)
        args=(--output-dir "${AUDIT_OUTPUT_DIR}")
        [[ "${JSON_OUTPUT}" == "true" ]] && args+=(--json)
        python3 "${SCRIPT_DIR}/repo_audit.py" "${args[@]}"
        ;;
    *) log "ERROR: Unsupported mode '${MODE}'"; exit 1 ;;
esac
