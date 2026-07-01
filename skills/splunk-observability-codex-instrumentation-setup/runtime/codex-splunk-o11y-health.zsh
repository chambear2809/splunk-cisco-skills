#!/bin/zsh
set -u

live=0
if [[ "${1:-}" == "--live" ]]; then
  live=1
elif [[ -n "${1:-}" && "${1:-}" != "--help" && "${1:-}" != "-h" ]]; then
  /usr/bin/printf 'Usage: %s [--live]\n' "${0:t}" >&2
  exit 2
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  /usr/bin/printf 'Usage: %s [--live]\n' "${0:t}"
  /usr/bin/printf 'Checks the pinned runtime and offline spans; --live also exports a synthetic turn.\n'
  exit 0
fi

codex_home="${CODEX_HOME:-${HOME}/.codex}"
bin_dir="${codex_home}/bin"
runtime_python="${CODEX_SPLUNK_O11Y_PYTHON:-${codex_home}/o11y-venv/bin/python}"
notify_script="${CODEX_SPLUNK_O11Y_NOTIFY_SCRIPT:-${bin_dir}/codex-splunk-o11y-notify.zsh}"
span_script="${CODEX_SPLUNK_O11Y_SPAN_SCRIPT:-${bin_dir}/codex-splunk-o11y-notify-span.py}"
config_file="${CODEX_SPLUNK_O11Y_RUNTIME_CONFIG:-${codex_home}/codex-splunk-o11y-runtime.json}"
lock_file="${codex_home}/o11y-runtime/requirements-notify.lock"
manifest_file="${codex_home}/o11y-runtime/manifest.json"
token_service="${CODEX_SPLUNK_TOKEN_KEYCHAIN_SERVICE:-codex-splunk-o11y-token}"
token_account="${CODEX_SPLUNK_TOKEN_KEYCHAIN_ACCOUNT:-${USER:-}}"
failures=0

pass() {
  /usr/bin/printf 'ok %s\n' "$*"
}

fail() {
  /usr/bin/printf 'FAIL %s\n' "$*" >&2
  failures=$((failures + 1))
}

[[ -x "${runtime_python}" ]] && pass "prebuilt Python runtime: ${runtime_python}" || fail "missing prebuilt runtime: ${runtime_python}"
[[ -f "${notify_script}" ]] && pass "notify wrapper present" || fail "missing notify wrapper: ${notify_script}"
[[ -f "${span_script}" ]] && pass "span emitter present" || fail "missing span emitter: ${span_script}"
[[ -f "${config_file}" ]] && pass "runtime config present" || fail "missing runtime config: ${config_file}"
[[ -f "${lock_file}" ]] && pass "requirements lock present" || fail "missing requirements lock: ${lock_file}"
[[ -f "${manifest_file}" ]] && pass "runtime manifest present" || fail "missing runtime manifest: ${manifest_file}"

if [[ -f "${notify_script}" ]]; then
  /bin/zsh -n "${notify_script}" 2>/dev/null && pass "notify wrapper syntax" || fail "notify wrapper syntax"
  if /usr/bin/grep -Eq '(^|[[:space:]])(uv|uvx|pip)([[:space:]]|$)' "${notify_script}"; then
    fail "notify wrapper contains a package-manager invocation"
  else
    pass "notify path contains no package-manager invocation"
  fi
fi

if [[ -x "${runtime_python}" && -f "${span_script}" ]]; then
  health_output="$(CODEX_HOME="${codex_home}" CODEX_SPLUNK_O11Y_RUNTIME_CONFIG="${config_file}" \
    "${runtime_python}" "${span_script}" --health 2>&1)"
  health_rc=$?
  if [[ ${health_rc} -eq 0 ]]; then
    pass "runtime dependency and resource contract"
    /usr/bin/printf '%s\n' "${health_output}"
  else
    fail "runtime dependency or resource contract: ${health_output}"
  fi

  smoke_output="$(CODEX_HOME="${codex_home}" CODEX_SPLUNK_O11Y_RUNTIME_CONFIG="${config_file}" \
    "${runtime_python}" "${span_script}" --offline-smoke 2>&1)"
  smoke_rc=$?
  if [[ ${smoke_rc} -eq 0 ]]; then
    pass "offline in-memory Codex GenAI smoke"
    /usr/bin/printf '%s\n' "${smoke_output}"
  else
    fail "offline in-memory Codex GenAI smoke: ${smoke_output}"
  fi
fi

if [[ -f "${manifest_file}" && -f "${lock_file}" ]]; then
  if python3 - "${manifest_file}" "${lock_file}" <<'PY'
import hashlib
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
actual = hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest()
assert manifest.get("requirements_sha256") == actual
assert manifest.get("package_installation_during_notify") is False
PY
  then
    pass "installed lock checksum and no-per-turn-install manifest"
  else
    fail "runtime manifest does not match installed lock"
  fi
fi

if [[ -f "${codex_home}/config.toml" ]]; then
  if /usr/bin/grep -Fq 'codex-splunk-o11y-notify.zsh' "${codex_home}/config.toml"; then
    pass "Codex config references the notify wrapper"
  else
    fail "Codex config does not reference codex-splunk-o11y-notify.zsh"
  fi
fi

if [[ ${live} -eq 1 && -x "${runtime_python}" && -f "${span_script}" ]]; then
  token="${SPLUNK_ACCESS_TOKEN:-}"
  if [[ -z "${token}" && -x /usr/bin/security && -n "${token_account}" ]]; then
    token="$(/usr/bin/security find-generic-password -a "${token_account}" -s "${token_service}" -w 2>/dev/null || true)"
  fi
  live_output="$(CODEX_HOME="${codex_home}" CODEX_SPLUNK_O11Y_RUNTIME_CONFIG="${config_file}" \
    SPLUNK_ACCESS_TOKEN="${token}" "${runtime_python}" "${span_script}" --live-smoke 2>&1)"
  live_rc=$?
  unset token
  if [[ ${live_rc} -eq 0 ]]; then
    pass "live OTLP export accepted"
    /usr/bin/printf '%s\n' "${live_output}"
  else
    fail "live OTLP export: ${live_output}"
  fi
fi

if [[ ${failures} -gt 0 ]]; then
  /usr/bin/printf 'Codex Splunk O11y health failed checks=%d\n' "${failures}" >&2
  exit 1
fi

pass "Codex Splunk O11y health complete"
exit 0
