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
