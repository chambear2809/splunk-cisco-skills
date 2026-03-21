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
    export _RESOLVED_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_SEARCH_SPLUNK_TARGET_ROLE=""
    export _WARNED_INVALID_SPLUNK_TARGET_ROLE=""
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
PROFILE_hf__SPLUNK_SEARCH_API_URI="https://hf.example.com:8089"
PROFILE_hf__SPLUNK_USER="hf-user"
PROFILE_hf__SPLUNK_PASS="hf-pass"
PROFILE_hf__SPLUNK_TARGET_ROLE="heavy-forwarder"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"
    unset SPLUNK_USER
    unset SPLUNK_PASS

    source "${LIB_DIR}/credential_helpers.sh"
    cloud_current_search_api_uri() { printf '%s' "https://shc1.example-stack.stg.splunkcloud.com:8089"; }
    acs_ensure_search_api_access() { return 0; }

    load_splunk_credentials

    rm -f "${credentials_file}"
    [ "${SPLUNK_URI}" = "https://shc1.example-stack.stg.splunkcloud.com:8089" ]
    [ "${SPLUNK_USER}" = "cloud-user" ]
    [ "${SPLUNK_PASS}" = "cloud-pass" ]
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

@test "resolve_splunk_target_role ignores invalid declared roles" {
    credentials_file=$(mktemp)
    cat > "${credentials_file}" <<'EOF'
SPLUNK_TARGET_ROLE="not-a-role"
SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
EOF
    export SPLUNK_CREDENTIALS_FILE="${credentials_file}"

    source "${LIB_DIR}/credential_helpers.sh"
    run resolve_splunk_target_role

    rm -f "${credentials_file}"
    [ "$status" -eq 0 ]
    [[ "${output}" == *"Ignoring invalid SPLUNK_TARGET_ROLE value"* ]]
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
