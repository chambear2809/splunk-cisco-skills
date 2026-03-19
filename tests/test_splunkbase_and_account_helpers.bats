#!/usr/bin/env bats
# Tests for splunkbase_helpers.sh and configure_account_helpers.sh.
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
    export SB_USER="testsbuser"
    export SB_PASS="testsbpass"

    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    LIB_DIR="${PROJECT_ROOT}/skills/shared/lib"
}

# --- _read_cookie_jar_value ---

@test "_read_cookie_jar_value reads a cookie from a Netscape jar file" {
    source "${LIB_DIR}/splunkbase_helpers.sh"
    tmpfile=$(mktemp)
    cat > "$tmpfile" <<'JAR'
# Netscape HTTP Cookie File
.splunkbase.splunk.com	TRUE	/	TRUE	0	sessionid	abc123
.splunkbase.splunk.com	TRUE	/	TRUE	0	csrf_splunkbase_token	xyz789
JAR
    result=$(_read_cookie_jar_value "$tmpfile" "sessionid")
    rm -f "$tmpfile"
    [ "$result" = "abc123" ]
}

@test "_read_cookie_jar_value reads csrf token" {
    source "${LIB_DIR}/splunkbase_helpers.sh"
    tmpfile=$(mktemp)
    cat > "$tmpfile" <<'JAR'
# Netscape HTTP Cookie File
.splunkbase.splunk.com	TRUE	/	TRUE	0	sessionid	abc123
.splunkbase.splunk.com	TRUE	/	TRUE	0	csrf_splunkbase_token	xyz789
JAR
    result=$(_read_cookie_jar_value "$tmpfile" "csrf_splunkbase_token")
    rm -f "$tmpfile"
    [ "$result" = "xyz789" ]
}

@test "_read_cookie_jar_value returns empty for missing cookie" {
    source "${LIB_DIR}/splunkbase_helpers.sh"
    tmpfile=$(mktemp)
    echo "# empty jar" > "$tmpfile"
    result=$(_read_cookie_jar_value "$tmpfile" "sessionid")
    rm -f "$tmpfile"
    [ -z "$result" ]
}

@test "_read_cookie_jar_value handles missing file gracefully" {
    source "${LIB_DIR}/splunkbase_helpers.sh"
    result=$(_read_cookie_jar_value "/nonexistent/cookie.jar" "sessionid")
    [ -z "$result" ]
}

# --- get_splunkbase_release_metadata ---

@test "get_splunkbase_release_metadata fails on empty API response" {
    source "${LIB_DIR}/splunkbase_helpers.sh"
    # Override curl to return empty response
    curl() { echo ""; return 0; }
    export -f curl
    run get_splunkbase_release_metadata "9999" ""
    [ "$status" -ne 0 ]
}

# --- rest_create_or_update_account (configure_account_helpers.sh) ---

@test "rest_create_or_update_account returns HTTP code on 201 create" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/configure_account_helpers.sh"

    # Mock splunk_curl_post to return 201
    splunk_curl_post() {
        echo "response body"
        echo "201"
    }
    export -f splunk_curl_post

    result=$(rest_create_or_update_account "sk" "http://test/endpoint" "acct1" "name=acct1" "field=val")
    [ "$result" = "201" ]
}

@test "rest_create_or_update_account falls back to update on 409" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/configure_account_helpers.sh"

    _MOCK_COUNTER=$(mktemp)
    echo "0" > "$_MOCK_COUNTER"
    export _MOCK_COUNTER

    splunk_curl_post() {
        local n
        n=$(cat "$_MOCK_COUNTER")
        n=$((n + 1))
        echo "$n" > "$_MOCK_COUNTER"
        if [ "$n" -eq 1 ]; then
            echo "conflict"
            echo "409"
        else
            echo "updated"
            echo "200"
        fi
    }
    export -f splunk_curl_post

    result=$(rest_create_or_update_account "sk" "http://test/endpoint" "acct1" "name=acct1" "field=val")
    rm -f "$_MOCK_COUNTER"
    [ "$result" = "200" ]
}

@test "rest_create_or_update_account fails on non-retryable error" {
    source "${LIB_DIR}/rest_helpers.sh"
    source "${LIB_DIR}/configure_account_helpers.sh"

    splunk_curl_post() {
        echo "server error"
        echo "500"
    }
    export -f splunk_curl_post

    run rest_create_or_update_account "sk" "http://test/endpoint" "acct1" "name=acct1" "field=val"
    [ "$status" -eq 1 ]
}
