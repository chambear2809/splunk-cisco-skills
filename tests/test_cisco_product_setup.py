#!/usr/bin/env python3
"""Regression tests for the Cisco product orchestrator."""

from __future__ import annotations

import importlib.util
import io
import json
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "skills/cisco-product-setup/scripts/build_catalog.py"
RESOLVE_SCRIPT = REPO_ROOT / "skills/cisco-product-setup/scripts/resolve_product.sh"
SETUP_SCRIPT = REPO_ROOT / "skills/cisco-product-setup/scripts/setup.sh"


class CiscoProductSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("build_catalog", BUILD_SCRIPT)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.module = module

        scan_glob = "splunk-cisco-app-navigator-*.tar.gz"
        if not list((REPO_ROOT / "splunk-ta").glob(scan_glob)):
            raise unittest.SkipTest(f"SCAN package ({scan_glob}) not in tree")

        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.catalog_path = Path(cls._tmpdir.name) / "catalog.json"
        catalog = module.build_catalog(module.find_scan_package(""))
        cls.catalog_path.write_text(module.render_catalog(catalog), encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    def run_command(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def run_setup_shell(self, shell_body: str) -> subprocess.CompletedProcess[str]:
        command = f"source {shlex.quote(str(SETUP_SCRIPT))}; {shell_body}"
        return self.run_command("bash", "-lc", command)

    def run_resolver_json(self, query: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = self.run_command(
            "bash",
            str(RESOLVE_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--json",
            query,
        )
        payload = json.loads(result.stdout)
        return result, payload

    def test_builder_check_matches_committed_catalog(self) -> None:
        result = self.run_command(sys.executable, str(BUILD_SCRIPT), "--check")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_resolve_aci(self) -> None:
        result, payload = self.run_resolver_json("ACI")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(payload["status"], "resolved")
        self.assertEqual(payload["matches"][0]["id"], "cisco_aci")

    def test_resolve_nexus_9000(self) -> None:
        result, payload = self.run_resolver_json("Nexus 9000")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(payload["status"], "resolved")
        self.assertEqual(payload["matches"][0]["id"], "cisco_nexus")

    def test_resolve_duo(self) -> None:
        result, payload = self.run_resolver_json("Duo")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(payload["status"], "resolved")
        self.assertEqual(payload["matches"][0]["id"], "cisco_duo")

    def test_resolve_ai_defense_prefers_active_product_over_legacy_keyword(self) -> None:
        for query in ("Cisco AI Defense", "cisco_ai_defense"):
            with self.subTest(query=query):
                result, payload = self.run_resolver_json(query)
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertEqual(payload["status"], "resolved")
                self.assertEqual(payload["matches"][0]["id"], "cisco_ai_defense")

    def test_resolve_cisco_is_ambiguous(self) -> None:
        result = self.run_command(
            "bash",
            str(RESOLVE_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "Cisco",
        )
        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertIn("Ambiguous product query: Cisco", result.stdout)

    def test_scan_package_sort_key_prefers_numeric_latest_version(self) -> None:
        paths = [
            Path("splunk-cisco-app-navigator-1.0.9.tar.gz"),
            Path("splunk-cisco-app-navigator-1.0.12.tar.gz"),
            Path("splunk-cisco-app-navigator-1.0.20.tar.gz"),
        ]
        ordered = sorted(paths, key=self.module.scan_package_sort_key)
        self.assertEqual(ordered[-1].name, "splunk-cisco-app-navigator-1.0.20.tar.gz")

    def test_scan_package_sort_key_uses_embedded_app_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_package = Path(tmpdir) / "splunk-cisco-app-navigator-1.0.12.tar.gz"
            latest_package = Path(tmpdir) / "splunk-cisco-app-navigator-scan_1025.tar.gz"
            self.write_scan_package(old_package, "1.0.12")
            self.write_scan_package(latest_package, "1.0.25")

            ordered = sorted(
                [latest_package, old_package],
                key=self.module.scan_package_sort_key,
            )

        self.assertEqual(ordered[-1].name, latest_package.name)

    @staticmethod
    def write_scan_package(path: Path, version: str) -> None:
        payload = f"""
[id]
name = splunk-cisco-app-navigator
version = {version}

[launcher]
version = {version}
""".lstrip().encode("utf-8")
        info = tarfile.TarInfo("splunk-cisco-app-navigator/default/app.conf")
        info.size = len(payload)
        with tarfile.open(path, "w:gz") as archive:
            archive.addfile(info, io.BytesIO(payload))

    def test_dry_run_aci_surfaces_route_template_and_dashboards(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "ACI",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Route type: dc_networking", result.stdout)
        self.assertIn("skills/cisco-dc-networking-setup/template.example", result.stdout)
        self.assertIn("fabric_dashboard", result.stdout)
        self.assertIn("skills/cisco-dc-networking-setup/scripts/validate.sh", result.stdout)

    def test_dry_run_catalyst_center_installs_ta_before_visualization_app(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Catalyst Center",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        ta_line = "  - TA_cisco_catalyst [7538] Cisco Catalyst Add-on for Splunk"
        app_line = "  - cisco-catalyst-app [7539] Cisco Enterprise Networking for Splunk Platform"
        self.assertIn(ta_line, result.stdout)
        self.assertIn(app_line, result.stdout)
        self.assertLess(result.stdout.index(ta_line), result.stdout.index(app_line))

    def test_dry_run_secure_access_installs_required_addon_before_app(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Secure Access",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        addon_line = "  - TA-cisco-cloud-security-addon [7569] Cisco Secure Access Add-on for Splunk"
        app_line = "  - cisco-cloud-security [5558] Cisco Secure Access App for Splunk"
        self.assertIn(addon_line, result.stdout)
        self.assertIn(app_line, result.stdout)
        self.assertLess(result.stdout.index(addon_line), result.stdout.index(app_line))

    def test_dry_run_evm_routes_to_security_cloud_install_only(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_evm",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["route"]["type"], "app_install_only")
        self.assertEqual(payload["resolved_product"]["primary_skill"], "splunk-app-install")
        self.assertEqual(payload["install_apps"][0]["app_name"], "CiscoSecurityCloud")
        self.assertEqual(payload["missing_values_for_configure"], [])
        self.assertIn("upstream EVM pipeline", payload["resolved_product"]["notes"])

    def test_dry_run_sca_routes_to_security_cloud_install_only(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_secure_cloud_analytics",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["route"]["type"], "app_install_only")
        self.assertEqual(payload["install_apps"][0]["app_name"], "CiscoSecurityCloud")
        self.assertIn("SCA/XDR pipeline", payload["resolved_product"]["notes"])

    def test_dry_run_webex_routes_to_first_class_skill(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_webex",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["route"]["type"], "webex")
        self.assertEqual(payload["resolved_product"]["primary_skill"], "cisco-webex-setup")
        self.assertEqual(payload["install_apps"][0]["app_name"], "ta_cisco_webex_add_on_for_splunk")
        self.assertEqual(payload["install_apps"][0]["splunkbase_id"], "8365")
        self.assertEqual(payload["install_apps"][1]["app_name"], "cisco_webex_meetings_app_for_splunk")
        self.assertEqual(payload["install_apps"][1]["splunkbase_id"], "4992")
        self.assertIn("skills/cisco-webex-setup/scripts/configure_account.sh", payload["workflow_scripts"])
        self.assertIn("client_secret (secret-file)", payload["missing_values_for_configure"])

    def test_webex_router_exposes_full_input_and_proxy_surface(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_webex",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        for expected in (
            "webex_endpoint",
            "method",
            "query_params",
            "request_body",
            "org_id",
            "webex_contact_center_region",
            "query_template",
            "site_url",
            "end_time",
            "interval",
            "proxy_enabled",
            "proxy_type",
            "proxy_url",
            "proxy_port",
            "proxy_username",
            "proxy_rdns",
            "webex_base_url",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, payload["optional_non_secret_keys"])
        self.assertIn("proxy_password", payload["secret_file_keys"])

    def test_webex_router_reports_type_specific_input_requirements(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_webex",
            "--set",
            "auto_inputs",
            "true",
            "--set",
            "input_type",
            "contact_center_search",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("org_id", payload["missing_values_for_configure"])
        self.assertIn("webex_contact_center_region", payload["missing_values_for_configure"])
        self.assertIn("start_time", payload["missing_values_for_configure"])

        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_webex",
            "--set",
            "auto_inputs",
            "true",
            "--set",
            "input_type",
            "generic_endpoint",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("webex_endpoint", payload["missing_values_for_configure"])

        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_webex",
            "--set",
            "auto_inputs",
            "true",
            "--set",
            "input_type",
            "meetings_summary_report",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("start_time", payload["missing_values_for_configure"])
        self.assertIn("site_url", payload["missing_values_for_configure"])

    def test_public_cisco_addons_route_to_first_class_skills(self) -> None:
        expected = {
            "cisco_esa": ("secure_email_web_gateway", "cisco-secure-email-web-gateway-setup", "Splunk_TA_cisco-esa", "1761"),
            "cisco_talos": ("talos_intelligence", "cisco-talos-intelligence-setup", "Splunk_TA_Talos_Intelligence", "7557"),
            "cisco_ucs": ("ucs_ta", "cisco-ucs-ta-setup", "Splunk_TA_cisco-ucs", "2731"),
            "cisco_wsa": ("secure_email_web_gateway", "cisco-secure-email-web-gateway-setup", "Splunk_TA_cisco-wsa", "1747"),
        }

        for product_id, (route_type, primary_skill, app_name, app_id) in expected.items():
            with self.subTest(product_id=product_id):
                result = self.run_command(
                    "bash",
                    str(SETUP_SCRIPT),
                    "--catalog",
                    str(self.catalog_path),
                    "--product",
                    product_id,
                    "--dry-run",
                    "--json",
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["route"]["type"], route_type)
                self.assertEqual(payload["resolved_product"]["primary_skill"], primary_skill)
                self.assertEqual(payload["install_apps"][0]["app_name"], app_name)
                self.assertEqual(payload["install_apps"][0]["splunkbase_id"], app_id)

    def test_public_cisco_addons_resolve_by_app_names_and_labels(self) -> None:
        expected = {
            "Splunk_TA_cisco-esa": "cisco_esa",
            "Splunk_TA_cisco-ucs": "cisco_ucs",
            "Splunk_TA_Talos_Intelligence": "cisco_talos",
            "ta_cisco_webex_add_on_for_splunk": "cisco_webex",
            "Talos Intelligence": "cisco_talos",
        }
        for query, product_id in expected.items():
            with self.subTest(query=query):
                result, payload = self.run_resolver_json(query)
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertEqual(payload["status"], "resolved")
                self.assertEqual(payload["matches"][0]["id"], product_id)

    def test_webex_contact_center_and_control_hub_route_to_webex_skill(self) -> None:
        for product_id in ("cisco_webex_contact_center", "cisco_webex_control_hub"):
            with self.subTest(product_id=product_id):
                result = self.run_command(
                    "bash",
                    str(SETUP_SCRIPT),
                    "--catalog",
                    str(self.catalog_path),
                    "--product",
                    product_id,
                    "--dry-run",
                    "--json",
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["route"]["type"], "webex")
                self.assertEqual(payload["resolved_product"]["primary_skill"], "cisco-webex-setup")

    def test_active_collector_products_route_to_partial_handoffs(self) -> None:
        expected = {
            "cisco_cucm": ("splunk-connect-for-syslog-setup", "cisco:ucm"),
            "cisco_expressway": ("splunk-connect-for-syslog-setup", "cisco:tvcs"),
            "cisco_meeting_management": ("splunk-connect-for-syslog-setup", "cisco:mm:audit"),
            "cisco_meeting_server": ("splunk-connect-for-syslog-setup", "cisco:ms"),
            "cisco_imc": ("splunk-connect-for-snmp-setup", "cisco:infraops"),
        }

        for product_id, (primary_skill, sourcetype) in expected.items():
            with self.subTest(product_id=product_id):
                result = self.run_command(
                    "bash",
                    str(SETUP_SCRIPT),
                    "--catalog",
                    str(self.catalog_path),
                    "--product",
                    product_id,
                    "--dry-run",
                    "--json",
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["resolved_product"]["automation_state"], "partial")
                self.assertEqual(payload["resolved_product"]["primary_skill"], primary_skill)
                self.assertEqual(payload["route"]["type"], "workflow_handoff")
                self.assertIn(sourcetype, payload["route"]["sourcetypes"])
                self.assertTrue(payload["route"]["handoff"])
                self.assertTrue(payload["workflow_scripts"])

    def test_active_products_do_not_remain_manual_gaps(self) -> None:
        catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        active_manual_gaps = [
            product["id"]
            for product in catalog["products"]
            if product["status"] == "active"
            and product["automation_state"] == "manual_gap"
        ]

        self.assertEqual(active_manual_gaps, [])

    def test_under_development_products_are_not_actionable_manual_gaps(self) -> None:
        catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        states = {
            product["id"]: product["automation_state"]
            for product in catalog["products"]
            if product["id"] in {"cisco_appomni", "cisco_radware"}
        }

        self.assertEqual(states["cisco_appomni"], "no_plans_available")
        self.assertEqual(states["cisco_radware"], "no_plans_available")

    def test_dry_run_secure_firewall_requires_variant(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Secure Firewall",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("variant: required", result.stdout)
        self.assertIn("Missing values for configure:\n  - variant", result.stdout)

    def test_dry_run_duo_requires_ikey_and_skey_but_not_proxy_password(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Duo",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("  - ikey (secret-file)", result.stdout)
        self.assertIn("  - skey (secret-file)", result.stdout)
        self.assertNotIn("proxy_password (secret-file)", result.stdout)

    def test_dry_run_secure_firewall_api_requires_password_secret(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Secure Firewall",
            "--set",
            "variant",
            "api",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("  - password (secret-file)", result.stdout)
        self.assertNotIn("pkcs_certificate (secret-file)", result.stdout)

    def test_dry_run_thousandeyes_only_requires_account_group(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco ThousandEyes",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Required non-secret keys:\n  - account_group", result.stdout)
        self.assertIn("Optional non-secret keys:\n  - account", result.stdout)
        self.assertIn("Missing values for configure:\n  - account_group", result.stdout)

    def test_effective_auto_inputs_defaults_false_when_unset(self) -> None:
        result = self.run_setup_shell(
            'USER_KEYS=(); USER_VALUES=(); if effective_auto_inputs; then echo true; else echo false; fi'
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "false")

    def test_effective_create_defaults_defaults_false_when_unset(self) -> None:
        result = self.run_setup_shell(
            'USER_KEYS=(); USER_VALUES=(); if effective_create_defaults; then echo true; else echo false; fi'
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "false")

    def test_cisco_spaces_routes_to_spaces_skill(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Spaces",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("Route type: spaces", result.stdout)
        self.assertIn("cisco-spaces-setup", result.stdout)
        self.assertIn("ta_cisco_spaces", result.stdout)
        self.assertIn("activation_token", result.stdout)
        self.assertIn("activation_token (secret-file)", result.stdout)
        self.assertIn("skills/cisco-spaces-setup/scripts/configure_stream.sh", result.stdout)

    def test_cisco_spaces_json_requires_activation_token_file(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Spaces",
            "--set",
            "name",
            "production",
            "--set",
            "region",
            "io",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["route"]["type"], "spaces")
        self.assertIn("activation_token", payload["required_secret_file_keys"])
        self.assertIn("activation_token (secret-file)", payload["missing_values_for_configure"])
        self.assertIn(
            "skills/cisco-spaces-setup/scripts/configure_stream.sh",
            payload["workflow_scripts"],
        )

    def test_cisco_spaces_json_surfaces_missing_secret_file_path(self) -> None:
        missing_path = str(Path(self._tmpdir.name) / "missing_spaces_token")
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Spaces",
            "--set",
            "name",
            "production",
            "--set",
            "region",
            "io",
            "--secret-file",
            "activation_token",
            missing_path,
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn(
            f"activation_token (secret-file missing: {missing_path})",
            payload["missing_values_for_configure"],
        )

    def test_install_only_json_does_not_report_configure_missing_values(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Spaces",
            "--install-only",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["planned_phases"], ["install"])
        self.assertEqual(payload["missing_values_for_configure"], [])

    def test_spaces_route_passes_custom_index_to_spaces_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = Path(tmpdir) / "spaces_token"
            log_path = Path(tmpdir) / "calls.log"
            token_path.write_text("token", encoding="utf-8")
            shell_body = f"""
                source {shlex.quote(str(SETUP_SCRIPT))}
                USER_KEYS=(name region index auto_inputs)
                USER_VALUES=(production io custom_spaces false)
                SECRET_KEYS=(activation_token)
                SECRET_PATHS=({shlex.quote(str(token_path))})
                EFFECTIVE_DEFAULT_NAME=production
                EFFECTIVE_DEFAULT_INDEX=cisco_spaces
                bash() {{
                    printf '%s\\n' "$*" >> {shlex.quote(str(log_path))}
                }}
                run_spaces_configure
                cat {shlex.quote(str(log_path))}
            """
            result = self.run_command("bash", "-lc", shell_body)

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("cisco-spaces-setup/scripts/setup.sh --index custom_spaces", result.stdout)
        self.assertIn("configure_stream.sh --name production", result.stdout)
        self.assertIn("--index custom_spaces", result.stdout)

    def test_cisco_hypershield_is_roadmap(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco Hypershield",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        self.assertIn("Automation state: unsupported_roadmap", result.stdout)


if __name__ == "__main__":
    unittest.main()
