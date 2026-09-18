#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SKILL_DIR}/../.." && pwd)"

# shellcheck source=../../shared/lib/credential_helpers.sh
source "${REPO_ROOT}/skills/shared/lib/credential_helpers.sh"
# shellcheck source=../../shared/lib/platform_version_helpers.sh
source "${REPO_ROOT}/skills/shared/lib/platform_version_helpers.sh"

MODE="plan"
OPERATION="changes"
TARGET_ROLE="${SPLUNK_TARGET_ROLE:-}"
RESTART_MODE="${PLATFORM_RESTART_MODE:-auto}"
EXPECTED_PORTS=""
TIMEOUT="${PLATFORM_RESTART_DEFAULT_TIMEOUT:-600}"
JSON_OUTPUT=false
DRY_RUN=false
ACCEPT_RESTART=false
RELOAD_HINT=""
AUDIT_OUTPUT_DIR="${REPO_ROOT}/splunk-platform-restart-rendered"

error_log() {
    log "$@" >&2
}

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

prepare_plan_context() {
    if ! load_splunk_connection_settings; then
        log "ERROR: Could not load the selected Splunk target settings."
        return 1
    fi
    if [[ -z "${TARGET_ROLE}" ]]; then
        TARGET_ROLE="${SPLUNK_TARGET_ROLE:-standalone}"
    fi
    if ! _platform_restart_validate_target_role "${TARGET_ROLE}"; then
        log "ERROR: --target-role and SPLUNK_TARGET_ROLE must select a supported restart topology."
        return 1
    fi
    # Keep the parent execution context aligned with an explicit CLI role (or
    # the file-backed role selected above), not only the planning subshell.
    SPLUNK_TARGET_ROLE="${TARGET_ROLE}"
}

build_plan() {
    if ! prepare_plan_context; then
        return 1
    fi
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
    if ! prepare_plan_context; then
        return 1
    fi
    if ! plan_text="$(build_plan)"; then
        return 1
    fi
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
    if ! prepare_plan_context; then
        return 1
    fi
    if ! plan_text="$(build_plan)"; then
        return 1
    fi
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
    local hint="$1" endpoint body sk execution_mode splunk_home stdin_content command platform http_code
    if ! prepare_plan_context; then
        error_log "ERROR: Could not prepare the selected Splunk reload target."
        return 1
    fi
    if ! platform="$(resolve_splunk_platform)"; then
        error_log "ERROR: Could not resolve the selected Splunk platform before reload."
        return 1
    fi
    if ! _platform_restart_validate_platform_role "${platform}" "${TARGET_ROLE}"; then
        error_log "ERROR: Reload target role is incompatible with the selected platform."
        return 1
    fi
    case "${hint}" in
        deploy-server|deployment-server|serverclass|serverclass.conf)
            if [[ "${platform}" != "enterprise" ]]; then
                error_log "ERROR: Host-command reload hints are supported only for a resolved Splunk Enterprise target."
                error_log "HANDOFF: Use a reviewed Cloud REST endpoint or the owning Cloud workflow for this reload."
                return 1
            fi
            case "${TARGET_ROLE}" in
                standalone|search-tier|heavy-forwarder) ;;
                *)
                    error_log "ERROR: Deploy-server reload is incompatible with the selected Splunk target role."
                    error_log "HANDOFF: Run this reload only on the reviewed deployment-server host."
                    return 1
                    ;;
            esac
            ;;
        workload|workload-pools|workload_rules|workload-rules)
            if [[ "${platform}" != "enterprise" ]]; then
                error_log "ERROR: Host-command reload hints are supported only for a resolved Splunk Enterprise target."
                error_log "HANDOFF: Use a reviewed Cloud REST endpoint or the owning Cloud workflow for this reload."
                return 1
            fi
            case "${TARGET_ROLE}" in
                standalone|search-tier) ;;
                *)
                    error_log "ERROR: Workload reload is incompatible with the selected Splunk target role."
                    error_log "HANDOFF: Run this reload only on the reviewed search-tier host."
                    return 1
                    ;;
            esac
            ;;
        /services*)
            case "${TARGET_ROLE}" in
                standalone|search-tier) ;;
                *)
                    error_log "ERROR: Generic REST reload is incompatible with the selected Splunk target role."
                    error_log "HANDOFF: Use the owning role-specific or cluster-aware workflow for this reload."
                    return 1
                    ;;
            esac
            ;;
    esac
    if [[ "${DRY_RUN}" == "true" ]]; then
        log "DRY RUN: would execute reload hint '${hint}' through the configured local/SSH/REST target path."
        return 0
    fi
    if ! execution_mode="$(platform_restart_execution_mode)"; then
        error_log "ERROR: Could not resolve the selected restart execution target."
        return 1
    fi
    splunk_home="${SPLUNK_HOME:-/opt/splunk}"
    if ! stdin_content="$(_platform_restart_stdin_auth)"; then
        return 1
    fi
    case "${hint}" in
        deploy-server|deployment-server|serverclass|serverclass.conf)
            command="$(hbs_shell_join "${splunk_home}/bin/splunk" reload deploy-server)"
            _platform_restart_run "${execution_mode}" "${command}" "${stdin_content}" || return 1
            ;;
        workload|workload-pools|workload_rules|workload-rules)
            command="$(hbs_shell_join "${splunk_home}/bin/splunk" _internal call /services/workloads/pools/_reload)"
            _platform_restart_run "${execution_mode}" "${command}" "${stdin_content}" >/dev/null || return 1
            command="$(hbs_shell_join "${splunk_home}/bin/splunk" _internal call /servicesNS/nobody/search/workloads/rules/_reload)"
            _platform_restart_run "${execution_mode}" "${command}" "${stdin_content}" >/dev/null || return 1
            ;;
        /services*)
            if ! sk="$(get_session_key "${SPLUNK_URI}")" || [[ -z "${sk}" ]]; then
                error_log "ERROR: Could not authenticate to the selected Splunk REST target; refusing reload."
                return 1
            fi
            endpoint="${hint%/}"
            case "${endpoint}" in
                */_reload) ;;
                *) endpoint="${endpoint}/_reload" ;;
            esac
            body="$(form_urlencode_pairs output_mode json)" || return 1
            if ! http_code="$(splunk_curl_post \
                "${sk}" "${body}" \
                --output /dev/null --write-out '%{http_code}' \
                "${SPLUNK_URI}${endpoint}")"; then
                error_log "ERROR: Splunk REST reload request failed before a successful HTTP response was observed."
                return 1
            fi
            if [[ ! "${http_code}" =~ ^[0-9]{3}$ ]]; then
                error_log "ERROR: Splunk REST reload returned an invalid HTTP status; refusing to report success."
                return 1
            fi
            case "${http_code}" in
                2??) ;;
                *)
                    error_log "ERROR: Splunk REST reload returned HTTP ${http_code}; refusing to report success."
                    return 1
                    ;;
            esac
            ;;
        *)
            error_log "ERROR: Unknown reload hint '${hint}'. Use deploy-server, workload, or /services/... endpoint."
            return 1
            ;;
    esac
}

run_restart() {
    local sk plan_text decision platform
    if [[ "${DRY_RUN}" == "true" ]]; then
        emit_plan
        return 0
    fi
    if [[ "${ACCEPT_RESTART}" != "true" ]]; then
        log "ERROR: --restart requires --accept-restart."
        return 1
    fi
    # Load and resolve the target in this shell before authentication or any
    # restart mutation. A successful build_plan command substitution cannot
    # safely establish parent-shell connection variables.
    if ! prepare_plan_context; then
        return 1
    fi
    if ! plan_text="$(build_plan)"; then
        return 1
    fi
    decision="$(plan_decision "${plan_text}")"
    if [[ "${RESTART_MODE}" == "none" || "${RESTART_MODE}" == "handoff" || "${RESTART_MODE}" == "idxc" || "${RESTART_MODE}" == "shc" ]] \
        || ! decision_is_actionable "${decision}" \
        || ! plan_path_is_executable "${plan_text}"; then
        print_plan "${plan_text}"
        emit_incomplete_handoff "${decision}"
        return 1
    fi
    if ! platform="$(resolve_splunk_platform)"; then
        log "ERROR: Could not resolve the selected Splunk platform before restart."
        return 1
    fi
    if [[ -n "${EXPECTED_PORTS}" && "${platform}" == "cloud" ]]; then
        print_plan "${plan_text}"
        log "ERROR: --expected-port cannot be verified through the Cloud ACS restart path."
        log "HANDOFF: Use a supported external service probe after ACS reports Ready, or omit this option."
        return 1
    fi
    if ! sk="$(get_session_key "${SPLUNK_URI}")"; then
        log "ERROR: Could not authenticate to the selected Splunk target before restart."
        return 1
    fi
    if [[ "${platform}" != "cloud" ]]; then
        local server_info_file enterprise_version
        server_info_file="$(mktemp)"
        chmod 600 "${server_info_file}"
        if ! splunk_curl "${sk}" --fail-with-body --show-error \
            "${SPLUNK_URI%/}/services/server/info?output_mode=json" >"${server_info_file}"; then
            rm -f "${server_info_file}"
            log "ERROR: Could not read /services/server/info before the Enterprise restart."
            return 1
        fi
        if ! enterprise_version="$(spv_require_supported_enterprise_server_info "${server_info_file}")"; then
            rm -f "${server_info_file}"
            return 1
        fi
        rm -f "${server_info_file}"
        log "Validated supported Splunk Enterprise runtime ${enterprise_version} before restart."
    fi
    if ! platform_restart_or_exit "${sk}" "${SPLUNK_URI}" "${OPERATION}" \
        "Restart manually before relying on ${OPERATION}."; then
        return 1
    fi
    if ! prepare_plan_context; then
        log "ERROR: Could not reload the selected Splunk target after execution."
        return 1
    fi
    if ! plan_text="$(build_plan)"; then
        log "ERROR: Could not rebuild the restart plan after execution."
        return 1
    fi
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
