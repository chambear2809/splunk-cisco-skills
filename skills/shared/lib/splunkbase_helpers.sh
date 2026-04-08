#!/usr/bin/env bash
# Splunkbase authentication, release resolution, and download helpers.
# Sourced by credential_helpers.sh; not intended for direct use.
#
# See credential_helpers.sh for the sourcing contract.

[[ -n "${_SPLUNKBASE_HELPERS_LOADED:-}" ]] && return 0
_SPLUNKBASE_HELPERS_LOADED=true

get_splunkbase_session() {
    local response_file cookie_file http_code response session

    _set_splunkbase_curl_tls_args || return 1
    response_file="$(mktemp)"
    chmod 600 "${response_file}"
    cookie_file="$(mktemp)"
    chmod 600 "${cookie_file}"

    if [[ -n "${SB_COOKIE_JAR:-}" && -f "${SB_COOKIE_JAR}" ]]; then
        rm -f "${SB_COOKIE_JAR}"
    fi

    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_splunkbase_curl_tls_args.
    http_code=$(curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
        -X POST "https://splunkbase.splunk.com/api/account:login" \
        -K <(
            printf 'form-string = "username=%s"\n' "$(_curl_config_escape "${SB_USER}")"
            printf 'form-string = "password=%s"\n' "$(_curl_config_escape "${SB_PASS}")"
        ) \
        -c "${cookie_file}" \
        -o "${response_file}" \
        -w '%{http_code}' 2>/dev/null || echo "000")

    response=$(<"${response_file}")
    rm -f "${response_file}"

    session=$(printf '%s' "${response}" | sed -n 's:.*<id>\([^<]*\)</id>.*:\1:p')

    if [[ "${http_code}" != "200" || -z "${session}" ]]; then
        rm -f "${cookie_file}"
        echo "ERROR: Failed to authenticate to Splunkbase session API." >&2
        if [[ -n "${response}" ]]; then
            echo "Response: $(printf '%s' "${response}" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')" >&2
        fi
        return 1
    fi

    SB_SESSION_ID="${session}"
    SB_COOKIE_JAR="${cookie_file}"
}

get_splunkbase_release_metadata() {
    local app_id="$1"
    local app_version="$2"
    local metadata

    _set_splunkbase_curl_tls_args || return 1

    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_splunkbase_curl_tls_args.
    metadata=$(curl -s ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} "https://splunkbase.splunk.com/api/v1/app/${app_id}/release/" 2>/dev/null \
        | python3 -c "
import json
import sys

requested_version = sys.argv[1]
app_id = sys.argv[2]

try:
    releases = json.load(sys.stdin)
except Exception:
    sys.exit(1)

if isinstance(releases, dict):
    releases = releases.get('releases', [])

if not isinstance(releases, list) or not releases:
    sys.exit(1)

release = None
if requested_version:
    for candidate in releases:
        version = candidate.get('name') or candidate.get('title') or candidate.get('version') or ''
        if version == requested_version:
            release = candidate
            break
else:
    release = releases[0]

if release is None:
    sys.exit(1)

version = release.get('name') or release.get('title') or release.get('version') or ''
filename = release.get('filename') or ''
if not version or not filename:
    sys.exit(1)

print(f'{version}\\t{filename}\\thttps://splunkbase.splunk.com/app/{app_id}/release/{version}/download/')
" "${app_version}" "${app_id}" 2>/dev/null) || {
        echo "ERROR: Failed to resolve Splunkbase release metadata for app ${app_id}${app_version:+ version ${app_version}}." >&2
        return 1
    }

    # shellcheck disable=SC2034  # SB_DOWNLOAD_VERSION, SB_DOWNLOAD_FILENAME read by callers
    IFS=$'\t' read -r SB_DOWNLOAD_VERSION SB_DOWNLOAD_FILENAME SB_DOWNLOAD_SOURCE_URL <<< "${metadata}"

    if [[ -z "${SB_DOWNLOAD_VERSION:-}" || -z "${SB_DOWNLOAD_FILENAME:-}" || -z "${SB_DOWNLOAD_SOURCE_URL:-}" ]]; then
        echo "ERROR: Splunkbase release metadata was incomplete for app ${app_id}${app_version:+ version ${app_version}}." >&2
        return 1
    fi
}

download_splunkbase_release() {
    local app_id="$1"
    local app_version="$2"
    local output_path="$3"
    local tmp_file meta http_code effective_url

    if [[ -z "${SB_SESSION_ID:-}" || -z "${SB_COOKIE_JAR:-}" || ! -f "${SB_COOKIE_JAR:-}" ]]; then
        get_splunkbase_session || return 1
    fi

    get_splunkbase_release_metadata "${app_id}" "${app_version}" || return 1

    tmp_file="$(mktemp)"
    # shellcheck disable=SC2034  # read by callers after download_splunkbase_release returns
    SB_DOWNLOAD_EFFECTIVE_URL=""

    mkdir -p "$(dirname "${output_path}")"
    if ! _set_splunkbase_curl_tls_args; then
        rm -f "${tmp_file}"
        return 1
    fi

    # shellcheck disable=SC2154  # _tls_verify_args is populated by _set_splunkbase_curl_tls_args.
    meta=$(curl -sL ${_tls_verify_args[@]+"${_tls_verify_args[@]}"} \
        -b "${SB_COOKIE_JAR}" \
        -K <(printf 'header = "X-Auth-Token: %s"\n' "$(_curl_config_escape "${SB_SESSION_ID}")") \
        -o "${tmp_file}" \
        -w $'%{http_code}\t%{url_effective}' \
        "${SB_DOWNLOAD_SOURCE_URL}" 2>/dev/null || printf '000\t')

    http_code="${meta%%$'\t'*}"
    effective_url=""
    if [[ "${meta}" == *$'\t'* ]]; then
        effective_url="${meta#*$'\t'}"
    fi

    if [[ "${http_code}" == "200" ]] && [[ -s "${tmp_file}" ]] && _is_splunk_package "${tmp_file}"; then
        # shellcheck disable=SC2034  # read by callers after download_splunkbase_release returns
        SB_DOWNLOAD_EFFECTIVE_URL="${effective_url}"
        mv -f "${tmp_file}" "${output_path}"
        return 0
    fi

    rm -f "${tmp_file}"
    echo "ERROR: Failed to download Splunkbase app ${app_id}${app_version:+ version ${app_version}}." >&2
    return 1
}

_read_cookie_jar_value() {
    python3 - "$1" "$2" <<'PY'
import sys

cookie_file = sys.argv[1]
target_name = sys.argv[2]

try:
    with open(cookie_file, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = raw_line.rstrip("\n").split("\t")
            if len(parts) < 7:
                continue
            name = parts[5]
            value = parts[6]
            if name == target_name:
                print(value, end="")
                break
except FileNotFoundError:
    pass
PY
}

get_splunkbase_cookies() {
    if [[ -z "${SB_SESSION_ID:-}" || -z "${SB_COOKIE_JAR:-}" || ! -f "${SB_COOKIE_JAR:-}" ]]; then
        get_splunkbase_session || return 1
    fi

    SB_SID=$(_read_cookie_jar_value "${SB_COOKIE_JAR}" "sessionid")
    SB_SSOID=$(_read_cookie_jar_value "${SB_COOKIE_JAR}" "csrf_splunkbase_token")

    if [[ -z "${SB_SID}" ]]; then
        echo "ERROR: Failed to read sessionid cookie from Splunkbase cookie jar." >&2
        return 1
    fi
}

get_splunkbase_token() {
    get_splunkbase_cookies || return 1
    local cookie_str=""
    [[ -n "${SB_SID:-}" ]] && cookie_str="sessionid=${SB_SID}"
    [[ -n "${SB_SSOID:-}" ]] && cookie_str="${cookie_str:+${cookie_str}; }csrf_splunkbase_token=${SB_SSOID}"
    printf '%s' "${cookie_str}"
}
