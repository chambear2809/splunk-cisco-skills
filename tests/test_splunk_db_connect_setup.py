"""Regression tests for splunk-db-connect-setup."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills/splunk-db-connect-setup"
SETUP = SKILL_DIR / "scripts/setup.sh"
RENDERER = SKILL_DIR / "scripts/render_assets.py"
VALIDATE = SKILL_DIR / "scripts/validate.sh"
TEMPLATE = SKILL_DIR / "template.example"
REGISTRY = REPO_ROOT / "skills/shared/app_registry.json"


def run_cmd(args: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=check,
    )


def write_spec(tmp: Path, body: str) -> Path:
    path = tmp / "spec.yaml"
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return path


def load_renderer_module():
    spec = importlib.util.spec_from_file_location("dbx_render_assets", RENDERER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SplunkDbConnectSetupTests(unittest.TestCase):
    def test_cli_help(self) -> None:
        for command in (
            ["bash", str(SETUP), "--help"],
            [sys.executable, str(RENDERER), "--help"],
            ["bash", str(VALIDATE), "--help"],
        ):
            with self.subTest(command=command):
                result = run_cmd(command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("DB Connect", result.stdout)

    def test_template_renders_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "rendered"
            result = run_cmd(
                [
                    "bash",
                    str(SETUP),
                    "--render",
                    "--validate",
                    "--spec",
                    str(TEMPLATE),
                    "--output-dir",
                    str(out),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            root = out / "splunk-db-connect"
            metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
            inventory = json.loads((root / "drivers/driver-inventory.json").read_text(encoding="utf-8"))
            install_script = (root / "install/install-apps.sh").read_text(encoding="utf-8")
            validation_spl = (root / "validation/validation.spl").read_text(encoding="utf-8")
            coverage = json.loads((root / "coverage.json").read_text(encoding="utf-8"))

            self.assertEqual(metadata["spec_version"], "splunk-db-connect-setup/v1")
            self.assertEqual(metadata["app"]["splunkbase_id"], "2686")
            self.assertIn("6150", metadata["install_ids"])
            self.assertIn("6152", metadata["install_ids"])
            self.assertEqual(inventory["db_connect"]["latest_verified_version"], "4.2.4")
            self.assertIn("skills/splunk-app-install/scripts/install_app.sh", install_script)
            self.assertIn("--app-id 2686", install_script)
            self.assertIn("--app-id 6150", install_script)
            self.assertIn("dbxquery", (root / "troubleshooting/runbook.md").read_text(encoding="utf-8"))
            self.assertIn("index=dbx_orders", validation_spl)
            self.assertTrue((root / "drivers/custom-driver-app/lib/dbxdrivers/README.md").is_file())
            self.assertIn(
                "db_connection_types",
                (root / "drivers/custom-driver-app/default/db_connection_types.conf").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Splunk Cloud Victoria DB Connect runs on the Cloud search head",
                (root / "cloud/outbound-allowlist.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Federated Search",
                (root / "operations/federated-search.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "Entra",
                (root / "security/auth-handoffs.md").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "3.18.5",
                (root / "operations/upgrade-backup-health.md").read_text(encoding="utf-8"),
            )
            features = set(coverage["coverage"]["features"])
            self.assertIn("cloud-custom-driver-lib-dbxdrivers", features)
            self.assertIn("databricks-data-source", features)
            self.assertIn("monitoring-console-health-checks", features)
            self.assertIn("fips-fresh-install-manual", features)
            self.assertIn("db-connect-over-federated-search", features)
            self.assertIn("external-secret-store-handoffs", features)

    def test_plaintext_and_fake_encrypted_secrets_are_rejected(self) -> None:
        cases = {
            "plaintext_password": """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                java:
                  version: "17"
                identities:
                  - name: bad
                    username: app
                    password: plaintext
            """,
            "fake_encrypted": """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                java:
                  version: "17"
                identities:
                  - name: bad
                    username: app
                    password_file: /tmp/dbx_password
                    copied_encrypted_value: "$7$not-portable"
            """,
            "jdbc_password": """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                java:
                  version: "21"
                connections:
                  - name: bad
                    jdbc_url: jdbc:postgresql://user:secret@db.example.com:5432/app
            """,
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for name, body in cases.items():
                with self.subTest(name=name):
                    spec = write_spec(tmp, body)
                    result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(spec)])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("ERROR", result.stderr)

    def test_topology_guardrails(self) -> None:
        cases = {
            "indexer": "indexer",
            "uf": "universal-forwarder",
            "deployment_server": "deployment-server",
            "shc_member": "shc-member",
        }
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            for name, target in cases.items():
                with self.subTest(name=name):
                    spec = write_spec(
                        tmp,
                        f"""
                        version: splunk-db-connect-setup/v1
                        platform:
                          type: enterprise
                        topology:
                          mode: single_sh
                          install_targets:
                            - {target}
                        java:
                          version: "17"
                        """,
                    )
                    result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(spec)])
                    self.assertNotEqual(result.returncode, 0)

    def test_cloud_classic_and_victoria_guardrails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            classic = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: cloud_classic
                topology:
                  mode: cloud_classic
                  install_targets:
                    - search-tier
                install:
                  install_apps: true
                java:
                  version: "17"
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(classic)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Cloud Classic", result.stderr)

            victoria_missing = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: cloud_victoria
                topology:
                  mode: cloud_victoria
                  install_targets:
                    - search-tier
                java:
                  version: "21"
                connections:
                  - name: appdb
                    jdbc_url: jdbc:postgresql://db.example.com:5432/app
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(victoria_missing)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outbound", result.stderr)

            victoria_ok = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: cloud_victoria
                topology:
                  mode: cloud_victoria
                  install_targets:
                    - search-tier
                java:
                  version: splunk-managed
                connections:
                  - name: appdb
                    jdbc_url: jdbc:postgresql://db.example.com:5432/app
                cloud_network:
                  outbound_allowlist:
                    - host: db.example.com
                      port: 5432
                      protocol: tcp
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(victoria_ok)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Splunk-managed", result.stdout)

            victoria_hf = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: cloud_victoria
                topology:
                  mode: cloud_victoria
                  install_targets:
                    - heavy-forwarder
                java:
                  version: "21"
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(victoria_hf)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("customer-managed heavy forwarders", result.stderr)

    def test_java_shc_archived_driver_and_hf_ha_rules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            java_11 = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                java:
                  version: "11"
                """,
            )
            self.assertNotEqual(
                run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(java_11)]).returncode,
                0,
            )

            shc_missing_deployer = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: shc
                  install_targets:
                    - search-tier
                java:
                  version: "17"
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(shc_missing_deployer)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("shc_deployer", result.stderr)

            archived = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                java:
                  version: "17"
                drivers:
                  - name: influx
                    type: splunkbase
                    splunkbase_id: "6759"
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(archived)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archived", result.stderr)

            hf_ha = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: heavy_forwarder_ha
                  install_targets:
                    - heavy-forwarder
                java:
                  version: "21"
                ha:
                  enabled: true
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(hf_ha)])
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("HF HA requested", result.stdout)

    def test_fips_requires_fresh_manual_install_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            fips_no_fresh_install = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                install:
                  install_apps: false
                java:
                  version: "21"
                security:
                  fips_mode: true
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(fips_no_fresh_install)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fips_fresh_install", result.stderr)

            fips_install_handoff = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                install:
                  install_apps: true
                java:
                  version: "21"
                security:
                  fips_mode: true
                  fips_fresh_install: true
                """,
            )
            result = run_cmd(["bash", str(SETUP), "--preflight", "--spec", str(fips_install_handoff)])
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manual fresh-install", result.stderr)

    def test_unknown_driver_is_not_installed_by_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = write_spec(
                tmp,
                """
                version: splunk-db-connect-setup/v1
                platform:
                  type: enterprise
                topology:
                  mode: single_sh
                  install_targets:
                    - search-tier
                java:
                  version: "17"
                drivers:
                  - name: manual-driver
                    type: splunkbase
                    splunkbase_id: "999999"
                """,
            )
            out = tmp / "rendered"
            result = run_cmd(
                [
                    "bash",
                    str(SETUP),
                    "--render",
                    "--validate",
                    "--spec",
                    str(spec),
                    "--output-dir",
                    str(out),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            install_script = (out / "splunk-db-connect/install/install-apps.sh").read_text(encoding="utf-8")
            self.assertIn("--app-id 2686", install_script)
            self.assertNotIn("--app-id 999999", install_script)
            self.assertIn("SKIP: driver app 999999", install_script)

    def test_driver_catalog_and_registry_coverage(self) -> None:
        module = load_renderer_module()
        expected = {
            "6149": ("1.2.2", "September 3, 2025"),
            "6150": ("1.3.2", "August 8, 2025"),
            "6151": ("2.2.2", "September 3, 2025"),
            "6152": ("1.2.2", "September 3, 2025"),
            "6153": ("1.2.4", "March 19, 2026"),
            "6154": ("1.1.3", "September 3, 2025"),
            "6332": ("1.1.1", "September 22, 2025"),
            "7095": ("1.3.0", "September 3, 2025"),
            "8133": ("1.0.1", "December 16, 2025"),
        }
        for app_id, (version, release_date) in expected.items():
            with self.subTest(app_id=app_id):
                self.assertEqual(module.DRIVER_CATALOG[app_id]["version"], version)
                self.assertEqual(module.DRIVER_CATALOG[app_id]["release_date"], release_date)
                self.assertEqual(module.DRIVER_CATALOG[app_id]["status"], "supported")

        self.assertEqual(module.DRIVER_CATALOG["6759"]["status"], "archived")
        self.assertEqual(module.DRIVER_CATALOG["6759"]["release_date"], "March 30, 2023")
        for database in ("informix", "sap-sql-anywhere", "sybase-ase", "hive", "bigquery", "databricks"):
            self.assertIn(database, module.CUSTOM_DRIVER_DATABASES)

        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        apps_by_id = {app["splunkbase_id"]: app for app in registry["apps"]}
        self.assertEqual(apps_by_id["2686"]["app_name"], "splunk_app_db_connect")
        self.assertEqual(apps_by_id["2686"]["latest_verified_version"], "4.2.4")
        self.assertNotIn("6759", apps_by_id)

        topology = next(item for item in registry["skill_topologies"] if item["skill"] == "splunk-db-connect-setup")
        self.assertEqual(topology["role_support"]["search-tier"], "supported")
        self.assertEqual(topology["role_support"]["heavy-forwarder"], "supported")
        self.assertEqual(topology["role_support"]["indexer"], "none")


if __name__ == "__main__":
    unittest.main()
