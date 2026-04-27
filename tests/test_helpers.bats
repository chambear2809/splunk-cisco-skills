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
    export _RESOLVED_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_PRIMARY_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_SEARCH_SPLUNK_TARGET_ROLE=""
    export _RESOLVED_SEARCH_CREDENTIAL_PROFILE=""
    export _WARNED_INVALID_SPLUNK_TARGET_ROLE=""
    export SPLUNK_USER="testuser"
    export SPLUNK_PASS="testpass"
    export SPLUNK_VERIFY_SSL="false"

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

@test "hbs_make_sshpass_file preserves existing cleanup trap" {
    source "${LIB_DIR}/host_bootstrap_helpers.sh"
    export SPLUNK_SSH_PASS="ssh-secret"
    marker_file=$(mktemp)
    rm -f "${marker_file}"

    trap "printf old > $(printf '%q' "${marker_file}")" EXIT
    pass_file="$(hbs_make_sshpass_file)"
    TEST_TEMP_FILES+=("${pass_file}" "${marker_file}")

    trap_output="$(trap -p EXIT)"
    [[ "${trap_output}" == *"printf old"* ]]
    [[ "${trap_output}" == *"rm -f"* ]]
    [[ "${trap_output}" == *"${pass_file}"* ]]

    rm -f "${pass_file}"
    trap - EXIT
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

@test "deployment_hec_token_record_from_conf parses bundle-managed inputs stanzas" {
    source "${LIB_DIR}/credential_helpers.sh"

    conf_content=$'[http]\ndisabled = 0\n\n[http://sc4s]\ndisabled = 0\nindex = sc4s\ntoken = abc-123\nuseACK = 0\n'

    run deployment_hec_token_record_from_conf "${conf_content}" "sc4s"

    [ "$status" -eq 0 ]
    [[ "$output" == *'"default_index": "sc4s"'* ]]
    [[ "$output" == *'"token": "abc-123"'* ]]
    [[ "$output" == *'"disabled": "0"'* ]]
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
