#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

PROJECT_PKG_DIR="${SCRIPT_DIR}/../../../splunk-ta"

PACKAGE_TYPE="auto"
EXECUTION_MODE="local"
ALLOW_STALE_LATEST=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Enterprise Latest Resolution Smoke Test

Usage: $(basename "$0") [OPTIONS]

Options:
  --package-type auto|tgz|rpm|deb|all
  --execution local|ssh
  --allow-stale-latest
  --help

Behavior:
  Resolves the latest official Splunk Enterprise package metadata from
  splunk.com and verifies that the official SHA512 checksum is discoverable.
  It does not download the package payload or write cache metadata.

Examples:
  $(basename "$0") --package-type auto
  $(basename "$0") --package-type all
  $(basename "$0") --package-type auto --execution ssh
EOF
    exit "${exit_code}"
}

validate_choice() {
    local value="$1"; shift
    local allowed
    for allowed in "$@"; do
        [[ "${value}" == "${allowed}" ]] && return 0
    done
    log "ERROR: Invalid value '${value}'. Expected one of: $*"
    exit 1
}

resolve_requested_package_types() {
    local preferred_type

    if [[ "${PACKAGE_TYPE}" == "all" ]]; then
        printf '%s\n' tgz deb rpm
        return 0
    fi

    if [[ "${PACKAGE_TYPE}" == "auto" ]]; then
        preferred_type="$(hbs_preferred_latest_package_type "${EXECUTION_MODE}")"
        if [[ "${preferred_type}" == "tgz" ]]; then
            log "INFO: Could not map the target OS family to deb or rpm; defaulting smoke resolution to tgz." >&2
        else
            log "INFO: Auto-selected ${preferred_type} for smoke resolution from the target OS family." >&2
        fi
        printf '%s\n' "${preferred_type}"
        return 0
    fi

    printf '%s\n' "${PACKAGE_TYPE}"
}

resolve_metadata_or_fallback() {
    local package_type="$1"
    local metadata=""
    local rc=0

    if metadata="$(hbs_resolve_latest_enterprise_download_metadata "${package_type}")"; then
        printf '%s\t%s' "live" "${metadata}"
        return 0
    fi

    if [[ "${ALLOW_STALE_LATEST}" != "true" ]]; then
        log "ERROR: Failed to resolve the latest official Splunk Enterprise ${package_type} package. Re-run with --allow-stale-latest if you want to test cached metadata." >&2
        return 1
    fi

    log "WARN: Live latest resolution failed; attempting stale metadata fallback for ${package_type}." >&2
    if metadata="$(hbs_read_latest_enterprise_metadata_cache "${PROJECT_PKG_DIR}" "${package_type}")"; then
        printf '%s\t%s' "cached" "${metadata}"
        return 0
    fi

    rc=$?
    if [[ "${rc}" -eq 2 ]]; then
        log "ERROR: Cached latest metadata for ${package_type} is older than 30 days." >&2
    else
        log "ERROR: No usable cached latest metadata exists for ${package_type}." >&2
    fi
    return 1
}

smoke_package_type() {
    local package_type="$1"
    local resolution source_kind metadata version package_url sha512_url sha512_value

    resolution="$(resolve_metadata_or_fallback "${package_type}")" || return 1
    IFS=$'\t' read -r source_kind metadata <<< "${resolution}"

    version="$(hbs_latest_enterprise_metadata_field "${metadata}" "version")"
    package_url="$(hbs_latest_enterprise_metadata_field "${metadata}" "package_url")"
    sha512_url="$(hbs_latest_enterprise_metadata_field "${metadata}" "sha512_url")"
    sha512_value="$(hbs_latest_enterprise_metadata_field "${metadata}" "sha512" 2>/dev/null || true)"
    if [[ -z "${sha512_value}" ]]; then
        sha512_value="$(hbs_fetch_expected_sha512 "${sha512_url}")"
    fi

    log "Smoke check passed for ${package_type} (${source_kind})"
    printf '  version: %s\n' "${version}"
    printf '  package: %s\n' "${package_url}"
    printf '  sha512:  %s\n' "${sha512_url}"
    printf '  digest:  %s\n' "${sha512_value}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --package-type) require_arg "$1" $# || exit 1; PACKAGE_TYPE="$2"; shift 2 ;;
        --execution) require_arg "$1" $# || exit 1; EXECUTION_MODE="$2"; shift 2 ;;
        --allow-stale-latest) ALLOW_STALE_LATEST=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice "${PACKAGE_TYPE}" auto tgz rpm deb all
validate_choice "${EXECUTION_MODE}" local ssh

if [[ "${EXECUTION_MODE}" == "ssh" && "${PACKAGE_TYPE}" == "auto" ]]; then
    load_splunk_ssh_credentials
fi

REQUESTED_PACKAGE_TYPES=()
while IFS= read -r package_type; do
    REQUESTED_PACKAGE_TYPES+=("${package_type}")
done < <(resolve_requested_package_types)

for package_type in "${REQUESTED_PACKAGE_TYPES[@]}"; do
    smoke_package_type "${package_type}"
done
