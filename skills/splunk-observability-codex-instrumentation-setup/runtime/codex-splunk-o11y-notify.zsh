#!/bin/zsh
# Fail-soft Codex notify fan-out.  Telemetry must never block the notifier that
# was already configured by Codex or an installed app.

umask 077

codex_home="${CODEX_HOME:-${HOME}/.codex}"
log_dir="${CODEX_SPLUNK_O11Y_LOG_DIR:-${codex_home}/log}"
log_file="${log_dir}/codex-splunk-o11y-notify.log"
span_script="${CODEX_SPLUNK_O11Y_SPAN_SCRIPT:-${codex_home}/bin/codex-splunk-o11y-notify-span.py}"
runtime_python="${CODEX_SPLUNK_O11Y_PYTHON:-${codex_home}/o11y-venv/bin/python}"
galileo_script="${CODEX_GALILEO_NOTIFY_SCRIPT:-${codex_home}/bin/codex-galileo-notify-turn.py}"
token_service="${CODEX_SPLUNK_TOKEN_KEYCHAIN_SERVICE:-codex-splunk-o11y-token}"
token_account="${CODEX_SPLUNK_TOKEN_KEYCHAIN_ACCOUNT:-${USER:-}}"

/bin/mkdir -p "${log_dir}" >/dev/null 2>&1 || true
/bin/chmod 700 "${log_dir}" >/dev/null 2>&1 || true
if [[ -f "${log_file}" && "$(/usr/bin/stat -f %z "${log_file}" 2>/dev/null || printf 0)" -gt 5242880 ]]; then
  /bin/mv -f "${log_file}" "${log_file}.1" >/dev/null 2>&1 || true
fi
/usr/bin/touch "${log_file}" >/dev/null 2>&1 || true
/bin/chmod 600 "${log_file}" >/dev/null 2>&1 || true

safe_log() {
  local message="${1:-unspecified}"
  /usr/bin/printf '%s %s\n' "$(/bin/date -u '+%Y-%m-%dT%H:%M:%SZ')" "${message}" >>"${log_file}" 2>/dev/null || true
}

previous_notifier=""
typeset -a previous_args
previous_args=()

# New explicit form supports fixed arguments without evaluating a shell string.
if [[ "${1:-}" == "--previous-notifier" ]]; then
  previous_notifier="${2:-}"
  shift 2 2>/dev/null || true
  while [[ "${1:-}" == "--previous-arg" ]]; do
    previous_args+=("${2:-}")
    shift 2 2>/dev/null || true
  done
# Backward compatibility with the already-deployed wrapper form.
elif [[ -n "${1:-}" && -x "${1}" ]]; then
  previous_notifier="${1}"
  shift
fi

event_name="${1:-turn-ended}"
payload="${2:-}"
if [[ "${event_name}" == \{* || "${event_name}" == \[* ]]; then
  payload="${event_name}"
  event_name="turn-ended"
fi

safe_log "invoked event=${event_name}"

# Invoke the existing notifier first and independently.  Its failure is logged,
# but never prevents telemetry and never changes Codex's notify result.
if [[ -n "${previous_notifier}" ]]; then
  if [[ -x "${previous_notifier}" ]]; then
    if [[ -n "${payload}" ]]; then
      "${previous_notifier}" "${previous_args[@]}" "${event_name}" "${payload}" 2>>"${log_file}"
    else
      "${previous_notifier}" "${previous_args[@]}" "${event_name}" 2>>"${log_file}"
    fi
    previous_rc=$?
    if [[ ${previous_rc} -ne 0 ]]; then
      safe_log "previous_notifier_failed status=${previous_rc} event=${event_name}"
    fi
  else
    safe_log "previous_notifier_skipped reason=not_executable event=${event_name}"
  fi
fi

run_galileo() {
  typeset -a command
  command=(python3 "${galileo_script}" --event "${event_name}")
  if [[ -n "${payload}" ]]; then
    command+=(--payload "${payload}")
  fi
  "${command[@]}" >/dev/null 2>>"${log_file}"
  local rc=$?
  if [[ ${rc} -ne 0 ]]; then
    safe_log "galileo_export_failed status=${rc} event=${event_name}"
  fi
}

if [[ -x "${galileo_script}" || -f "${galileo_script}" ]]; then
  if [[ "${CODEX_SPLUNK_O11Y_FOREGROUND:-0}" == "1" ]]; then
    run_galileo
  else
    run_galileo &!
  fi
fi

run_splunk_export() {
  local token="${SPLUNK_ACCESS_TOKEN:-}"
  if [[ -z "${token}" && -x /usr/bin/security && -n "${token_account}" ]]; then
    token="$(/usr/bin/security find-generic-password -a "${token_account}" -s "${token_service}" -w 2>/dev/null || true)"
  fi
  if [[ -z "${token}" ]]; then
    safe_log "splunk_token_not_found event=${event_name} continuing_for_tokenless_collector"
  fi

  local output
  if [[ -n "${payload}" ]]; then
    output="$(/usr/bin/printf '%s' "${payload}" | /usr/bin/env \
      -u CODEX_SPLUNK_TRACE_ENDPOINT \
      -u CODEX_SPLUNK_METRICS_ENDPOINT \
      SPLUNK_ACCESS_TOKEN="${token}" \
      "${runtime_python}" "${span_script}" --event "${event_name}" --payload-stdin 2>>"${log_file}")"
  else
    output="$(/usr/bin/env \
      -u CODEX_SPLUNK_TRACE_ENDPOINT \
      -u CODEX_SPLUNK_METRICS_ENDPOINT \
      SPLUNK_ACCESS_TOKEN="${token}" \
      "${runtime_python}" "${span_script}" --event "${event_name}" 2>>"${log_file}")"
  fi
  local rc=$?
  unset token
  if [[ ${rc} -ne 0 ]]; then
    safe_log "span_export_failed status=${rc} event=${event_name}"
    return 0
  fi

  local trace_id
  trace_id="$(/usr/bin/printf '%s\n' "${output}" | /usr/bin/sed -n 's/.*"trace_id"[[:space:]]*:[[:space:]]*"\([0-9A-Fa-f]\{32\}\)".*/\1/p' | /usr/bin/tail -1)"
  if [[ -n "${trace_id}" ]]; then
    safe_log "span_export_ok event=${event_name} trace_id=${trace_id}"
  else
    safe_log "span_export_noop event=${event_name}"
  fi
  return 0
}

# There is intentionally no package-manager fallback here.  Runtime creation is
# an explicit, one-time install action; a missing runtime is a health failure,
# not permission to resolve packages during every Codex turn.
if [[ ! -x "${runtime_python}" ]]; then
  safe_log "span_export_skipped reason=missing_prebuilt_runtime path=${runtime_python}"
elif [[ ! -f "${span_script}" ]]; then
  safe_log "span_export_skipped reason=missing_span_script path=${span_script}"
else
  if [[ "${CODEX_SPLUNK_O11Y_FOREGROUND:-0}" == "1" ]]; then
    run_splunk_export
  else
    run_splunk_export &!
  fi
fi

exit 0
