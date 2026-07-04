#!/usr/bin/env bats

setup() {
    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    LIB_DIR="${PROJECT_ROOT}/skills/shared/lib"
    TEST_TEMP_FILES=()
}

teardown() {
    for path in "${TEST_TEMP_FILES[@]+"${TEST_TEMP_FILES[@]}"}"; do
        rm -rf "${path}"
    done
}

@test "credential curl policy rejects URL redirect config protocol TLS and owned-header overrides" {
    source "${LIB_DIR}/credential_curl_helpers.sh"
    url="https://api.example.invalid/v1/status"

    run credential_curl_validate_request_args false --url "${url}" "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"caller URL"* ]]

    run credential_curl_validate_request_args false --location "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"redirect controls"* ]]

    run credential_curl_validate_request_args false -sK/tmp/hostile "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"config and transfer-boundary"* ]]

    run credential_curl_validate_request_args false --proto '=http,https' "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns protocol"* ]]

    run credential_curl_validate_request_args false --insecure "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns TLS"* ]]

    run credential_curl_validate_request_args false -H 'Authorization: stolen' "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns authentication"* ]]

    run credential_curl_validate_request_args false -H 'Authorization : stolen' "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"malformed caller header names"* ]]

    run credential_curl_validate_request_args false -H 'X-Cisco-Meraki-API-Key: stolen' "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns authentication"* ]]

    run credential_curl_validate_request_args false -H 'Content-Length: 1' "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"framing headers"* ]]

    run credential_curl_validate_request_args false -H @/tmp/headers "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"caller headers"* ]]

    run credential_curl_validate_request_args false --data-binary @/etc/passwd "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"file-backed body"* ]]

    run credential_curl_validate_request_args false --data-urlencode secret@/etc/passwd "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"file-backed URL-encoded"* ]]

    run credential_curl_validate_request_args false -F 'field=value;headers=@/etc/passwd' "${url}"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"form arguments"* ]]

    run credential_curl_validate_request_args false --data-binary @- "${url}"
    [ "${status}" -eq 0 ]
}

@test "descriptor-bound body streaming rejects symlinks and hardlinks" {
    source "${LIB_DIR}/credential_curl_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    payload="${mock_dir}/payload.json"
    printf '%s\n' '{"safe":true}' > "${payload}"

    run credential_curl_stream_file "${payload}"
    [ "${status}" -eq 0 ]
    [ "${output}" = '{"safe":true}' ]

    ln -s "${payload}" "${mock_dir}/payload-link"
    run credential_curl_stream_file "${mock_dir}/payload-link"
    [ "${status}" -ne 0 ]

    ln "${payload}" "${mock_dir}/payload-hardlink"
    run credential_curl_stream_file "${payload}"
    [ "${status}" -ne 0 ]
}

@test "credential curl auth config rejects symlinks hardlinks and escaped newlines" {
    source "${LIB_DIR}/credential_curl_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    victim="${mock_dir}/victim"
    printf '%s\n' 'header = "Authorization: Bearer secret"' > "${victim}"
    chmod 600 "${victim}"

    ln -s "${victim}" "${mock_dir}/symlink"
    run credential_curl_validate_auth_config "${mock_dir}/symlink"
    [ "${status}" -ne 0 ]

    ln "${victim}" "${mock_dir}/hardlink"
    run credential_curl_validate_auth_config "${mock_dir}/hardlink"
    [ "${status}" -ne 0 ]

    escaped="${mock_dir}/escaped"
    printf '%s\n' 'header = "Authorization: Bearer secret\nHost: capture.invalid"' > "${escaped}"
    chmod 600 "${escaped}"
    run credential_curl_validate_auth_config "${escaped}"
    [ "${status}" -ne 0 ]

    unsafe_header="${mock_dir}/unsafe-header"
    printf '%s\n' 'header = "Host: capture.invalid"' > "${unsafe_header}"
    chmod 600 "${unsafe_header}"
    run credential_curl_validate_auth_config "${unsafe_header}"
    [ "${status}" -ne 0 ]

    header_file="${mock_dir}/header-file"
    printf '%s\n' 'header = "@/tmp/caller-controlled-headers"' > "${header_file}"
    chmod 600 "${header_file}"
    run credential_curl_validate_auth_config "${header_file}"
    [ "${status}" -ne 0 ]
}

@test "credential curl writer binds private secret and output descriptors" {
    source "${LIB_DIR}/credential_curl_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    secret_file="${mock_dir}/token"
    output_file="${mock_dir}/auth"
    printf '%s\n' 'safe-token' > "${secret_file}"
    : > "${output_file}"
    chmod 600 "${secret_file}" "${output_file}"

    run credential_curl_write_header_config \
        "${secret_file}" "X-Cisco-Meraki-API-Key" "${output_file}"
    [ "${status}" -eq 0 ]
    [ "$(<"${output_file}")" = 'header = "X-Cisco-Meraki-API-Key: safe-token"' ]

    secret_link="${mock_dir}/token-link"
    ln -s "${secret_file}" "${secret_link}"
    run credential_curl_write_header_config \
        "${secret_link}" "Authorization" "${output_file}"
    [ "${status}" -ne 0 ]

    secret_hardlink="${mock_dir}/token-hardlink"
    ln "${secret_file}" "${secret_hardlink}"
    run credential_curl_write_header_config \
        "${secret_file}" "Authorization" "${output_file}"
    [ "${status}" -ne 0 ]
    rm -f "${secret_hardlink}"

    printf '%s\n%s\n' 'line-one' 'line-two' > "${secret_file}"
    run credential_curl_write_header_config \
        "${secret_file}" "Authorization" "${output_file}"
    [ "${status}" -ne 0 ]

    printf '%s\n' 'safe-token' > "${secret_file}"
    run credential_curl_write_header_config \
        "${secret_file}" "Authorization" "${output_file}" "Bearer "
    [ "${status}" -eq 0 ]
    [ "$(<"${output_file}")" = 'header = "Authorization: Bearer safe-token"' ]

    printf '%s\n' 'p@ss"with\slashes' > "${secret_file}"
    run credential_curl_write_user_config \
        "${secret_file}" "soar_local_admin" "${output_file}"
    [ "${status}" -eq 0 ]
    [ "$(<"${output_file}")" = 'user = "soar_local_admin:p@ss\"with\\slashes"' ]
    printf '%s\n' 'safe-token' > "${secret_file}"

    output_link="${mock_dir}/auth-link"
    ln -s "${output_file}" "${output_link}"
    run credential_curl_write_header_config \
        "${secret_file}" "Authorization" "${output_link}"
    [ "${status}" -ne 0 ]

    output_hardlink="${mock_dir}/auth-hardlink"
    ln "${output_file}" "${output_hardlink}"
    before="$(<"${output_file}")"
    run credential_curl_write_header_config \
        "${secret_file}" "Authorization" "${output_file}"
    [ "${status}" -ne 0 ]
    [ "$(<"${output_hardlink}")" = "${before}" ]
}

@test "Edge Processor wrapper rejects hostile args and pins curl transport" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    token_file="${mock_dir}/token"
    args_log="${mock_dir}/args"
    marker="${mock_dir}/ran"
    printf '%s' 'edge-secret' > "${token_file}"
    chmod 600 "${token_file}"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
output=""
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-o" ]]; then output="$2"; shift 2; continue; fi
    shift
done
printf '%s' '{"ok":true}' > "${output}"
printf '%s' '200'
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}" CURL_ARGS_LOG="${args_log}"
    export PATH="${mock_dir}:${PATH}"

    log() { printf '%s\n' "$*" >&2; }
    export -f log
    export _CRED_HELPERS_LOADED=true
    source "${LIB_DIR}/edge_processor_helpers.sh"

    run ep_api_call "https://edge.example.invalid" "${token_file}" GET "/status" \
        --url "http://capture.invalid"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    result="$(ep_api_call "https://edge.example.invalid" "${token_file}" GET "/status")"
    [ "${result}" = '{"ok":true}' ]
    [ "$(head -n 1 "${args_log}")" = "-q" ]
    grep -q -- "--proto" "${args_log}"
    grep -q -- "=https" "${args_log}"
    grep -q -- "--max-redirs" "${args_log}"
    grep -q -- "--globoff" "${args_log}"
}

@test "AppDynamics wrapper validates auth config and rejects caller transport overrides" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    auth_config="${mock_dir}/auth"
    hostile_config="${mock_dir}/hostile"
    args_log="${mock_dir}/args"
    marker="${mock_dir}/ran"
    printf '%s\n' 'header = "Authorization: Bearer appd-secret"' > "${auth_config}"
    printf '%s\n' 'url = "http://capture.invalid"' > "${hostile_config}"
    chmod 600 "${auth_config}" "${hostile_config}"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
printf '%s' '{}'
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}" CURL_ARGS_LOG="${args_log}"
    export PATH="${mock_dir}:${PATH}"
    source "${LIB_DIR}/appdynamics_helpers.sh"

    run appd_curl -fsS -K "${hostile_config}" "https://controller.example.invalid/status"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    run appd_curl -fsS -K "${auth_config}" --location \
        "https://controller.example.invalid/status"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    result="$(appd_curl -fsS -K "${auth_config}" "https://controller.example.invalid/status")"
    [ "${result}" = '{}' ]
    [ "$(head -n 1 "${args_log}")" = "-q" ]
    grep -q -- "--proto" "${args_log}"
    grep -q -- "--max-redirs" "${args_log}"
    grep -q -- "--globoff" "${args_log}"
}

@test "AppDynamics Events header writer rejects linked inputs and destinations" {
    source "${LIB_DIR}/appdynamics_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    key="${mock_dir}/events-key"
    headers="${mock_dir}/headers"
    printf '%s\n' 'events-secret' > "${key}"
    : > "${headers}"
    chmod 600 "${key}" "${headers}"

    run appd_events_api_headers_file account "${key}" "${headers}"
    [ "${status}" -eq 0 ]
    grep -q '^header = "X-Events-API-Key: events-secret"$' "${headers}"
    run credential_curl_validate_auth_config "${headers}"
    [ "${status}" -eq 0 ]

    ln -s "${key}" "${mock_dir}/key-link"
    run appd_events_api_headers_file account "${mock_dir}/key-link" "${headers}"
    [ "${status}" -ne 0 ]

    ln "${key}" "${mock_dir}/key-hardlink"
    run appd_events_api_headers_file account "${key}" "${headers}"
    [ "${status}" -ne 0 ]
    rm -f "${mock_dir}/key-hardlink"

    victim="${mock_dir}/victim"
    printf '%s\n' 'do-not-touch' > "${victim}"
    chmod 600 "${victim}"
    rm -f "${headers}"
    ln -s "${victim}" "${headers}"
    run appd_events_api_headers_file account "${key}" "${headers}"
    [ "${status}" -ne 0 ]
    [ "$(<"${victim}")" = "do-not-touch" ]

    rm -f "${headers}"
    ln "${victim}" "${headers}"
    run appd_events_api_headers_file account "${key}" "${headers}"
    [ "${status}" -ne 0 ]
    [ "$(<"${victim}")" = "do-not-touch" ]

    real_parent="${mock_dir}/real-parent"
    mkdir "${real_parent}"
    ln -s "${real_parent}" "${mock_dir}/linked-parent"
    run appd_events_api_headers_file account "${key}" "${mock_dir}/linked-parent/headers"
    [ "${status}" -ne 0 ]
    [ ! -e "${real_parent}/headers" ]
}

@test "Edge and SOAR reject unsafe origins paths methods and CA newline injection" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    token="${mock_dir}/token"
    password="${mock_dir}/password"
    printf '%s' 'edge-token' > "${token}"
    printf '%s' 'admin-password' > "${password}"
    chmod 600 "${token}" "${password}"
    marker="${mock_dir}/curl-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
exit 0
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}" PATH="${mock_dir}:${PATH}"
    log() { printf '%s\n' "$*" >&2; }
    export -f log
    export _CRED_HELPERS_LOADED=true
    source "${LIB_DIR}/edge_processor_helpers.sh"

    run ep_api_call "https://edge.invalid/base" "${token}" GET /status
    [ "${status}" -ne 0 ]
    run ep_api_call "https://edge.invalid" "${token}" TRACE /status
    [ "${status}" -ne 0 ]
    run ep_instance_status "https://edge.invalid" "${token}" '../escape'
    [ "${status}" -ne 0 ]
    export EP_API_CA_CERT=$'bad\n--insecure'
    run ep_api_call "https://edge.invalid" "${token}" GET /status
    [ "${status}" -ne 0 ]
    unset EP_API_CA_CERT
    [ ! -e "${marker}" ]

    unset _SOAR_HELPERS_LOADED
    source "${LIB_DIR}/soar_helpers.sh"
    run soar_rest_call "https://soar.invalid/base" "${token}" GET /rest/version
    [ "${status}" -ne 0 ]
    run soar_rest_call "https://soar.invalid" "${token}" TRACE /rest/version
    [ "${status}" -ne 0 ]
    run soar_rest_call "https://soar.invalid" "${token}" GET '//capture.invalid/path'
    [ "${status}" -ne 0 ]
    mkdir "${mock_dir}/tmp"
    export TMPDIR="${mock_dir}/tmp"
    export SOAR_API_CA_CERT=$'bad\n--insecure'
    run _soar_admin_basic_auth_call "https://soar.invalid" "${password}" GET /rest/version
    [ "${status}" -ne 0 ]
    unset SOAR_API_CA_CERT
    [ -z "$(find "${mock_dir}/tmp" -mindepth 1 -maxdepth 1 -print -quit)" ]
    [ ! -e "${marker}" ]
}

@test "Splunkbase authenticated login disables curlrc redirects and owns transport" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    args_log="${mock_dir}/args"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
response=""
cookie=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) response="$2"; shift 2 ;;
        -c) cookie="$2"; shift 2 ;;
        *) shift ;;
    esac
done
printf '%s' '<response><id>session-id</id></response>' > "${response}"
printf '%s\n' '# cookie jar' > "${cookie}"
printf '%s' '200'
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_ARGS_LOG="${args_log}" PATH="${mock_dir}:${PATH}"
    export SB_USER="user" SB_PASS="pass"
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/splunkbase_helpers.sh"

    get_splunkbase_session

    [ "${SB_SESSION_ID}" = "session-id" ]
    [ "$(head -n 1 "${args_log}")" = "-q" ]
    grep -q -- "--proto" "${args_log}"
    grep -q -- "--max-redirs" "${args_log}"
    grep -q -- "--globoff" "${args_log}"
    ! grep -Eq -- '(^|[[:space:]])(-L|--location)([[:space:]]|$)' "${args_log}"
    rm -f "${SB_COOKIE_JAR}"
}

@test "Splunkbase redirect follow-up strips cookie and X-Auth credentials" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    calls_file="${mock_dir}/calls"
    args_log="${mock_dir}/args"
    cookie_file="${mock_dir}/cookies"
    output_file="${mock_dir}/package.tgz"
    printf '%s' '0' > "${calls_file}"
    printf '%s\n' '# cookie jar' > "${cookie_file}"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
count="$(cat "${CURL_CALLS_FILE}")"
count=$((count + 1))
printf '%s' "${count}" > "${CURL_CALLS_FILE}"
{
    printf 'CALL=%s\n' "${count}"
    printf '%s\n' "$@"
} >> "${CURL_ARGS_LOG}"
header=""
output=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -D) header="$2"; shift 2 ;;
        -o) output="$2"; shift 2 ;;
        *) shift ;;
    esac
done
if [[ "${count}" == "1" ]]; then
    printf 'HTTP/1.1 302 Found\r\nLocation: https://cdn.example.invalid/package.tgz\r\n\r\n' > "${header}"
    : > "${output}"
    printf '302\thttps://splunkbase.splunk.com/app/1/release/1/download/'
else
    printf 'HTTP/1.1 200 OK\r\n\r\n' > "${header}"
    printf '%s' 'package-bytes' > "${output}"
    printf '200\thttps://cdn.example.invalid/package.tgz'
fi
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_CALLS_FILE="${calls_file}" CURL_ARGS_LOG="${args_log}"
    export PATH="${mock_dir}:${PATH}"
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/splunkbase_helpers.sh"
    export SB_SESSION_ID="session-id" SB_COOKIE_JAR="${cookie_file}"

    get_splunkbase_release_metadata() {
        SB_DOWNLOAD_VERSION="1"
        SB_DOWNLOAD_FILENAME="package.tgz"
        SB_DOWNLOAD_SOURCE_URL="https://splunkbase.splunk.com/app/1/release/1/download/"
    }
    _is_splunk_package() { return 0; }
    export -f get_splunkbase_release_metadata _is_splunk_package

    download_splunkbase_release "1" "1" "${output_file}"

    [ "$(cat "${calls_file}")" = "2" ]
    [ "$(cat "${output_file}")" = "package-bytes" ]
    first_args="$(sed -n '/^CALL=1$/,/^CALL=2$/p' "${args_log}")"
    second_args="$(sed -n '/^CALL=2$/,$p' "${args_log}")"
    [[ "${first_args}" == *"-b"* ]]
    [[ "${first_args}" == *"-K"* ]]
    [[ "${second_args}" != *$'\n-b\n'* ]]
    [[ "${second_args}" != *$'\n-K\n'* ]]
    [[ "${second_args}" == *"https://cdn.example.invalid/package.tgz"* ]]
}
