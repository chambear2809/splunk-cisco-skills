#!/usr/bin/env bash
# Splunk Platform restart/reload orchestration helpers.
# Source after credential_helpers.sh has loaded rest, ACS, deployment, and host
# bootstrap helpers.

[[ -n "${_RESTART_HELPERS_LOADED:-}" ]] && return 0
_RESTART_HELPERS_LOADED=true

PLATFORM_RESTART_DEFAULT_TIMEOUT="${PLATFORM_RESTART_DEFAULT_TIMEOUT:-600}"
PLATFORM_RESTART_CONNECT_TIMEOUT="${PLATFORM_RESTART_CONNECT_TIMEOUT:-10}"

_platform_restart_bool() {
    case "${1:-}" in
        1|[Tt][Rr][Uu][Ee]|[Yy]|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;;
        *) return 1 ;;
    esac
}

_platform_restart_safe_unit() {
    [[ "${1:-}" =~ ^[A-Za-z0-9_.@-]+\.service$ ]]
}

_platform_restart_uri_host() {
    local uri="${1:-${SPLUNK_URI:-}}"
    if type splunk_host_from_uri >/dev/null 2>&1; then
        splunk_host_from_uri "${uri}"
        return 0
    fi
    python3 -c "from urllib.parse import urlparse; import sys; print(urlparse(sys.argv[1]).hostname or '', end='')" "${uri}" 2>/dev/null
}

platform_restart_execution_mode() {
    local host

    if [[ -n "${PLATFORM_RESTART_EXECUTION:-}" ]]; then
        printf '%s' "${PLATFORM_RESTART_EXECUTION}"
        return 0
    fi
    if type deployment_execution_mode_for_profile >/dev/null 2>&1; then
        deployment_execution_mode_for_profile ""
        return 0
    fi

    host="$(_platform_restart_uri_host "${SPLUNK_URI:-}")"
    case "${SPLUNK_SSH_HOST:-${host}}" in
        ""|localhost|127.0.0.1|::1) printf '%s' "local" ;;
        *) printf '%s' "ssh" ;;
    esac
}

_platform_restart_can_use_ssh() {
    [[ -n "${SPLUNK_SSH_HOST:-}" || -n "${SPLUNK_HOST:-}" || -n "${SPLUNK_URI:-}" ]] || return 1
    [[ -n "${SPLUNK_SSH_PASS:-}" ]] || return 1
    command -v sshpass >/dev/null 2>&1
}

_platform_restart_capture() {
    local execution_mode="$1" raw_cmd="$2"
    if [[ "${execution_mode}" == "ssh" ]] && ! _platform_restart_can_use_ssh; then
        return 1
    fi
    hbs_capture_target_cmd "${execution_mode}" "${raw_cmd}"
}

_platform_restart_run() {
    local execution_mode="$1" raw_cmd="$2" stdin_content="${3:-}"
    if [[ "${execution_mode}" == "ssh" ]] && ! _platform_restart_can_use_ssh; then
        return 1
    fi
    hbs_run_target_cmd_with_stdin "${execution_mode}" "${raw_cmd}" "${stdin_content}"
}

platform_restart_detect_systemd_unit() {
    local execution_mode="${1:-$(platform_restart_execution_mode)}"
    local unit raw_cmd
    local -a candidates=()

    if [[ -n "${SPLUNK_SYSTEMD_UNIT:-}" ]]; then
        candidates+=("${SPLUNK_SYSTEMD_UNIT}")
    fi
    candidates+=(Splunkd.service splunk.service splunkd.service SplunkForwarder.service)

    for unit in "${candidates[@]}"; do
        _platform_restart_safe_unit "${unit}" || continue
        raw_cmd="command -v systemctl >/dev/null 2>&1 && systemctl show $(printf '%q' "${unit}") -p ExecStart --value 2>/dev/null | grep -q '_internal_launch_under_systemd' && printf '%s' $(printf '%q' "${unit}")"
        if _platform_restart_capture "${execution_mode}" "${raw_cmd}" 2>/dev/null | grep -q .; then
            printf '%s' "${unit}"
            return 0
        fi
    done
    return 1
}

platform_restart_has_noninteractive_privilege() {
    local execution_mode="${1:-$(platform_restart_execution_mode)}"
    local uid

    uid="$(_platform_restart_capture "${execution_mode}" "id -u" 2>/dev/null || true)"
    if [[ "${uid}" == "0" ]]; then
        return 0
    fi
    _platform_restart_run "${execution_mode}" "sudo -n true" "" >/dev/null 2>&1
}

_platform_restart_command_prefix() {
    local execution_mode="${1:-$(platform_restart_execution_mode)}"
    local uid

    uid="$(_platform_restart_capture "${execution_mode}" "id -u" 2>/dev/null || true)"
    if [[ "${uid}" == "0" ]]; then
        return 0
    fi
    printf '%s' "sudo -n "
}

_platform_restart_stdin_auth() {
    if [[ -n "${SPLUNK_USER:-}" && -n "${SPLUNK_PASS:-}" ]]; then
        printf '%s\n%s\n' "${SPLUNK_USER}" "${SPLUNK_PASS}"
    fi
}

_platform_restart_cli() {
    local execution_mode="$1" splunk_home="$2" use_sudo="${3:-false}"
    local splunk_bin cmd prefix stdin_content

    splunk_bin="${splunk_home%/}/bin/splunk"
    cmd="$(hbs_shell_join "${splunk_bin}" restart)"
    if [[ "${use_sudo}" == "true" ]]; then
        prefix="$(_platform_restart_command_prefix "${execution_mode}")"
        cmd="${prefix}${cmd}"
    fi
    stdin_content="$(_platform_restart_stdin_auth)"
    _platform_restart_run "${execution_mode}" "${cmd}" "${stdin_content}"
}

_platform_restart_rest_fallback_allowed() {
    _platform_restart_bool "${PLATFORM_RESTART_ALLOW_REST_FALLBACK:-false}" \
        || _platform_restart_bool "${ALLOW_REST_FALLBACK:-false}"
}

platform_restart_handoff() {
    local operation="${1:-changes}"
    local reason="${2:-No safe noninteractive restart path was detected.}"

    log "Restart handoff required for ${operation}: ${reason}"
    if is_splunk_cloud 2>/dev/null; then
        log "Splunk Cloud: run 'acs status current-stack' and restart only if restartRequired=true."
    else
        log "Enterprise: run the restart with the host's supported service manager, then verify ${SPLUNK_URI:-https://localhost:8089}/services/server/info."
        log "For a safer plan, run: bash skills/splunk-platform-restart-orchestrator/scripts/setup.sh --plan-restart --operation '$operation'"
    fi
}

platform_reload_or_restart_guidance() {
    local prefix="${1:-changes}"
    if is_splunk_cloud 2>/dev/null; then
        echo "Splunk Cloud: check 'acs status current-stack' after ${prefix} and run 'acs restart current-stack' only if restartRequired=true."
    elif [[ "${prefix}" == *"deploy"* || "${prefix}" == *"serverclass"* ]]; then
        echo "Deployment server: prefer 'splunk reload deploy-server' after ${prefix}; client restarts depend on serverclass issueReload/restartIfNeeded/restartSplunkd."
    elif [[ "${prefix}" == *"workload"* ]]; then
        echo "Workload Management: prefer the documented workload _reload endpoints after ${prefix}; restart only if a separate platform change requires it."
    else
        echo "Plan a Splunk restart for ${prefix} with splunk-platform-restart-orchestrator; on systemd hosts use a supported CLI/systemctl path rather than defaulting to REST restart."
    fi
}

platform_restart_plan() {
    local operation="${1:-changes}" target_role="${2:-${SPLUNK_TARGET_ROLE:-standalone}}" restart_mode="${3:-${PLATFORM_RESTART_MODE:-auto}}"
    local execution_mode splunk_home systemd_unit decision

    execution_mode="$(platform_restart_execution_mode 2>/dev/null || echo "unknown")"
    splunk_home="${SPLUNK_HOME:-/opt/splunk}"
    systemd_unit="$(platform_restart_detect_systemd_unit "${execution_mode}" 2>/dev/null || true)"
    decision="handoff"

    if is_splunk_cloud 2>/dev/null; then
        decision="acs"
    elif [[ "${restart_mode}" == "none" || "${restart_mode}" == "handoff" ]]; then
        decision="handoff"
    elif [[ "${restart_mode}" == "rest" ]]; then
        decision="rest-explicit"
    elif [[ "${restart_mode}" == "acs" ]]; then
        decision="invalid-enterprise-acs"
    elif [[ "${target_role}" == "indexer" || "${restart_mode}" == "idxc" ]]; then
        decision="delegate-splunk-indexer-cluster-setup"
    elif [[ "${restart_mode}" == "shc" ]]; then
        decision="shc-rolling-restart"
    elif [[ -n "${systemd_unit}" ]]; then
        if platform_restart_has_noninteractive_privilege "${execution_mode}"; then
            decision="systemd-cli"
        elif _platform_restart_rest_fallback_allowed; then
            decision="rest-explicit-fallback"
        else
            decision="handoff-systemd-privilege"
        fi
    elif _platform_restart_capture "${execution_mode}" "$(hbs_shell_join test -x "${splunk_home%/}/bin/splunk")" >/dev/null 2>&1; then
        decision="cli"
    elif _platform_restart_rest_fallback_allowed; then
        decision="rest-explicit-fallback"
    fi

    cat <<EOF
operation=${operation}
target_role=${target_role}
restart_mode=${restart_mode}
execution_mode=${execution_mode}
splunk_home=${splunk_home}
systemd_unit=${systemd_unit:-none}
decision=${decision}
EOF
}

platform_restart_or_exit() {
    local sk="$1" uri="$2" operation="$3"
    local skip_msg="${4:-Restart manually before relying on the updated state.}"
    local restart_mode="${PLATFORM_RESTART_MODE:-auto}"
    local target_role="${SPLUNK_TARGET_ROLE:-standalone}"
    local execution_mode splunk_home systemd_unit rc

    if [[ "${RESTART_SPLUNK:-true}" != "true" ]]; then
        log "Skipping Splunk restart (--no-restart). ${skip_msg}"
        return 0
    fi

    if is_splunk_cloud 2>/dev/null; then
        cloud_app_restart_or_exit "${operation}" "${skip_msg}"
        return $?
    fi

    execution_mode="$(platform_restart_execution_mode 2>/dev/null || echo "unknown")"
    splunk_home="${SPLUNK_HOME:-/opt/splunk}"

    case "${restart_mode}" in
        none|handoff)
            platform_restart_handoff "${operation}" "Restart mode is ${restart_mode}."
            return 0
            ;;
        acs)
            log "ERROR: --restart-mode acs is only valid for Splunk Cloud targets."
            return 1
            ;;
        idxc)
            platform_restart_handoff "${operation}" "Indexer cluster restarts are delegated to splunk-indexer-cluster-setup."
            return 0
            ;;
        shc)
            platform_restart_handoff "${operation}" "Use 'splunk rolling-restart shcluster-members -searchable true' or the SHC captain restart endpoint after health checks."
            return 0
            ;;
        rest)
            PLATFORM_RESTART_ALLOW_REST_FALLBACK=true
            ;;
        auto|systemd|cli) ;;
        *)
            log "ERROR: Unknown restart mode '${restart_mode}'."
            return 1
            ;;
    esac

    if [[ "${target_role}" == "indexer" && "${restart_mode}" == "auto" ]]; then
        platform_restart_handoff "${operation}" "Indexer target detected; use cluster-aware rolling restart or peer offline/start semantics."
        return 0
    fi

    systemd_unit="$(platform_restart_detect_systemd_unit "${execution_mode}" 2>/dev/null || true)"
    if [[ "${restart_mode}" == "systemd" || ( "${restart_mode}" == "auto" && -n "${systemd_unit}" ) ]]; then
        if [[ -z "${systemd_unit}" ]]; then
            platform_restart_handoff "${operation}" "No Splunk systemd unit was detected."
            return 0
        fi
        if ! platform_restart_has_noninteractive_privilege "${execution_mode}"; then
            if _platform_restart_rest_fallback_allowed; then
                log "WARNING: No noninteractive systemd privilege detected; using explicit REST fallback for ${operation}."
            else
                platform_restart_handoff "${operation}" "Detected ${systemd_unit}, but no noninteractive sudo/polkit restart privilege is available."
                return 0
            fi
        else
            log "Restarting Splunk with the systemd-managed CLI path to complete ${operation}..."
            _platform_restart_cli "${execution_mode}" "${splunk_home}" true
            rc=$?
            if (( rc != 0 )); then
                log "ERROR: systemd-managed CLI restart failed."
                return "${rc}"
            fi
            wait_for_splunk_ready "${uri}" "${PLATFORM_RESTART_DEFAULT_TIMEOUT}" 5 || {
                log "ERROR: Splunk did not come back online before the restart timeout expired."
                return 1
            }
            log "SUCCESS: Splunk restart completed and the management API is responding again."
            return 0
        fi
    fi

    if [[ "${restart_mode}" == "cli" || "${restart_mode}" == "auto" ]]; then
        if _platform_restart_capture "${execution_mode}" "$(hbs_shell_join test -x "${splunk_home%/}/bin/splunk")" >/dev/null 2>&1; then
            log "Restarting Splunk with the CLI path to complete ${operation}..."
            _platform_restart_cli "${execution_mode}" "${splunk_home}" false
            rc=$?
            if (( rc != 0 )); then
                log "ERROR: Splunk CLI restart failed."
                return "${rc}"
            fi
            wait_for_splunk_ready "${uri}" "${PLATFORM_RESTART_DEFAULT_TIMEOUT}" 5 || {
                log "ERROR: Splunk did not come back online before the restart timeout expired."
                return 1
            }
            log "SUCCESS: Splunk restart completed and the management API is responding again."
            return 0
        fi
    fi

    if _platform_restart_rest_fallback_allowed; then
        log "Restarting Splunk through explicit REST fallback to complete ${operation}..."
        restart_splunk_and_wait "${sk}" "${uri}" 90 "${PLATFORM_RESTART_DEFAULT_TIMEOUT}"
        rc=$?
        case "${rc}" in
            0)
                log "SUCCESS: REST restart completed and the management API is responding again."
                return 0
                ;;
            2)
                log "ERROR: Splunk did not stop responding after the REST restart request."
                return 1
                ;;
            3)
                log "ERROR: Splunk did not come back online before the REST restart timeout expired."
                return 1
                ;;
            *)
                log "ERROR: REST restart failed (HTTP ${SPLUNK_RESTART_HTTP_CODE:-unknown})."
                return 1
                ;;
        esac
    fi

    platform_restart_handoff "${operation}" "No safe local, SSH, or systemd restart path was detected, and REST fallback was not explicitly allowed."
    return 0
}
