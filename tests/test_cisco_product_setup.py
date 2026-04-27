#!/usr/bin/env python3
"""Regression tests for the Cisco product orchestrator."""

from __future__ import annotations

import importlib.util
import json
import shlex
import subprocess
import sys
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
