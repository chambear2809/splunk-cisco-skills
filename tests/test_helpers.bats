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
    export SPLUNK_USER="testuser"
    export SPLUNK_PASS="testpass"
    export SPLUNK_VERIFY_SSL="false"

    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    LIB_DIR="${PROJECT_ROOT}/skills/shared/lib"
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

@test "form_urlencode_pairs rejects odd number of args" {
    source "${LIB_DIR}/rest_helpers.sh"
    run form_urlencode_pairs key1
    [ "$status" -eq 1 ]
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

# --- _curl_ssl_flags ---

@test "_curl_ssl_flags returns -sk when SPLUNK_VERIFY_SSL is false" {
    source "${LIB_DIR}/rest_helpers.sh"
    export SPLUNK_VERIFY_SSL="false"
    result=$(_curl_ssl_flags)
    [ "$result" = "-sk" ]
}

@test "_curl_ssl_flags returns -s when SPLUNK_VERIFY_SSL is true" {
    source "${LIB_DIR}/rest_helpers.sh"
    export SPLUNK_VERIFY_SSL="true"
    result=$(_curl_ssl_flags)
    [ "$result" = "-s" ]
}

@test "_curl_ssl_flags defaults to -sk when unset" {
    source "${LIB_DIR}/rest_helpers.sh"
    unset SPLUNK_VERIFY_SSL
    result=$(_curl_ssl_flags)
    [ "$result" = "-sk" ]
}

@test "_curl_ssl_flags returns -s when SPLUNK_CA_CERT is set" {
    source "${LIB_DIR}/rest_helpers.sh"
    tmpfile=$(mktemp)
    export SPLUNK_CA_CERT="$tmpfile"
    result=$(_curl_ssl_flags)
    rm -f "$tmpfile"
    unset SPLUNK_CA_CERT
    [ "$result" = "-s" ]
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

@test "_set_splunkbase_curl_tls_args verifies by default" {
    source "${LIB_DIR}/rest_helpers.sh"
    unset SPLUNKBASE_VERIFY_SSL
    unset SPLUNKBASE_CA_CERT
    _set_splunkbase_curl_tls_args
    [ "${#_tls_verify_args[@]}" -eq 0 ]
}

@test "_set_app_download_curl_tls_args inherits insecure Splunk mode by default" {
    source "${LIB_DIR}/rest_helpers.sh"
    export SPLUNK_VERIFY_SSL="false"
    unset APP_DOWNLOAD_VERIFY_SSL
    unset APP_DOWNLOAD_CA_CERT
    _set_app_download_curl_tls_args
    [ "${_tls_verify_args[0]}" = "-k" ]
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

# --- _is_splunk_package ---

@test "_is_splunk_package rejects non-tar file" {
    source "${LIB_DIR}/rest_helpers.sh"
    tmpfile=$(mktemp)
    echo "not a tar file" > "$tmpfile"
    run _is_splunk_package "$tmpfile"
    rm -f "$tmpfile"
    [ "$status" -ne 0 ]
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
