"""Contract coverage for the Cisco Catalyst TA setup skill."""

from __future__ import annotations

import json

from tests.regression_helpers import REPO_ROOT


SKILL_ROOT = REPO_ROOT / "skills" / "cisco-catalyst-ta-setup"


def test_setup_covers_current_parameter_complete_inputs_and_intervals() -> None:
    setup = (SKILL_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")

    expected_inputs = {
        "cisco_catalyst_dnac_clienthealth": "300",
        "cisco_catalyst_dnac_devicehealth": "300",
        "cisco_catalyst_dnac_compliance": "900",
        "cisco_catalyst_dnac_issue": "300",
        "cisco_catalyst_dnac_networkhealth": "300",
        "cisco_catalyst_dnac_securityadvisory": "3600",
        "cisco_catalyst_dnac_swim": "3600",
        "cisco_catalyst_dnac_application_traffic": "900",
        "cisco_catalyst_dnac_audit_logs": "300",
        "cisco_catalyst_dnac_client": "3600",
        "cisco_catalyst_dnac_site_topology": "3600",
        "cisco_catalyst_ise_administrative_input": "3600",
        "cisco_catalyst_sdwan_health": "900",
        "cisco_catalyst_sdwan_site_and_tunnel_health": "3600",
        "cisco_catalyst_sdwan_audit_logs": "300",
        "cisco_catalyst_sdwan_energy_stats": "300",
        "cisco_catalyst_cybervision_activities": "300",
        "cisco_catalyst_cybervision_components": "900",
        "cisco_catalyst_cybervision_devices": "900",
        "cisco_catalyst_cybervision_events": "300",
        "cisco_catalyst_cybervision_flows": "300",
        "cisco_catalyst_cybervision_vulnerabilities": "900",
    }

    for input_type, interval in expected_inputs.items():
        assert input_type in setup
        assert f'"{input_type}|{interval}|' in setup

    assert "utd_health,link_health,sse_tunnel_health" in setup
    assert "site_health,tunnel_health,sse_tunnels" in setup
    assert 'ta_handler_available "data/inputs/${optional_type}"' in setup
    assert "the installed TA does not expose this 3.2.44 source-contract handler" in setup


def test_setup_does_not_guess_environment_specific_input_parameters() -> None:
    setup = (SKILL_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")

    for input_type in (
        "cisco_catalyst_dnac_api",
        "cisco_catalyst_center_reports",
        "cisco_catalyst_ise_api",
        "cisco_catalyst_ise_analytics_reports",
        "cisco_catalyst_sdwan_api",
        "cisco_catalyst_cybervision_api",
    ):
        assert f'rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "{input_type}"' not in setup


def test_completion_validation_requires_recent_product_data() -> None:
    validator = (SKILL_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")

    assert "earliest=-24h" in validator
    for sourcetype_family in (
        "cisco:dnac:*",
        "cisco:catalyst:center:*",
        "cisco:ise:*",
        "cisco:sdwan:*",
        "cisco:cybervision:*",
    ):
        assert sourcetype_family in validator
    assert "sdwan_ingress_count" in validator
    assert "Recent SD-WAN text events satisfy ingest readiness" in validator
    assert "TA Data Collection Health dashboard search has" in validator
    assert "event=poll-complete" in validator


def test_account_tls_verification_is_scoped_per_account() -> None:
    configurator = (SKILL_ROOT / "scripts" / "configure_account.sh").read_text(
        encoding="utf-8"
    )
    validator = (SKILL_ROOT / "scripts" / "validate.sh").read_text(encoding="utf-8")

    assert 'VERIFY_SSL="true"' in configurator
    assert 'verify_ssl "${VERIFY_SSL}"' in configurator
    assert "rest_set_verify_ssl" not in configurator
    assert "tls_disabled_accounts" in validator
    assert "account(s) disable TLS certificate verification" in validator


def test_beta_iosxe_cli_account_and_input_match_current_allowlist() -> None:
    configurator = (SKILL_ROOT / "scripts" / "configure_account.sh").read_text(
        encoding="utf-8"
    )
    setup = (SKILL_ROOT / "scripts" / "setup.sh").read_text(encoding="utf-8")
    template = (SKILL_ROOT / "template.example").read_text(encoding="utf-8")

    for value in (
        "TA_cisco_catalyst_cli_account",
        "host_key_fingerprint",
        "iosxe_cli",
    ):
        assert value in configurator
    for command_id in (
        "dspfarm_profile",
        "sdwan_bfd_sessions",
        "sdwan_bfd_history",
        "version",
        "inventory",
    ):
        assert command_id in setup
    assert 'rest_create_input "$SK" "$SPLUNK_URI" "$APP_NAME" "cisco_catalyst_cli_command"' in setup
    assert 'ta_handler_available "TA_cisco_catalyst_cli_account"' in configurator
    assert 'ta_handler_available "data/inputs/cisco_catalyst_cli_command"' in setup
    assert 'input_name="CLI_${account}_${command_id}"' in setup
    assert "host_key_fingerprint" in template


def test_mcp_tools_cover_structured_health_and_current_device_fields() -> None:
    payload = json.loads((SKILL_ROOT / "mcp_tools.json").read_text(encoding="utf-8"))
    tools = {tool["_key"]: tool for tool in payload["tools"]}

    assert "by index sourcetype" in tools["cisco_catalyst:check_health"]["spl"]
    assert "cisco_catalyst:collection_status" in tools
    assert "event=poll-complete" in tools["cisco_catalyst:collection_status"]["spl"]
    device_health = tools["cisco_catalyst:dnac_device_health"]["spl"]
    assert "OverallHealth" in device_health
    assert "DeviceName" in device_health
    assert "overallHealth" not in device_health
    bfd = tools["cisco_catalyst:sdwan_bfd"]["spl"]
    assert "cisco:sdwan:custom:device_bfd_summary" in bfd
    assert "cisco:sdwan:custom:device_bfd_synced_sessions" in bfd
    assert "cisco:sdwan:custom:device_bfd_history" in bfd
    assert "target_device_id" in bfd
    syslog = tools["cisco_catalyst:sdwan_syslog_status"]["spl"]
    assert "cisco:firewall:logs" in syslog
    assert "cisco:sdwan:utd:logs" in syslog
    assert "cisco:sdwan:syslog" in syslog
    assert "HSL and Unified Logging" in tools["cisco_catalyst:sdwan_syslog_status"][
        "description"
    ]
    cli = tools["cisco_catalyst:iosxe_cli_status"]["spl"]
    assert "cisco:iosxe:cli:*" in cli
    collection = tools["cisco_catalyst:collection_status"]["spl"]
    assert "splunktaciscocli:log" in collection
    assert "Cisco-IOS-XE-CLI" in collection


def test_docs_record_current_ta_source_contract_without_overstating_package_evidence() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL_ROOT / "reference.md").read_text(encoding="utf-8")

    # The source contract and the package evidence now agree on 3.2.44, which is
    # also the current public release. The docs must say so explicitly rather
    # than leave a stale evidence-behind-contract claim in place.
    assert "now the same release, `3.2.44`" in skill
    assert "29 modular input types" in reference

    # Closing that gap must not turn into overstated evidence: the one surviving
    # package gap still has to be recorded rather than silently dropped.
    assert "no public release through `3.2.44` ships" in skill
    assert "IOS-XE CLI" in skill


def test_docs_cover_sdwan_device_scope_and_bfd_example() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL_ROOT / "reference.md").read_text(encoding="utf-8")
    combined = skill + reference

    for value in (
        "device_scope",
        "target_device_id",
        "/dataservice/device/bfd/summary",
        "/dataservice/device/bfd/synced/sessions",
        "/dataservice/device/bfd/history",
        "cisco:sdwan:custom:device_bfd_summary",
        "cisco:sdwan:custom:device_bfd_synced_sessions",
        "cisco:sdwan:custom:device_bfd_history",
    ):
        assert value in combined

    assert "does not execute `show sdwan bfd session`" in skill
    assert "editable on all seven API input forms" in reference


def test_docs_distinguish_sdwan_syslog_hsl_and_cli_collection_paths() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL_ROOT / "reference.md").read_text(encoding="utf-8")
    validator = (SKILL_ROOT / "scripts" / "validate.sh").read_text(
        encoding="utf-8"
    )
    combined = skill + reference

    for value in (
        "cisco:firewall:logs",
        "cisco:sdwan:utd:logs",
        "cisco:sdwan:utdhealth",
        "cisco:sdwan:syslog",
        "UDP 514",
        "SC4S",
        "High Speed Logging",
        "Splunk Stream",
        "Cisco IOS-XE CLI Input (Beta)",
        "does not issue `enable`",
    ):
        assert value in combined

    assert "affected releases/templates" in combined
    assert "separate vManage REST/API health snapshot" in combined
    assert "cisco:viptela" in combined
    assert "SD-WAN Text-Syslog Readiness" in validator
    assert "cisco:firewall:logs" in validator
    assert "cisco:iosxe:cli:*" in validator
