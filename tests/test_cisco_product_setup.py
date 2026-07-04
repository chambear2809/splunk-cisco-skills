#!/usr/bin/env python3
"""Regression tests for the Cisco product orchestrator."""

from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


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

        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.catalog_path = Path(cls._tmpdir.name) / "catalog.json"
        catalog = module.build_catalog()
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

    def test_pinned_scan_fixture_has_verified_provenance(self) -> None:
        manifest_path = REPO_ROOT / "skills/cisco-product-setup/scan_source.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fixture_path = manifest_path.parent / manifest["fixture"]["path"]
        fixture_payload = fixture_path.read_bytes()
        fixture = json.loads(fixture_payload)
        catalog = json.loads(
            (REPO_ROOT / "skills/cisco-product-setup/catalog.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["source"]["kind"], "scan_public_catalog")
        self.assertEqual(manifest["source"]["url"], self.module.SCAN_SOURCE_URL)
        self.assertEqual(manifest["source"]["catalog_version"], "2026_06_26_1427")
        self.assertEqual(manifest["source"]["minimum_scan_version"], "1.0.28")
        self.assertEqual(
            date.fromisoformat(manifest["source"]["retrieved_date"]).isoformat(),
            manifest["source"]["retrieved_date"],
        )
        self.assertRegex(manifest["source"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            hashlib.sha256(fixture_payload).hexdigest(),
            manifest["fixture"]["sha256"],
        )
        self.assertEqual(len(fixture["products"]), manifest["fixture"]["product_count"])
        self.assertEqual(
            catalog["scan_source"]["normalized_fixture_sha256"],
            manifest["fixture"]["sha256"],
        )
        self.assertEqual(
            catalog["scan_source"]["sha256"],
            manifest["source"]["sha256"],
        )

    def test_scan_fixture_rejects_untrusted_source_identity_and_date(self) -> None:
        manifest = json.loads(
            (REPO_ROOT / "skills/cisco-product-setup/scan_source.json").read_text(
                encoding="utf-8"
            )
        )
        invalid_values = (
            ("kind", "vendor_mirror", "kind"),
            ("url", "https://example.invalid/scan/products.conf", "URL"),
            ("retrieved_date", "July 3, 2026", "retrieved_date"),
            ("retrieved_date", "2026-02-30", "retrieved_date"),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "scan_source.json"
            for field, value, expected_error in invalid_values:
                with self.subTest(field=field, value=value):
                    candidate = json.loads(json.dumps(manifest))
                    candidate["source"][field] = value
                    manifest_path.write_text(
                        json.dumps(candidate),
                        encoding="utf-8",
                    )
                    with mock.patch.object(
                        self.module,
                        "SCAN_SOURCE_MANIFEST_PATH",
                        manifest_path,
                    ):
                        with self.assertRaisesRegex(ValueError, expected_error):
                            self.module.load_scan_source_fixture()

    def test_live_scan_source_binds_raw_source_to_normalized_fixture(self) -> None:
        source_payload = b"""# version = 2026_07_03_0000
# min_app_version = 1.0.28

[cisco_test_product]
display_name = Cisco Test Product
status = active
category = test
sourcetypes = cisco:test
"""
        live_products = self.module.parse_scan_products(source_payload.decode("utf-8"))
        matching_fixture_text = self.module.render_scan_fixture(live_products)
        matching_fixture_sha = hashlib.sha256(
            matching_fixture_text.encode("utf-8")
        ).hexdigest()
        altered_products = json.loads(json.dumps(live_products))
        altered_products[0]["display_name"] = "Altered Product"
        altered_fixture_text = self.module.render_scan_fixture(altered_products)
        altered_fixture_sha = hashlib.sha256(
            altered_fixture_text.encode("utf-8")
        ).hexdigest()

        manifest = {
            "schema_version": 1,
            "source": {
                "kind": "scan_public_catalog",
                "url": self.module.SCAN_SOURCE_URL,
                "catalog_version": "2026_07_03_0000",
                "minimum_scan_version": "1.0.28",
                "sha256": hashlib.sha256(source_payload).hexdigest(),
                "retrieved_date": "2026-07-03",
            },
            "fixture": {
                "path": "scan_products.fixture.json",
                "product_count": 1,
                "sha256": matching_fixture_sha,
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_root = Path(tmpdir)
            manifest_path = fixture_root / "scan_source.json"
            fixture_path = fixture_root / manifest["fixture"]["path"]
            with mock.patch.object(
                self.module,
                "SCAN_SOURCE_MANIFEST_PATH",
                manifest_path,
            ), mock.patch.object(
                self.module,
                "SKILL_ROOT",
                fixture_root,
            ), mock.patch.object(
                self.module,
                "fetch_scan_source",
                return_value=source_payload,
            ):
                fixture_path.write_text(matching_fixture_text, encoding="utf-8")
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertTrue(
                    self.module.check_live_scan_source(self.module.SCAN_SOURCE_URL)
                )

                manifest["fixture"]["sha256"] = altered_fixture_sha
                fixture_path.write_text(altered_fixture_text, encoding="utf-8")
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertFalse(
                    self.module.check_live_scan_source(self.module.SCAN_SOURCE_URL)
                )

    def test_default_builder_does_not_discover_a_vendor_package(self) -> None:
        original = self.module.find_scan_package
        original_fetch = self.module.fetch_scan_source

        def fail_if_called(_explicit: str) -> Path:
            raise AssertionError("default fixture build must not discover a vendor package")

        def fail_if_networked(_source_url: str) -> bytes:
            raise AssertionError("default fixture build must remain offline")

        self.module.find_scan_package = fail_if_called
        self.module.fetch_scan_source = fail_if_networked
        try:
            catalog = self.module.build_catalog()
        finally:
            self.module.find_scan_package = original
            self.module.fetch_scan_source = original_fetch

        self.assertEqual(catalog["product_count"], 86)
        self.assertEqual(catalog["scan_source"]["kind"], "scan_public_catalog")

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

    def test_resolve_asa_ftd_syslog_intents_to_dedicated_ta(self) -> None:
        queries = (
            "Cisco ASA syslog",
            "ASA syslog",
            "Cisco FTD syslog",
            "FTD syslog",
            "Cisco Secure Firewall syslog",
            "Splunk_TA_cisco-asa",
        )
        for query in queries:
            with self.subTest(query=query):
                result, payload = self.run_resolver_json(query)
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertEqual(payload["status"], "resolved")
                product = payload["matches"][0]
                self.assertEqual(product["id"], "cisco_asa_ftd_syslog")
                self.assertEqual(product["automation_state"], "partial")
                self.assertEqual(product["route_type"], "asa_ta")
                self.assertEqual(product["primary_skill"], "cisco-asa-ta-setup")

    def test_resolve_secure_firewall_api_intents_to_security_cloud(self) -> None:
        for query in (
            "Cisco Secure Firewall (FTD/eStreamer/ASA)",
            "Cisco Secure Firewall API",
            "FMC API",
            "FTD API",
            "Cisco FTD API",
            "eStreamer",
            "FTD eStreamer",
            "Cisco FTD eStreamer",
        ):
            with self.subTest(query=query):
                result, payload = self.run_resolver_json(query)
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertEqual(payload["status"], "resolved")
                product = payload["matches"][0]
                self.assertEqual(product["id"], "cisco_secure_firewall")
                self.assertEqual(product["route_type"], "security_cloud_variant")
                self.assertEqual(product["primary_skill"], "cisco-security-cloud-setup")
                self.assertEqual(set(product["route"]["variants"]), {"api", "estreamer"})
                self.assertEqual(
                    product["sourcetypes"],
                    ["cisco:sfw:estreamer", "cisco:sfw:policy"],
                )

    def test_bare_asa_ftd_requests_return_explicit_collection_choice(self) -> None:
        expected_ids = {"cisco_asa_ftd_syslog", "cisco_secure_firewall"}
        expected_skills = {"cisco-asa-ta-setup", "cisco-security-cloud-setup"}
        for query in ("ASA", "FTD", "Cisco ASA", "Cisco FTD", "Cisco Firepower Threat Defense"):
            with self.subTest(query=query):
                result, payload = self.run_resolver_json(query)
                self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
                self.assertEqual(payload["status"], "ambiguous")
                self.assertEqual({item["id"] for item in payload["matches"]}, expected_ids)
                self.assertEqual(
                    {item["primary_skill"] for item in payload["matches"]},
                    expected_skills,
                )

        result = self.run_command(
            "bash",
            str(RESOLVE_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "Cisco ASA",
        )
        self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
        self.assertIn("Cisco ASA / FTD Syslog", result.stdout)
        self.assertIn("-> cisco-asa-ta-setup", result.stdout)
        self.assertIn("-> cisco-security-cloud-setup", result.stdout)

    def test_resolve_ai_defense_prefers_active_product_over_legacy_keyword(self) -> None:
        for query in ("Cisco AI Defense", "cisco_ai_defense"):
            with self.subTest(query=query):
                result, payload = self.run_resolver_json(query)
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertEqual(payload["status"], "resolved")
                self.assertEqual(payload["matches"][0]["id"], "cisco_ai_defense")

    def test_resolve_cisco_cloud_control_synthetic_product(self) -> None:
        for query in ("Cisco Cloud Control", "Cloud Control"):
            with self.subTest(query=query):
                result, payload = self.run_resolver_json(query)
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                self.assertEqual(payload["status"], "resolved")
                self.assertEqual(payload["matches"][0]["id"], "cisco_cloud_control")

    def test_security_cloud_control_remains_distinct_from_cloud_control(self) -> None:
        result, payload = self.run_resolver_json("Cisco Security Cloud Control")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertEqual(payload["status"], "resolved")
        self.assertEqual(payload["matches"][0]["id"], "cisco_security_cloud_control")

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

    def test_hyperflex_routes_to_intersight_partial_handoff(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco HyperFlex",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["resolved_product"]["automation_state"], "partial")
        self.assertEqual(payload["route"]["type"], "intersight")
        self.assertEqual(payload["resolved_product"]["primary_skill"], "cisco-intersight-setup")
        self.assertEqual(payload["install_apps"][0]["app_name"], "Splunk_TA_Cisco_Intersight")
        self.assertIn("HyperFlex coverage is routed through", payload["resolved_product"]["notes"])

    def test_iosxr_platforms_route_to_cisco_os_observability_handoff(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "Cisco IOS-XR Platforms",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["resolved_product"]["automation_state"], "partial")
        self.assertEqual(payload["route"]["type"], "workflow_handoff")
        self.assertEqual(
            payload["resolved_product"]["primary_skill"],
            "splunk-observability-cisco-nexus-integration",
        )
        self.assertIn("cisco_os receiver", payload["route"]["handoff"])
        self.assertIn(
            "skills/splunk-observability-cisco-nexus-integration/scripts/setup.sh",
            payload["workflow_scripts"],
        )

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

    def test_dry_run_asa_syslog_routes_to_ta_action_path(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "FTD syslog",
            "--dry-run",
            "--json",
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["resolved_product"]["id"], "cisco_asa_ftd_syslog")
        self.assertEqual(payload["resolved_product"]["automation_state"], "partial")
        self.assertEqual(payload["resolved_product"]["primary_skill"], "cisco-asa-ta-setup")
        self.assertEqual(payload["route"]["type"], "asa_ta")
        self.assertEqual(payload["route"]["default_index"], "cisco_asa")
        self.assertEqual(payload["route"]["sourcetypes"], ["cisco:asa"])
        self.assertIn("external syslog receiver", payload["route"]["handoff"])
        self.assertEqual(payload["install_apps"][0]["app_name"], "Splunk_TA_cisco-asa")
        self.assertEqual(payload["install_apps"][0]["splunkbase_id"], "1620")
        self.assertEqual(payload["missing_values_for_configure"], [])
        self.assertIn(
            "skills/cisco-asa-ta-setup/scripts/setup.sh",
            payload["workflow_scripts"],
        )
        self.assertIn(
            "skills/cisco-asa-ta-setup/scripts/validate.sh",
            payload["workflow_scripts"],
        )

    def test_secure_firewall_syslog_variant_is_not_a_security_cloud_route(self) -> None:
        result = self.run_command(
            "bash",
            str(SETUP_SCRIPT),
            "--catalog",
            str(self.catalog_path),
            "--product",
            "cisco_secure_firewall",
            "--set",
            "variant",
            "syslog",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 1, msg=result.stdout + result.stderr)
        self.assertIn("Invalid value 'syslog' for variant", result.stderr)
        self.assertIn("--product 'Cisco ASA syslog'", result.stderr)
        self.assertIn("cisco-asa-ta-setup", result.stderr)
        self.assertIn("api", result.stderr)
        self.assertIn("estreamer", result.stderr)

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
