#!/usr/bin/env python3
"""Static coverage tests for the first-class Cisco Splunkbase product skills."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class CiscoSplunkbaseProductCoverageTests(unittest.TestCase):
    def run_help(self, path: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(REPO_ROOT / path), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_new_skill_scripts_expose_help_without_live_splunk(self) -> None:
        scripts = [
            "skills/cisco-webex-setup/scripts/setup.sh",
            "skills/cisco-webex-setup/scripts/configure_account.sh",
            "skills/cisco-webex-setup/scripts/configure_inputs.sh",
            "skills/cisco-webex-setup/scripts/validate.sh",
            "skills/cisco-ucs-ta-setup/scripts/setup.sh",
            "skills/cisco-ucs-ta-setup/scripts/configure_server.sh",
            "skills/cisco-ucs-ta-setup/scripts/configure_task.sh",
            "skills/cisco-ucs-ta-setup/scripts/validate.sh",
            "skills/cisco-secure-email-web-gateway-setup/scripts/setup.sh",
            "skills/cisco-secure-email-web-gateway-setup/scripts/render_ingestion_assets.sh",
            "skills/cisco-secure-email-web-gateway-setup/scripts/validate.sh",
            "skills/cisco-talos-intelligence-setup/scripts/setup.sh",
            "skills/cisco-talos-intelligence-setup/scripts/configure_service_account.sh",
            "skills/cisco-talos-intelligence-setup/scripts/validate.sh",
        ]
        for script in scripts:
            with self.subTest(script=script):
                result = self.run_help(script)
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertIn("Usage:", result.stdout + result.stderr)

    def test_webex_reference_covers_package_inputs_sourcetypes_and_macros(self) -> None:
        reference = (REPO_ROOT / "skills/cisco-webex-setup/reference.md").read_text(encoding="utf-8")
        account_script = (REPO_ROOT / "skills/cisco-webex-setup/scripts/configure_account.sh").read_text(encoding="utf-8")
        router = (REPO_ROOT / "skills/cisco-product-setup/scripts/setup.sh").read_text(encoding="utf-8")
        for expected in (
            "webex_meetings",
            "webex_meetings_summary_report",
            "webex_admin_audit_events",
            "webex_security_audit_events",
            "webex_meeting_qualities",
            "webex_detailed_call_history",
            "webex_generic_endpoint",
            "webex_base_url",
            "webex_contact_center_search",
            "cisco:webex:meeting:attendee:reports",
            "cisco:webex:contact:center:AAR",
            "cisco:webex:contact:center:CSR",
            "webex_meeting",
            "webex_calling",
            "webex_contact_center",
            "webex_indexes",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, reference)
        for expected in (
            "--webex-endpoint",
            "--webex-base-url",
            "--query-params",
            "--request-body",
            "--org-id",
            "--webex-contact-center-region",
            "--query-template",
            "--proxy-password-file",
        ):
            with self.subTest(router_option=expected):
                self.assertIn(expected, router)
        for expected in (
            '"logging"',
            '"proxy"',
            "--proxy-password-file",
            "--site-url",
        ):
            with self.subTest(account_script_expected=expected):
                self.assertIn(expected, account_script)

    def test_ucs_reference_covers_templates_and_task_fields(self) -> None:
        reference = (REPO_ROOT / "skills/cisco-ucs-ta-setup/reference.md").read_text(encoding="utf-8")
        for expected in (
            "splunk_ta_cisco_ucs_servers",
            "splunk_ta_cisco_ucs_templates",
            "cisco_ucs_task",
            "UCS_Fault",
            "UCS_Inventory",
            "UCS_Performance",
            "faultInst",
            "computeBlade",
            "swSystemStats",
            "cisco:ucs",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, reference)

    def test_secure_email_web_gateway_reference_covers_sourcetypes_and_macros(self) -> None:
        reference = (REPO_ROOT / "skills/cisco-secure-email-web-gateway-setup/reference.md").read_text(encoding="utf-8")
        for expected in (
            "Cisco_ESA_Index",
            "Cisco_WSA_Index",
            "cisco:esa:textmail",
            "cisco:esa:cef",
            "cisco:esa:amp",
            "cisco:esa:authentication",
            "cisco:wsa:l4tm",
            "cisco:wsa:squid:new",
            "cisco:wsa:w3c:recommended",
            "cisco_wsa",
            "cisco_esa",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, reference)

    def test_talos_reference_covers_custom_rest_actions_and_threatlist(self) -> None:
        reference = (REPO_ROOT / "skills/cisco-talos-intelligence-setup/reference.md").read_text(encoding="utf-8")
        setup_script = (REPO_ROOT / "skills/cisco-talos-intelligence-setup/scripts/setup.sh").read_text(encoding="utf-8")
        validate_script = (REPO_ROOT / "skills/cisco-talos-intelligence-setup/scripts/validate.sh").read_text(encoding="utf-8")
        for expected in (
            "query_reputation",
            "get_talos_enrichment",
            "Talos_Intelligence_Service",
            "intelligence_collection_from_talos",
            "intelligence_enrichment_with_talos",
            "talos:<observable_type>",
            "threatlist://talos_intelligence_ip_blacklist",
            "https://www.talosintelligence.com/documents/ip-blacklist",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, reference)
        for expected in (
            "SplunkEnterpriseSecuritySuite",
            "7.3.2",
            "FedRAMP/GovCloud",
            "support_preflight",
        ):
            with self.subTest(setup_expected=expected):
                self.assertIn(expected, setup_script)
        for expected in (
            "SplunkEnterpriseSecuritySuite",
            "7.3.2",
            "FedRAMP/GovCloud",
            "query_reputation",
        ):
            with self.subTest(validate_expected=expected):
                self.assertIn(expected, validate_script)


if __name__ == "__main__":
    unittest.main()
