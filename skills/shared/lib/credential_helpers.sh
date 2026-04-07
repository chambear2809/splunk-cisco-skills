#!/usr/bin/env bash
# Shared credential helper library for Splunk skill scripts.
# This is now a thin shim that sources the focused module files.
# All existing callers that `source credential_helpers.sh` continue to work.
#
# Contract:
#   - These libraries are designed to be sourced into scripts that use
#     'set -euo pipefail'. Functions that check state (rest_check_app,
#     rest_check_index, etc.) return non-zero on "not found" — callers
#     MUST use 'if', '||', or '&&' to handle the exit status.
#   - Functions that perform actions (rest_create_index, rest_set_conf, etc.)
#     return non-zero on failure and print an error message to stderr.

[[ -n "${_CRED_HELPERS_LOADED:-}" ]] && return 0
_CRED_HELPERS_LOADED=true

# shellcheck disable=SC2034  # consumed by credentials.sh after source
_RESOLVED_SPLUNK_PLATFORM=""

if [[ -z "${SCRIPT_DIR:-}" ]]; then
    # shellcheck disable=SC2034  # convenience variable for callers
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
source "${_LIB_DIR}/host_bootstrap_helpers.sh"
source "${_LIB_DIR}/deployment_helpers.sh"
source "${_LIB_DIR}/registry_helpers.sh"
source "${_LIB_DIR}/acs_helpers.sh"
source "${_LIB_DIR}/splunkbase_helpers.sh"
source "${_LIB_DIR}/configure_account_helpers.sh"
