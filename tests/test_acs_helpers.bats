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
    unset SPLUNK_PROFILE SPLUNK_SEARCH_PROFILE SPLUNK_INGEST_PROFILE
    unset SPLUNK_DEPLOYER_PROFILE SPLUNK_CLUSTER_MANAGER_PROFILE
    unset SPLUNK_SEARCH_API_URI SPLUNK_URI SPLUNK_HOST SPLUNK_MGMT_PORT
    unset SPLUNK_CLOUD_STACK SPLUNK_CLOUD_SEARCH_HEAD
    unset ACS_BOUND_TARGET_CONTEXT ACS_BOUND_REQUIRE_CONFIG_MATCH ACS_BOUND_SERVER
    unset ACS_BOUND_SPLUNK_CLOUD_STACK ACS_BOUND_SPLUNK_CLOUD_SEARCH_HEAD
    export _ACS_CONTEXT_PREPARED="false"
    export _ACS_CONTEXT_TARGET=""
    export _ACS_CONTEXT_IDENTITY=""
    export _CREDENTIAL_FILE_WAS_USED=""
    load_splunk_platform_settings() { :; }

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

@test "ACS app inventory rejects empty malformed and schema-incomplete pages" {
    source "${LIB_DIR}/acs_helpers.sh"
    acs_command() {
        printf '%s' "${ACS_APPS_BODY}"
    }
    export -f acs_command

    for ACS_APPS_BODY in '' 'not-json' '{}' '{"apps":{}}' '{"apps":["not-an-app-record"]}'; do
        export ACS_APPS_BODY
        run acs_apps_list_all_json --splunkbase
        [ "${status}" -ne 0 ]
    done

    export ACS_APPS_BODY='{"apps":[]}'
    run acs_apps_list_all_json --splunkbase
    [ "${status}" -eq 0 ]
    [ "${output}" = '{"apps": []}' ]
}

@test "allowlist describe rejects missing or malformed subnet observations" {
    source "${LIB_DIR}/acs_helpers.sh"
    acs_command() {
        printf '%s' "${ACS_ALLOWLIST_BODY}"
    }
    export -f acs_command

    for ACS_ALLOWLIST_BODY in '' 'not-json' '{}' '{"subnets":{}}' '{"subnets":[7]}'; do
        export ACS_ALLOWLIST_BODY
        run acs_ipallowlist_describe search-api
        [ "${status}" -ne 0 ]
        run acs_ipallowlist_describe_v6 search-api
        [ "${status}" -ne 0 ]
    done
}

@test "allowlist apply refuses mutation when baseline observation is incomplete" {
    source "${LIB_DIR}/acs_helpers.sh"
    marker="${BATS_TMPDIR}/allowlist-mutation-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export ACS_ALLOWLIST_MUTATION_MARKER="${marker}"
    acs_command() {
        if [[ "$2" == "describe" ]]; then
            printf '%s' '{}'
            return 0
        fi
        touch "${ACS_ALLOWLIST_MUTATION_MARKER}"
    }
    export -f acs_command

    run acs_ipallowlist_apply_plan search-api ipv4 198.51.100.1/32

    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "search API access refuses allowlist creation after an incomplete observation" {
    source "${LIB_DIR}/acs_helpers.sh"
    marker="${BATS_TMPDIR}/search-api-allowlist-mutation-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export ACS_ALLOWLIST_MUTATION_MARKER="${marker}"
    acs_prepare_context() { return 0; }
    _detect_public_ip() { printf '%s' '198.51.100.10'; }
    acs_command() {
        if [[ "$1 $2 $3" == "ip-allowlist list search-api" ]]; then
            printf '%s' '{}'
            return 0
        fi
        touch "${ACS_ALLOWLIST_MUTATION_MARKER}"
    }
    export -f acs_prepare_context _detect_public_ip acs_command

    run acs_ensure_search_api_access

    [ "${status}" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "acs_stack_status_snapshot requires observed infrastructure and restart state" {
    source "${LIB_DIR}/acs_helpers.sh"
    acs_prepare_context() { return 0; }
    acs_command() {
        printf '%s' '{"infrastructure":{"status":"Ready"},"messages":{"restartRequired":false}}'
    }
    export -f acs_prepare_context acs_command

    run acs_stack_status_snapshot
    [ "$status" -eq 0 ]
    [ "$output" = $'Ready\tfalse' ]
}

@test "acs restart status rejects empty malformed and incomplete observations" {
    source "${LIB_DIR}/acs_helpers.sh"
    acs_prepare_context() { return 0; }
    acs_command() {
        printf '%s' "${ACS_STATUS_BODY}"
    }
    export -f acs_prepare_context acs_command

    for ACS_STATUS_BODY in \
        '' \
        'not-json' \
        '{}' \
        '{"infrastructure":{"status":"Ready"}}' \
        '{"infrastructure":{"status":"Ready"},"messages":{"restartRequired":"false"}}' \
        '{"infrastructure":{"status":"Failed"},"messages":{"restartRequired":false}}' \
        '{"infrastructure":{"status":"Pending"},"messages":{"restartRequired":false}}'; do
        export ACS_STATUS_BODY
        run acs_restart_required
        [ "$status" -ne 0 ]
        [ "$output" != "false" ]
    done
}

@test "cloud restart refuses mutation when status observation is incomplete" {
    source "${LIB_DIR}/acs_helpers.sh"
    marker="${BATS_TMPDIR}/acs-restart-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export ACS_RESTART_MARKER="${marker}"
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "status" ]]; then
            printf '%s' '{}'
            return 0
        fi
        touch "${ACS_RESTART_MARKER}"
    }
    export -f acs_prepare_context acs_command

    run cloud_restart_if_required 1
    [ "$status" -ne 0 ]
    [ ! -e "${marker}" ]
}

@test "cloud restart does not report success when restart is false but stack is not Ready" {
    source "${LIB_DIR}/acs_helpers.sh"
    marker="${BATS_TMPDIR}/acs-nonready-restart-marker-${BASHPID}"
    TEST_TEMP_FILES+=("${marker}")
    export ACS_RESTART_MARKER="${marker}"
    acs_prepare_context() { return 0; }
    acs_command() {
        if [[ "$1" == "status" ]]; then
            printf '%s' "{\"infrastructure\":{\"status\":\"${ACS_INFRA_STATUS}\"},\"messages\":{\"restartRequired\":false}}"
            return 0
        fi
        touch "${ACS_RESTART_MARKER}"
    }
    export -f acs_prepare_context acs_command

    for ACS_INFRA_STATUS in Failed Pending; do
        export ACS_INFRA_STATUS
        run cloud_restart_if_required 1
        [ "$status" -ne 0 ]
        [[ "$output" == *"not Ready"* ]]
        [ ! -e "${marker}" ]
    done
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

@test "acs_rest_curl propagates platform settings loader failures" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/acs_helpers.sh"
    load_splunk_platform_settings() { return 1; }
    export STACK_TOKEN='test-token'

    run acs_rest_curl "https://admin.splunk.com/test"

    [ "${status}" -ne 0 ]
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

@test "rendered ACS target binding refuses changed configured target before mutation" {
    mock_dir="$(mktemp -d)"
    TEST_TEMP_FILES+=("${mock_dir}")
    marker="${mock_dir}/acs-ran"
    cat > "${mock_dir}/acs" <<'EOF'
#!/usr/bin/env bash
touch "${ACS_MUTATION_MARKER}"
EOF
    chmod +x "${mock_dir}/acs"

    source "${LIB_DIR}/acs_helpers.sh"
    load_splunk_platform_settings() { :; }
    export ACS_SERVER="https://admin.splunk.com"
    export SPLUNK_CLOUD_STACK="changed-stack"
    export SPLUNK_CLOUD_SEARCH_HEAD=""
    export ACS_BOUND_TARGET_CONTEXT=true
    export ACS_BOUND_REQUIRE_CONFIG_MATCH=true
    export ACS_BOUND_SERVER="https://admin.splunk.com"
    export ACS_BOUND_SPLUNK_CLOUD_STACK="reviewed-stack"
    export ACS_BOUND_SPLUNK_CLOUD_SEARCH_HEAD=""
    export ACS_MUTATION_MARKER="${marker}"

    PATH="${mock_dir}:${PATH}" run acs_command indexes create synthetic_index

    [ "${status}" -ne 0 ]
    [[ "${output}" == *"configured ACS stack changed"* ]]
    [ ! -e "${marker}" ]
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
