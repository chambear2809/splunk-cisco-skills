#!/usr/bin/env python3
"""Regression coverage for the Splunk Supported Add-ons router."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


SETUP = REPO_ROOT / "skills/splunk-supported-addons-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-supported-addons-setup/scripts/validate.sh"
CATALOG = REPO_ROOT / "skills/splunk-supported-addons-setup/catalog.json"
REGISTRY = REPO_ROOT / "skills/shared/app_registry.json"
SOURCE_PACKS = REPO_ROOT / "skills/splunk-data-source-readiness-doctor/source_packs.json"
CLOUD_MATRIX = REPO_ROOT / "CLOUD_DEPLOYMENT_MATRIX.md"
ROLE_MATRIX = REPO_ROOT / "DEPLOYMENT_ROLE_MATRIX.md"


class SplunkSupportedAddonsSetupTests(unittest.TestCase):
    def run_setup(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SETUP), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_validate_script_passes(self) -> None:
        result = subprocess.run(
            ["bash", str(VALIDATE)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_catalog_contains_unix_linux_profiles_and_researched_versions(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        profiles = {profile["key"]: profile for profile in catalog["profiles"]}

        self.assertEqual(catalog["last_researched"], "2026-05-19")
        self.assertIn("unix-linux-os-scripts", profiles)
        self.assertIn("linux-collectd-auditd", profiles)
        self.assertEqual(len(catalog["official_glossary"]["entries"]), 80)
        routes = catalog["official_glossary"]["routes"]
        self.assertEqual(routes["unix-and-linux"]["profile"], "unix-linux-os-scripts")
        self.assertEqual(routes["linux"]["profile"], "linux-collectd-auditd")
        self.assertEqual(routes["cisco-ise"]["handoff_skill"], "cisco-catalyst-ta-setup")
        self.assertEqual(routes["microsoft-windows"]["status"], "install_only_handoff")
        self.assertEqual(profiles["unix-linux-os-scripts"]["add_on"]["splunkbase_id"], "833")
        self.assertEqual(profiles["unix-linux-os-scripts"]["add_on"]["latest_verified_version"], "10.2.0")
        self.assertEqual(profiles["linux-collectd-auditd"]["add_on"]["splunkbase_id"], "3412")
        self.assertEqual(profiles["linux-collectd-auditd"]["add_on"]["latest_verified_version"], "2.1.1")
        self.assertIn("linux:collectd:http:metrics", profiles["linux-collectd-auditd"]["metric_source_types"])
        self.assertIn("cpu_metric", profiles["unix-linux-os-scripts"]["metric_source_types"])

    def test_resolver_handles_app_names_ids_and_domain_default(self) -> None:
        cases = {
            "unix-linux": "unix-linux-os-scripts",
            "Unix and Linux": "unix-linux-os-scripts",
            "Linux": "linux-collectd-auditd",
            "Splunk_TA_nix": "unix-linux-os-scripts",
            "833": "unix-linux-os-scripts",
            "collectd": "linux-collectd-auditd",
            "3412": "linux-collectd-auditd",
            "linux:collectd:http:metrics": "linux-collectd-auditd",
        }
        for query, expected_key in cases.items():
            with self.subTest(query=query):
                result = self.run_setup("--phase", "resolve", "--profile", query, "--json")
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["profile"]["key"], expected_key)

    def test_coverage_phase_and_non_unix_resolution_are_explicit(self) -> None:
        coverage = self.run_setup("--phase", "coverage", "--json")
        self.assertEqual(coverage.returncode, 0, msg=coverage.stdout + coverage.stderr)
        payload = json.loads(coverage.stdout)

        self.assertEqual(payload["entry_count"], 80)
        self.assertEqual(payload["summary"]["first_class_profile"], 2)
        self.assertNotIn("manual_gap", payload["summary"])
        self.assertEqual(payload["summary"]["install_only_handoff"], 69)

        windows = self.run_setup("--phase", "resolve", "--profile", "Microsoft Windows", "--json")
        self.assertEqual(windows.returncode, 0, msg=windows.stdout + windows.stderr)
        windows_payload = json.loads(windows.stdout)
        self.assertEqual(windows_payload["coverage"]["status"], "install_only_handoff")
        self.assertEqual(windows_payload["coverage"]["readiness_source_pack"], "windows_security")

        apache = self.run_setup("--phase", "resolve", "--profile", "Apache Web Server", "--json")
        self.assertEqual(apache.returncode, 0, msg=apache.stdout + apache.stderr)
        apache_payload = json.loads(apache.stdout)
        self.assertEqual(apache_payload["coverage"]["status"], "install_only_handoff")
        self.assertEqual(apache_payload["coverage"]["handoff_skill"], "splunk-app-install")
        self.assertIn("official Supported Add-on handoff", apache_payload["coverage"]["notes"])
        self.assertIn("install_local_template", apache_payload["coverage"]["commands"])

        cisco = self.run_setup("--phase", "resolve", "--profile", "Cisco ISE", "--json")
        self.assertEqual(cisco.returncode, 0, msg=cisco.stdout + cisco.stderr)
        cisco_payload = json.loads(cisco.stdout)
        self.assertEqual(cisco_payload["coverage"]["status"], "handoff_profile")
        self.assertEqual(cisco_payload["coverage"]["handoff_skill"], "cisco-catalyst-ta-setup")

    def test_generic_supported_addon_handoff_render_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered = self.run_setup(
                "--phase",
                "render",
                "--profile",
                "Apache Web Server",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
            payload = json.loads(rendered.stdout)
            self.assertEqual(payload["coverage"]["key"], "apache-web-server")

            handoff_dir = Path(tmpdir) / "apache-web-server"
            plan = (handoff_dir / "handoff-plan.md").read_text(encoding="utf-8")
            commands = (handoff_dir / "install-commands.sh").read_text(encoding="utf-8")

            self.assertIn("Apache Web Server Supported Add-on Handoff", plan)
            self.assertIn("ADDON_PACKAGE", commands)
            self.assertIn("ADDON_URL", commands)
            self.assertIn("SPLUNKBASE_APP_ID", commands)

        install = self.run_setup("--phase", "install-command", "--profile", "Apache Web Server", "--json")
        self.assertEqual(install.returncode, 0, msg=install.stdout + install.stderr)
        install_payload = json.loads(install.stdout)
        self.assertEqual(install_payload["command"], ["bash", "skills/splunk-app-install/scripts/install_app.sh", "--help"])

        readiness = self.run_setup("--phase", "readiness-command", "--profile", "Microsoft Windows", "--json")
        self.assertEqual(readiness.returncode, 0, msg=readiness.stdout + readiness.stderr)
        readiness_payload = json.loads(readiness.stdout)
        self.assertIn("windows_security", readiness_payload["command"])

    def test_every_official_glossary_entry_resolves_and_renders(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        entries = catalog["official_glossary"]["entries"]

        with tempfile.TemporaryDirectory() as tmpdir:
            for entry in entries:
                with self.subTest(entry=entry["key"]):
                    resolved = self.run_setup("--phase", "resolve", "--profile", entry["name"], "--json")
                    self.assertEqual(resolved.returncode, 0, msg=resolved.stdout + resolved.stderr)
                    resolved_payload = json.loads(resolved.stdout)
                    self.assertTrue(
                        "profile" in resolved_payload or "coverage" in resolved_payload,
                        msg=resolved.stdout,
                    )

                    rendered = self.run_setup(
                        "--phase",
                        "render",
                        "--profile",
                        entry["name"],
                        "--output-dir",
                        tmpdir,
                        "--dry-run",
                        "--json",
                    )
                    self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
                    rendered_payload = json.loads(rendered.stdout)
                    self.assertTrue(
                        "profile" in rendered_payload or "coverage" in rendered_payload,
                        msg=rendered.stdout,
                    )

    def test_render_outputs_reviewable_unix_and_collectd_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            nix = self.run_setup(
                "--phase",
                "render",
                "--profile",
                "Splunk_TA_nix",
                "--output-dir",
                tmpdir,
                "--event-index",
                "os",
                "--metrics-index",
                "os_metrics",
                "--json",
            )
            self.assertEqual(nix.returncode, 0, msg=nix.stdout + nix.stderr)
            nix_dir = Path(tmpdir) / "unix-linux-os-scripts"
            nix_inputs = (nix_dir / "inputs.local.conf.template").read_text(encoding="utf-8")
            nix_plan = (nix_dir / "profile-plan.md").read_text(encoding="utf-8")
            nix_commands = (nix_dir / "install-commands.sh").read_text(encoding="utf-8")

            self.assertIn("Splunk_TA_nix", nix_plan)
            self.assertIn("sourcetype = linux_secure", nix_inputs)
            self.assertIn("index = os_metrics", nix_inputs)
            self.assertIn("--app-id 833", nix_commands)
            self.assertIn("splunk-data-source-readiness-doctor", nix_commands)

            collectd = self.run_setup(
                "--phase",
                "render",
                "--profile",
                "linux collectd",
                "--output-dir",
                tmpdir,
                "--event-index",
                "linux",
                "--metrics-index",
                "linux_metrics",
                "--json",
            )
            self.assertEqual(collectd.returncode, 0, msg=collectd.stdout + collectd.stderr)
            collectd_dir = Path(tmpdir) / "linux-collectd-auditd"
            collectd_http = (collectd_dir / "collectd-write-http.conf.template").read_text(encoding="utf-8")
            collectd_props = (collectd_dir / "props.local.conf.template").read_text(encoding="utf-8")
            collectd_inputs = (collectd_dir / "inputs.local.conf.template").read_text(encoding="utf-8")

            self.assertIn("linux:collectd:http:metrics", collectd_http)
            self.assertIn("METRICS_PROTOCOL = COLLECTD_HTTP", collectd_props)
            self.assertIn("sourcetype = linux:audit", collectd_inputs)
            self.assertNotIn("__HEC_TOKEN_VALUE__\n__HEC_TOKEN_VALUE__", collectd_http)

    def test_install_commands_route_to_splunk_app_install(self) -> None:
        result = self.run_setup("--phase", "install-command", "--profile", "3412", "--json")
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["command"][:3], ["bash", "skills/splunk-app-install/scripts/install_app.sh", "--source"])
        self.assertIn("3412", payload["command"])

    def test_registry_and_readiness_source_pack_route_to_router(self) -> None:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        apps = {app["splunkbase_id"]: app for app in registry["apps"]}
        topologies = {entry["skill"]: entry for entry in registry["skill_topologies"]}

        self.assertEqual(apps["833"]["skill"], "splunk-supported-addons-setup")
        self.assertEqual(apps["833"]["app_name"], "Splunk_TA_nix")
        self.assertTrue(apps["833"]["capabilities"]["uf_safe"])
        self.assertEqual(apps["3412"]["skill"], "splunk-supported-addons-setup")
        self.assertEqual(apps["3412"]["app_name"], "Splunk_TA_Linux")
        self.assertEqual(topologies["splunk-supported-addons-setup"]["role_support"]["universal-forwarder"], "supported")

        source_packs = json.loads(SOURCE_PACKS.read_text(encoding="utf-8"))
        linux_pack = next(pack for pack in source_packs["packs"] if pack["id"] == "linux_secure_auditd")
        self.assertIn("splunk-supported-addons-setup", linux_pack["handoffs"])
        self.assertIn("Splunk_TA_Linux", linux_pack["match"]["app_names"])
        self.assertIn("linux_audit", linux_pack["match"]["sourcetypes"])
        self.assertIn("linux:audit", linux_pack["defaults"]["expected_sourcetypes"])

    def test_rendered_handoff_commands_match_target_skill_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--phase",
                "render",
                "--profile",
                "Splunk_TA_Linux",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            commands = (Path(tmpdir) / "linux-collectd-auditd" / "install-commands.sh").read_text(encoding="utf-8")

            self.assertIn("skills/splunk-hec-service-setup/scripts/setup.sh", commands)
            self.assertIn("--sourcetype linux:collectd:http:json", commands)
            self.assertIn("--sourcetype linux:collectd:http:metrics", commands)
            self.assertIn("--default-index os --allowed-indexes os", commands)
            self.assertIn("--default-index os_metrics --allowed-indexes os_metrics", commands)
            self.assertNotIn("--default-sourcetype", commands)

    def test_generated_deployment_docs_surface_supported_addons_rows(self) -> None:
        cloud = CLOUD_MATRIX.read_text(encoding="utf-8")
        role = ROLE_MATRIX.read_text(encoding="utf-8")

        self.assertIn("| `splunk-supported-addons-setup` | N/A |", cloud)
        self.assertIn("| `splunk-supported-addons-setup` Unix/Linux | 833 |", cloud)
        self.assertIn("| `splunk-supported-addons-setup` Linux CollectD | 3412 |", cloud)
        self.assertIn("| `Splunk_TA_nix` | `splunk-supported-addons-setup` | Required | Supported | Supported | Supported | None |", role)
        self.assertIn("| `Splunk_TA_Linux` | `splunk-supported-addons-setup` | Required | Supported | Supported | Supported | Supported |", role)


if __name__ == "__main__":
    unittest.main()
