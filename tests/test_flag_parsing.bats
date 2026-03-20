#!/usr/bin/env bats
# Tests for flag argument guards and configure_account.sh argument parsing.
#
# Covers audit items 13 (require_arg), 14 (script flag basics), 16 (account parsing).
# Run with: bats tests/test_flag_parsing.bats

setup() {
    export _CRED_HELPERS_LOADED=""
    export _CREDENTIALS_LOADED=""
    export _REST_HELPERS_LOADED=""
    export _ACS_HELPERS_LOADED=""
    export _SPLUNKBASE_HELPERS_LOADED=""
    export _CONFIGURE_ACCOUNT_HELPERS_LOADED=""

    TEST_DIR="$(cd "$(dirname "$BATS_TEST_FILENAME")" && pwd)"
    PROJECT_ROOT="$(cd "${TEST_DIR}/.." && pwd)"
    LIB_DIR="${PROJECT_ROOT}/skills/shared/lib"

    # Create a mock credentials file so scripts source without error
    MOCK_DIR="$(mktemp -d)"
    MOCK_BIN="${MOCK_DIR}/bin"
    mkdir -p "${MOCK_BIN}"
    MOCK_CRED="${MOCK_DIR}/credentials"
    cat > "${MOCK_CRED}" <<'EOF'
SPLUNK_SEARCH_API_URI="https://example.invalid:8089"
SPLUNK_USER="user"
SPLUNK_PASS="pass"
EOF

    # Provide mock curl that always returns 401 (auth failure)
    cat > "${MOCK_BIN}/curl" <<'PYEOF'
#!/usr/bin/env python3
import sys
args = " ".join(sys.argv[1:])
if "%{http_code}" in args:
    sys.stdout.write("401")
raise SystemExit(0)
PYEOF
    chmod +x "${MOCK_BIN}/curl"

    # Provide mock nc
    cat > "${MOCK_BIN}/nc" <<'SH'
#!/usr/bin/env bash
exit 0
SH
    chmod +x "${MOCK_BIN}/nc"

    export PATH="${MOCK_BIN}:${PATH}"
    export SPLUNK_CREDENTIALS_FILE="${MOCK_CRED}"
}

teardown() {
    rm -rf "${MOCK_DIR}"
}

# --- require_arg ---

@test "require_arg succeeds when a value argument is present" {
    source "${LIB_DIR}/rest_helpers.sh"
    # Simulate: $1 is --flag, $# is 2 (flag + value)
    run require_arg "--flag" 2
    [ "$status" -eq 0 ]
}

@test "require_arg fails when value argument is missing" {
    source "${LIB_DIR}/rest_helpers.sh"
    # Simulate: $1 is --flag, $# is 1 (flag only, no value)
    run require_arg "--flag" 1
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Option '--flag' requires a value" ]]
}

# --- configure_account.sh missing required args ---

@test "catalyst-ta configure_account fails cleanly with no args" {
    run bash "${PROJECT_ROOT}/skills/cisco-catalyst-ta-setup/scripts/configure_account.sh"
    [ "$status" -eq 1 ]
    [[ "$output" =~ "--type and --name are required" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "meraki configure_account fails cleanly with no args" {
    run bash "${PROJECT_ROOT}/skills/cisco-meraki-ta-setup/scripts/configure_account.sh"
    [ "$status" -eq 1 ]
    [[ "$output" =~ "--name" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "intersight configure_account fails cleanly with no args" {
    run bash "${PROJECT_ROOT}/skills/cisco-intersight-setup/scripts/configure_account.sh"
    [ "$status" -eq 1 ]
    [[ "$output" =~ "--name" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "dc-networking configure_account fails cleanly with no args" {
    run bash "${PROJECT_ROOT}/skills/cisco-dc-networking-setup/scripts/configure_account.sh"
    [ "$status" -eq 1 ]
    [[ "$output" =~ "--type" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

# --- require_arg guard prevents unbound variable on missing flag value ---

@test "catalyst-ta configure_account rejects --type without value" {
    run bash "${PROJECT_ROOT}/skills/cisco-catalyst-ta-setup/scripts/configure_account.sh" --type
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "meraki configure_account rejects --name without value" {
    run bash "${PROJECT_ROOT}/skills/cisco-meraki-ta-setup/scripts/configure_account.sh" --name
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "dc-networking configure_account rejects --hostname without value" {
    run bash "${PROJECT_ROOT}/skills/cisco-dc-networking-setup/scripts/configure_account.sh" --hostname
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

# --- install_app.sh / uninstall_app.sh / configure_streams.sh flag basics ---

@test "install_app --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk App Installer" ]]
}

@test "uninstall_app --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-app-install/scripts/uninstall_app.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Uninstall a Splunk App" ]]
}

@test "configure_streams --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-stream-setup/scripts/configure_streams.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Stream Protocol Configuration" ]]
}

@test "install_app rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "install_app rejects --source without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-app-install/scripts/install_app.sh" --source
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "configure_streams rejects --enable without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-stream-setup/scripts/configure_streams.sh" --enable
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "security-cloud configure_product --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/cisco-security-cloud-setup/scripts/configure_product.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Cisco Security Cloud Product Setup" ]]
}

@test "security-cloud configure_product --list-products exits 0" {
    run bash "${PROJECT_ROOT}/skills/cisco-security-cloud-setup/scripts/configure_product.sh" --list-products
    [ "$status" -eq 0 ]
    [[ "$output" =~ "xdr" ]]
    [[ "$output" =~ "duo" ]]
}

@test "secure-access configure_settings --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/cisco-secure-access-setup/scripts/configure_settings.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Cisco Secure Access Settings Configuration" ]]
}

@test "secure-access configure_settings rejects invalid cloudlock boolean" {
    run bash "${PROJECT_ROOT}/skills/cisco-secure-access-setup/scripts/configure_settings.sh" \
      --org-id example-org \
      --cloudlock-incident-details maybe
    [ "$status" -eq 1 ]
    [[ "$output" =~ "must be true or false" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}
