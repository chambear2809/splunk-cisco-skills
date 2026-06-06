#!/usr/bin/env python3
"""Regression coverage for Splunk Cloud-friendly endpoint/API TA setup skills.

These skills are render-first: the render phase must run fully offline and emit
package-accurate inputs.conf stanzas, source types, and account runbooks. The
registry and supported-addons router must route to them.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

SKILLS = REPO_ROOT / "skills"
REGISTRY = json.loads((SKILLS / "shared/app_registry.json").read_text(encoding="utf-8"))
ADDONS_CATALOG = json.loads(
    (SKILLS / "splunk-supported-addons-setup/catalog.json").read_text(encoding="utf-8")
)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(args), cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60
    )
    return result


class WindowsTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-windows-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-windows-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-windows-ta-setup/scripts/validate.sh")

    def test_render_emits_real_wineventlog_and_perfmon_stanzas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-windows-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[WinEventLog://Security]", inputs)
            self.assertIn("[perfmon://CPU]", inputs)
            self.assertIn("[WinHostMon://Computer]", inputs)
            self.assertIn("index = wineventlog", inputs)
            self.assertIn("index = perfmon", inputs)
            plan = (out / "profile-plan.md").read_text(encoding="utf-8")
            self.assertIn("WinEventLog:Security", plan)
            self.assertIn("Authentication", plan)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)

    def test_scripts_do_not_take_secret_args(self) -> None:
        text = Path(self.setup).read_text(encoding="utf-8")
        self.assertNotIn("--password", text)
        self.assertNotIn("--secret", text)


class AwsTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-aws-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-aws-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-aws-ta-setup/scripts/validate.sh")

    def test_render_emits_sqs_based_s3_and_config_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-aws-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[aws_sqs_based_s3://cloudtrail]", inputs)
            self.assertIn("s3_file_decoder = CloudTrail", inputs)
            self.assertIn("sourcetype = aws:cloudtrail", inputs)
            self.assertIn("[aws_config://config]", inputs)
            self.assertIn("sourcetype = aws:config", inputs)
            self.assertIn("sourcetype = aws:cloudwatch:guardduty", inputs)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("/servicesNS/nobody/Splunk_TA_aws/account", account)
            self.assertIn("splunk-cloud-data-manager-setup", account)

    def test_feed_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--feeds", "config", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmp) / "splunk-aws-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[aws_config://config]", inputs)
            self.assertNotIn("aws_sqs_based_s3", inputs)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class MicrosoftCloudSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-microsoft-cloud-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-microsoft-cloud-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-microsoft-cloud-setup/scripts/validate.sh")

    def test_render_emits_o365_and_mscs_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-microsoft-cloud"
            o365 = (out / "inputs.o365.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[splunk_ta_o365_management_activity://", o365)
            self.assertIn("content_type = Audit.AzureActiveDirectory", o365)
            self.assertIn("sourcetype = o365:management:activity", o365)
            mscs = (out / "inputs.mscs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[mscs_azure_audit://", mscs)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("splunk_ta_o365_tenants", account)
            self.assertIn("splunk_ta_mscs_azureaccount", account)

    def test_single_product_render(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--products", "o365", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-microsoft-cloud"
            self.assertTrue((out / "inputs.o365.local.conf.template").is_file())
            self.assertFalse((out / "inputs.mscs.local.conf.template").is_file())

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class OktaTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-okta-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-okta-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-okta-ta-setup/scripts/validate.sh")

    def test_render_emits_okta_metric_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-okta-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[okta_identity_cloud://okta_log]", inputs)
            self.assertIn("metric = log", inputs)
            self.assertIn("global_account = okta_prod", inputs)
            plan = (out / "profile-plan.md").read_text(encoding="utf-8")
            self.assertIn("OktaIM2:log", plan)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("Splunk_TA_okta_identity_cloud_account", account)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class GcpTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-gcp-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-gcp-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-gcp-ta-setup/scripts/validate.sh")

    def test_render_emits_pubsub_log_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-gcp-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[google_cloud_pubsub://", inputs)
            self.assertIn("google_subscriptions = splunk-export-sub", inputs)
            self.assertIn("sourcetype = google:gcp:pubsub:message", inputs)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("/servicesNS/nobody/Splunk_TA_google-cloudplatform/google_credentials", account)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class ServiceNowTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-servicenow-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-servicenow-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-servicenow-ta-setup/scripts/validate.sh")

    def test_render_emits_per_table_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-servicenow-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[snow://incident]", inputs)
            self.assertIn("table = incident", inputs)
            self.assertIn("timefield = sys_updated_on", inputs)
            self.assertIn("sourcetype = snow:incident", inputs)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("splunk_ta_snow_account", account)

    def test_table_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--tables", "cmdb_ci", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmp) / "splunk-servicenow-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[snow://cmdb_ci]", inputs)
            self.assertNotIn("[snow://incident]", inputs)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class GoogleWorkspaceTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-google-workspace-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-google-workspace-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-google-workspace-ta-setup/scripts/validate.sh")

    def test_render_emits_all_package_input_families(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-google-workspace-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            for stanza in (
                "[activity_report://gws_activity_admin]",
                "[gws_gmail_logs://gws_gmail_logs]",
                "[gws_gmail_logs_migrated://gws_gmail_logs_migrated]",
                "[gws_user_identity://gws_user_identity]",
                "[gws_alert_center://gws_alert_center]",
                "[gws_usage_report://gws_usage_user]",
            ):
                self.assertIn(stanza, inputs)
            self.assertIn("account = gws_prod", inputs)
            plan = (out / "profile-plan.md").read_text(encoding="utf-8")
            self.assertIn("gws:reports:<application>", plan)
            self.assertIn("gws:gmail", plan)
            self.assertIn("gws:users:identity", plan)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("splunk_ta_google_workspace_account", account)
            metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["latest_verified_version"], "4.0.0")

    def test_input_family_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--inputs", "gws_alert_center", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmp) / "splunk-google-workspace-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[gws_alert_center://gws_alert_center]", inputs)
            self.assertNotIn("activity_report://", inputs)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class MicrosoftSecurityTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-microsoft-security-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-microsoft-security-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-microsoft-security-ta-setup/scripts/validate.sh")

    def test_render_emits_defender_inputs_macros_and_alert_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-microsoft-security-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            for stanza in (
                "[microsoft_365_defender_endpoint_incidents://defender_incidents]",
                "[microsoft_defender_endpoint_atp_alerts://defender_atp_alerts]",
                "[microsoft_defender_endpoint_machines://defender_machines]",
                "[microsoft_defender_endpoint_simulations://defender_simulations]",
                "[microsoft_defender_event_hub://defender_event_hub]",
                "[microsoft_defender_threat_intelligence_datasets://defender_threat_intel]",
            ):
                self.assertIn(stanza, inputs)
            self.assertIn("sourcetype = ms365:defender:incident", inputs)
            self.assertIn("sourcetype = ms:defender:eventhub", inputs)
            self.assertIn("DeviceProcessEvents", inputs)
            macros = (out / "macros.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[defender_index]", macros)
            self.assertIn("definition = index=microsoft_security", macros)
            plan = (out / "profile-plan.md").read_text(encoding="utf-8")
            self.assertIn("defender_advanced_hunting", plan)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("Splunk_TA_MS_Security_account", account)
            self.assertIn("Splunk Cloud", account)

    def test_feed_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--feeds", "event_hub", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmp) / "splunk-microsoft-security-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[microsoft_defender_event_hub://defender_event_hub]", inputs)
            self.assertNotIn("microsoft_365_defender_endpoint_incidents", inputs)

    def test_setup_and_validate_help_and_no_secret_args(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)
        text = Path(self.setup).read_text(encoding="utf-8")
        self.assertNotIn("--password", text)
        self.assertNotIn("--secret", text)


class SysmonTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-sysmon-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-sysmon-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-sysmon-ta-setup/scripts/validate.sh")

    def test_endpoint_mode_is_not_wec_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--mode", "endpoint", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmp) / "splunk-sysmon-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[WinEventLog://Microsoft-Windows-Sysmon/Operational]", inputs)
            self.assertIn("source = XmlWinEventLog:Microsoft-Windows-Sysmon/Operational", inputs)
            self.assertNotIn("[WinEventLog://WEC-Sysmon]", inputs)

    def test_wec_mode_is_not_endpoint_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--mode", "wec", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmp) / "splunk-sysmon-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[WinEventLog://WEC-Sysmon]", inputs)
            self.assertIn("sourcetype = XmlWinEventLog:WEC-Sysmon", inputs)
            self.assertNotIn("[WinEventLog://Microsoft-Windows-Sysmon/Operational]", inputs)
            plan = (Path(tmp) / "splunk-sysmon-ta" / "profile-plan.md").read_text(encoding="utf-8")
            self.assertIn("ms-sysmon-process", plan)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class GitHubTaSetupTests(unittest.TestCase):
    render = str(SKILLS / "splunk-github-ta-setup/scripts/render_assets.py")
    setup = str(SKILLS / "splunk-github-ta-setup/scripts/setup.sh")
    validate = str(SKILLS / "splunk-github-ta-setup/scripts/validate.sh")

    def test_render_emits_audit_user_alert_inputs_and_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmp) / "splunk-github-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[github_audit_input://github_audit]", inputs)
            self.assertIn("[github_user_input://github_user]", inputs)
            self.assertIn("[github_alerts_input://github_code_scanning_alerts]", inputs)
            self.assertIn("alert_type = code_scanning_alerts", inputs)
            self.assertIn("alert_type = dependabot_alerts", inputs)
            self.assertIn("alert_type = secret_scanning_alerts", inputs)
            plan = (out / "profile-plan.md").read_text(encoding="utf-8")
            self.assertIn("github:cloud:audit", plan)
            self.assertIn("github:enterprise:audit", plan)
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertIn("Splunk_TA_github_account", account)
            self.assertIn("source = http:github", account)

    def test_input_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run(sys.executable, self.render, "--output-dir", tmp, "--inputs", "audit", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmp) / "splunk-github-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[github_audit_input://github_audit]", inputs)
            self.assertNotIn("github_alerts_input://", inputs)

    def test_setup_and_validate_help(self) -> None:
        self.assertEqual(run("bash", self.setup, "--help").returncode, 0)
        self.assertEqual(run("bash", self.validate, "--help").returncode, 0)


class WiringTests(unittest.TestCase):
    def test_skill_topologies_registered(self) -> None:
        skills = {e["skill"] for e in REGISTRY["skill_topologies"]}
        for skill in (
            "splunk-windows-ta-setup",
            "splunk-aws-ta-setup",
            "splunk-microsoft-cloud-setup",
            "splunk-okta-ta-setup",
            "splunk-gcp-ta-setup",
            "splunk-servicenow-ta-setup",
            "splunk-google-workspace-ta-setup",
            "splunk-microsoft-security-ta-setup",
            "splunk-sysmon-ta-setup",
            "splunk-github-ta-setup",
            "splunk-syslog-web-proxy-ta-setup",
            "splunk-rsa-securid-ta-setup",
            "splunk-cyberark-ta-setup",
            "splunk-box-ta-setup",
            "splunk-salesforce-ta-setup",
        ):
            self.assertIn(skill, skills)

    def test_supported_addons_routes_point_to_new_skills(self) -> None:
        routes = ADDONS_CATALOG["official_glossary"]["routes"]
        self.assertEqual(routes["microsoft-windows"], {
            "status": "handoff_profile",
            "handoff_skill": "splunk-windows-ta-setup",
            "readiness_source_pack": "windows_security",
        })
        expected = {
            "amazon-web-services": "splunk-aws-ta-setup",
            "microsoft-office-365": "splunk-microsoft-cloud-setup",
            "microsoft-cloud-services": "splunk-microsoft-cloud-setup",
            "okta-identity-cloud": "splunk-okta-ta-setup",
            "google-cloud-platform": "splunk-gcp-ta-setup",
            "servicenow": "splunk-servicenow-ta-setup",
            "google-workspace": "splunk-google-workspace-ta-setup",
            "microsoft-security": "splunk-microsoft-security-ta-setup",
            "sysmon": "splunk-sysmon-ta-setup",
            "github": "splunk-github-ta-setup",
            "salesforce": "splunk-salesforce-ta-setup",
            "box": "splunk-box-ta-setup",
            "cyberark": "splunk-cyberark-ta-setup",
            "cyberark-epm": "splunk-cyberark-ta-setup",
            "rsa-securid": "splunk-rsa-securid-ta-setup",
            "rsa-securid-cas": "splunk-rsa-securid-ta-setup",
            "apache-web-server": "splunk-syslog-web-proxy-ta-setup",
            "symantec-blue-coat-proxysg": "splunk-syslog-web-proxy-ta-setup",
            "microsoft-sql-server": "splunk-database-ta-setup",
            "mysql": "splunk-database-ta-setup",
            "oracle-database": "splunk-database-ta-setup",
            "microsoft-exchange": "splunk-microsoft-exchange-ta-setup",
            "microsoft-scom": "splunk-microsoft-scom-ta-setup",
            "netapp-data-ontap": "splunk-netapp-ontap-ta-setup",
            "carbon-black": "splunk-security-appliance-ta-setup",
            "symantec-endpoint-protection": "splunk-security-appliance-ta-setup",
        }
        for key, skill in expected.items():
            self.assertEqual(routes[key]["status"], "handoff_profile")
            self.assertEqual(routes[key]["handoff_skill"], skill)
        self.assertEqual(routes["microsoft-windows"]["status"], "handoff_profile")


if __name__ == "__main__":
    unittest.main()
