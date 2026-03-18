#!/usr/bin/env bash
# Shared credential helper library for Splunk skill scripts.
# This is now a thin shim that sources the focused module files.
# All existing callers that `source credential_helpers.sh` continue to work.

[[ -n "${_CRED_HELPERS_LOADED:-}" ]] && return 0
_CRED_HELPERS_LOADED=true

_RESOLVED_SPLUNK_PLATFORM=""

if [[ -z "${SCRIPT_DIR:-}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
fi

_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PROJECT_ROOT="$(cd "${_LIB_DIR}/../../.." 2>/dev/null && pwd)"
if [[ -n "${SPLUNK_CREDENTIALS_FILE:-}" ]]; then
    _CRED_FILE="${SPLUNK_CREDENTIALS_FILE}"
elif [[ -f "${_PROJECT_ROOT}/credentials" ]]; then
    _CRED_FILE="${_PROJECT_ROOT}/credentials"
else
    _CRED_FILE="${HOME}/.splunk/credentials"
fi

source "${_LIB_DIR}/credentials.sh"
source "${_LIB_DIR}/rest_helpers.sh"
source "${_LIB_DIR}/acs_helpers.sh"
source "${_LIB_DIR}/splunkbase_helpers.sh"
source "${_LIB_DIR}/configure_account_helpers.sh"
