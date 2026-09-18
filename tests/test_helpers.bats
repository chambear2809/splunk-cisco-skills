#!/usr/bin/env bats
# Integration tests for shared shell helpers.
# Requires bats-core: brew install bats-core
#
# Run with: bats tests/test_helpers.bats

setup() {
    export _CRED_HELPERS_LOADED=""
    export _CREDENTIALS_LOADED=""
    export _REST_HELPERS_LOADED=""
    export _ACS_HELPERS_LOADED=""
    export _SPLUNKBASE_HELPERS_LOADED=""
    export _CONFIGURE_ACCOUNT_HELPERS_LOADED=""
    export _REGISTRY_HELPERS_LOADED=""
    export _HOST_BOOTSTRAP_HELPERS_LOADED=""
    export _DEPLOYMENT_HELPERS_LOADED=""
    export _RESTART_HELPERS_LOADED=""
    export _PLATFORM_RESTART_RESOLVED_PLATFORM=""
    export _RESOLVED_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_CREDENTIAL_PROFILE=""
    export _RESOLVED_CREDENTIAL_PROFILE_REQUEST=""
    export _RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_SEARCH_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
    export _RESOLVED_SEARCH_CREDENTIAL_PROFILE_REQUEST=""
    export _RESOLVED_SPLUNK_PLATFORM_CONTEXT=""
    export _LOADED_CREDENTIAL_SELECTION_CONTEXT=""
    export _CREDENTIAL_FILE_WAS_USED=""
    export _ACS_CONTEXT_PREPARED="false"
    export _ACS_CONTEXT_TARGET=""
    export _ACS_CONTEXT_IDENTITY=""
    export _WARNED_INVALID_SPLUNK_TARGET_ROLE=""
    export SPLUNK_USER="testuser"
    export SPLUNK_PASS="testpass"
    export SPLUNK_VERIFY_SSL="false"
    unset SPLUNK_ALLOW_INSECURE_HTTP
    unset APP_DOWNLOAD_ALLOW_HTTP
    unset _WARNED_APP_DOWNLOAD_HTTP
    unset _WARNED_SPLUNK_INSECURE_HTTP
    unset SPLUNK_PROFILE SPLUNK_SEARCH_PROFILE SPLUNK_INGEST_PROFILE
    unset SPLUNK_DEPLOYER_PROFILE SPLUNK_CLUSTER_MANAGER_PROFILE
    unset SPLUNK_DELIVERY_PLANE SPLUNK_TARGET_ROLE SPLUNK_SEARCH_TARGET_ROLE SPLUNK_PLATFORM
    unset SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_HOST SPLUNK_MGMT_PORT SPLUNK_SSH_HOST
    unset SPLUNK_SSH_PORT SPLUNK_SSH_USER SPLUNK_SSH_PASS SPLUNK_RESOLVE
    unset PLATFORM_RESTART_MODE PLATFORM_RESTART_EXECUTION
    unset PLATFORM_RESTART_ALLOW_REST_FALLBACK ALLOW_REST_FALLBACK RESTART_SPLUNK
    unset SPLUNK_CLOUD_STACK SPLUNK_CLOUD_SEARCH_HEAD ACS_SERVER STACK_TOKEN
    unset STACK_USERNAME STACK_PASSWORD STACK_TOKEN_USER

    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    LIB_DIR="${PROJECT_ROOT}/skills/shared/lib"

    # Track temp files/dirs created during this test for cleanup on failure.
    TEST_TEMP_FILES=()
}

teardown() {
    # Clean up any temp files/dirs that the test may have leaked on failure.
    for f in "${TEST_TEMP_FILES[@]+"${TEST_TEMP_FILES[@]}"}"; do
        rm -rf "${f}"
    done
    rm -rf "${BATS_TMPDIR}"/set_conf_args_* 2>/dev/null || true
}

# --- form_urlencode_pairs ---

@test "form_urlencode_pairs encodes simple key-value pairs" {
    source "${LIB_DIR}/rest_helpers.sh"
    result=$(form_urlencode_pairs key1 value1 key2 value2)
    [ "$result" = "key1=value1&key2=value2" ]
}

@test "form_urlencode_pairs encodes special characters" {
    source "${LIB_DIR}/rest_helpers.sh"
    result=$(form_urlencode_pairs user "hello world" pass "a&b=c")
    [ "$result" = "user=hello+world&pass=a%26b%3Dc" ]
}

@test "form_urlencode_pairs keeps values off python argv" {
    source "${LIB_DIR}/rest_helpers.sh"
    real_python="$(command -v python3)"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    argv_log="${mock_dir}/python-argv.log"
    cat > "${mock_dir}/python3" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${PYTHON_ARG_LOG}"
exec "${REAL_PYTHON}" "$@"
EOF
    chmod +x "${mock_dir}/python3"

    export REAL_PYTHON="${real_python}"
    export PYTHON_ARG_LOG="${argv_log}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"
    result=$(form_urlencode_pairs user "secret value" token "tok&n")
    PATH="${old_path}"

    [ "$result" = "user=secret+value&token=tok%26n" ]
    ! grep -q "secret value" "${argv_log}"
    ! grep -q "tok&n" "${argv_log}"
}

@test "form_urlencode_pairs rejects odd number of args" {
    source "${LIB_DIR}/rest_helpers.sh"
    run form_urlencode_pairs key1
    [ "$status" -eq 1 ]
}

@test "_curl_config_escape keeps values off python argv" {
    source "${LIB_DIR}/rest_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    argv_log="${mock_dir}/python-argv.log"
    cat > "${mock_dir}/python3" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${PYTHON_ARG_LOG}"
exit 9
EOF
    chmod +x "${mock_dir}/python3"

    export PYTHON_ARG_LOG="${argv_log}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"
    result=$(_curl_config_escape $'tok"en\\value\r\n')
    PATH="${old_path}"

    [ "$result" = 'tok\"en\\value\r\n' ]
    [ ! -e "${argv_log}" ]
}

# --- _urlencode ---

@test "_urlencode encodes spaces and special chars" {
    source "${LIB_DIR}/rest_helpers.sh"
    result=$(_urlencode "hello world/test")
    [ "$result" = "hello%20world%2Ftest" ]
}

@test "_urlencode handles empty string" {
    source "${LIB_DIR}/rest_helpers.sh"
    result=$(_urlencode "")
    [ "$result" = "" ]
}

@test "_set_splunk_curl_tls_args adds cacert when configured" {
    source "${LIB_DIR}/rest_helpers.sh"
    tmpfile=$(mktemp)
    export SPLUNK_CA_CERT="$tmpfile"
    _set_splunk_curl_tls_args
    [ "${_tls_verify_args[0]}" = "--cacert" ]
    [ "${_tls_verify_args[1]}" = "$tmpfile" ]
    rm -f "$tmpfile"
    unset SPLUNK_CA_CERT
}

@test "_set_splunk_curl_tls_args verifies by default when SPLUNK_VERIFY_SSL is unset" {
    # Locks in the secure-by-default TLS posture for Splunk REST connections
    # (no -k flag emitted) so a future change cannot silently regress it.
    source "${LIB_DIR}/rest_helpers.sh"
    unset SPLUNK_VERIFY_SSL
    unset SPLUNK_CA_CERT
    _set_splunk_curl_tls_args
    [ "${#_tls_verify_args[@]}" -eq 0 ]
}

@test "_set_splunk_curl_tls_args supports SPLUNK_VERIFY_SSL=false opt-out for self-signed Splunk" {
    # Self-signed on-prem deployments are common; the explicit opt-out must
    # produce -k and warn-once without requiring any code change.
    source "${LIB_DIR}/rest_helpers.sh"
    export SPLUNK_VERIFY_SSL="false"
    unset SPLUNK_CA_CERT
    unset _WARNED_SPLUNK_INSECURE_TLS
    _set_splunk_curl_tls_args 2>/dev/null
    [ "${_tls_verify_args[0]}" = "-k" ]
    unset SPLUNK_VERIFY_SSL
}

@test "_set_splunkbase_curl_tls_args verifies by default" {
    source "${LIB_DIR}/rest_helpers.sh"
    unset SPLUNKBASE_VERIFY_SSL
    unset SPLUNKBASE_CA_CERT
    _set_splunkbase_curl_tls_args
    [ "${#_tls_verify_args[@]}" -eq 0 ]
}

@test "_set_app_download_curl_tls_args does not inherit Splunk REST TLS opt-out" {
    source "${LIB_DIR}/rest_helpers.sh"
    export SPLUNK_VERIFY_SSL="false"
    unset APP_DOWNLOAD_VERIFY_SSL
    unset APP_DOWNLOAD_CA_CERT
    unset _WARNED_APP_DOWNLOAD_INSECURE_TLS
    _set_app_download_curl_tls_args 2>/dev/null
    [ "${#_tls_verify_args[@]}" -eq 0 ]
}

@test "_set_app_download_curl_tls_args verifies by default when nothing is overridden" {
    source "${LIB_DIR}/rest_helpers.sh"
    unset SPLUNK_VERIFY_SSL
    unset APP_DOWNLOAD_VERIFY_SSL
    unset SPLUNK_CA_CERT
    unset APP_DOWNLOAD_CA_CERT
    _set_app_download_curl_tls_args
    [ "${#_tls_verify_args[@]}" -eq 0 ]
}

@test "credential-bearing Splunk helpers reject plaintext HTTP before curl" {
    source "${LIB_DIR}/rest_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    marker="${mock_dir}/curl-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
exit 0
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    run get_session_key "http://splunk.example:8089"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"SPLUNK_ALLOW_INSECURE_HTTP=true"* ]]
    [ ! -e "${marker}" ]

    password_file="${mock_dir}/password"
    printf '%s\n' "testpass" > "${password_file}"
    chmod 600 "${password_file}"
    run get_session_key_from_password_file \
        "http://splunk.example:8089" "${password_file}" "testuser"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    run splunk_curl "session-key" "http://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    run splunk_curl_post \
        "session-key" "name=value" "http://splunk.example:8089/services/example"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    run verify_search_api_connectivity "http://splunk.example:8089"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    run get_session_key "http://embedded-user:embedded-secret@splunk.example:8089"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"embedded userinfo is refused"* ]]
    [[ "${output}" != *"embedded-secret"* ]]
    [ ! -e "${marker}" ]
    PATH="${old_path}"
}

@test "SPLUNK_VERIFY_SSL=false does not authorize plaintext HTTP" {
    source "${LIB_DIR}/rest_helpers.sh"
    export SPLUNK_VERIFY_SSL="false"
    unset SPLUNK_ALLOW_INSECURE_HTTP
    run get_session_key "http://splunk.example:8089"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"refuses plaintext HTTP"* ]]
}

@test "lab-only HTTP opt-in warns and permits captured password authentication" {
    source "${LIB_DIR}/rest_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    args_log="${mock_dir}/curl-args"
    stdin_log="${mock_dir}/curl-stdin"
    warning_log="${mock_dir}/warning"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
cat > "${CURL_STDIN_LOG}"
printf '%s\n' '<response><sessionKey>captured-session</sessionKey></response>'
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_ARGS_LOG="${args_log}"
    export CURL_STDIN_LOG="${stdin_log}"
    export SPLUNK_ALLOW_INSECURE_HTTP="true"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    session_key="$(get_session_key "http://splunk.example:8089" 2>"${warning_log}")"
    PATH="${old_path}"

    [ "${session_key}" = "captured-session" ]
    [ "$(cat "${stdin_log}")" = "username=testuser&password=testpass" ]
    grep -q "WARNING: LAB ONLY" "${warning_log}"
    grep -q -- "--proto" "${args_log}"
    grep -q -- "=http,https" "${args_log}"
    [ "$(tail -n 3 "${args_log}")" = $'--max-redirs\n0\n--globoff' ]
}

@test "authenticated HTTPS keeps TLS verification controls and HTTPS-only protocols" {
    source "${LIB_DIR}/rest_helpers.sh"
    unset SPLUNK_ALLOW_INSECURE_HTTP
    export SPLUNK_VERIFY_SSL="false"
    _prepare_splunk_transport_for_curl_args "https://splunk.example:8089/services/server/info"
    _set_splunk_curl_tls_args 2>/dev/null
    [ "${_splunk_transport_curl_args[0]}" = "--proto" ]
    [ "${_splunk_transport_curl_args[1]}" = "=https" ]
    [ "${_splunk_transport_curl_args[4]}" = "--max-redirs" ]
    [ "${_splunk_transport_curl_args[5]}" = "0" ]
    [ "${_splunk_transport_curl_args[6]}" = "--globoff" ]
    [ "${_tls_verify_args[0]}" = "-k" ]
}

@test "authenticated curl transport accepts bounded response size controls" {
    source "${LIB_DIR}/rest_helpers.sh"

    run _prepare_splunk_transport_for_curl_args \
        --connect-timeout 5 --max-time 15 --max-filesize 1048576 \
        "https://splunk.example:8089/services/server/info"

    [ "${status}" -eq 0 ]
}

@test "authenticated curl wrappers reject caller transport and redirect overrides" {
    source "${LIB_DIR}/rest_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    marker="${mock_dir}/curl-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
exit 0
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    run splunk_curl "session-key" --location \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"rejects caller redirect controls"* ]]

    run splunk_curl "session-key" --max-redirs 0 \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"rejects caller redirect controls"* ]]

    run splunk_curl "session-key" --proto '=http,https' \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns curl protocol"* ]]

    run splunk_curl "session-key" -K "${mock_dir}/override.curlrc" \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"config/transfer-boundary"* ]]

    run splunk_curl "session-key" \
        "https://splunk.example:8089/services/server/info" \
        "-sK${mock_dir}/override.curlrc"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"config/transfer-boundary"* ]]

    run splunk_curl "session-key" -sk \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns curl TLS verification policy"* ]]

    run splunk_curl "session-key" --insecure \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns curl TLS verification policy"* ]]

    run splunk_curl "session-key" -H 'Authorization: Bearer override' \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"owns authentication"* ]]

    run splunk_curl "session-key" -H 'Authorization : Bearer override' \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"malformed caller header names"* ]]

    run splunk_curl "session-key" --header @/tmp/hostile-headers \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"file-backed"* ]]

    run splunk_curl "session-key" -H $'Accept: application/json\r\nHost: capture.invalid' \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"malformed caller headers"* ]]

    run splunk_curl "session-key" \
        "https://splunk.example:8089/services/server/info" \
        --variable 'hidden=https://other.example:8089/credential-capture' \
        --expand-url '{{hidden}}'
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"rejects curl URL expansion options"* ]]

    run splunk_curl "session-key" --data \
        "https://validator-decoy.example/payload" \
        "other.example:8089/credential-capture"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"ambiguous URL token"* ]]

    run splunk_curl "session-key" --data-binary @/etc/passwd \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"file-backed body"* ]]

    run splunk_curl "session-key" --data-urlencode secret@/etc/passwd \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"file-backed URL-encoded"* ]]

    run splunk_curl "session-key" -F 'field=value;headers=@/etc/passwd' \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"form arguments"* ]]

    run splunk_curl $'unsafe\nheader-injection' \
        "https://splunk.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"unsafe for curl config"* ]]

    run splunk_curl "session-key" \
        "https://splunk-a.example:8089/services/server/info" \
        "https://splunk-b.example:8089/services/server/info"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"requires exactly one"* ]]
    [[ "${output}" == *"found 2"* ]]
    [ ! -e "${marker}" ]
    PATH="${old_path}"
}

@test "authenticated curl refuses a transport-policy loader failure before any request" {
    source "${LIB_DIR}/rest_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    marker="${mock_dir}/curl-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
exit 0
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"
    load_splunk_transport_policy() { return 1; }
    export -f load_splunk_transport_policy

    run splunk_curl "session-key" \
        "https://splunk.example:8089/services/server/info"

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"refusing the request"* ]]
    [ ! -e "${marker}" ]

    run restart_splunk_and_wait \
        "session-key" "https://splunk.example:8089" 1 1
    PATH="${old_path}"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "authenticated curl propagates transport reset failure before any request" {
    source "${LIB_DIR}/rest_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    marker="${mock_dir}/curl-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
exit 0
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}"
    export SPLUNK_RESOLVE="not-a-valid-resolve-route"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    run splunk_curl "session-key" \
        "https://splunk.example:8089/services/server/info"

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"SPLUNK_RESOLVE must be a curl --resolve mapping"* ]]
    [ ! -e "${marker}" ]

    run restart_splunk_and_wait \
        "session-key" "https://splunk.example:8089" 1 1
    PATH="${old_path}"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "REST app observation distinguishes exact presence verified absence and probe failure" {
    source "${LIB_DIR}/rest_helpers.sh"
    splunk_curl() {
        case "${REST_APP_OBSERVATION}" in
            present)
                printf '%s\n%s' '{"entry":[{"name":"SyntheticApp","content":{}}]}' '200'
                ;;
            absent)
                printf '%s\n%s' '{}' '404'
                ;;
            malformed)
                printf '%s\n%s' '{}' '200'
                ;;
            transport)
                return 1
                ;;
        esac
    }
    export -f splunk_curl

    export REST_APP_OBSERVATION=present
    run rest_observe_app "session-key" "https://splunk.example:8089" "SyntheticApp"
    [ "${status}" -eq 0 ]

    export REST_APP_OBSERVATION=absent
    run rest_observe_app "session-key" "https://splunk.example:8089" "SyntheticApp"
    [ "${status}" -eq 1 ]

    for REST_APP_OBSERVATION in malformed transport; do
        export REST_APP_OBSERVATION
        run rest_observe_app "session-key" "https://splunk.example:8089" "SyntheticApp"
        [ "${status}" -eq 2 ]
    done
}

@test "REST HEC readers reject malformed or missing detailed observations" {
    source "${LIB_DIR}/rest_helpers.sh"
    splunk_curl() { printf '%s\n%s' "${REST_HEC_BODY}" "${REST_HEC_HTTP_CODE}"; }
    export -f splunk_curl
    export REST_HEC_HTTP_CODE=200

    for REST_HEC_BODY in \
        '' \
        'not-json' \
        '{}' \
        '{"entry":[{"name":"http://synthetic-hec","content":{}}]}'; do
        export REST_HEC_BODY
        run rest_get_hec_token_state "session-key" "https://splunk.example:8089" "synthetic-hec"
        [ "${status}" -ne 0 ]
        run rest_get_hec_token_record "session-key" "https://splunk.example:8089" "synthetic-hec"
        [ "${status}" -ne 0 ]
    done

    export REST_HEC_BODY='{"entry":[]}'
    run rest_get_hec_token_state "session-key" "https://splunk.example:8089" "synthetic-hec"
    [ "${status}" -eq 0 ]
    [ "${output}" = "missing" ]
    run rest_get_hec_token_record "session-key" "https://splunk.example:8089" "synthetic-hec"
    [ "${status}" -ne 0 ]

    export REST_HEC_BODY='{"entry":[{"name":"http://synthetic-hec","content":{"disabled":false,"index":"netops"}}]}'
    run rest_get_hec_token_state "session-key" "https://splunk.example:8089" "synthetic-hec"
    [ "${status}" -eq 0 ]
    [ "${output}" = "enabled" ]
    run rest_get_hec_token_record "session-key" "https://splunk.example:8089" "synthetic-hec"
    [ "${status}" -eq 0 ]
    [[ "${output}" == *'"default_index": "netops"'* ]]
}

@test "REST HEC readers reject non-2xx empty and exact-entry bodies" {
    source "${LIB_DIR}/rest_helpers.sh"
    splunk_curl() { printf '%s\n%s' "${REST_HEC_BODY}" "${REST_HEC_HTTP_CODE}"; }
    export -f splunk_curl

    export REST_HEC_HTTP_CODE=503
    export REST_HEC_BODY='{"entry":[]}'
    run rest_get_hec_token_state "session-key" "https://splunk.example:8089" "synthetic-hec"
    [ "${status}" -ne 0 ]
    [ "${output}" != "missing" ]

    export REST_HEC_HTTP_CODE=500
    export REST_HEC_BODY='{"entry":[{"name":"http://synthetic-hec","content":{"disabled":false,"index":"netops","token":"synthetic-secret"}}]}'
    run rest_get_hec_token_state "session-key" "https://splunk.example:8089" "synthetic-hec"
    [ "${status}" -ne 0 ]
    [ "${output}" != "enabled" ]
    [[ "${output}" != *"synthetic-secret"* ]]

    run rest_get_hec_token_record "session-key" "https://splunk.example:8089" "synthetic-hec"
    [ "${status}" -ne 0 ]
    [[ "${output}" != *"synthetic-secret"* ]]
}

@test "restart helpers refuse unresolved platforms before planning or restart" {
    credentials_file="$(mktemp)"
    marker="${BATS_TMPDIR}/restart-route-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export PLATFORM_RESTART_MODE="rest"
    export PLATFORM_RESTART_ALLOW_REST_FALLBACK="true"
    export PLATFORM_RESTART_EXECUTION="local"
    source "${LIB_DIR}/credential_helpers.sh"

    resolve_splunk_platform() { return 1; }
    cloud_app_restart_or_exit() { touch "${RESTART_ROUTE_MARKER}"; }
    restart_splunk_and_wait() { touch "${RESTART_ROUTE_MARKER}"; }
    hbs_capture_target_cmd() { touch "${RESTART_ROUTE_MARKER}"; }
    export RESTART_ROUTE_MARKER="${marker}"
    export -f resolve_splunk_platform cloud_app_restart_or_exit
    export -f restart_splunk_and_wait hbs_capture_target_cmd

    run platform_restart_plan "synthetic operation" "standalone" "rest"
    [ "${status}" -ne 0 ]
    [[ "${output}" != *"decision="* ]]
    [ ! -e "${marker}" ]

    run platform_restart_or_exit \
        "synthetic-session-key" "https://splunk.example:8089" "synthetic operation"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "restart helpers reject an invalid explicit platform without routing a restart" {
    credentials_file="$(mktemp)"
    marker="${BATS_TMPDIR}/invalid-platform-restart-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="synthetic-invalid-platform"
SPLUNK_URI="https://splunk.example:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export PLATFORM_RESTART_MODE="rest"
    export PLATFORM_RESTART_ALLOW_REST_FALLBACK="true"
    export PLATFORM_RESTART_EXECUTION="local"
    source "${LIB_DIR}/credential_helpers.sh"

    cloud_app_restart_or_exit() { touch "${RESTART_ROUTE_MARKER}"; }
    restart_splunk_and_wait() { touch "${RESTART_ROUTE_MARKER}"; }
    hbs_capture_target_cmd() { touch "${RESTART_ROUTE_MARKER}"; }
    export RESTART_ROUTE_MARKER="${marker}"
    export -f cloud_app_restart_or_exit restart_splunk_and_wait hbs_capture_target_cmd

    run platform_restart_plan "synthetic operation" "standalone" "rest"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"must be cloud or enterprise"* ]]
    [[ "${output}" != *"synthetic-invalid-platform"* ]]
    [[ "${output}" != *"decision="* ]]
    [ ! -e "${marker}" ]

    run platform_restart_or_exit \
        "synthetic-session-key" "https://splunk.example:8089" "synthetic operation"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "restart execution routing rejects an unknown explicit mode" {
    source "${LIB_DIR}/credential_helpers.sh"
    export PLATFORM_RESTART_EXECUTION="synthetic-invalid-execution"

    run platform_restart_execution_mode

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"must be local or ssh"* ]]
    [[ "${output}" != *"synthetic-invalid-execution"* ]]
}

@test "platform resolver rejects an unknown explicit platform" {
    credentials_file="$(mktemp)"
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="synthetic-invalid-platform"
SPLUNK_URI="https://splunk.example.invalid:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    source "${LIB_DIR}/credential_helpers.sh"

    run resolve_splunk_platform

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"must be cloud or enterprise"* ]]
    [[ "${output}" != *"synthetic-invalid-platform"* ]]
}

@test "password-file session authentication descriptor-binds secrets before curl" {
    source "${LIB_DIR}/rest_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    args_log="${mock_dir}/curl-args"
    stdin_log="${mock_dir}/curl-stdin"
    marker="${mock_dir}/curl-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
cat > "${CURL_STDIN_LOG}"
printf '%s\n' '<response><sessionKey>file-session</sessionKey></response>'
EOF
    chmod +x "${mock_dir}/curl"
    password_file="${mock_dir}/password"
    printf '%s\n' 'p&a=s value' > "${password_file}"
    chmod 600 "${password_file}"
    export CURL_ARGS_LOG="${args_log}" CURL_STDIN_LOG="${stdin_log}" CURL_MARKER="${marker}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    session_key="$(get_session_key_from_password_file \
        "https://splunk.example:8089" "${password_file}" "admin-user")"
    [ "${session_key}" = "file-session" ]
    [ "$(<"${stdin_log}")" = "username=admin-user&password=p%26a%3Ds+value" ]
    ! grep -q -- 'p&a=s value' "${args_log}"
    [ "$(head -n 1 "${args_log}")" = "-q" ]

    rm -f "${marker}" "${args_log}" "${stdin_log}"
    password_link="${mock_dir}/password-link"
    ln -s "${password_file}" "${password_link}"
    run get_session_key_from_password_file \
        "https://splunk.example:8089" "${password_link}" "admin-user"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    password_hardlink="${mock_dir}/password-hardlink"
    ln "${password_file}" "${password_hardlink}"
    run get_session_key_from_password_file \
        "https://splunk.example:8089" "${password_file}" "admin-user"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    PATH="${old_path}"
}

@test "hbs_make_curl_auth_config writes 0600 curl config without argv secrets" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/host_bootstrap_helpers.sh"

    escaped=$(hbs_curl_config_escape $'pa"ss\\word\r\n')
    [ "$escaped" = 'pa\"ss\\word\r\n' ]

    auth_config=$(hbs_make_curl_auth_config 'admin"user' $'pa"ss\\word')
    TEST_TEMP_FILES+=("$auth_config")

    [ -f "$auth_config" ]
    mode=$(stat -c "%a" "$auth_config" 2>/dev/null || stat -f "%Lp" "$auth_config")
    [ "$mode" = "600" ]

    config_text=$(cat "$auth_config")
    [ "$config_text" = 'user = "admin\"user:pa\"ss\\word"' ]
}

@test "host bootstrap downloads disable curlrc and constrain redirects and protocols" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    args_log="${mock_dir}/curl-args"
    marker="${mock_dir}/curl-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
printf '%s' 'download-body'
EOF
    chmod +x "${mock_dir}/curl"
    export CURL_MARKER="${marker}" CURL_ARGS_LOG="${args_log}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    result="$(hbs_fetch_url_text \
        "https://download.example.invalid/file" "download-user" "download-secret")"
    [ "${result}" = "download-body" ]
    [ "$(head -n 1 "${args_log}")" = "-q" ]
    grep -q -- "--proto" "${args_log}"
    grep -q -- "=https" "${args_log}"
    grep -q -- "--proto-redir" "${args_log}"
    grep -q -- "--max-redirs" "${args_log}"
    grep -q -- "--globoff" "${args_log}"
    ! grep -q -- "--location-trusted" "${args_log}"
    ! grep -q -- "download-secret" "${args_log}"

    rm -f "${marker}" "${args_log}"
    run hbs_fetch_url_text "http://download.example.invalid/file" \
        "download-user" "download-secret"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *"APP_DOWNLOAD_ALLOW_HTTP=true"* ]]
    [ ! -e "${marker}" ]

    export APP_DOWNLOAD_ALLOW_HTTP=true
    result="$(hbs_fetch_url_text "http://download.example.invalid/file" 2>"${mock_dir}/warning")"
    [ "${result}" = "download-body" ]
    grep -q "LAB ONLY" "${mock_dir}/warning"
    grep -q -- "=http,https" "${args_log}"

    PATH="${old_path}"
}

@test "host bootstrap uses strict pinned host keys and passes password only on fd 3" {
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    known_hosts="${mock_dir}/known_hosts"
    printf '%s\n' 'host.example ssh-ed25519 AAAATESTKEY' > "${known_hosts}"
    chmod 600 "${known_hosts}"
    cat > "${mock_dir}/sshpass" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${SSHPASS_ARGS_LOG}"
for argument in "$@"; do
    case "${argument}" in
        UserKnownHostsFile=*)
            trust_copy="${argument#*=}"
            printf '%s' "${trust_copy}" > "${SSHPASS_TRUST_PATH_LOG}"
            cat "${trust_copy}" > "${SSHPASS_TRUST_CONTENT_LOG}"
            ;;
    esac
done
IFS= read -r supplied_password <&3
printf '%s' "${supplied_password}" > "${SSHPASS_PASSWORD_LOG}"
if [[ -n "${SPLUNK_SSH_PASS+x}" || -n "${SSHPASS+x}" ]]; then
    printf '%s' inherited > "${SSHPASS_ENV_LOG}"
fi
EOF
    chmod +x "${mock_dir}/sshpass"
    export SSHPASS_ARGS_LOG="${mock_dir}/args.log"
    export SSHPASS_PASSWORD_LOG="${mock_dir}/password.log"
    export SSHPASS_ENV_LOG="${mock_dir}/env.log"
    export SSHPASS_TRUST_PATH_LOG="${mock_dir}/trust-path.log"
    export SSHPASS_TRUST_CONTENT_LOG="${mock_dir}/trust-content.log"
    export SPLUNK_SSH_HOST="host.example"
    export SPLUNK_SSH_PORT="22"
    export SPLUNK_SSH_USER="splunk"
    export SPLUNK_SSH_PASS="ssh-secret"
    export SPLUNK_SSH_KNOWN_HOSTS_FILE="${known_hosts}"
    unset SPLUNK_SSH_HOST_KEY_FINGERPRINT SPLUNK_SSH_ALLOW_TOFU SSHPASS
    load_splunk_ssh_credentials() { :; }
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    hbs_run_target_cmd ssh "printf ok"

    [ "$(sed -n '1p' "${SSHPASS_ARGS_LOG}")" = "-d" ]
    [ "$(sed -n '2p' "${SSHPASS_ARGS_LOG}")" = "3" ]
    grep -q 'StrictHostKeyChecking=yes' "${SSHPASS_ARGS_LOG}"
    trust_copy="$(cat "${SSHPASS_TRUST_PATH_LOG}")"
    [ "${trust_copy}" != "${known_hosts}" ]
    [ "$(cat "${SSHPASS_TRUST_CONTENT_LOG}")" = 'host.example ssh-ed25519 AAAATESTKEY' ]
    [ ! -e "${trust_copy}" ]
    grep -q 'GlobalKnownHostsFile=/dev/null' "${SSHPASS_ARGS_LOG}"
    ! grep -q 'accept-new' "${SSHPASS_ARGS_LOG}"
    ! grep -q 'ssh-secret' "${SSHPASS_ARGS_LOG}"
    [ "$(cat "${SSHPASS_PASSWORD_LOG}")" = "ssh-secret" ]
    [ ! -e "${SSHPASS_ENV_LOG}" ]

    PATH="${old_path}"
}

@test "host bootstrap rejects unsafe known_hosts files before copying them" {
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    source_file="${mock_dir}/known_hosts"
    printf '%s\n' 'host.example ssh-ed25519 AAAATESTKEY' > "${source_file}"
    chmod 600 "${source_file}"

    ln -s "${source_file}" "${mock_dir}/symlink"
    run hbs_prepare_known_hosts_copy "${mock_dir}/symlink"
    [ "${status}" -ne 0 ]

    ln "${source_file}" "${mock_dir}/hardlink"
    run hbs_prepare_known_hosts_copy "${source_file}"
    [ "${status}" -ne 0 ]
    rm -f "${mock_dir}/hardlink"

    chmod 666 "${source_file}"
    run hbs_prepare_known_hosts_copy "${source_file}"
    [ "${status}" -ne 0 ]
}

@test "host bootstrap fails closed without a host-key pin" {
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    cat > "${mock_dir}/sshpass" <<'EOF'
#!/usr/bin/env bash
touch "${SSHPASS_RAN_MARKER}"
EOF
    chmod +x "${mock_dir}/sshpass"
    export SSHPASS_RAN_MARKER="${mock_dir}/ran"
    export SPLUNK_SSH_HOST="host.example" SPLUNK_SSH_PORT="22"
    export SPLUNK_SSH_USER="splunk" SPLUNK_SSH_PASS="ssh-secret"
    unset SPLUNK_SSH_KNOWN_HOSTS_FILE SPLUNK_SSH_HOST_KEY_FINGERPRINT SPLUNK_SSH_ALLOW_TOFU
    load_splunk_ssh_credentials() { :; }
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    run hbs_run_target_cmd ssh "true"

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"production SSH requires"* ]]
    [ ! -e "${SSHPASS_RAN_MARKER}" ]
    PATH="${old_path}"
}

@test "host bootstrap permits accept-new only through the warned lab TOFU gate" {
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    cat > "${mock_dir}/sshpass" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${SSHPASS_ARGS_LOG}"
IFS= read -r _password <&3
EOF
    chmod +x "${mock_dir}/sshpass"
    export SSHPASS_ARGS_LOG="${mock_dir}/args.log"
    export SPLUNK_SSH_HOST="host.example" SPLUNK_SSH_PORT="22"
    export SPLUNK_SSH_USER="splunk" SPLUNK_SSH_PASS="ssh-secret"
    export SPLUNK_SSH_ALLOW_TOFU="true"
    unset SPLUNK_SSH_KNOWN_HOSTS_FILE SPLUNK_SSH_HOST_KEY_FINGERPRINT
    load_splunk_ssh_credentials() { :; }
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    run hbs_run_target_cmd ssh "true"

    [ "${status}" -eq 0 ]
    [[ "${output}" == *"LAB-ONLY SSH TOFU IS ENABLED"* ]]
    grep -q 'StrictHostKeyChecking=accept-new' "${SSHPASS_ARGS_LOG}"
    ! grep -q 'StrictHostKeyChecking=yes' "${SSHPASS_ARGS_LOG}"
    PATH="${old_path}"
}

@test "host bootstrap validates remote tmpdir and staging basename before SCP" {
    source "${LIB_DIR}/host_bootstrap_helpers.sh"

    hbs_validate_remote_stage_path "/var/tmp/splunk" "package.tgz"
    run hbs_validate_remote_stage_path "var/tmp" "package.tgz"
    [ "${status}" -ne 0 ]
    run hbs_validate_remote_stage_path "/var/tmp/../root" "package.tgz"
    [ "${status}" -ne 0 ]
    run hbs_validate_remote_stage_path "/var/tmp" "../../package.tgz"
    [ "${status}" -ne 0 ]
    run hbs_validate_remote_stage_path "/var/tmp" "package name.tgz"
    [ "${status}" -ne 0 ]
}

@test "host bootstrap accepts only the scanned key matching a pinned fingerprint" {
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    expected='SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA'
    cat > "${mock_dir}/ssh-keyscan" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' 'host.example ssh-ed25519 AAAAMATCH' 'host.example ssh-rsa AAAAOTHER'
EOF
    cat > "${mock_dir}/ssh-keygen" <<'EOF'
#!/usr/bin/env bash
IFS= read -r key_line
case "${key_line}" in
    *AAAAMATCH) printf '%s\n' '256 SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA host (ED25519)' ;;
    *) printf '%s\n' '3072 SHA256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB host (RSA)' ;;
esac
EOF
    chmod +x "${mock_dir}/ssh-keyscan" "${mock_dir}/ssh-keygen"
    export SPLUNK_SSH_HOST="host.example" SPLUNK_SSH_PORT="22"
    export SPLUNK_SSH_USER="splunk" SPLUNK_SSH_PASS="ssh-secret"
    export SPLUNK_SSH_HOST_KEY_FINGERPRINT="${expected}"
    unset SPLUNK_SSH_KNOWN_HOSTS_FILE SPLUNK_SSH_ALLOW_TOFU
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"

    hbs_prepare_ssh_trust

    [ -f "${HBS_SSH_TRUST_TEMP_FILE}" ]
    grep -q 'AAAAMATCH' "${HBS_SSH_TRUST_TEMP_FILE}"
    ! grep -q 'AAAAOTHER' "${HBS_SSH_TRUST_TEMP_FILE}"
    [[ " ${HBS_SSH_TRUST_ARGS[*]} " == *" StrictHostKeyChecking=yes "* ]]
    hbs_cleanup_ssh_trust
    PATH="${old_path}"
}

@test "hbs_append_cleanup_trap composes with an existing cleanup trap" {
    # This helper still has a valid use case in get_splunkbase_session and
    # other functions that are invoked WITHOUT command substitution. Verify
    # the append-not-replace semantics independently.
    captured="$(
        set -e
        source "${LIB_DIR}/host_bootstrap_helpers.sh"
        marker_file="$(mktemp)"
        rm -f "${marker_file}"
        trap "printf existing > $(printf '%q' "${marker_file}")" EXIT
        hbs_append_cleanup_trap "printf added >> $(printf '%q' "${marker_file}")" EXIT
        trap_output="$(trap -p EXIT)"
        printf 'TRAP_OUTPUT=%s\n' "${trap_output}"
        rm -f "${marker_file}"
        trap - EXIT
    )"

    [[ "${captured}" == *"printf existing"* ]]
    [[ "${captured}" == *"printf added"* ]]
}

# --- log ---

@test "log outputs timestamped message" {
    source "${LIB_DIR}/rest_helpers.sh"
    result=$(log "test message")
    [[ "$result" =~ \[20[0-9]{2}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}\]\ test\ message ]]
}

# --- read_secret_file ---

@test "read_secret_file reads and trims whitespace" {
    source "${LIB_DIR}/rest_helpers.sh"
    tmpfile=$(mktemp)
    printf '  secret_value  \n' > "$tmpfile"
    result=$(read_secret_file "$tmpfile")
    rm -f "$tmpfile"
    [ "$result" = "secret_value" ]
}

@test "read_secret_file fails on missing file" {
    source "${LIB_DIR}/rest_helpers.sh"
    run read_secret_file "/nonexistent/path"
    [ "$status" -eq 1 ]
}

# --- sanitize_response ---

@test "sanitize_response redacts password fields" {
    source "${LIB_DIR}/rest_helpers.sh"
    input="password=hunter2&token=abc123&user=admin"
    result=$(sanitize_response "$input")
    [[ "$result" =~ password=REDACTED ]]
    [[ "$result" =~ token=REDACTED ]]
    [[ "$result" =~ user=admin ]]
}

@test "sanitize_response redacts JSON secret fields" {
    source "${LIB_DIR}/rest_helpers.sh"
    input='{"refresh_token":"abc123","password":"hunter2","nested":{"apiKey":"xyz789","pkcs_certificate":"cert"},"cii_json_text":"blob","user":"admin"}'
    result=$(sanitize_response "$input")
    [[ "$result" =~ '"refresh_token": "REDACTED"' || "$result" =~ '"refresh_token":"REDACTED"' ]]
    [[ "$result" =~ '"password": "REDACTED"' || "$result" =~ '"password":"REDACTED"' ]]
    [[ "$result" =~ '"apiKey": "REDACTED"' || "$result" =~ '"apiKey":"REDACTED"' ]]
    [[ "$result" =~ '"pkcs_certificate": "REDACTED"' || "$result" =~ '"pkcs_certificate":"REDACTED"' ]]
    [[ "$result" =~ '"cii_json_text": "REDACTED"' || "$result" =~ '"cii_json_text":"REDACTED"' ]]
    [[ "$result" =~ '"user": "admin"' || "$result" =~ '"user":"admin"' ]]
}

# --- _is_splunk_package ---

@test "_is_splunk_package rejects non-tar file" {
    source "${LIB_DIR}/rest_helpers.sh"
    tmpfile=$(mktemp)
    echo "not a tar file" > "$tmpfile"
    run _is_splunk_package "$tmpfile"
    rm -f "$tmpfile"
    [ "$status" -ne 0 ]
}

@test "read_secret_file rejects symlinks hardlinks and broad modes" {
    source "${LIB_DIR}/rest_helpers.sh"
    tmpdir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${tmpdir}")
    secret="${tmpdir}/secret"
    printf '%s\n' 'private-value' > "${secret}"
    chmod 600 "${secret}"

    ln -s "${secret}" "${tmpdir}/link"
    run read_secret_file "${tmpdir}/link"
    [ "${status}" -ne 0 ]

    ln "${secret}" "${tmpdir}/hard"
    run read_secret_file "${secret}"
    [ "${status}" -ne 0 ]
    rm -f "${tmpdir}/hard"

    chmod 644 "${secret}"
    run read_secret_file "${secret}"
    [ "${status}" -ne 0 ]
}

# --- rest_set_verify_ssl ---

@test "rest_set_verify_ssl calls rest_set_conf with correct arguments" {
    source "${LIB_DIR}/rest_helpers.sh"

    rest_set_conf() {
        echo "$*" > "${BATS_TMPDIR}/set_conf_args_${BASHPID}"
    }
    export -f rest_set_conf

    run rest_set_verify_ssl "sk" "https://uri" "MyApp" "my_settings" "default" "verify_ssl" "False"
    [ "$status" -eq 0 ]
    local captured
    captured=$(cat "${BATS_TMPDIR}"/set_conf_args_* 2>/dev/null)
    rm -f "${BATS_TMPDIR}"/set_conf_args_*
    [[ "$captured" == *"MyApp"* ]]
    [[ "$captured" == *"my_settings"* ]]
    [[ "$captured" == *"default"* ]]
    [[ "$captured" == *"verify_ssl"* ]]
    [[ "$captured" == *"False"* ]]
}

@test "rest_set_conf rejects HTTP success when requested fields do not read back" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        printf '%s\n%s' \
            '{"entry":[{"name":"logging","content":{"loglevel":"WARN","api_token":"observed-synthetic-value"}}]}' \
            '200'
    }
    splunk_curl_post() {
        printf '%s\n%s' '{}' '200'
    }

    run rest_set_conf "synthetic-session-key" "https://splunk.example:8089" \
        "ExampleApp" "settings" "logging" \
        "loglevel=INFO&api_token=requested-synthetic-secret"

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"requested-field readback failed"* ]]
    [[ "${output}" != *"requested-synthetic-secret"* ]]
    [[ "${output}" != *"observed-synthetic-value"* ]]
}

@test "app presence and version readers reject non-exact HTTP 200 payloads" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        if [[ "$*" == *"%{http_code}"* ]]; then
            printf '%s\n%s' "${MOCK_APP_RESPONSE}" '200'
        else
            printf '%s' "${MOCK_APP_RESPONSE}"
        fi
    }

    local payload
    for payload in \
        '{"entry":[{"name":"wrong_app","content":{"version":"9.9.9","token":"synthetic-secret"}}]}' \
        '{"entry":[]}' \
        '{"entry":['; do
        export MOCK_APP_RESPONSE="${payload}"

        run rest_observe_app "synthetic-session-key" "https://splunk.example:8089" "expected_app"
        [ "${status}" -eq 2 ]
        [[ "${output}" != *"synthetic-secret"* ]]

        run rest_get_app_version "synthetic-session-key" "https://splunk.example:8089" "expected_app"
        [ "${status}" -ne 0 ]
        [[ "${output}" != *"synthetic-secret"* ]]
    done

    export MOCK_APP_RESPONSE='{"entry":[{"name":"expected_app","content":{"version":"1.2.3"}}]}'
    run rest_get_app_version "synthetic-session-key" "https://splunk.example:8089" "expected_app"
    [ "${status}" -eq 0 ]
    [ "${output}" = "1.2.3" ]
}

@test "rest_create_input rejects HTTP success when disabled state does not read back" {
    source "${LIB_DIR}/rest_helpers.sh"

    splunk_curl() {
        printf '%s\n%s' \
            '{"entry":[{"name":"example_input://sample","content":{"index":"main","disabled":"1"}}]}' \
            '200'
    }
    splunk_curl_post() {
        printf '%s\n%s' '{}' '200'
    }

    run rest_create_input "synthetic-session-key" "https://splunk.example:8089" \
        "ExampleApp" "example_input" "sample" "index=main&disabled=0"

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"requested enabled/disabled state"* ]]
}

@test "load_ingest_connection_settings resolves ingest profile URI and HEC URL" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_USER="search-user"
SPLUNK_PASS="search-pass"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_TARGET_ROLE="heavy-forwarder"
PROFILE_ingest__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
PROFILE_ingest__SPLUNK_HEC_URL="https://hf-ingest.example.com:8088/services/collector/event"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    rm -f "${credentials_file}"
    [ "${INGEST_SPLUNK_URI}" = "https://hf.example.com:8089" ]
    [ "${INGEST_SPLUNK_USER}" = "ingest-user" ]
    [ "${INGEST_SPLUNK_TARGET_ROLE}" = "heavy-forwarder" ]
    [ "${INGEST_SPLUNK_HEC_URL}" = "https://hf-ingest.example.com:8088/services/collector/event" ]
}
@test "load_ingest_connection_settings prefers an ingest host and port over inherited search URI" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_HOST="hf.example.com"
PROFILE_ingest__SPLUNK_MGMT_PORT="8090"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://hf.example.com:8090" ]
    [ "${INGEST_SPLUNK_URI}" = "https://hf.example.com:8090" ]
    [ "${INGEST_SPLUNK_HOST}" = "hf.example.com" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "8090" ]
}

@test "load_ingest_connection_settings builds a host-only ingest endpoint with the management port default" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:9443"
SPLUNK_MGMT_PORT="9999"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_HOST="hf.example.com"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://hf.example.com:8089" ]
    [ "${INGEST_SPLUNK_URI}" = "https://hf.example.com:8089" ]
    [ "${INGEST_SPLUNK_HOST}" = "hf.example.com" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "8089" ]
}

@test "load_ingest_connection_settings prefers an ingest legacy URI over inherited search URI" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_URI="https://legacy-ingest.example.com:8088"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://legacy-ingest.example.com:8088" ]
    [ "${INGEST_SPLUNK_URI}" = "https://legacy-ingest.example.com:8088" ]
    [ "${INGEST_SPLUNK_HOST}" = "legacy-ingest.example.com" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "8088" ]
}

@test "load_ingest_connection_settings ignores a profile-local port without a profile-local endpoint" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_MGMT_PORT="8091"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://search.example.com:8089" ]
    [ "${INGEST_SPLUNK_URI}" = "https://search.example.com:8089" ]
    [ "${INGEST_SPLUNK_HOST}" = "search.example.com" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "8089" ]
}

@test "load_ingest_connection_settings derives HTTPS default port from explicit URI" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_SEARCH_API_URI="https://ingest.example.com"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://ingest.example.com" ]
    [ "${INGEST_SPLUNK_HOST}" = "ingest.example.com" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "443" ]
}

@test "load_ingest_connection_settings keeps the whole inherited URI for a port-only profile" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://authoritative.example.com:8089"
SPLUNK_HOST="stale.example.com"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_MGMT_PORT="8091"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://authoritative.example.com:8089" ]
    [ "${INGEST_SPLUNK_HOST}" = "authoritative.example.com" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "8089" ]
}

@test "load_ingest_connection_settings brackets an explicit IPv6 ingest host" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_HOST="2001:db8::10"
PROFILE_ingest__SPLUNK_MGMT_PORT="8090"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://[2001:db8::10]:8090" ]
    [ "${INGEST_SPLUNK_URI}" = "https://[2001:db8::10]:8090" ]
    [ "${INGEST_SPLUNK_HOST}" = "2001:db8::10" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "8090" ]
}

@test "load_ingest_connection_settings inherits the current endpoint only when ingest profile has no endpoint" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_INGEST_PROFILE="ingest"
PROFILE_ingest__SPLUNK_USER="ingest-user"
PROFILE_ingest__SPLUNK_PASS="ingest-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_ingest_connection_settings

    [ "${INGEST_SPLUNK_SEARCH_API_URI}" = "https://search.example.com:8089" ]
    [ "${INGEST_SPLUNK_URI}" = "https://search.example.com:8089" ]
    [ "${INGEST_SPLUNK_HOST}" = "search.example.com" ]
    [ "${INGEST_SPLUNK_MGMT_PORT}" = "8089" ]
}

@test "primary legacy URI suppresses a distinct flat search and SSH target" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="primary"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
SPLUNK_SSH_HOST="flat-search.example.com"
PROFILE_primary__SPLUNK_URI="https://primary.example.com:8090"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    [ "${SPLUNK_SEARCH_API_URI}" = "https://primary.example.com:8090" ]
    [ "${SPLUNK_URI}" = "https://primary.example.com:8090" ]
    [ "${SPLUNK_HOST}" = "primary.example.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8090" ]
    [ -z "${SPLUNK_SSH_HOST:-}" ]
}

@test "primary host endpoint suppresses distinct flat URI aliases and SSH target" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="primary"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
SPLUNK_URI="https://flat-legacy.example.com:8088"
SPLUNK_SSH_HOST="flat-search.example.com"
PROFILE_primary__SPLUNK_HOST="primary.example.com"
PROFILE_primary__SPLUNK_MGMT_PORT="8091"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    [ "${SPLUNK_SEARCH_API_URI}" = "https://primary.example.com:8091" ]
    [ "${SPLUNK_URI}" = "https://primary.example.com:8091" ]
    [ "${SPLUNK_HOST}" = "primary.example.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8091" ]
    [ -z "${SPLUNK_SSH_HOST:-}" ]
}

@test "search legacy URI suppresses a distinct flat search and SSH target" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_PROFILE="search"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
SPLUNK_SSH_HOST="flat-search.example.com"
PROFILE_search__SPLUNK_URI="https://selected-search.example.com:8092"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    [ "${SPLUNK_SEARCH_API_URI}" = "https://selected-search.example.com:8092" ]
    [ "${SPLUNK_URI}" = "https://selected-search.example.com:8092" ]
    [ "${SPLUNK_HOST}" = "selected-search.example.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8092" ]
    [ -z "${SPLUNK_SSH_HOST:-}" ]
}

@test "search host endpoint suppresses distinct flat URI aliases and SSH target" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_PROFILE="search"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
SPLUNK_URI="https://flat-legacy.example.com:8088"
SPLUNK_SSH_HOST="flat-search.example.com"
PROFILE_search__SPLUNK_HOST="selected-search.example.com"
PROFILE_search__SPLUNK_MGMT_PORT="8093"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    [ "${SPLUNK_SEARCH_API_URI}" = "https://selected-search.example.com:8093" ]
    [ "${SPLUNK_URI}" = "https://selected-search.example.com:8093" ]
    [ "${SPLUNK_HOST}" = "selected-search.example.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8093" ]
    [ -z "${SPLUNK_SSH_HOST:-}" ]
}

@test "search profile resolve mapping overrides the flat target mapping" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_PROFILE="search"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
SPLUNK_RESOLVE="flat-search.example.com:8089:192.0.2.10"
PROFILE_search__SPLUNK_SEARCH_API_URI="https://selected-search.example.com:8089"
PROFILE_search__SPLUNK_RESOLVE="selected-search.example.com:8089:192.0.2.20"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    [ "${SPLUNK_SEARCH_API_URI}" = "https://selected-search.example.com:8089" ]
    [ "${SPLUNK_RESOLVE}" = "selected-search.example.com:8089:192.0.2.20" ]
}

@test "search profile without an endpoint inherits the complete current route" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_PROFILE="search"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8094"
SPLUNK_SSH_HOST="flat-search.example.com"
SPLUNK_RESOLVE="flat-search.example.com:8094:192.0.2.30"
PROFILE_search__SPLUNK_USER="search-user"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    [ "${SPLUNK_SEARCH_API_URI}" = "https://flat-search.example.com:8094" ]
    [ "${SPLUNK_URI}" = "https://flat-search.example.com:8094" ]
    [ "${SPLUNK_HOST}" = "flat-search.example.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8094" ]
    [ "${SPLUNK_SSH_HOST}" = "flat-search.example.com" ]
    [ "${SPLUNK_RESOLVE}" = "flat-search.example.com:8094:192.0.2.30" ]
}

@test "explicit environment endpoint and SSH overrides remain authoritative" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="primary"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
SPLUNK_SSH_HOST="flat-search.example.com"
PROFILE_primary__SPLUNK_HOST="profile.example.com"
PROFILE_primary__SPLUNK_MGMT_PORT="8095"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_URI="https://operator.example.com:8096"
    export SPLUNK_SSH_HOST="operator-ssh.example.com"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    [ "${SPLUNK_SEARCH_API_URI}" = "https://operator.example.com:8096" ]
    [ "${SPLUNK_URI}" = "https://operator.example.com:8096" ]
    [ "${SPLUNK_HOST}" = "operator.example.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8096" ]
    [ "${SPLUNK_SSH_HOST}" = "operator-ssh.example.com" ]
}

@test "credential target rewrite fails before a mutation marker" {
    credentials_file=$(mktemp)
    marker=$(mktemp)
    rm -f "${marker}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://reviewed.example.com:8089"
SPLUNK_SSH_HOST="reviewed.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings
    printf '%s\n' \
        'SPLUNK_SEARCH_API_URI="https://rewritten.example.com:8089"' \
        'SPLUNK_SSH_HOST="rewritten.example.com"' > "${credentials_file}"

    reload_then_mark_mutation() {
        load_splunk_connection_settings || return 1
        touch "${marker}"
    }
    run reload_then_mark_mutation

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"credential file changed after settings were loaded"* ]]
    [[ "${output}" != *"reviewed.example.com"* ]]
    [[ "${output}" != *"rewritten.example.com"* ]]
    [ ! -e "${marker}" ]
}

@test "direct post-load route change fails before a mutation marker" {
    credentials_file=$(mktemp)
    marker=$(mktemp)
    rm -f "${marker}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://reviewed.example.com:8089"
SPLUNK_SSH_HOST="reviewed.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings
    SPLUNK_SEARCH_API_URI="https://changed.example.com:8090"
    SPLUNK_URI="https://changed.example.com:8090"
    SPLUNK_HOST="changed.example.com"
    SPLUNK_MGMT_PORT="8090"
    SPLUNK_SSH_HOST="changed.example.com"

    reload_then_mark_mutation() {
        load_splunk_connection_settings || return 1
        touch "${marker}"
    }
    run reload_then_mark_mutation

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"changed outside a reviewed internal transition"* ]]
    [[ "${output}" != *"reviewed.example.com"* ]]
    [[ "${output}" != *"changed.example.com"* ]]
    [ ! -e "${marker}" ]
}

@test "direct post-load SSH port change fails before a mutation marker" {
    credentials_file=$(mktemp)
    marker=$(mktemp)
    rm -f "${marker}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://reviewed.example.com:8089"
SPLUNK_SSH_HOST="reviewed.example.com"
SPLUNK_SSH_PORT="22"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings
    SPLUNK_SSH_PORT="2222"

    reload_then_mark_mutation() {
        load_splunk_connection_settings || return 1
        touch "${marker}"
    }
    run reload_then_mark_mutation

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"changed outside a reviewed internal transition"* ]]
    [[ "${output}" != *"2222"* ]]
    [ ! -e "${marker}" ]
}

@test "direct post-load resolve change fails before a mutation marker" {
    credentials_file=$(mktemp)
    marker=$(mktemp)
    rm -f "${marker}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://reviewed.example.com:8089"
SPLUNK_RESOLVE="reviewed.example.com:8089:192.0.2.10"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings
    SPLUNK_RESOLVE="reviewed.example.com:8089:192.0.2.20"

    reload_then_mark_mutation() {
        load_splunk_connection_settings || return 1
        touch "${marker}"
    }
    run reload_then_mark_mutation

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"changed outside a reviewed internal transition"* ]]
    [[ "${output}" != *"192.0.2.10"* ]]
    [[ "${output}" != *"192.0.2.20"* ]]
    [ ! -e "${marker}" ]
}

@test "reviewed internal runtime route transition advances the binding" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://reviewed.example.com:8089"
SPLUNK_SSH_HOST="reviewed.example.com"
SPLUNK_SSH_PORT="22"
SPLUNK_RESOLVE="reviewed.example.com:8089:192.0.2.10"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings
    _credential_transition_runtime_route \
        "https://internal-transition.example.com:8090" set \
        "internal-transition.example.com" set "2222" set \
        "internal-transition.example.com:8090:192.0.2.20"

    run _credential_assert_bound_runtime_route

    [ "${status}" -eq 0 ]
    [ "${SPLUNK_SEARCH_API_URI}" = "https://internal-transition.example.com:8090" ]
    [ "${SPLUNK_URI}" = "https://internal-transition.example.com:8090" ]
    [ "${SPLUNK_HOST}" = "internal-transition.example.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8090" ]
    [ "${SPLUNK_SSH_HOST}" = "internal-transition.example.com" ]
    [ "${SPLUNK_SSH_PORT}" = "2222" ]
    [ "${SPLUNK_RESOLVE}" = "internal-transition.example.com:8090:192.0.2.20" ]
}

@test "SSH credential loading defaults its port through a reviewed transition" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://reviewed.example.com:8089"
SPLUNK_SSH_HOST="reviewed.example.com"
SPLUNK_SSH_USER="splunk"
SPLUNK_SSH_PASS="synthetic-password"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_ssh_credentials

    run _credential_assert_bound_runtime_route

    [ "${status}" -eq 0 ]
    [ "${SPLUNK_SSH_HOST}" = "reviewed.example.com" ]
    [ "${SPLUNK_SSH_PORT}" = "22" ]
}

@test "primary cloud URI helper uses the resolved primary endpoint unit" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_CLOUD_STACK="profile-stack"
PROFILE_cloud__SPLUNK_HOST="profile-stack.stg.splunkcloud.com"
PROFILE_cloud__SPLUNK_MGMT_PORT="8097"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_HOST="hf.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run _primary_cloud_search_api_uri

    [ "${status}" -eq 0 ]
    [ "${output}" = "https://profile-stack.stg.splunkcloud.com:8097" ]
}

@test "load_splunk_connection_settings rejects an explicitly unknown primary profile" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="missing"
PROFILE_known__SPLUNK_HOST="known.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run load_splunk_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"primary credential profile is not defined"* ]]
    [[ "${output}" != *"known.example.com"* ]]
}

@test "load_ingest_connection_settings rejects an explicitly unknown ingest profile" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_INGEST_PROFILE="missing"
PROFILE_known__SPLUNK_HOST="known.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run load_ingest_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"ingest profile is not defined"* ]]
    [[ "${output}" != *"known.example.com"* ]]
}

@test "load_splunk_connection_settings rejects an explicitly unknown search profile" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_PROFILE="missing"
SPLUNK_SEARCH_API_URI="https://flat.example.com:8089"
PROFILE_known__SPLUNK_HOST="known.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run load_splunk_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"search profile is not defined"* ]]
    [[ "${output}" != *"known.example.com"* ]]
}

@test "load_splunk_connection_settings rejects an explicitly unknown deployer profile" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_DEPLOYER_PROFILE="missing"
SPLUNK_SEARCH_API_URI="https://flat.example.com:8089"
PROFILE_known__SPLUNK_HOST="known.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run load_splunk_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"deployer profile is not defined"* ]]
    [[ "${output}" != *"known.example.com"* ]]
}

@test "load_splunk_connection_settings rejects an explicitly unknown cluster-manager profile" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLUSTER_MANAGER_PROFILE="missing"
SPLUNK_SEARCH_API_URI="https://flat.example.com:8089"
PROFILE_known__SPLUNK_HOST="known.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run load_splunk_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"cluster-manager profile is not defined"* ]]
    [[ "${output}" != *"known.example.com"* ]]
}

@test "load_splunk_connection_settings rejects profile changes after target settings are loaded" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="one"
PROFILE_one__SPLUNK_HOST="one.example.com"
PROFILE_two__SPLUNK_HOST="two.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings
    export SPLUNK_PROFILE="two"
    run load_splunk_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"profile selection changed"* ]]
    [[ "${output}" != *"one.example.com"* ]]
    [[ "${output}" != *"two.example.com"* ]]
}

@test "load_splunk_connection_settings rejects a profile-local primary-profile redirect" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="one"
PROFILE_one__SPLUNK_PROFILE="two"
PROFILE_one__SPLUNK_HOST="one.example.com"
PROFILE_two__SPLUNK_HOST="two.example.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run load_splunk_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"refusing the target change"* ]]
    [[ "${output}" != *"one.example.com"* ]]
    [[ "${output}" != *"two.example.com"* ]]
}

@test "load_splunk_connection_settings rejects disappearance of a previously used credential file" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://original.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings
    rm -f "${credentials_file}"
    run load_splunk_connection_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"selected credential file changed after settings were loaded"* ]]
}

@test "load_splunk_connection_settings does not partially apply a parser failure" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    printf 'SPLUNK_HOST="synthetic.example.com"\n\377' > "${credentials_file}"
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    unset SPLUNK_HOST

    source "${LIB_DIR}/credential_helpers.sh"
    if load_splunk_connection_settings; then
        false
    fi
    [ -z "${SPLUNK_HOST:-}" ]
}

@test "credential loader rejects NUL-delimited assignment injection without partial state" {
    credentials_file=$(mktemp)
    loader_diagnostic=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}" "${loader_diagnostic}")
    printf 'SPLUNK_HOST=synthetic.example.com\0BASH_ENV\0/tmp/synthetic-startup\0\n' > "${credentials_file}"
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    unset SPLUNK_HOST BASH_ENV

    source "${LIB_DIR}/credential_helpers.sh"
    if load_splunk_connection_settings >/dev/null 2>"${loader_diagnostic}"; then
        false
    fi

    grep -q "must not contain NUL bytes" "${loader_diagnostic}"
    [ -z "${SPLUNK_HOST:-}" ]
    [ -z "${BASH_ENV:-}" ]
}

@test "ACS context failures refuse index mutation before stale context can be reused" {
    credentials_file=$(mktemp)
    mock_dir=$(mktemp -d)
    TEST_TEMP_FILES+=("${credentials_file}" "${mock_dir}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="target"
SPLUNK_CLOUD_SEARCH_HEAD="sh1"
STACK_TOKEN="synthetic-token"
EOF
    cat > "${mock_dir}/acs" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${ACS_CALL_LOG}"
case "$*" in
    *"config add-stack"*) [[ "${ACS_MODE}" != "add-fail" ]] ;;
    *"config use-stack"*) [[ "${ACS_MODE}" != "use-fail" ]] ;;
    *"login"*) [[ "${ACS_MODE}" != "login-fail" ]] ;;
    *"config current-stack"*)
        case "${ACS_MODE}" in
            mismatch-stack|stale) printf '%s\n' 'Stack: other' 'Current Search Head: sh1' ;;
            mismatch-search) printf '%s\n' 'Stack: target' 'Current Search Head: sh2' ;;
            missing-identity) printf '%s\n' 'Current Search Head: sh1' ;;
            current-fail) exit 1 ;;
            *) printf '%s\n' 'Stack: target' 'Current Search Head: sh1' ;;
        esac
        ;;
    *"indexes describe"*) exit 1 ;;
    *"indexes create"*) touch "${ACS_MUTATION_MARKER}" ;;
esac
EOF
    chmod +x "${mock_dir}/acs"
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export ACS_SERVER="https://admin.splunk.com"
    export ACS_CALL_LOG="${mock_dir}/calls"
    export ACS_MUTATION_MARKER="${mock_dir}/mutation"
    export PATH="${mock_dir}:${PATH}"

    source "${LIB_DIR}/credential_helpers.sh"
    for ACS_MODE in use-fail login-fail mismatch-stack mismatch-search missing-identity current-fail; do
        export ACS_MODE
        export _ACS_CONTEXT_PREPARED="false"
        export _ACS_CONTEXT_TARGET=""
        export _ACS_CONTEXT_IDENTITY=""
        run cloud_create_index "synthetic_index"
        [ "${status}" -ne 0 ]
        [ ! -e "${ACS_MUTATION_MARKER}" ]
    done
}

@test "ACS context refuses mutation without an explicitly selected stack" {
    credentials_file=$(mktemp)
    mock_dir=$(mktemp -d)
    TEST_TEMP_FILES+=("${credentials_file}" "${mock_dir}")
    cat > "${credentials_file}" <<'EOF'
STACK_TOKEN="synthetic-token"
EOF
    cat > "${mock_dir}/acs" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    *"config current-stack"*) printf '%s\n' 'Stack: stale-stack' ;;
    *"indexes create"*) touch "${ACS_MUTATION_MARKER}" ;;
esac
EOF
    chmod +x "${mock_dir}/acs"
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export ACS_SERVER="https://admin.splunk.com"
    export ACS_MUTATION_MARKER="${mock_dir}/mutation"
    export PATH="${mock_dir}:${PATH}"

    source "${LIB_DIR}/credential_helpers.sh"
    run cloud_create_index "synthetic_index"

    [ "${status}" -ne 0 ]
    [ ! -e "${ACS_MUTATION_MARKER}" ]
}

@test "ACS context refuses mutation when a previously verified CLI context becomes stale" {
    credentials_file=$(mktemp)
    mock_dir=$(mktemp -d)
    TEST_TEMP_FILES+=("${credentials_file}" "${mock_dir}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="target"
SPLUNK_CLOUD_SEARCH_HEAD="sh1"
STACK_TOKEN="synthetic-token"
EOF
    cat > "${mock_dir}/acs" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    *"config current-stack"*)
        if [[ "${ACS_MODE}" == "stale" ]]; then
            printf '%s\n' 'Stack: other' 'Current Search Head: sh1'
        else
            printf '%s\n' 'Stack: target' 'Current Search Head: sh1'
        fi
        ;;
    *"indexes describe"*) exit 1 ;;
    *"indexes create"*) touch "${ACS_MUTATION_MARKER}" ;;
esac
EOF
    chmod +x "${mock_dir}/acs"
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export ACS_SERVER="https://admin.splunk.com"
    export ACS_MUTATION_MARKER="${mock_dir}/mutation"
    export PATH="${mock_dir}:${PATH}"
    source "${LIB_DIR}/credential_helpers.sh"

    export ACS_MODE="current"
    acs_prepare_context
    [ "${_ACS_CONTEXT_PREPARED}" = "true" ]
    export ACS_MODE="stale"
    if cloud_create_index "synthetic_index"; then
        false
    fi
    [ "${_ACS_CONTEXT_PREPARED}" = "false" ]
    [ ! -e "${ACS_MUTATION_MARKER}" ]
}

@test "ACS context target changes invalidate a previously verified context" {
    credentials_file=$(mktemp)
    mock_dir=$(mktemp -d)
    TEST_TEMP_FILES+=("${credentials_file}" "${mock_dir}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="target"
SPLUNK_CLOUD_SEARCH_HEAD="sh1"
STACK_TOKEN="synthetic-token"
EOF
    cat > "${mock_dir}/acs" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    *"config current-stack"*) printf '%s\n' 'Stack: target' 'Current Search Head: sh1' ;;
    *"indexes describe"*) exit 1 ;;
    *"indexes create"*) touch "${ACS_MUTATION_MARKER}" ;;
esac
EOF
    chmod +x "${mock_dir}/acs"
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export ACS_SERVER="https://admin.splunk.com"
    export ACS_MUTATION_MARKER="${mock_dir}/mutation"
    export PATH="${mock_dir}:${PATH}"
    source "${LIB_DIR}/credential_helpers.sh"

    acs_prepare_context
    [ "${_ACS_CONTEXT_PREPARED}" = "true" ]
    export SPLUNK_CLOUD_STACK="changed-target"
    run cloud_create_index "synthetic_index"
    [ "${status}" -ne 0 ]
    [ ! -e "${ACS_MUTATION_MARKER}" ]
}

@test "ACS context propagates username/password token-user login failures and success" {
    credentials_file=$(mktemp)
    mock_dir=$(mktemp -d)
    TEST_TEMP_FILES+=("${credentials_file}" "${mock_dir}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="target"
SPLUNK_CLOUD_SEARCH_HEAD="sh1"
STACK_USERNAME="stack-user"
STACK_PASSWORD="stack-pass"
STACK_TOKEN_USER="token-user"
EOF
    cat > "${mock_dir}/acs" <<'EOF'
#!/usr/bin/env bash
case "$*" in
    *"config add-stack"*) [[ "${ACS_MODE}" != "add-fail" ]] ;;
    *"config use-stack"*) exit 0 ;;
    *"login"*) [[ "${ACS_MODE}" != "login-fail" ]] ;;
    *"config current-stack"*) printf '%s\n' 'Stack: target' 'Current Search Head: sh1' ;;
esac
EOF
    chmod +x "${mock_dir}/acs"
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export ACS_SERVER="https://admin.splunk.com"
    export PATH="${mock_dir}:${PATH}"
    source "${LIB_DIR}/credential_helpers.sh"

    export ACS_MODE="login-fail"
    if acs_prepare_context; then
        false
    fi
    [ "${_ACS_CONTEXT_PREPARED}" = "false" ]

    # An add-stack refusal can mean the stack already exists; successful
    # selection plus identity readback, not add-stack alone, establishes trust.
    export ACS_MODE="add-fail"
    acs_prepare_context
    [ "${_ACS_CONTEXT_PREPARED}" = "true" ]
}

@test "rest_set_conf uses bundle helper for clustered search-tier config writes" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_DEPLOYER_PROFILE="deployer"
PROFILE_deployer__SPLUNK_SEARCH_API_URI="https://deployer.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"

    deployment_bundle_set_conf_for_current_target() {
        echo "$*"
    }
    export -f deployment_bundle_set_conf_for_current_target

    output="$(rest_set_conf "sk" "https://search.example.com:8089" "MyApp" "macros" "stanza" "definition=index")"
    status=$?

    rm -f "${credentials_file}"

    [ "$status" -eq 0 ]
    [[ "$output" == *"MyApp macros stanza definition=index"* ]]
}

@test "rest_set_conf rejects an unknown deployer before REST fallback" {
    credentials_file=$(mktemp)
    marker="${BATS_TMPDIR}/rest-fallback-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_DEPLOYER_PROFILE="missing"
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_USER="search-user"
SPLUNK_PASS="search-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    splunk_curl_post() {
        touch "${REST_FALLBACK_MARKER}"
        return 0
    }
    export REST_FALLBACK_MARKER="${marker}"
    export -f splunk_curl_post

    if rest_set_conf "synthetic-session-key" "https://search.example.com:8089" \
        "MyApp" "macros" "stanza" "definition=index"; then
        false
    fi
    [ ! -e "${marker}" ]
}

@test "bundle routing honors a file-backed REST delivery plane on its first decision" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_DELIVERY_PLANE="rest"
SPLUNK_DEPLOYER_PROFILE="deployer"
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
PROFILE_deployer__SPLUNK_SEARCH_API_URI="https://deployer.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run deployment_should_manage_search_config_via_bundle

    [ "${status}" -eq 1 ]
}

@test "invalid delivery plane is rejected without echoing its value" {
    export SPLUNK_DELIVERY_PLANE="synthetic-invalid-plane"
    source "${LIB_DIR}/credential_helpers.sh"

    run resolve_delivery_plane

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"must be auto, rest, or bundle"* ]]
    [[ "${output}" != *"synthetic-invalid-plane"* ]]
}

@test "forced bundle search routing refuses REST fallback when deployer route is absent" {
    credentials_file=$(mktemp)
    marker="${BATS_TMPDIR}/forced-bundle-rest-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="enterprise"
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_DELIVERY_PLANE="bundle"
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    splunk_curl_post() {
        touch "${FORCED_BUNDLE_REST_MARKER}"
        return 0
    }
    export FORCED_BUNDLE_REST_MARKER="${marker}"
    export -f splunk_curl_post

    run deployment_should_manage_search_config_via_bundle
    [ "${status}" -eq 2 ]

    if rest_set_conf "synthetic-session-key" "https://search.example.com:8089" \
        "MyApp" "macros" "stanza" "definition=index"; then
        false
    fi
    [ ! -e "${marker}" ]
}

@test "forced bundle routing returns status 2 without a compatible app or ingest route" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="enterprise"
SPLUNK_TARGET_ROLE="heavy-forwarder"
SPLUNK_DELIVERY_PLANE="bundle"
SPLUNK_SEARCH_API_URI="https://forwarder.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"

    run deployment_should_use_bundle_for_current_target
    [ "${status}" -eq 2 ]

    run deployment_index_bundle_profile
    [ "${status}" -eq 2 ]

    run deployment_should_manage_ingest_hec_via_bundle
    [ "${status}" -eq 2 ]
}

@test "automatic bundle routing may fall back when no bundle route exists" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="enterprise"
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_DELIVERY_PLANE="auto"
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"

    run deployment_should_manage_search_config_via_bundle
    [ "${status}" -eq 1 ]
}

@test "deployment_set_app_visible rejects an unknown deployer before REST fallback" {
    credentials_file=$(mktemp)
    marker="${BATS_TMPDIR}/app-visible-fallback-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_DEPLOYER_PROFILE="missing"
SPLUNK_SEARCH_API_URI="https://search.example.com:8089"
SPLUNK_USER="search-user"
SPLUNK_PASS="search-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    splunk_curl() {
        touch "${APP_VISIBLE_FALLBACK_MARKER}"
        return 0
    }
    export APP_VISIBLE_FALLBACK_MARKER="${marker}"
    export -f splunk_curl

    if deployment_set_app_visible "synthetic-session-key" "https://search.example.com:8089" \
        "MyApp" "true"; then
        false
    fi
    [ ! -e "${marker}" ]
}

@test "platform_create_index rejects an unknown cluster manager before REST fallback" {
    credentials_file=$(mktemp)
    marker="${BATS_TMPDIR}/index-rest-fallback-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${credentials_file}" "${marker}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="enterprise"
SPLUNK_TARGET_ROLE="indexer"
SPLUNK_CLUSTER_MANAGER_PROFILE="missing"
SPLUNK_SEARCH_API_URI="https://indexer.example.com:8089"
SPLUNK_USER="indexer-user"
SPLUNK_PASS="indexer-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    rest_create_index() {
        touch "${INDEX_REST_FALLBACK_MARKER}"
        return 0
    }
    export INDEX_REST_FALLBACK_MARKER="${marker}"
    export -f rest_create_index

    if platform_create_index "synthetic-session-key" "https://indexer.example.com:8089" \
        "synthetic_index" "512000" "event"; then
        false
    fi
    [ ! -e "${marker}" ]
}

@test "deployment_bundle_apply_on_profile uses profile credentials for cluster-manager auth" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_USER="global-user"
SPLUNK_PASS="global-pass"
PROFILE_cluster__SPLUNK_SEARCH_API_URI="https://localhost:8089"
PROFILE_cluster__SPLUNK_URI="${PROFILE_cluster__SPLUNK_SEARCH_API_URI}"
PROFILE_cluster__SPLUNK_USER="cluster-user"
PROFILE_cluster__SPLUNK_PASS="cluster-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_HOME="${BATS_TMPDIR}/splunk-${BASHPID}"
    mkdir -p "${SPLUNK_HOME}/bin"

    source "${LIB_DIR}/credential_helpers.sh"

    # Credentials are now passed via a temp file read inside the script, not on the CLI.
    # Mock hbs_run_target_cmd_with_stdin to capture the script content (arg $3).
    hbs_run_target_cmd_with_stdin() {
        echo "$3"
    }
    export -f hbs_run_target_cmd_with_stdin
    # Also mock hbs_prefix_with_sudo since it's called to build the command arg.
    hbs_prefix_with_sudo() {
        echo "$2"
    }
    export -f hbs_prefix_with_sudo

    run deployment_bundle_apply_on_profile "cluster" "idxc" "" "" ""

    [ "$status" -eq 0 ]
    # The script content should invoke apply cluster-bundle with credentials read
    # from a temp file (not inline), and should not contain the literal password.
    [[ "$output" == *"apply cluster-bundle"* ]]
    [[ "$output" == *"-answer-yes"* ]]
    [[ "$output" != *"cluster-pass"* ]]
}

@test "host-only deployer and cluster-manager profiles do not inherit the flat search or SSH target" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://flat-search.example.com:8089"
SPLUNK_SSH_HOST="localhost"
SPLUNK_SSH_PORT="2200"
SPLUNK_RESOLVE="flat-search.example.com:8089:192.0.2.40"
SPLUNK_DEPLOYER_PROFILE="deployer"
SPLUNK_CLUSTER_MANAGER_PROFILE="manager"
PROFILE_deployer__SPLUNK_HOST="deployer.example.com"
PROFILE_deployer__SPLUNK_SSH_PORT="2222"
PROFILE_deployer__SPLUNK_RESOLVE="deployer.example.com:8089:192.0.2.41"
PROFILE_manager__SPLUNK_HOST="manager.example.com"
PROFILE_manager__SPLUNK_MGMT_PORT="8090"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    capture_deployment_profile_route() {
        deployment_apply_profile_globals "$1" || return 1
        printf '%s\n' \
            "${SPLUNK_SEARCH_API_URI}" "${SPLUNK_URI}" "${SPLUNK_HOST}" \
            "${SPLUNK_MGMT_PORT}" "${SPLUNK_SSH_HOST}" \
            "ssh_port=${SPLUNK_SSH_PORT:-<unset>}" \
            "resolve=${SPLUNK_RESOLVE:-<unset>}"
    }
    export -f capture_deployment_profile_route

    run deployment_execution_mode_for_profile "deployer"
    [ "${status}" -eq 0 ]
    [ "${output}" = "ssh" ]
    run capture_deployment_profile_route "deployer"
    [ "${status}" -eq 0 ]
    [ "${output}" = $'https://deployer.example.com:8089\nhttps://deployer.example.com:8089\ndeployer.example.com\n8089\ndeployer.example.com\nssh_port=2222\nresolve=deployer.example.com:8089:192.0.2.41' ]
    [[ "${output}" != *"flat-search.example.com"* ]]

    run deployment_execution_mode_for_profile "manager"
    [ "${status}" -eq 0 ]
    [ "${output}" = "ssh" ]
    run capture_deployment_profile_route "manager"
    [ "${status}" -eq 0 ]
    [ "${output}" = $'https://manager.example.com:8090\nhttps://manager.example.com:8090\nmanager.example.com\n8090\nmanager.example.com\nssh_port=2200\nresolve=<unset>' ]
    [[ "${output}" != *"flat-search.example.com"* ]]
}

@test "explicit same-host deployment profile clears an inherited resolve mapping" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://shared.example.com:8089"
SPLUNK_RESOLVE="shared.example.com:8089:192.0.2.50"
PROFILE_deployer__SPLUNK_SEARCH_API_URI="https://shared.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_connection_settings

    apply_profile_and_report_resolve() {
        deployment_apply_profile_globals "deployer" || return 1
        printf '%s' "${SPLUNK_RESOLVE:-<unset>}"
    }
    run apply_profile_and_report_resolve

    [ "${status}" -eq 0 ]
    [ "${output}" = "<unset>" ]
}

@test "search-head bundle apply rejects plaintext target before staging credentials" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export BUNDLE_STAGE_MARKER="${BATS_TMPDIR}/bundle-stage-${BASHPID}"

    source "${LIB_DIR}/credential_helpers.sh"

    hbs_stage_file_for_execution() {
        touch "${BUNDLE_STAGE_MARKER}"
        printf '%s' "$2"
    }
    export -f hbs_stage_file_for_execution

    run deployment_bundle_apply_current_profile \
        "shc" "http://deployer.example.com:8089" "cluster-user" "cluster-pass"

    [ "$status" -ne 0 ]
    [[ "$output" == *"refuses plaintext HTTP"* ]]
    [ ! -e "${BUNDLE_STAGE_MARKER}" ]
}

@test "deployment_hec_token_record_from_conf parses bundle-managed inputs stanzas" {
    source "${LIB_DIR}/credential_helpers.sh"

    conf_content=$'[http]\ndisabled = 0\n\n[http://sc4s]\ndisabled = 0\nindex = sc4s\ntoken = abc-123\nuseACK = 0\n'

    run deployment_hec_token_record_from_conf "${conf_content}" "sc4s"

    [ "$status" -eq 0 ]
    [[ "$output" == *'"default_index": "sc4s"'* ]]
    [[ "$output" == *'"token": "abc-123"'* ]]
    [[ "$output" == *'"disabled": "0"'* ]]
}

@test "bundle HEC malformed config and unknown disabled state cannot prove absence or trigger create" {
    source "${LIB_DIR}/credential_helpers.sh"
    marker="${BATS_TMPDIR}/bundle-hec-malformed-write-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export BUNDLE_HEC_WRITE_MARKER="${marker}"

    deployment_bundle_hec_inputs_content() {
        printf '%s' "${BUNDLE_HEC_CONF}"
    }
    deployment_bundle_write_hec_token() {
        touch "${BUNDLE_HEC_WRITE_MARKER}"
    }
    export -f deployment_bundle_hec_inputs_content deployment_bundle_write_hec_token

    for BUNDLE_HEC_CONF in \
        $'[http]\ndisabled = 0\n\n[http://sc4s]\nindex = sc4s\nmalformed-sensitive-fragment\ntoken = synthetic-secret\n' \
        $'[http]\ndisabled = uncertain\n\n[http://sc4s]\nindex = sc4s\ntoken = synthetic-secret\n'; do
        export BUNDLE_HEC_CONF

        run deployment_get_bundle_hec_token_state "sc4s"
        [ "${status}" -ne 0 ]
        [ "${output}" != "missing" ]
        [[ "${output}" != *"synthetic-secret"* ]]

        run deployment_create_cluster_bundle_hec_token "sc4s" "sc4s" "" "0"
        [ "${status}" -ne 0 ]
        [[ "${output}" != *"synthetic-secret"* ]]
        [ ! -e "${marker}" ]
    done
}

@test "bundle HEC observation failures propagate without triggering token writes" {
    source "${LIB_DIR}/credential_helpers.sh"
    marker="${BATS_TMPDIR}/bundle-hec-write-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export BUNDLE_HEC_WRITE_MARKER="${marker}"

    deployment_get_bundle_hec_token_record() {
        return 1
    }
    deployment_bundle_write_hec_token() {
        touch "${BUNDLE_HEC_WRITE_MARKER}"
    }
    export -f deployment_get_bundle_hec_token_record deployment_bundle_write_hec_token

    run deployment_get_bundle_hec_token_state "sc4s"
    [ "${status}" -ne 0 ]
    [ "${output}" != "missing" ]

    run deployment_create_cluster_bundle_hec_token "sc4s" "sc4s" "" "0"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    run deployment_enable_cluster_bundle_hec_token "sc4s"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]

    run deployment_update_cluster_bundle_hec_token_default_index "sc4s" "sc4s"
    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "bundle HEC genuine stanza absence remains a successful missing observation" {
    source "${LIB_DIR}/credential_helpers.sh"
    marker="${BATS_TMPDIR}/bundle-hec-absent-write-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export BUNDLE_HEC_WRITE_MARKER="${marker}"

    deployment_get_bundle_hec_token_record() {
        printf '%s' '{}'
    }
    deployment_bundle_write_hec_token() {
        touch "${BUNDLE_HEC_WRITE_MARKER}"
    }
    export -f deployment_get_bundle_hec_token_record deployment_bundle_write_hec_token

    run deployment_get_bundle_hec_token_state "sc4s"
    [ "${status}" -eq 0 ]
    [ "${output}" = "missing" ]

    run deployment_create_cluster_bundle_hec_token "sc4s" "sc4s" "" "0"
    [ "${status}" -eq 0 ]
    [ -e "${marker}" ]
}

@test "bundle config read failure cannot merge from an empty baseline" {
    source "${LIB_DIR}/credential_helpers.sh"
    marker="${BATS_TMPDIR}/bundle-conf-write-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export BUNDLE_CONF_WRITE_MARKER="${marker}"

    deployment_bundle_conf_path_on_profile() {
        printf '%s' '/synthetic/local/indexes.conf'
    }
    deployment_capture_target_file_with_profile() {
        return 1
    }
    deployment_bundle_write_conf_content_on_profile() {
        touch "${BUNDLE_CONF_WRITE_MARKER}"
    }
    export -f deployment_bundle_conf_path_on_profile
    export -f deployment_capture_target_file_with_profile
    export -f deployment_bundle_write_conf_content_on_profile

    run deployment_bundle_set_conf_on_profile \
        "cluster" "idxc" "managed" "indexes" "synthetic" "datatype=event"

    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "bundle app observation distinguishes present absent and probe failure" {
    source "${LIB_DIR}/credential_helpers.sh"

    deployment_bundle_app_dir_current_profile() {
        printf '%s' '/synthetic/apps/TestApp'
    }
    deployment_execution_mode_for_profile() {
        printf '%s' 'local'
    }
    hbs_capture_target_cmd() {
        case "${APP_PROBE_MODE}" in
            present|absent) printf '%s' "${APP_PROBE_MODE}" ;;
            error) return 1 ;;
        esac
    }
    export -f deployment_bundle_app_dir_current_profile
    export -f deployment_execution_mode_for_profile hbs_capture_target_cmd

    export APP_PROBE_MODE="present"
    run deployment_bundle_app_exists_current_profile "shc" "TestApp"
    [ "${status}" -eq 0 ]

    export APP_PROBE_MODE="absent"
    run deployment_bundle_app_exists_current_profile "shc" "TestApp"
    [ "${status}" -eq 1 ]

    export APP_PROBE_MODE="error"
    run deployment_bundle_app_exists_current_profile "shc" "TestApp"
    [ "${status}" -eq 2 ]
}

@test "bundle app profile preparation failure is an observation error" {
    source "${LIB_DIR}/credential_helpers.sh"

    load_splunk_connection_settings() {
        return 1
    }
    export -f load_splunk_connection_settings

    run deployment_bundle_app_exists_on_profile "deployer" "shc" "TestApp"
    [ "${status}" -eq 2 ]
}

@test "bundle scaffold refuses to write app metadata after a failed probe" {
    source "${LIB_DIR}/credential_helpers.sh"
    marker="${BATS_TMPDIR}/bundle-scaffold-write-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export BUNDLE_SCAFFOLD_WRITE_MARKER="${marker}"

    deployment_execution_mode_for_profile() {
        printf '%s' 'local'
    }
    hbs_run_target_cmd() {
        return 0
    }
    hbs_prefix_with_sudo() {
        printf '%s' "$2"
    }
    hbs_capture_target_cmd() {
        return 1
    }
    hbs_write_target_file() {
        touch "${BUNDLE_SCAFFOLD_WRITE_MARKER}"
    }
    export -f deployment_execution_mode_for_profile hbs_run_target_cmd
    export -f hbs_prefix_with_sudo hbs_capture_target_cmd hbs_write_target_file

    run deployment_bundle_scaffold_app_current_profile "/synthetic/apps" "TestApp"

    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

# --- deployment-role helpers ---

@test "resolve_splunk_target_role infers search-tier for a cloud-only target" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="example-stack"
STACK_TOKEN="token"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    result=$(resolve_splunk_target_role)

    rm -f "${credentials_file}"
    [ "${result}" = "search-tier" ]
}

@test "resolve_splunk_target_role keeps the cloud search-tier role active in hybrid mode" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
PROFILE_cloud__STACK_TOKEN="token"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    result=$(resolve_splunk_target_role)

    rm -f "${credentials_file}"
    [ "${result}" = "search-tier" ]
}

@test "resolve_primary_splunk_target_role lets env override the selected profile role" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
PROFILE_cloud__STACK_TOKEN="token"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_TARGET_ROLE="indexer"

    source "${LIB_DIR}/credential_helpers.sh"
    result=$(resolve_primary_splunk_target_role)

    rm -f "${credentials_file}"
    unset SPLUNK_TARGET_ROLE
    [ "${result}" = "indexer" ]
}

@test "resolve_splunk_target_role uses the paired search target role when enterprise is active" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
PROFILE_cloud__STACK_TOKEN="token"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_PLATFORM="enterprise"

    source "${LIB_DIR}/credential_helpers.sh"
    result=$(resolve_splunk_target_role)

    rm -f "${credentials_file}"
    unset SPLUNK_PLATFORM
    [ "${result}" = "heavy-forwarder" ]
}

@test "resolve_splunk_target_role uses the paired role for single-profile hybrid enterprise runs" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="example-stack"
STACK_TOKEN="token"
SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_PLATFORM="enterprise"

    source "${LIB_DIR}/credential_helpers.sh"
    result=$(resolve_splunk_target_role)

    rm -f "${credentials_file}"
    unset SPLUNK_PLATFORM
    [ "${result}" = "heavy-forwarder" ]
}

@test "resolve_splunk_target_role uses the paired role without hybrid ambiguity output" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="example-stack"
STACK_TOKEN="token"
SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run resolve_splunk_target_role

    rm -f "${credentials_file}"
    [ "$status" -eq 0 ]
    [ "$output" = "heavy-forwarder" ]
}

@test "resolve_search_splunk_target_role accepts an explicit paired role without a search profile" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="example-stack"
STACK_TOKEN="token"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_SEARCH_TARGET_ROLE="external-collector"

    source "${LIB_DIR}/credential_helpers.sh"
    result=$(resolve_search_splunk_target_role)

    rm -f "${credentials_file}"
    unset SPLUNK_SEARCH_TARGET_ROLE
    [ "${result}" = "external-collector" ]
}

@test "load_splunk_credentials restores primary cloud credentials in hybrid mode" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
PROFILE_cloud__SPLUNK_USER="cloud-user"
PROFILE_cloud__SPLUNK_PASS="cloud-pass"
PROFILE_cloud__SPLUNK_TARGET_ROLE="search-tier"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://sh-forwarder.example.com:8089"
PROFILE_hf__SPLUNK_USER="hf-user"
PROFILE_hf__SPLUNK_PASS="hf-pass"
PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    unset SPLUNK_USER
    unset SPLUNK_PASS

    source "${LIB_DIR}/credential_helpers.sh"
    cloud_current_search_api_uri() { printf '%s' "https://shc1.example-stack.stg.splunkcloud.com:8089"; }
    # Model the real ACS preparation path, which reloads the configured paired
    # profile before the observed Cloud route is published.
    acs_ensure_search_api_access() { load_splunk_platform_settings; }

    load_splunk_credentials

    rm -f "${credentials_file}"
    [ "${SPLUNK_URI}" = "https://shc1.example-stack.stg.splunkcloud.com:8089" ]
    [ "${SPLUNK_SEARCH_API_URI}" = "https://shc1.example-stack.stg.splunkcloud.com:8089" ]
    [ "${SPLUNK_HOST}" = "shc1.example-stack.stg.splunkcloud.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8089" ]
    [ "${SPLUNK_USER}" = "cloud-user" ]
    [ "${SPLUNK_PASS}" = "cloud-pass" ]
}

@test "load_splunk_platform_settings infers staging ACS server from the selected cloud profile" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://example-stack.stg.splunkcloud.com:8089"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
PROFILE_hf__SPLUNK_USER="hf-user"
PROFILE_hf__SPLUNK_PASS="hf-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_platform_settings

    rm -f "${credentials_file}"
    [ "${ACS_SERVER}" = "https://staging.admin.splunk.com" ]
}

@test "search profile endpoint cannot redirect ACS away from the primary cloud environment" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_CLOUD_STACK="production-stack"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_HOST="unrelated.stg.splunkcloud.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    load_splunk_platform_settings
    primary_uri="$(_primary_cloud_search_api_uri)"

    [ "${SPLUNK_URI}" = "https://unrelated.stg.splunkcloud.com:8089" ]
    [ "${ACS_SERVER}" = "https://admin.splunk.com" ]
    [ "${primary_uri}" = "https://production-stack.splunkcloud.com:8089" ]
}

@test "load_splunk_platform_settings rejects an unrecognized explicit Cloud search head" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="cloud"
SPLUNK_CLOUD_STACK="example-stack"
SPLUNK_CLOUD_SEARCH_HEAD="unrecognized.example.splunkcloud.com"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    source "${LIB_DIR}/credential_helpers.sh"

    run load_splunk_platform_settings

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"recognized ACS search-head prefix"* ]]
    [[ "${output}" != *"unrecognized.example"* ]]
}

@test "load_splunk_credentials falls back to the primary cloud URI when current search head lookup fails" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
PROFILE_cloud__SPLUNK_SEARCH_API_URI="https://example-stack.stg.splunkcloud.com:8089"
PROFILE_cloud__STACK_USERNAME="stack-user"
PROFILE_cloud__STACK_PASSWORD="stack-pass"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
PROFILE_hf__SPLUNK_USER="hf-user"
PROFILE_hf__SPLUNK_PASS="hf-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    unset SPLUNK_USER
    unset SPLUNK_PASS

    source "${LIB_DIR}/credential_helpers.sh"
    cloud_current_search_api_uri() { return 1; }
    acs_ensure_search_api_access() { return 0; }

    load_splunk_credentials

    rm -f "${credentials_file}"
    [ "${SPLUNK_URI}" = "https://example-stack.stg.splunkcloud.com:8089" ]
    [ "${SPLUNK_SEARCH_API_URI}" = "https://example-stack.stg.splunkcloud.com:8089" ]
    [ "${SPLUNK_HOST}" = "example-stack.stg.splunkcloud.com" ]
    [ "${SPLUNK_MGMT_PORT}" = "8089" ]
    [ "${SPLUNK_USER}" = "stack-user" ]
    [ "${SPLUNK_PASS}" = "stack-pass" ]
}

@test "load_splunk_credentials preserves env overrides after refreshing the cloud URI" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PROFILE="cloud"
SPLUNK_SEARCH_PROFILE="hf"
PROFILE_cloud__SPLUNK_PLATFORM="cloud"
PROFILE_cloud__SPLUNK_CLOUD_STACK="example-stack"
PROFILE_cloud__ACS_SERVER="https://staging.admin.splunk.com"
PROFILE_cloud__STACK_TOKEN="token"
PROFILE_cloud__STACK_USERNAME="stack-user"
PROFILE_cloud__STACK_PASSWORD="stack-pass"
PROFILE_cloud__SPLUNK_USER="cloud-user"
PROFILE_cloud__SPLUNK_PASS="cloud-pass"
PROFILE_hf__SPLUNK_PLATFORM="enterprise"
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
PROFILE_hf__SPLUNK_USER="hf-user"
PROFILE_hf__SPLUNK_PASS="hf-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_USER="altadmin"
    export SPLUNK_PASS="altpass"

    source "${LIB_DIR}/credential_helpers.sh"
    cloud_current_search_api_uri() { printf '%s' "https://shc1.example-stack.stg.splunkcloud.com:8089"; }
    acs_ensure_search_api_access() { return 0; }

    load_splunk_credentials

    rm -f "${credentials_file}"
    [ "${SPLUNK_URI}" = "https://shc1.example-stack.stg.splunkcloud.com:8089" ]
    [ "${SPLUNK_USER}" = "altadmin" ]
    [ "${SPLUNK_PASS}" = "altpass" ]
    unset SPLUNK_USER
    unset SPLUNK_PASS
}

@test "warn_if_role_unsupported_for_app_id returns success for warning-only checks" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_TARGET_ROLE="universal-forwarder"
SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run warn_if_role_unsupported_for_app_id "7539"

    rm -f "${credentials_file}"
    [ "$status" -eq 0 ]
    [[ "${output}" == *"not modeled for role 'universal-forwarder'"* ]]
}

@test "resolve_splunk_target_role rejects invalid declared roles" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_TARGET_ROLE="not-a-role"
SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run resolve_splunk_target_role

    rm -f "${credentials_file}"
    [ "$status" -ne 0 ]
    [[ "${output}" == *"SPLUNK_TARGET_ROLE must be"* ]]
    [[ "${output}" != *"not-a-role"* ]]
}

@test "automatic deployment routing rejects an invalid explicit target role" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="enterprise"
SPLUNK_TARGET_ROLE="not-a-role"
SPLUNK_DELIVERY_PLANE="auto"
SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run deployment_should_use_bundle_for_current_target

    [ "$status" -eq 2 ]
    [[ "${output}" == *"SPLUNK_TARGET_ROLE must be"* ]]
    [[ "${output}" != *"not-a-role"* ]]
}

@test "deployment REST context rejects partial session output from failed authentication" {
    credentials_file=$(mktemp)
    TEST_TEMP_FILES+=("${credentials_file}")
    cat > "${credentials_file}" <<'EOF'
SPLUNK_PLATFORM="enterprise"
SPLUNK_SEARCH_API_URI="https://search.example.invalid:8089"
SPLUNK_USER="search-user"
SPLUNK_PASS="search-pass"
PROFILE_manager__SPLUNK_SEARCH_API_URI="https://manager.example.invalid:8089"
PROFILE_manager__SPLUNK_USER="manager-user"
PROFILE_manager__SPLUNK_PASS="manager-pass"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    get_session_key() {
        printf '%s' "partial-session-output"
        return 1
    }

    run deployment_prepare_rest_context \
        "manager" "" "https://search.example.invalid:8089"

    [ "${status}" -ne 0 ]
    [ -z "${output}" ]
}

@test "warn_if_cloud_pairing_missing_for_skill stays quiet for enterprise-side hybrid runs" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="example-stack"
STACK_TOKEN="token"
SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
SPLUNK_TARGET_ROLE="search-tier"
SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run warn_if_cloud_pairing_missing_for_skill "splunk-stream-setup"

    rm -f "${credentials_file}"
    [ "$status" -eq 0 ]
    [ -z "${output}" ]
}

@test "warn_if_cloud_pairing_missing_for_skill warns for a cloud workflow with no paired role" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="example-stack"
STACK_TOKEN="token"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run warn_if_cloud_pairing_missing_for_skill "splunk-stream-setup"

    rm -f "${credentials_file}"
    [ "$status" -eq 0 ]
    [[ "${output}" == *"expects a paired Cloud runtime role: heavy-forwarder or universal-forwarder"* ]]
}

@test "warn_if_cloud_pairing_missing_for_skill stays quiet when the paired role is declared" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_CLOUD_STACK="example-stack"
STACK_TOKEN="token"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    export SPLUNK_SEARCH_TARGET_ROLE="heavy-forwarder"

    source "${LIB_DIR}/credential_helpers.sh"
    run warn_if_cloud_pairing_missing_for_skill "splunk-stream-setup"

    rm -f "${credentials_file}"
    unset SPLUNK_SEARCH_TARGET_ROLE
    [ "$status" -eq 0 ]
    [ -z "${output}" ]
}
