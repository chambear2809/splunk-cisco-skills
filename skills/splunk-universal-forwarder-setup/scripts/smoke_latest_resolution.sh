#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../shared/lib/credential_helpers.sh"
source "${SCRIPT_DIR}/../../shared/lib/host_bootstrap_helpers.sh"

PROJECT_PKG_DIR="${SCRIPT_DIR}/../../../splunk-ta"

TARGET_OS="linux"
TARGET_ARCH="auto"
PACKAGE_TYPE="auto"
ALLOW_STALE_LATEST=false

usage() {
    local exit_code="${1:-0}"
    cat <<EOF
Splunk Universal Forwarder Latest Resolution Smoke Test

Usage: $(basename "$0") [OPTIONS]

Options:
  --target-os linux|macos|windows|freebsd|solaris|aix|all
  --target-arch auto|amd64|x64|x86|arm64|ppc64le|s390x|intel|universal2|freebsd13-amd64|freebsd14-amd64|sparc|powerpc
  --package-type auto|tgz|rpm|deb|msi|dmg|pkg|txz|p5p|tar-z|all
  --allow-stale-latest
  --help

Behavior:
  Resolves latest official Universal Forwarder metadata and verifies that
  Splunk's official SHA512 checksum is discoverable. It does not download the
  package payload or write cache metadata.
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

default_arch_for_os() {
    case "$1" in
        linux) printf '%s' "amd64" ;;
        macos) printf '%s' "universal2" ;;
        windows) printf '%s' "x64" ;;
        freebsd) printf '%s' "freebsd14-amd64" ;;
        solaris) printf '%s' "amd64" ;;
        aix) printf '%s' "powerpc" ;;
    esac
}

default_package_types_for_os() {
    case "$1" in
        linux) printf '%s\n' tgz deb rpm ;;
        macos) printf '%s\n' tgz dmg ;;
        windows) printf '%s\n' msi ;;
        freebsd) printf '%s\n' tgz txz ;;
        solaris) printf '%s\n' tar-z p5p ;;
        aix) printf '%s\n' tgz ;;
    esac
}

resolve_metadata_or_fallback() {
    local target_os="$1"
    local target_arch="$2"
    local package_type="$3"
    local metadata rc=0

    if metadata="$(hbs_resolve_latest_universal_forwarder_download_metadata "${target_os}" "${target_arch}" "${package_type}")"; then
        printf '%s\t%s' "live" "${metadata}"
        return 0
    fi
    if [[ "${ALLOW_STALE_LATEST}" != "true" ]]; then
        log "ERROR: Failed to resolve latest Universal Forwarder ${target_os}/${target_arch}/${package_type}. Re-run with --allow-stale-latest to test cached metadata." >&2
        return 1
    fi
    log "WARN: Live latest resolution failed; attempting stale metadata fallback for ${target_os}/${target_arch}/${package_type}." >&2
    if metadata="$(hbs_read_latest_universal_forwarder_metadata_cache "${PROJECT_PKG_DIR}" "${target_os}" "${target_arch}" "${package_type}")"; then
        printf '%s\t%s' "cached" "${metadata}"
        return 0
    fi
    rc=$?
    if [[ "${rc}" -eq 2 ]]; then
        log "ERROR: Cached latest metadata for ${target_os}/${target_arch}/${package_type} is older than 30 days." >&2
    else
        log "ERROR: No usable cached latest metadata exists for ${target_os}/${target_arch}/${package_type}." >&2
    fi
    return 1
}

smoke_one() {
    local target_os="$1"
    local target_arch="$2"
    local package_type="$3"
    local resolution source_kind metadata version package_url sha512_url sha512_value apply_state

    resolution="$(resolve_metadata_or_fallback "${target_os}" "${target_arch}" "${package_type}")" || return 1
    IFS=$'\t' read -r source_kind metadata <<< "${resolution}"
    version="$(hbs_latest_enterprise_metadata_field "${metadata}" "version")"
    package_url="$(hbs_latest_enterprise_metadata_field "${metadata}" "package_url")"
    sha512_url="$(hbs_latest_enterprise_metadata_field "${metadata}" "sha512_url")"
    apply_state="$(hbs_latest_enterprise_metadata_field "${metadata}" "v1_apply" 2>/dev/null || true)"
    sha512_value="$(hbs_latest_enterprise_metadata_field "${metadata}" "sha512" 2>/dev/null || true)"
    if [[ -z "${sha512_value}" ]]; then
        sha512_value="$(hbs_fetch_expected_sha512 "${sha512_url}")"
    fi
    log "Smoke check passed for ${target_os}/${target_arch}/${package_type} (${source_kind}, ${apply_state:-metadata-only})"
    printf '  version: %s\n' "${version}"
    printf '  package: %s\n' "${package_url}"
    printf '  sha512:  %s\n' "${sha512_url}"
    printf '  digest:  %s\n' "${sha512_value}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-os) require_arg "$1" $# || exit 1; TARGET_OS="$2"; shift 2 ;;
        --target-arch) require_arg "$1" $# || exit 1; TARGET_ARCH="$2"; shift 2 ;;
        --package-type) require_arg "$1" $# || exit 1; PACKAGE_TYPE="$(hbs_normalize_universal_forwarder_package_type "$2")"; shift 2 ;;
        --allow-stale-latest) ALLOW_STALE_LATEST=true; shift ;;
        --help) usage 0 ;;
        *) echo "Unknown option: $1" >&2; usage 1 ;;
    esac
done

validate_choice "${TARGET_OS}" linux macos windows freebsd solaris aix all
validate_choice "${PACKAGE_TYPE}" auto tgz rpm deb msi dmg pkg txz p5p tar-z all

OS_LIST=()
if [[ "${TARGET_OS}" == "all" ]]; then
    OS_LIST=(linux macos windows freebsd solaris aix)
else
    OS_LIST=("${TARGET_OS}")
fi

for os_name in "${OS_LIST[@]}"; do
    arch="${TARGET_ARCH}"
    [[ "${arch}" == "auto" ]] && arch="$(default_arch_for_os "${os_name}")"
    PACKAGE_TYPES=()
    if [[ "${PACKAGE_TYPE}" == "all" || "${PACKAGE_TYPE}" == "auto" ]]; then
        while IFS= read -r item; do
            PACKAGE_TYPES+=("${item}")
        done < <(default_package_types_for_os "${os_name}")
    else
        PACKAGE_TYPES=("${PACKAGE_TYPE}")
    fi
    for item in "${PACKAGE_TYPES[@]}"; do
        smoke_one "${os_name}" "${arch}" "${item}"
    done
done
