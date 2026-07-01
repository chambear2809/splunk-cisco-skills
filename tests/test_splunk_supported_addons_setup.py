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

        self.assertEqual(catalog["last_researched"], "2026-06-06")
        self.assertIn("unix-linux-os-scripts", profiles)
        self.assertIn("linux-collectd-auditd", profiles)
        self.assertEqual(len(catalog["official_glossary"]["entries"]), 80)
        routes = catalog["official_glossary"]["routes"]
        self.assertEqual(routes["unix-and-linux"]["profile"], "unix-linux-os-scripts")
        self.assertEqual(routes["linux"]["profile"], "linux-collectd-auditd")
        self.assertEqual(routes["amazon-kinesis-firehose"]["handoff_skill"], "splunk-amazon-kinesis-firehose-setup")
        self.assertEqual(routes["amazon-kinesis-firehose"]["readiness_source_pack"], "amazon_kinesis_firehose")
        self.assertEqual(routes["cisco-asa"]["handoff_skill"], "cisco-asa-ta-setup")
        self.assertEqual(routes["cisco-asa"]["readiness_source_pack"], "cisco_asa")
        self.assertEqual(routes["cisco-ise"]["handoff_skill"], "cisco-catalyst-ta-setup")
        self.assertEqual(routes["microsoft-windows"]["status"], "handoff_profile")
        self.assertEqual(routes["microsoft-windows"]["handoff_skill"], "splunk-windows-ta-setup")
        self.assertEqual(routes["amazon-web-services"]["handoff_skill"], "splunk-aws-ta-setup")
        self.assertEqual(routes["microsoft-office-365"]["handoff_skill"], "splunk-microsoft-cloud-setup")
        self.assertEqual(routes["microsoft-cloud-services"]["handoff_skill"], "splunk-microsoft-cloud-setup")
        self.assertEqual(routes["okta-identity-cloud"]["handoff_skill"], "splunk-okta-ta-setup")
        self.assertEqual(routes["google-cloud-platform"]["handoff_skill"], "splunk-gcp-ta-setup")
        self.assertEqual(routes["servicenow"]["handoff_skill"], "splunk-servicenow-ta-setup")
        self.assertEqual(routes["google-workspace"]["handoff_skill"], "splunk-google-workspace-ta-setup")
        self.assertEqual(routes["microsoft-security"]["handoff_skill"], "splunk-microsoft-security-ta-setup")
        self.assertEqual(routes["sysmon"]["handoff_skill"], "splunk-sysmon-ta-setup")
        self.assertEqual(routes["github"]["handoff_skill"], "splunk-github-ta-setup")
        self.assertEqual(routes["vmware"]["handoff_skill"], "splunk-vmware-ta-setup")
        self.assertEqual(routes["vmware-esxi-logs"]["handoff_skill"], "splunk-vmware-ta-setup")
        self.assertEqual(routes["vmware-metrics-indexes"]["handoff_skill"], "splunk-vmware-ta-setup")
        self.assertEqual(routes["salesforce"]["handoff_skill"], "splunk-salesforce-ta-setup")
        self.assertEqual(routes["salesforce"]["readiness_source_pack"], "salesforce")
        self.assertEqual(routes["box"]["handoff_skill"], "splunk-box-ta-setup")
        self.assertEqual(routes["cyberark"]["readiness_source_pack"], "cyberark_epv_pta")
        self.assertEqual(routes["cyberark-epm"]["readiness_source_pack"], "cyberark_epm")
        self.assertEqual(routes["rsa-securid"]["handoff_skill"], "splunk-rsa-securid-ta-setup")
        self.assertEqual(routes["rsa-securid-cas"]["readiness_source_pack"], "rsa_securid_cas")
        self.assertEqual(routes["symantec-blue-coat-proxysg"]["handoff_skill"], "splunk-syslog-web-proxy-ta-setup")
        self.assertEqual(routes["symantec-blue-coat-proxysg"]["product_selector"], "bluecoat")
        self.assertEqual(routes["crowdstrike-fdr"]["readiness_source_pack"], "crowdstrike_falcon")
        self.assertEqual(routes["microsoft-sql-server"]["handoff_skill"], "splunk-database-ta-setup")
        self.assertEqual(routes["microsoft-sql-server"]["readiness_source_pack"], "mssql_database")
        self.assertEqual(routes["mysql"]["product_selector"], "mysql")
        self.assertEqual(routes["oracle-database"]["readiness_source_pack"], "oracle_database")
        self.assertEqual(routes["microsoft-exchange"]["handoff_skill"], "splunk-microsoft-exchange-ta-setup")
        self.assertEqual(routes["microsoft-scom"]["readiness_source_pack"], "microsoft_scom")
        self.assertEqual(routes["microsoft-hyper-v"]["handoff_skill"], "splunk-windows-ta-setup")
        self.assertEqual(routes["microsoft-hyper-v"]["product_selector"], "hyper_v")
        self.assertEqual(routes["netapp-data-ontap"]["handoff_skill"], "splunk-netapp-ontap-ta-setup")
        self.assertEqual(routes["netapp-data-ontap-extractions"]["product_selector"], "extractions")
        self.assertEqual(routes["netapp-data-ontap-indexes"]["product_selector"], "indexes")
        self.assertEqual(routes["carbon-black"]["readiness_source_pack"], "carbon_black")
        self.assertEqual(routes["symantec-endpoint-protection"]["handoff_skill"], "splunk-security-appliance-ta-setup")
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
        self.assertEqual(payload["summary"]["install_only_handoff"], 20)
        self.assertEqual(payload["summary"]["handoff_profile"], 58)

        windows = self.run_setup("--phase", "resolve", "--profile", "Microsoft Windows", "--json")
        self.assertEqual(windows.returncode, 0, msg=windows.stdout + windows.stderr)
        windows_payload = json.loads(windows.stdout)
        self.assertEqual(windows_payload["coverage"]["status"], "handoff_profile")
        self.assertEqual(windows_payload["coverage"]["handoff_skill"], "splunk-windows-ta-setup")
        self.assertEqual(windows_payload["coverage"]["readiness_source_pack"], "windows_security")

        apache = self.run_setup("--phase", "resolve", "--profile", "Apache Web Server", "--json")
        self.assertEqual(apache.returncode, 0, msg=apache.stdout + apache.stderr)
        apache_payload = json.loads(apache.stdout)
        self.assertEqual(apache_payload["coverage"]["status"], "handoff_profile")
        self.assertEqual(apache_payload["coverage"]["handoff_skill"], "splunk-syslog-web-proxy-ta-setup")
        self.assertEqual(apache_payload["coverage"]["readiness_source_pack"], "apache_web")
        self.assertEqual(apache_payload["coverage"]["product_selector"], "apache")

        cisco = self.run_setup("--phase", "resolve", "--profile", "Cisco ISE", "--json")
        self.assertEqual(cisco.returncode, 0, msg=cisco.stdout + cisco.stderr)
        cisco_payload = json.loads(cisco.stdout)
        self.assertEqual(cisco_payload["coverage"]["status"], "handoff_profile")
        self.assertEqual(cisco_payload["coverage"]["handoff_skill"], "cisco-catalyst-ta-setup")

        asa = self.run_setup("--phase", "resolve", "--profile", "Cisco ASA", "--json")
        self.assertEqual(asa.returncode, 0, msg=asa.stdout + asa.stderr)
        asa_payload = json.loads(asa.stdout)
        self.assertEqual(asa_payload["coverage"]["status"], "handoff_profile")
        self.assertEqual(asa_payload["coverage"]["handoff_skill"], "cisco-asa-ta-setup")

        firehose = self.run_setup("--phase", "resolve", "--profile", "Amazon Kinesis Firehose", "--json")
        self.assertEqual(firehose.returncode, 0, msg=firehose.stdout + firehose.stderr)
        firehose_payload = json.loads(firehose.stdout)
        self.assertEqual(firehose_payload["coverage"]["status"], "handoff_profile")
        self.assertEqual(
            firehose_payload["coverage"]["handoff_skill"],
            "splunk-amazon-kinesis-firehose-setup",
        )

        vmware = self.run_setup("--phase", "resolve", "--profile", "VMware Metrics Indexes", "--json")
        self.assertEqual(vmware.returncode, 0, msg=vmware.stdout + vmware.stderr)
        vmware_payload = json.loads(vmware.stdout)
        self.assertEqual(vmware_payload["coverage"]["status"], "handoff_profile")
        self.assertEqual(vmware_payload["coverage"]["handoff_skill"], "splunk-vmware-ta-setup")

    def test_generic_supported_addon_handoff_render_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            rendered = self.run_setup(
                "--phase",
                "render",
                "--profile",
                "BMC Remedy",
                "--output-dir",
                tmpdir,
                "--json",
            )
            self.assertEqual(rendered.returncode, 0, msg=rendered.stdout + rendered.stderr)
            payload = json.loads(rendered.stdout)
            self.assertEqual(payload["coverage"]["key"], "bmc-remedy")

            handoff_dir = Path(tmpdir) / "bmc-remedy"
            plan = (handoff_dir / "handoff-plan.md").read_text(encoding="utf-8")
            commands = (handoff_dir / "install-commands.sh").read_text(encoding="utf-8")

            self.assertIn("BMC Remedy Supported Add-on Handoff", plan)
            self.assertIn("ADDON_PACKAGE", commands)
            self.assertIn("ADDON_URL", commands)
            self.assertIn("SPLUNKBASE_APP_ID", commands)

        install = self.run_setup("--phase", "install-command", "--profile", "BMC Remedy", "--json")
        self.assertNotEqual(install.returncode, 0)
        self.assertIn("no executable install route", install.stdout + install.stderr)
        self.assertIn("explicit source", install.stdout + install.stderr)

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
        self.assertEqual(apps["3549"]["skill"], "splunk-salesforce-ta-setup")
        self.assertEqual(apps["2679"]["app_name"], "Splunk_TA_box")
        self.assertEqual(apps["5160"]["skill"], "splunk-cyberark-ta-setup")
        self.assertTrue(apps["2891"]["capabilities"]["uf_safe"])
        self.assertEqual(apps["5210"]["app_name"], "Splunk_TA_rsa_securid_cas")
        self.assertEqual(apps["3186"]["skill"], "splunk-syslog-web-proxy-ta-setup")
        self.assertEqual(apps["2648"]["skill"], "splunk-database-ta-setup")
        self.assertEqual(apps["2648"]["app_name"], "Splunk_TA_microsoft-sqlserver")
        self.assertEqual(apps["2848"]["app_name"], "Splunk_TA_mysql")
        self.assertEqual(apps["1910"]["app_name"], "Splunk_TA_oracle")
        self.assertEqual(apps["3225"]["skill"], "splunk-microsoft-exchange-ta-setup")
        self.assertEqual(apps["5663"]["app_name"], "SA-ExchangeIndex")
        self.assertEqual(apps["2729"]["app_name"], "Splunk_TA_microsoft-scom")
        self.assertEqual(apps["3418"]["skill"], "splunk-netapp-ontap-ta-setup")
        self.assertEqual(apps["5615"]["app_name"], "TA-ONTAP-FieldExtractions")
        self.assertEqual(apps["5616"]["app_name"], "SA-ONTAPIndex")
        self.assertEqual(apps["2790"]["skill"], "splunk-security-appliance-ta-setup")
        self.assertEqual(apps["2772"]["app_name"], "Splunk_TA_symantec-ep")
        self.assertIn("splunk-syslog-web-proxy-ta-setup", topologies)
        self.assertIn("splunk-database-ta-setup", topologies)
        self.assertIn("splunk-microsoft-exchange-ta-setup", topologies)
        self.assertIn("splunk-microsoft-scom-ta-setup", topologies)
        self.assertIn("splunk-netapp-ontap-ta-setup", topologies)
        self.assertIn("splunk-security-appliance-ta-setup", topologies)
        self.assertEqual(topologies["splunk-supported-addons-setup"]["role_support"]["universal-forwarder"], "supported")

        source_packs = json.loads(SOURCE_PACKS.read_text(encoding="utf-8"))
        linux_pack = next(pack for pack in source_packs["packs"] if pack["id"] == "linux_secure_auditd")
        self.assertIn("splunk-supported-addons-setup", linux_pack["handoffs"])
        self.assertIn("Splunk_TA_Linux", linux_pack["match"]["app_names"])
        self.assertIn("linux_audit", linux_pack["match"]["sourcetypes"])
        self.assertIn("linux:audit", linux_pack["defaults"]["expected_sourcetypes"])
        packs = {pack["id"]: pack for pack in source_packs["packs"]}
        self.assertIn("Splunk_TA_microsoft-sqlserver", packs["mssql_database"]["match"]["app_names"])
        self.assertIn("MSExchange:2013:MessageTracking", packs["microsoft_exchange"]["defaults"]["expected_sourcetypes"])
        self.assertIn("Splunk_TA_microsoft-scom", packs["microsoft_scom"]["match"]["app_names"])
        self.assertIn("ontap:perf", packs["netapp_ontap"]["defaults"]["expected_sourcetypes"])
        self.assertIn("bit9:carbonblack:json", packs["carbon_black"]["match"]["sourcetypes"])
        self.assertIn("symantec:ep:risk:file", packs["symantec_endpoint_protection"]["defaults"]["expected_sourcetypes"])

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

    def test_new_shared_syslog_routes_cover_selected_parser_products(self) -> None:
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        routes = catalog["official_glossary"]["routes"]
        expected = {
            "apache-web-server": ("apache_web", "apache"),
            "nginx": ("nginx_web", "nginx"),
            "microsoft-iis": ("microsoft_iis", "iis"),
            "tomcat": ("tomcat_web", "tomcat"),
            "haproxy": ("haproxy", "haproxy"),
            "squid-proxy": ("squid_proxy", "squid"),
            "symantec-blue-coat-proxysg": ("bluecoat_proxy", "bluecoat"),
            "forcepoint-web-security": ("forcepoint_web", "forcepoint"),
            "check-point-log-exporter": ("checkpoint_log_exporter", "checkpoint"),
            "f5-big-ip": ("f5_bigip", "f5"),
            "citrix-netscaler": ("citrix_netscaler", "citrix"),
            "infoblox": ("infoblox", "infoblox"),
        }
        for key, (pack, selector) in expected.items():
            with self.subTest(key=key):
                self.assertEqual(routes[key]["status"], "handoff_profile")
                self.assertEqual(routes[key]["handoff_skill"], "splunk-syslog-web-proxy-ta-setup")
                self.assertEqual(routes[key]["readiness_source_pack"], pack)
                self.assertEqual(routes[key]["product_selector"], selector)

    def test_generated_deployment_docs_surface_supported_addons_rows(self) -> None:
        cloud = CLOUD_MATRIX.read_text(encoding="utf-8")
        role = ROLE_MATRIX.read_text(encoding="utf-8")

        self.assertIn("| `splunk-supported-addons-setup` | N/A |", cloud)
        self.assertIn("| `splunk-supported-addons-setup` Unix/Linux | 833 |", cloud)
        self.assertIn("| `splunk-supported-addons-setup` Linux CollectD | 3412 |", cloud)
        self.assertIn("| `Splunk_TA_nix` | `splunk-supported-addons-setup` | Required | Supported | Supported | Supported | None |", role)
        self.assertIn("| `Splunk_TA_Linux` | `splunk-supported-addons-setup` | Required | Supported | Supported | Supported | Supported |", role)
        self.assertIn("| `splunk-salesforce-ta-setup` | 3549 |", cloud)
        self.assertIn("| `splunk-syslog-web-proxy-ta-setup` | Multiple |", cloud)
        self.assertIn("| `Splunk_TA_salesforce` | `splunk-salesforce-ta-setup` | Required | None | Supported | None | None |", role)
        self.assertIn("| `Splunk_TA_bluecoat-proxysg` | `splunk-syslog-web-proxy-ta-setup` | Required | Supported | Supported | Supported | Supported |", role)
        self.assertIn("| `splunk-database-ta-setup` | Multiple |", cloud)
        self.assertIn("| `splunk-microsoft-exchange-ta-setup` | Multiple |", cloud)
        self.assertIn("| `splunk-microsoft-scom-ta-setup` | 2729 |", cloud)
        self.assertIn("| `splunk-netapp-ontap-ta-setup` | Multiple |", cloud)
        self.assertIn("| `splunk-security-appliance-ta-setup` | Multiple |", cloud)
        self.assertIn("| `Splunk_TA_microsoft-sqlserver` | `splunk-database-ta-setup` | Required | Supported | Supported | Supported | None |", role)
        self.assertIn("| `TA-Exchange-ClientAccess` | `splunk-microsoft-exchange-ta-setup` | Required | Supported | Supported | Supported | None |", role)
        self.assertIn("| `Splunk_TA_microsoft-scom` | `splunk-microsoft-scom-ta-setup` | Required | None | Supported | None | None |", role)
        self.assertIn("| `Splunk_TA_ontap` | `splunk-netapp-ontap-ta-setup` | Required | Supported | Supported | None | None |", role)
        self.assertIn("| `Splunk_TA_bit9-carbonblack` | `splunk-security-appliance-ta-setup` | Required | Supported | Supported | Supported | Supported |", role)


if __name__ == "__main__":
    unittest.main()
