
#!/usr/bin/env python3
"""Regression coverage for SaaS, security, and shared syslog/web-proxy TA renderers."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

SKILLS = REPO_ROOT / "skills"
SECRET_ARG_RE = re.compile(r"--(?:password|passwd|secret|token|client-secret|api-key)\b", re.IGNORECASE)
UNSCOPED_OR_RE = re.compile(r"\bOR\s+sourcetype=", re.IGNORECASE)


def run_cmd(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


class NewTaRendererTests(unittest.TestCase):
    def assert_help_and_no_secret_args(self, skill: str) -> None:
        setup = SKILLS / skill / "scripts/setup.sh"
        validate = SKILLS / skill / "scripts/validate.sh"
        self.assertEqual(run_cmd("bash", str(setup), "--help").returncode, 0)
        self.assertEqual(run_cmd("bash", str(validate), "--help").returncode, 0)
        self.assertIsNone(SECRET_ARG_RE.search(setup.read_text(encoding="utf-8")))
        self.assertIsNone(UNSCOPED_OR_RE.search(validate.read_text(encoding="utf-8")))

    def assert_no_unscoped_validation_or(self, output_dir: Path) -> None:
        validation = (output_dir / "validation-searches.spl").read_text(encoding="utf-8")
        self.assertIsNone(UNSCOPED_OR_RE.search(validation))

    def test_salesforce_default_and_selector_render(self) -> None:
        self.assert_help_and_no_secret_args("splunk-salesforce-ta-setup")
        render = SKILLS / "splunk-salesforce-ta-setup/scripts/render_assets.py"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmpdir) / "splunk-salesforce-ta"
            metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["splunkbase_id"], "3549")
            self.assertEqual(metadata["latest_verified_version"], "6.0.2")
            self.assertIn("sfdc:loginhistory", metadata["sourcetypes"])
            self.assertIn("[sfdc_object://loginhistory]", inputs)
            self.assertIn("[sfdc_event_log://event_log]", inputs)
            self.assertIn("Splunk_TA_salesforce_account", account)
            self.assert_no_unscoped_validation_or(out)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--objects", "user", "--no-event-log", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmpdir) / "splunk-salesforce-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[sfdc_object://user]", inputs)
            self.assertNotIn("[sfdc_object://loginhistory]", inputs)
            self.assertNotIn("sfdc_event_log://", inputs)

    def test_box_default_and_selector_render(self) -> None:
        self.assert_help_and_no_secret_args("splunk-box-ta-setup")
        render = SKILLS / "splunk-box-ta-setup/scripts/render_assets.py"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmpdir) / "splunk-box-ta"
            metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertEqual(metadata["splunkbase_id"], "2679")
            self.assertEqual(metadata["latest_verified_version"], "4.0.0")
            self.assertIn("box:filecontent:json", metadata["sourcetypes"])
            self.assertIn("[box_service://box_historical]", inputs)
            self.assertIn("[box_live_monitoring_service://box_live]", inputs)
            self.assertIn("[box_file_ingestion_service://box_file]", inputs)
            self.assert_no_unscoped_validation_or(out)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--inputs", "live", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmpdir) / "splunk-box-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[box_live_monitoring_service://box_live]", inputs)
            self.assertNotIn("[box_service://box_historical]", inputs)
            self.assertNotIn("[box_file_ingestion_service://box_file]", inputs)

    def test_cyberark_supported_epm_and_archived_epv_pta_render(self) -> None:
        self.assert_help_and_no_secret_args("splunk-cyberark-ta-setup")
        render = SKILLS / "splunk-cyberark-ta-setup/scripts/render_assets.py"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmpdir) / "splunk-cyberark-ta"
            metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            handoff = (out / "transport-handoff.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["apps"]["epm"]["splunkbase_id"], "5160")
            self.assertEqual(metadata["apps"]["epv_pta"]["splunkbase_id"], "2891")
            self.assertTrue(metadata["apps"]["epv_pta"]["archived_not_supported"])
            self.assertIn("[application_events://application_events]", inputs)
            self.assertIn("cyberark:epv:cef", handoff)
            self.assertIn("archived/not-supported", handoff)
            self.assert_no_unscoped_validation_or(out)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--products", "epm", "--epm-inputs", "threat_detection", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmpdir) / "splunk-cyberark-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[threat_detection://threat_detection]", inputs)
            self.assertNotIn("application_events://", inputs)

    def test_rsa_cas_and_am_render(self) -> None:
        self.assert_help_and_no_secret_args("splunk-rsa-securid-ta-setup")
        render = SKILLS / "splunk-rsa-securid-ta-setup/scripts/render_assets.py"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmpdir) / "splunk-rsa-securid-ta"
            metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            handoff = (out / "transport-handoff.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["apps"]["cas"]["splunkbase_id"], "5210")
            self.assertEqual(metadata["apps"]["am"]["app_name"], "Splunk_TA_rsa-securid")
            self.assertIn("[cloud_administration_api://rsa_cas_adminlog]", inputs)
            self.assertIn("endpoint = /v2/users/highrisk", inputs)
            self.assertIn("rsa:securid:syslog", handoff)
            self.assert_no_unscoped_validation_or(out)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--products", "cas", "--cas-endpoints", "riskuser", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            inputs = (Path(tmpdir) / "splunk-rsa-securid-ta" / "inputs.local.conf.template").read_text(encoding="utf-8")
            self.assertIn("[cloud_administration_api://rsa_cas_riskuser]", inputs)
            self.assertNotIn("rsa_cas_adminlog", inputs)

    def test_syslog_web_proxy_default_and_selector_render(self) -> None:
        self.assert_help_and_no_secret_args("splunk-syslog-web-proxy-ta-setup")
        render = SKILLS / "splunk-syslog-web-proxy-ta-setup/scripts/render_assets.py"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmpdir) / "splunk-syslog-web-proxy-ta"
            metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            handoff = (out / "transport-handoff.md").read_text(encoding="utf-8")
            account = (out / "account-setup.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["profiles"]["apache"]["id"], "3186")
            self.assertEqual(metadata["profiles"]["checkpoint"]["app"], "Splunk_TA_checkpoint_log_exporter")
            self.assertIn("sourcetype = apache:access:combined", inputs)
            self.assertIn("C:\\inetpub\\logs\\LogFiles\\W3SVC*\\*.log", inputs)
            self.assertIn("bluecoat:proxysg:access:syslog", handoff)
            self.assertIn("cp_log:syslog", handoff)
            self.assertIn("does not accept credential values", account)
            self.assertIn("SC4S/syslog", account)
            self.assert_no_unscoped_validation_or(out)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd("python3", str(render), "--output-dir", tmpdir, "--products", "apache,bluecoat", "--json")
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            out = Path(tmpdir) / "splunk-syslog-web-proxy-ta"
            inputs = (out / "inputs.local.conf.template").read_text(encoding="utf-8")
            handoff = (out / "transport-handoff.md").read_text(encoding="utf-8")
            self.assertIn("apache:access:combined", inputs)
            self.assertNotIn("nginx:plus:access", inputs)
            self.assertNotIn("ms:iis:auto", inputs)
            self.assertIn("bluecoat:proxysg:access:syslog", handoff)
            self.assertNotIn("cp_log:syslog", handoff)

    def test_renderers_reject_empty_selectors(self) -> None:
        cases = [
            ("splunk-salesforce-ta-setup/scripts/render_assets.py", "--objects"),
            ("splunk-box-ta-setup/scripts/render_assets.py", "--inputs"),
            ("splunk-cyberark-ta-setup/scripts/render_assets.py", "--products"),
            ("splunk-rsa-securid-ta-setup/scripts/render_assets.py", "--products"),
            ("splunk-syslog-web-proxy-ta-setup/scripts/render_assets.py", "--products"),
        ]
        for script, selector in cases:
            with self.subTest(script=script, selector=selector):
                result = run_cmd("python3", str(SKILLS / script), selector, "")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("at least one", result.stderr)


if __name__ == "__main__":
    unittest.main()
