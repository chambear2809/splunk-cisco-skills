#!/usr/bin/env bats
# Tests for acs_helpers.sh helpers.
# Requires bats-core: brew install bats-core

setup() {
    export _CRED_HELPERS_LOADED=""
    export _CREDENTIALS_LOADED=""
    export _REST_HELPERS_LOADED=""
    export _ACS_HELPERS_LOADED=""
    export _SPLUNKBASE_HELPERS_LOADED=""
    export _CONFIGURE_ACCOUNT_HELPERS_LOADED=""
    export SPLUNK_USER="testuser"
    export SPLUNK_PASS="testpass"
    export SPLUNK_VERIFY_SSL="false"

    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    LIB_DIR="${PROJECT_ROOT}/skills/shared/lib"

    TEST_TEMP_FILES=()
}

teardown() {
    for f in "${TEST_TEMP_FILES[@]+"${TEST_TEMP_FILES[@]}"}"; do
        rm -rf "${f}"
    done
}

# --- acs_cli_available ---

@test "acs_cli_available returns 0 when acs is on PATH" {
    source "${LIB_DIR}/acs_helpers.sh"
    # acs may or may not be installed; skip if missing
    if ! command -v acs >/dev/null 2>&1; then
        skip "acs CLI not installed"
    fi
    run acs_cli_available
    [ "$status" -eq 0 ]
}

@test "acs_cli_available returns non-zero when acs is missing" {
    source "${LIB_DIR}/acs_helpers.sh"
    PATH="/nonexistent" run acs_cli_available
    [ "$status" -ne 0 ]
}

# --- acs_extract_http_response_json ---

@test "acs_extract_http_response_json extracts response from structured list" {
    source "${LIB_DIR}/acs_helpers.sh"
    input='[{"type":"http","response":"{\"name\":\"test\"}"}]'
    result=$(echo "$input" | acs_extract_http_response_json)
    [ "$result" = '{"name": "test"}' ]
}

@test "acs_extract_http_response_json returns {} for empty input" {
    source "${LIB_DIR}/acs_helpers.sh"
    result=$(echo "" | acs_extract_http_response_json)
    [ "$result" = "{}" ]
}

@test "acs_extract_http_response_json passes through plain dict" {
    source "${LIB_DIR}/acs_helpers.sh"
    input='{"status":"Ready"}'
    result=$(echo "$input" | acs_extract_http_response_json)
    [ "$result" = '{"status": "Ready"}' ]
}

@test "acs_extract_http_response_json returns {} for non-JSON" {
    source "${LIB_DIR}/acs_helpers.sh"
    result=$(echo "not json" | acs_extract_http_response_json)
    [ "$result" = "{}" ]
}

# --- cloud_requires_local_scope ---

@test "cloud_requires_local_scope returns 0 when search head is set" {
    source "${LIB_DIR}/acs_helpers.sh"
    export SPLUNK_CLOUD_SEARCH_HEAD="shc1"
    run cloud_requires_local_scope
    [ "$status" -eq 0 ]
}

@test "cloud_requires_local_scope returns 1 when search head is empty" {
    source "${LIB_DIR}/acs_helpers.sh"
    export SPLUNK_CLOUD_SEARCH_HEAD=""
    run cloud_requires_local_scope
    [ "$status" -ne 0 ]
}

# --- acs_rest_curl transport policy ---

@test "acs_rest_curl disables curl config, redirects, and URL globbing" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    args_log="${mock_dir}/curl-args"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
EOF
    chmod +x "${mock_dir}/curl"

    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"
    export STACK_TOKEN='test-token'
    export CURL_ARGS_LOG="${args_log}"
    PATH="${mock_dir}:${PATH}" run acs_rest_curl \
        "https://admin.splunk.com/test/adminconfig/v2/private-connectivity/eligibility"

    [ "$status" -eq 0 ]
    [ "$(head -n 1 "${args_log}")" = "-q" ]
    grep -q -- "--proto" "${args_log}"
    grep -q -- "--proto-redir" "${args_log}"
    grep -q -- "--max-redirs" "${args_log}"
    grep -q -- "--globoff" "${args_log}"
    [ "$(tail -n 3 "${args_log}")" = $'--max-redirs\n0\n--globoff' ]
}

@test "acs_rest_curl rejects plaintext, userinfo, and caller curl configuration" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"
    export STACK_TOKEN='test-token'

    run acs_rest_curl "http://admin.splunk.com/test"
    [ "$status" -ne 0 ]
    [[ "$output" == *"HTTPS URL"* ]]

    run acs_rest_curl "https://user:do-not-echo@admin.splunk.com/test"
    [ "$status" -ne 0 ]
    [[ "$output" == *"credential-free"* ]]
    [[ "$output" != *"do-not-echo"* ]]

    run acs_rest_curl "https://admin.splunk.com/test" --config /tmp/override
    [ "$status" -ne 0 ]
    [[ "$output" == *"rejected"* ]]

    run acs_rest_curl "https://admin.splunk.com/test" --header "Authorization: Bearer override"
    [ "$status" -ne 0 ]
    [[ "$output" == *"authentication is helper-owned"* ]]

    run acs_rest_curl "https://admin.splunk.com/test" --header $'Content-Type: application/json\r\nX-Evil: yes'
    [ "$status" -ne 0 ]
    [[ "$output" == *"unsafe header"* ]]
}

@test "ACS token transport is pinned to allowlisted configured origins" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    curl_marker="${mock_dir}/curl-ran"
    acs_marker="${mock_dir}/acs-ran"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
touch "${CURL_MARKER}"
EOF
    cat > "${mock_dir}/acs" <<'EOF'
#!/usr/bin/env bash
touch "${ACS_MARKER}"
EOF
    chmod +x "${mock_dir}/curl" "${mock_dir}/acs"

    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"
    export STACK_TOKEN='test-token'
    export CURL_MARKER="${curl_marker}"
    export ACS_MARKER="${acs_marker}"
    export ACS_SERVER='https://admin.splunk.com'

    PATH="${mock_dir}:${PATH}" run acs_rest_curl "https://capture.invalid/steal"
    [ "$status" -ne 0 ]
    [[ "$output" == *"allowlisted ACS_SERVER origin"* ]]
    [ ! -e "${curl_marker}" ]

    export ACS_SERVER='https://capture.invalid'
    load_splunk_platform_settings() { :; }
    PATH="${mock_dir}:${PATH}" run acs_command status current-stack
    [ "$status" -ne 0 ]
    [[ "$output" == *"ACS_SERVER must be exactly"* ]]
    [ ! -e "${acs_marker}" ]

    export ACS_SERVER='https://staging.admin.splunk.com'
    PATH="${mock_dir}:${PATH}" run acs_rest_curl \
        "https://staging.admin.splunk.com/test/adminconfig/v2/status"
    [ "$status" -eq 0 ]
    [ -e "${curl_marker}" ]
}

@test "ACS public IP discovery ignores curlrc and does not follow redirects" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    args_log="${mock_dir}/curl-args"
    cat > "${mock_dir}/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${CURL_ARGS_LOG}"
printf '%s\n' '203.0.113.25'
EOF
    chmod +x "${mock_dir}/curl"

    source "${LIB_DIR}/acs_helpers.sh"
    export CURL_ARGS_LOG="${args_log}"
    old_path="${PATH}"
    PATH="${mock_dir}:${PATH}"
    result="$(_detect_public_ip)"
    PATH="${old_path}"

    [ "${result}" = "203.0.113.25" ]
    [ "$(head -n 1 "${args_log}")" = "-q" ]
    grep -q -- "--proto" "${args_log}"
    grep -q -- "--proto-redir" "${args_log}"
    grep -q -- "--max-redirs" "${args_log}"
    grep -q -- "--globoff" "${args_log}"
    ! grep -q -- "--location" "${args_log}"
}
