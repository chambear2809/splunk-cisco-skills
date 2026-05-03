#!/usr/bin/env python3
"""Security portfolio coverage and dry-run regressions."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


REGISTRY_PATH = REPO_ROOT / "skills/shared/app_registry.json"
ARI_REQUIRED_INDEXES = ["ari_staging", "ari_asset", "ari_internal", "ari_ta"]
ARI_CAPABILITIES = {
    "ari_manage_data_source_settings",
    "ari_manage_metric_settings",
    "ari_manage_report_exceptions",
    "ari_dashboard_add_alerts",
    "ari_edit_table_fields",
    "ari_save_filters",
    "ari_manage_filters",
    "ari_manage_homepage_settings",
}
ARI_HANDOFF_KEYS = {
    "preflight",
    "post_install",
    "admin",
    "risk_compliance",
    "response_audit",
    "investigation",
    "es_integration",
    "exposure_analytics",
    "addon",
    "echo",
    "upgrade",
    "uninstall",
}


def run_bash(rel_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["bash", str(REPO_ROOT / rel_path), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def load_json_from_bash(rel_path: str, *args: str) -> dict:
    result = run_bash(rel_path, *args)
    return json.loads(result.stdout)


def test_security_portfolio_router_classifies_products_and_offerings() -> None:
    payload = load_json_from_bash(
        "skills/splunk-security-portfolio-setup/scripts/setup.sh",
        "--list-products",
        "--json",
    )

    assert payload["last_verified"] == "2026-05-03"
    entries = {entry["key"]: entry for entry in payload["entries"]}

    expected_products = {
        "enterprise-security": "existing_skill",
        "security-essentials": "first_class",
        "soar": "first_class",
        "uba": "partial",
        "attack-analyzer": "first_class",
        "asset-risk-intelligence": "first_class",
    }
    for key, status in expected_products.items():
        assert entries[key]["status"] == status
        assert entries[key]["route"]

    associated = {
        "soar-export": "first_class",
        "mission-control": "bundled_es",
        "exposure-analytics": "bundled_es",
        "detection-studio": "bundled_es",
        "tim-cloud": "bundled_es",
        "splunk-cloud-connect": "bundled_es",
        "dlx": "bundled_es",
        "security-content-update": "install_only",
        "pci-compliance": "install_only",
        "infosec": "install_only",
        "fraud-analytics": "manual_gap",
        "automation-broker": "partial",
    }
    for key, status in associated.items():
        assert entries[key]["status"] == status


def test_security_portfolio_router_preserves_specific_handoffs() -> None:
    soar_export = load_json_from_bash(
        "skills/splunk-security-portfolio-setup/scripts/setup.sh",
        "--product",
        "soar export",
        "--json",
    )
    assert soar_export["entry"]["key"] == "soar-export"
    assert soar_export["route_command"][-1] == "--install-export-app"

    broker = load_json_from_bash(
        "skills/splunk-security-portfolio-setup/scripts/setup.sh",
        "--product",
        "automation broker",
        "--json",
    )
    assert broker["entry"]["key"] == "automation-broker"
    assert broker["route_command"][-1] == "--automation-broker-plan"

    escu = load_json_from_bash(
        "skills/splunk-security-portfolio-setup/scripts/setup.sh",
        "--product",
        "security content update",
        "--json",
    )
    assert escu["entry"]["key"] == "security-content-update"
    assert escu["route_command"] == [
        "bash",
        "skills/splunk-enterprise-security-config/scripts/setup.sh",
        "--spec",
        "skills/splunk-enterprise-security-config/templates/es-config.example.yaml",
        "--mode",
        "preview",
    ]


def test_security_portfolio_registry_entries_are_complete() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    apps_by_id = {app["splunkbase_id"]: app for app in registry["apps"]}
    topologies = {entry["skill"]: entry for entry in registry["skill_topologies"]}
    cloud_labels = {row["label"] for row in registry["documentation"]["cloud_matrix_rows"]}

    expected_apps = {
        "3435": ("splunk-security-essentials-setup", "Splunk_Security_Essentials", "9.0"),
        "7180": ("splunk-asset-risk-intelligence-setup", "SplunkAssetRiskIntelligence", "9.0"),
        "7214": (
            "splunk-asset-risk-intelligence-setup",
            "Splunk Asset and Risk Intelligence Technical Add-on For Windows",
            "9.0",
        ),
        "7416": (
            "splunk-asset-risk-intelligence-setup",
            "Splunk Asset and Risk Intelligence Technical Add-on For Linux",
            "9.0",
        ),
        "7417": (
            "splunk-asset-risk-intelligence-setup",
            "Splunk Asset and Risk Intelligence Technical Add-on For macOS",
            "9.0",
        ),
        "6999": ("splunk-attack-analyzer-setup", "Splunk_TA_SAA", "9.0"),
        "7000": ("splunk-attack-analyzer-setup", "Splunk_App_SAA", "9.0"),
        "4147": ("splunk-uba-setup", "Splunk-UBA-SA-Kafka", "9.2"),
        "6361": ("splunk-soar-setup", "splunk_app_soar", "10.0"),
        "3411": ("splunk-soar-setup", "phantom", "10.2"),
        "3449": ("splunk-enterprise-security-config", "DA-ESS-ContentUpdate", "8.0"),
    }
    for app_id, (skill, app_name, min_splunk_version) in expected_apps.items():
        app = apps_by_id[app_id]
        assert app["skill"] == skill
        assert app["app_name"] == app_name
        assert app["min_splunk_version"] == min_splunk_version
        assert set(app["capabilities"]) == {
            "needs_custom_rest",
            "needs_search_time_objects",
            "needs_kvstore",
            "needs_python_runtime",
            "needs_packet_capture",
            "uf_safe",
        }
    assert apps_by_id["3449"]["license_ack_url"] == "https://www.apache.org/licenses/LICENSE-2.0"

    for skill in {
        "splunk-security-portfolio-setup",
        "splunk-security-essentials-setup",
        "splunk-soar-setup",
        "splunk-uba-setup",
        "splunk-attack-analyzer-setup",
        "splunk-asset-risk-intelligence-setup",
    }:
        assert skill in topologies

    assert topologies["splunk-security-essentials-setup"]["role_support"]["search-tier"] == "required"
    assert topologies["splunk-soar-setup"]["role_support"]["external-collector"] == "supported"
    assert topologies["splunk-uba-setup"]["role_support"]["indexer"] == "supported"
    assert topologies["splunk-attack-analyzer-setup"]["cloud_pairing"] == ["indexer", "heavy-forwarder"]
    for app_id in {"7214", "7416", "7417"}:
        assert apps_by_id[app_id]["role_support"]["indexer"] == "supported"
        assert apps_by_id[app_id]["role_support"]["universal-forwarder"] == "supported"
        assert apps_by_id[app_id]["role_support"]["search-tier"] == "none"
        assert apps_by_id[app_id]["capabilities"]["uf_safe"] is True
    assert "`splunk-security-portfolio-setup`" in cloud_labels
    assert "`splunk-enterprise-security-config` content update" in cloud_labels
    assert "`splunk-asset-risk-intelligence-setup` Windows TA handoff" in cloud_labels
    assert "`splunk-asset-risk-intelligence-setup` Linux TA handoff" in cloud_labels
    assert "`splunk-asset-risk-intelligence-setup` macOS TA handoff" in cloud_labels


def test_security_skill_dry_runs_emit_json_without_secret_values(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("super-secret-value\n", encoding="utf-8")
    os.chmod(secret_file, 0o600)

    sse = load_json_from_bash(
        "skills/splunk-security-essentials-setup/scripts/setup.sh",
        "--dry-run",
        "--json",
    )
    assert sse["app_id"] == "3435"
    assert "Content Mapping" in sse["checklist"]

    saa_result = run_bash(
        "skills/splunk-attack-analyzer-setup/scripts/setup.sh",
        "--dry-run",
        "--json",
        "--tenant-url",
        "https://attack.example.com",
        "--api-key-file",
        str(secret_file),
    )
    assert "super-secret-value" not in saa_result.stdout
    saa = json.loads(saa_result.stdout)
    assert {app["app_id"] for app in saa["apps"]} == {"6999", "7000"}
    assert saa["index"] == "saa"
    assert saa["macro"] == {"app": "Splunk_App_SAA", "name": "saa_indexes", "definition": "index=saa"}
    assert saa["handoff"]["api_key_file_ready"] is True

    ari = load_json_from_bash(
        "skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh",
        "--dry-run",
        "--json",
    )
    assert ari["restricted_download"] is True
    assert ari["app_id"] == "7180"
    assert ari["latest_researched_version"] == "1.2.1"
    assert ari["indexes"]["required"] == ARI_REQUIRED_INDEXES
    assert ari["required_indexes"] == ARI_REQUIRED_INDEXES
    assert set(ari["roles"]["included"]) == {"ari_admin", "ari_analyst"}
    assert set(ari["capabilities"]["ari_admin_defaults"]) == ARI_CAPABILITIES
    assert "9.1.3" in ari["compatibility"]["docs_signal"]["splunk_platform"]
    assert set(ari["handoffs"]) == ARI_HANDOFF_KEYS
    assert {entry["splunkbase_id"] for entry in ari["related_products"]["technical_addons"]} == {
        "7214",
        "7416",
        "7417",
    }
    assert ari["related_products"]["echo"]["documented"] is True
    assert ari["related_products"]["echo"]["splunkbase_id"] is None
    assert "normal_integration" in ari["es_modes"]
    assert "exposure_analytics_8_5_plus" in ari["es_modes"]
    assert "upgrade" in ari["lifecycle"]
    assert "uninstall" in ari["lifecycle"]
    assert ari["sources"]["splunkbase_app"] == "https://splunkbase.splunk.com/app/7180"
    assert ari["sources"]["addon_windows"] == "https://splunkbase.splunk.com/app/7214"

    soar_result = run_bash(
        "skills/splunk-soar-setup/scripts/setup.sh",
        "--dry-run",
        "--json",
        "--install-export-app",
        "--automation-broker-plan",
        "--broker-runtime",
        "podman",
        "--soar-url",
        "https://soar.example.com",
        "--auth-file",
        str(secret_file),
        "--ca-cert-file",
        str(secret_file),
    )
    assert "super-secret-value" not in soar_result.stdout
    soar = json.loads(soar_result.stdout)
    assert soar["server_install_supported"] is True
    assert any(app["app_id"] == "3411" and app["selected"] for app in soar["apps"])
    assert soar["automation_broker"]["handoff_only"] is False
    assert soar["automation_broker"]["runtime"] == "podman"
    assert soar["handoff"]["auth_file_ready"] is True

    uba = load_json_from_bash(
        "skills/splunk-uba-setup/scripts/setup.sh",
        "--dry-run",
        "--json",
    )
    assert uba["status"] == "partial"
    assert uba["standalone_uba_server_install_supported"] is False
    assert uba["end_of_sale"] == "2025-12-12"
    assert uba["end_of_support"] == "2027-01-31"
    assert uba["kafka_app"]["install_requested"] is False

    uba_kafka = load_json_from_bash(
        "skills/splunk-uba-setup/scripts/setup.sh",
        "--dry-run",
        "--json",
        "--install-kafka-app",
    )
    assert uba_kafka["kafka_app"]["app_id"] == "4147"
    assert "4147" in uba_kafka["kafka_install_command"]


def test_asset_risk_intelligence_full_handoff_covers_all_surfaces() -> None:
    payload = load_json_from_bash(
        "skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh",
        "--dry-run",
        "--json",
        "--full-handoff",
    )

    assert set(payload["handoffs"]) == ARI_HANDOFF_KEYS
    assert all(entry["selected"] for entry in payload["handoffs"].values())
    assert set(payload["phases"]) == {
        "preflight",
        "post-install-handoff",
        "admin-handoff",
        "risk-handoff",
        "response-audit-handoff",
        "investigation-handoff",
        "es-integration-handoff",
        "exposure-analytics-handoff",
        "addon-handoff",
        "echo-handoff",
        "upgrade-handoff",
        "uninstall-handoff",
    }

    expected_surfaces = {
        "post_install": {"Post-install configuration", "internal lookups", "enrichment rules"},
        "admin": {"event searches", "data source activation", "source priorities", "field priorities", "field mappings", "inventory retention"},
        "risk_compliance": {"metric exceptions", "identity risk scoring", "risk processing settings"},
        "response_audit": {"responses", "audit reports", "operational logs", "license usage", "operational health"},
        "investigation": {"asset investigation", "software investigation", "attack surface explorer", "field reference"},
        "es_integration": {"ari_lookup_host()", "ari_lookup_ip()", "ari_risk_score", "ES risk factors"},
        "exposure_analytics": {
            "Splunk Asset and Risk Intelligence - Asset",
            "Splunk Asset and Risk Intelligence - IP",
            "Splunk Asset and Risk Intelligence - Mac",
            "Splunk Asset and Risk Intelligence - User",
        },
        "addon": {"Windows technical add-on 7214", "Linux technical add-on 7416", "macOS technical add-on 7417"},
        "echo": {"inventory sync", "asset association sync", "metric sync", "synchronization history"},
        "upgrade": {"backup app and KV stores", "disable processing searches", "rerun post-install configuration"},
        "uninstall": {"remove Enterprise Security integration first", "do not remove ARI indexes by default"},
    }
    for key, surfaces in expected_surfaces.items():
        assert surfaces <= set(payload["handoffs"][key]["surfaces"])


def test_asset_risk_intelligence_new_flags_appear_in_help() -> None:
    result = run_bash("skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh", "--help")
    for flag in (
        "--preflight-only",
        "--full-handoff",
        "--post-install-handoff",
        "--admin-handoff",
        "--risk-handoff",
        "--response-audit-handoff",
        "--investigation-handoff",
        "--es-integration-handoff",
        "--exposure-analytics-handoff",
        "--addon-handoff",
        "--echo-handoff",
        "--upgrade-handoff",
        "--uninstall-handoff",
    ):
        assert flag in result.stdout


def test_asset_risk_intelligence_validation_guardrails_before_auth() -> None:
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "skills/splunk-asset-risk-intelligence-setup/scripts/validate.sh"),
            "--not-a-real-flag",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Unknown option" in result.stderr
    assert "Splunk Authentication" not in result.stdout

    help_result = run_bash(
        "skills/splunk-asset-risk-intelligence-setup/scripts/validate.sh",
        "--help",
    )
    forbidden_promises = (
        "delete index",
        "index deletion",
        "remove indexes",
        "remove ES integration",
        "disable ES integration",
        "ServiceNow credentials",
        "Echo credentials",
        "deploy UF",
        "deploy Universal Forwarder",
    )
    combined = help_result.stdout + help_result.stderr
    for phrase in forbidden_promises:
        assert phrase not in combined

    validate_text = (
        REPO_ROOT / "skills/splunk-asset-risk-intelligence-setup/scripts/validate.sh"
    ).read_text(encoding="utf-8")
    for phrase in forbidden_promises:
        assert phrase not in validate_text


def test_asset_risk_intelligence_validate_json_helpers_preserve_stdin() -> None:
    script = REPO_ROOT / "skills/splunk-asset-risk-intelligence-setup/scripts/validate.sh"
    probe = f"""
set -euo pipefail
tmp="$(mktemp)"
awk '/^json_field_from_first_entry\\(\\)/,/^}}/ {{print}}' {script} > "$tmp"
awk '/^count_json_entries\\(\\)/,/^}}/ {{print}}' {script} >> "$tmp"
awk '/^capability_present\\(\\)/,/^}}/ {{print}}' {script} >> "$tmp"
awk '/^parse_related_products\\(\\)/,/^}}/ {{print}}' {script} >> "$tmp"
. "$tmp"
rm -f "$tmp"
test "$(printf '%s' '{{"entry":[{{"content":{{"version":"9.2.1"}}}}]}}' | json_field_from_first_entry version)" = "9.2.1"
test "$(printf '%s' '{{"entry":[{{}},{{}}]}}' | count_json_entries)" = "2"
printf '%s' '{{"entry":[{{"name":"ari_manage_filters","content":{{}}}}]}}' | capability_present ari_manage_filters
test "$(printf '%s' '{{"entry":[{{"name":"Splunk Asset and Risk Intelligence Technical Add-on For Linux"}},{{"name":"Splunk Asset and Risk Intelligence Echo"}}]}}' | parse_related_products)" = "Echo, Linux TA"
"""
    result = subprocess.run(
        ["bash", "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_attack_analyzer_interval_guardrail_rejects_too_fast_polling() -> None:
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "skills/splunk-attack-analyzer-setup/scripts/setup.sh"),
            "--dry-run",
            "--json",
            "--interval",
            "299",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "at least 300" in result.stderr


def test_new_security_validate_scripts_support_help_without_auth() -> None:
    validate_scripts = [
        "skills/splunk-security-portfolio-setup/scripts/validate.sh",
        "skills/splunk-security-essentials-setup/scripts/validate.sh",
        "skills/splunk-attack-analyzer-setup/scripts/validate.sh",
        "skills/splunk-asset-risk-intelligence-setup/scripts/validate.sh",
        "skills/splunk-soar-setup/scripts/validate.sh",
        "skills/splunk-uba-setup/scripts/validate.sh",
    ]
    for script in validate_scripts:
        result = run_bash(script, "--help")
        assert "Usage:" in result.stdout
        assert "Splunk Authentication" not in result.stdout


def test_new_security_scripts_keep_secret_hygiene_contracts() -> None:
    scripts = [
        REPO_ROOT / "skills/splunk-security-essentials-setup/scripts/setup.sh",
        REPO_ROOT / "skills/splunk-attack-analyzer-setup/scripts/setup.sh",
        REPO_ROOT / "skills/splunk-asset-risk-intelligence-setup/scripts/setup.sh",
        REPO_ROOT / "skills/splunk-soar-setup/scripts/setup.sh",
        REPO_ROOT / "skills/splunk-uba-setup/scripts/setup.sh",
    ]
    forbidden = [
        "SPLUNK_PASS=",
        "SB_PASS=",
        "--password ",
        "--api-key ",
        "--token ",
    ]
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{script} contains forbidden secret pattern {needle!r}"
        assert "--file" in text

    soar_template = (REPO_ROOT / "skills/splunk-soar-setup/template.example").read_text(
        encoding="utf-8"
    )
    assert "soar_platform" in soar_template
    assert "soar_tgz" in soar_template
    assert "postgres" in soar_template.lower()

    soar_skill_files = [
        path
        for path in (REPO_ROOT / "skills/splunk-soar-setup").rglob("*")
        if path.is_file() and path.suffix in {"", ".example", ".json", ".md", ".py", ".sh"}
    ]
    soar_skill_text = "\n".join(path.read_text(encoding="utf-8") for path in soar_skill_files)
    assert "Splunkbase 6361" in soar_skill_text or "Splunkbase `6361`" in soar_skill_text
    assert "Splunkbase 3411" in soar_skill_text or "Splunkbase `3411`" in soar_skill_text
    for forbidden_doc_text in ("5119", "4977", "Splunk_TA_phantom"):
        assert forbidden_doc_text not in soar_skill_text
