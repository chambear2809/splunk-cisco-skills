#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../lib/credential_helpers.sh"

usage() {
    cat <<EOF
Batch-uninstall apps from Splunk Cloud.

Attempts ACS uninstall first. If apps persist on the search tier after ACS
reports success, falls back to direct REST DELETE on the search-tier endpoint.
Triggers a single ACS restart at the end.

Usage: $(basename "$0") [OPTIONS] <app_name> [app_name...]

Options:
  --no-restart         Skip the final ACS restart
  --help               Show this help

Example:
  $(basename "$0") Splunk_TA_Cisco_Intersight cisco_dc_networking_app_for_splunk Splunk_TA_cisco_meraki
EOF
    exit 0
}

APP_NAMES=()
RESTART=true

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-restart) RESTART=false; shift ;;
        --help) usage ;;
        --*) log "Unknown option: $1"; usage ;;
        *) APP_NAMES+=("$1"); shift ;;
    esac
done

if (( ${#APP_NAMES[@]} == 0 )); then
    log "ERROR: At least one app name is required."
    usage
fi

if ! is_splunk_cloud; then
    log "ERROR: This script is for Splunk Cloud only."
    exit 1
fi

refresh_verify_session() {
    SK_VERIFY=""

    if [[ -z "${SPLUNK_URI:-}" ]] || [[ "${SPLUNK_URI}" != *".splunkcloud.com"* ]]; then
        return 1
    fi

    load_splunk_credentials 2>/dev/null || return 1
    SK_VERIFY=$(get_session_key "${SPLUNK_URI}" 2>/dev/null || true)
    [[ -n "${SK_VERIFY}" ]]
}

acs_prepare_context || exit 1

log "=== Cloud Batch Uninstall ==="
log "Apps: ${APP_NAMES[*]}"
log ""

acs_failures=0
delete_failures=0
verification_available=false
final_failures=0

for app in "${APP_NAMES[@]}"; do
    log "Uninstalling '${app}' via ACS..."
    set +e
    if cloud_requires_local_scope; then
        output=$(acs_command apps uninstall "${app}" --scope local 2>&1)
    else
        output=$(acs_command apps uninstall "${app}" 2>&1)
    fi
    rc=$?
    set -e
    if (( rc == 0 )); then
        log "  ACS uninstall accepted for '${app}'."
    else
        log "  ACS uninstall returned rc=${rc} for '${app}' (may already be removed)."
        [[ -n "${output}" ]] && printf '%s\n' "${output}" >&2
        acs_failures=$((acs_failures + 1))
    fi
done

if ${RESTART}; then
    log ""
    log "Triggering ACS restart..."
    cloud_restart_if_required 900
fi

rest_fallback_needed=false
if refresh_verify_session; then
    verification_available=true
    for app in "${APP_NAMES[@]}"; do
        if rest_check_app "${SK_VERIFY}" "${SPLUNK_URI}" "${app}"; then
            log "WARNING: '${app}' still present on search tier after ACS uninstall."
            rest_fallback_needed=true
        fi
    done
else
    log "Search-tier verification skipped after ACS uninstall (no REST access)."
fi

if ${rest_fallback_needed}; then
    log ""
    log "Attempting direct REST DELETE fallback for remaining apps..."
    for app in "${APP_NAMES[@]}"; do
        if rest_check_app "${SK_VERIFY}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
            delete_code=$(splunk_curl "${SK_VERIFY}" \
                -X DELETE "${SPLUNK_URI}/services/apps/local/${app}?output_mode=json" \
                -o /dev/null -w '%{http_code}' 2>/dev/null || echo "000")
            case "${delete_code}" in
                200) log "  REST DELETE succeeded for '${app}'." ;;
                404) log "  '${app}' already absent (HTTP 404)." ;;
                *)
                    log "  WARNING: REST DELETE returned HTTP ${delete_code} for '${app}'."
                    delete_failures=$((delete_failures + 1))
                    ;;
            esac
        fi
    done

    if ${RESTART}; then
        log ""
        log "Triggering post-fallback ACS restart..."
        cloud_restart_if_required 900
    fi
fi

log ""
log "=== Final verification ==="
if refresh_verify_session; then
    verification_available=true
    for app in "${APP_NAMES[@]}"; do
        if rest_check_app "${SK_VERIFY}" "${SPLUNK_URI}" "${app}" 2>/dev/null; then
            log "  ${app} = STILL PRESENT (may need per-member SHC cleanup)"
            final_failures=$((final_failures + 1))
        else
            log "  ${app} = removed"
        fi
    done
else
    log "  Search-tier verification skipped (no REST access)."
fi

log ""
log "=== Batch uninstall complete ==="

if (( final_failures > 0 )); then
    exit 1
fi

if [[ "${verification_available}" != "true" ]] && (( acs_failures > 0 || delete_failures > 0 )); then
    exit 1
fi
