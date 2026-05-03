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

@test "sc4s setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-connect-for-syslog-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "SC4S Setup Automation" ]]
}

@test "sc4s validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-connect-for-syslog-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "SC4S Validation" ]]
}

@test "sc4snmp setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-connect-for-snmp-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "SC4SNMP Setup Automation" ]]
}

@test "sc4snmp validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-connect-for-snmp-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "SC4SNMP Validation" ]]
}

@test "enterprise host setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-host-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Host Setup" ]]
}

@test "enterprise host validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-host-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Host Validation" ]]
}

@test "enterprise kubernetes setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Kubernetes Setup" ]]
}

@test "enterprise kubernetes validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Kubernetes Validation" ]]
}

@test "observability otel collector setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Observability OTel Collector setup" ]]
    [[ "$output" =~ "--render-platform-hec-helper" ]]
}

@test "observability otel collector validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Observability OTel Collector validation" ]]
    [[ "$output" =~ "--check-platform-hec" ]]
}

@test "agent management setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-agent-management-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Agent Management Setup" ]]
}

@test "agent management validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-agent-management-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Agent Management Validation" ]]
}

@test "workload management setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-workload-management-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Workload Management Setup" ]]
}

@test "workload management validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-workload-management-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Workload Management Validation" ]]
}

@test "hec service setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-hec-service-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk HEC Service Setup" ]]
}

@test "hec service validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-hec-service-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk HEC Service Validation" ]]
}

@test "federated search setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-federated-search-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Federated Search Setup" ]]
}

@test "federated search validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-federated-search-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Federated Search Validation" ]]
}

@test "smartstore setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Index Lifecycle / SmartStore Setup" ]]
}

@test "smartstore validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-index-lifecycle-smartstore-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Index Lifecycle / SmartStore Validation" ]]
}

@test "monitoring console setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-monitoring-console-setup/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Monitoring Console Setup" ]]
}

@test "monitoring console validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-monitoring-console-setup/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Monitoring Console Validation" ]]
}

@test "enterprise security install setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Security Install" ]]
}

@test "enterprise security install validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Security Install Validation" ]]
}

@test "enterprise security config setup --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Security Configuration" ]]
    [[ "$output" =~ "--spec PATH" ]]
    [[ "$output" =~ "--mode preview|apply|validate|inventory|export" ]]
    [[ "$output" =~ "--baseline" ]]
    [[ "$output" =~ "--all-indexes" ]]
}

@test "enterprise security config validate --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/validate.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk Enterprise Security Configuration Validation" ]]
}

@test "enterprise host smoke latest resolution --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-host-setup/scripts/smoke_latest_resolution.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Latest Resolution Smoke Test" ]]
}

@test "sc4s setup rejects invalid vendor port protocol" {
    run bash "${PROJECT_ROOT}/skills/splunk-connect-for-syslog-setup/scripts/setup.sh" \
      --render-host \
      --vendor-port checkpoint:ietf_udp:9000
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Invalid value 'ietf_udp'" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "sc4snmp setup rejects invalid hec tls verify" {
    combined="$(bash "${PROJECT_ROOT}/skills/splunk-connect-for-snmp-setup/scripts/setup.sh" \
      --render-compose \
      --hec-tls-verify maybe 2>&1 || true)"
    [[ "$combined" =~ "Expected yes or no" ]]
    [[ ! "$combined" =~ "unbound variable" ]]
}

@test "sc4snmp setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-connect-for-snmp-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "sc4snmp validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-connect-for-snmp-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "agent management setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-agent-management-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "workload management setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-workload-management-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "hec service setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-hec-service-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "federated search setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-federated-search-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "smartstore setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-index-lifecycle-smartstore-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "monitoring console setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-monitoring-console-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "federated search validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-federated-search-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "smartstore validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-index-lifecycle-smartstore-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "monitoring console validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-monitoring-console-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security install rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security install rejects --source without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --source
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security install rejects invalid deployment type" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" \
      --deployment-type invalid
    [ "$status" -eq 1 ]
    [[ "$output" =~ "--deployment-type must be search_head or shc_deployer" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security install exposes new preflight and bundle flags in help" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "--preflight-only" ]]
    [[ "$output" =~ "--skip-preflight" ]]
    [[ "$output" =~ "--confirm-upgrade" ]]
    [[ "$output" =~ "--backup-notice PATH" ]]
    [[ "$output" =~ "--set-shc-limits" ]]
    [[ "$output" =~ "--allow-deployment-client" ]]
    [[ "$output" =~ "--apply-bundle" ]]
    [[ "$output" =~ "--shc-target-uri URI" ]]
    [[ "$output" =~ "--generate-ta-for-indexers DIR" ]]
    [[ "$output" =~ "--deploy-ta-for-indexers CM_URI" ]]
    [[ "$output" =~ "--backup-kvstore" ]]
    [[ "$output" =~ "--uninstall" ]]
}

@test "enterprise security install rejects --backup-notice without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --backup-notice
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security install rejects --shc-target-uri without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --shc-target-uri
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
}

@test "enterprise security install rejects --generate-ta-for-indexers without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --generate-ta-for-indexers
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
}

@test "enterprise security install rejects --deploy-ta-for-indexers without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --deploy-ta-for-indexers
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
}

@test "ta_for_indexers generator --help exits 0" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/generate_ta_for_indexers.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Splunk_TA_ForIndexers Generator" ]]
    [[ "$output" =~ "--package PATH" ]]
    [[ "$output" =~ "--output-dir DIR" ]]
}

@test "ta_for_indexers generator rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/generate_ta_for_indexers.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "ta_for_indexers generator extracts Splunk_TA_ForIndexers when ES package present" {
    if ! ls "${PROJECT_ROOT}/splunk-ta/splunk-enterprise-security_"*.spl >/dev/null 2>&1; then
        skip "Local ES package is not present; skip extraction smoke test"
    fi
    out_dir="${MOCK_DIR}/ta-fi-extract"
    mkdir -p "${out_dir}"
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/generate_ta_for_indexers.sh" \
        --output-dir "${out_dir}" --force
    [ "$status" -eq 0 ]
    # The last stdout line is the generated file path.
    generated_path="$(printf '%s\n' "$output" | tail -1)"
    [ -f "${generated_path}" ]
    [[ "${generated_path}" =~ Splunk_TA_ForIndexers ]]
}

@test "enterprise security install generate-only path runs without Splunk credentials" {
    if ! ls "${PROJECT_ROOT}/splunk-ta/splunk-enterprise-security_"*.spl >/dev/null 2>&1; then
        skip "Local ES package is not present; skip extraction smoke test"
    fi
    empty_creds="${MOCK_DIR}/empty_creds"
    : > "${empty_creds}"
    out_dir="${MOCK_DIR}/ta-fi-via-setup"
    mkdir -p "${out_dir}"
    run env SPLUNK_CREDENTIALS_FILE="${empty_creds}" bash \
        "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" \
        --generate-ta-for-indexers "${out_dir}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Generate Splunk_TA_ForIndexers" ]]
    [[ ! "$output" =~ "ERROR: Splunk credentials are required" ]]
}

@test "enterprise security config rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security config rejects --enable-dm without value" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --enable-dm
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security config rejects invalid declarative mode" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --mode nope
    [ "$status" -eq 1 ]
    [[ "$output" =~ "--mode must be preview, apply, validate, inventory, or export" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security config requires --apply for apply mode" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --mode apply
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Declarative apply mode requires --apply" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security config rejects --apply with non-apply mode" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --mode preview --apply
    [ "$status" -eq 1 ]
    [[ "$output" =~ "--apply cannot be combined with --mode preview" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security config previews JSON spec without writes" {
    spec_path="${MOCK_DIR}/es-config.json"
    printf '{"baseline":{"enabled":true,"lookup_order":true},"indexes":{"groups":["exposure"]}}' > "${spec_path}"

    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --spec "${spec_path}" --mode preview
    [ "$status" -eq 0 ]
    [[ "$output" =~ '"mode": "preview"' ]]
    [[ "$output" =~ "ea_discovery" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security config writes preview output file" {
    output_path="${MOCK_DIR}/preview.json"

    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --output "${output_path}"
    [ "$status" -eq 0 ]
    [[ -s "${output_path}" ]]
    run grep -q '"mode": "preview"' "${output_path}"
    [ "$status" -eq 0 ]
}

@test "enterprise security config combines declarative spec with imperative shortcuts" {
    spec_path="${MOCK_DIR}/es-config-combo.json"
    printf '{"baseline":{"enabled":true,"lookup_order":true}}' > "${spec_path}"

    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" \
        --spec "${spec_path}" \
        --mode preview \
        --baseline
    [ "$status" -ne 0 ]
    # Declarative phase ran (preview JSON appears in stdout) AND the script
    # then announced the imperative phase before failing because there are
    # no real Splunk credentials in the test env.
    [[ "$output" =~ "imperative phase" ]] || [[ "$output" =~ "imperative" ]]
    [[ "$output" =~ '"mode": "preview"' ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise security config strict flag rejects unknown sections" {
    spec_path="${MOCK_DIR}/es-config-typo.json"
    printf '{"valdation":{"searches":[]}}' > "${spec_path}"

    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" \
        --spec "${spec_path}" \
        --mode preview \
        --strict
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Strict mode" ]] || [[ "$output" =~ "unknown top-level" ]]
    [[ "$output" =~ "valdation" ]]
}

@test "enterprise security config --stop-on-error appears in help text" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-config/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "--stop-on-error" ]]
    [[ "$output" =~ "--strict" ]]
}

@test "enterprise security install --force-apply-bundle appears in help text" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-security-install/scripts/setup.sh" --help
    [ "$status" -eq 0 ]
    [[ "$output" =~ "--force-apply-bundle" ]]
}

@test "deployment helpers preserve passwords containing colons" {
    # Inline reproduction of the newline-delimited credential file logic
    # added to skills/shared/lib/deployment_helpers.sh. Verifies that a
    # password with ':' is recovered intact, which would have silently
    # truncated under the old `auth_value%%:*` colon split.
    cred_file="${MOCK_DIR}/cred-with-colon"
    printf '%s\n%s\n' 'admin' 'p:a:s:s' > "${cred_file}"
    chmod 600 "${cred_file}"
    run bash -c '
set -euo pipefail
{ IFS= read -r auth_user; IFS= read -r auth_pass; } < "$1"
printf "user=%s\npass=%s\n" "${auth_user}" "${auth_pass}"
' _ "${cred_file}"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "user=admin" ]]
    [[ "$output" =~ "pass=p:a:s:s" ]]
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

# --- unknown-flag rejection for Cisco TA and platform setup scripts ---

@test "catalyst-ta setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-catalyst-ta-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "meraki-ta setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-meraki-ta-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "dc-networking setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-dc-networking-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "intersight setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-intersight-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "thousandeyes setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-thousandeyes-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "appdynamics setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-appdynamics-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "secure-access setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-secure-access-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "security-cloud setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-security-cloud-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "enhanced-netflow setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-catalyst-enhanced-netflow-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "enterprise-networking setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-enterprise-networking-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "stream setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-stream-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "product-setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-product-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "enterprise kubernetes setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise kubernetes setup rejects missing values" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/setup.sh" --target
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "enterprise kubernetes validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-enterprise-kubernetes-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "observability otel collector setup rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "observability otel collector setup rejects missing flag values" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/setup.sh" --realm
    [ "$status" -eq 1 ]
    [[ "$output" =~ "requires a value" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "observability otel collector validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/splunk-observability-otel-collector-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
    [[ ! "$output" =~ "unbound variable" ]]
}

@test "secure-access validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-secure-access-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}

@test "security-cloud validate rejects unknown flag" {
    run bash "${PROJECT_ROOT}/skills/cisco-security-cloud-setup/scripts/validate.sh" --bogus
    [ "$status" -eq 1 ]
    [[ "$output" =~ "Unknown option" ]]
}
