#!/usr/bin/env python3
"""Regression tests for the splunk-kvstore-admin-setup renderer and wrapper."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-kvstore-admin-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-kvstore-admin-setup/scripts/setup.sh"


class KvstoreAdminTests(unittest.TestCase):
    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(RENDERER), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def run_setup(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SETUP), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_shc_render_emits_lifecycle_and_governance_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--topology", "shc",
                "--collection-name", "asset_inventory",
                "--collection-fields", "ip:string,risk:number",
                "--lookup-definition-name", "asset_inventory_lookup",
                "--disable-startup-upgrade", "true",
                "--target-kvstore-version", "8.0",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "kvstore"
            for name in (
                "backup.sh", "restore.sh", "clean.sh", "migrate.sh", "upgrade.sh",
                "status.sh", "preflight.sh", "server.conf", "collections.conf", "transforms.conf",
            ):
                self.assertTrue((render_dir / name).exists(), name)
            collections = (render_dir / "collections.conf").read_text(encoding="utf-8")
            transforms = (render_dir / "transforms.conf").read_text(encoding="utf-8")
            server = (render_dir / "server.conf").read_text(encoding="utf-8")
            migrate = (render_dir / "migrate.sh").read_text(encoding="utf-8")
            upgrade = (render_dir / "upgrade.sh").read_text(encoding="utf-8")
            backup = (render_dir / "backup.sh").read_text(encoding="utf-8")
            self.assertIn("[asset_inventory]", collections)
            self.assertIn("field.ip = string", collections)
            self.assertIn("external_type = kvstore", transforms)
            self.assertIn("fields_list = _key, ip, risk", transforms)
            self.assertIn("kvstoreUpgradeOnStartupEnabled = false", server)
            self.assertIn("start-shcluster-migration kvstore -storageEngine wiredTiger", migrate)
            self.assertIn("start-shcluster-upgrade kvstore -version", upgrade)
            self.assertIn("backup kvstore -pointInTime true", backup)
            self.assertIn("spv_require_supported_splunk_home", backup)

    def test_rejects_arbitrary_enterprise_version_as_kvstore_server_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--topology", "shc",
                "--target-kvstore-version", "10.5",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("supported 7.0 or 8.0.x", result.stderr)

    def test_rejects_bad_field_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--collection-name", "c1",
                "--collection-fields", "ip:ipaddress",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Field type", result.stderr)

    def test_rejects_lookup_without_collection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--lookup-definition-name", "orphan_lookup",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires --collection-name", result.stderr)

    def test_restore_refused_without_acceptance_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--phase", "apply",
                "--operation", "restore",
                "--backup-archive-name", "kvdump.tar.gz",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-kvstore-restore", result.stdout + result.stderr)

    def test_clean_refused_without_acceptance_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--phase", "apply",
                "--operation", "clean",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-kvstore-clean", result.stdout + result.stderr)

    def test_dry_run_collections_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--dry-run",
                "--phase", "apply",
                "--operation", "collections",
                "--collection-name", "asset_inventory",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)

    def test_cloud_host_lifecycle_apply_exits_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            for operation in ("backup", "restore", "clean", "migrate", "upgrade"):
                with self.subTest(operation=operation):
                    output_dir = Path(tmpdir) / operation
                    output_dir.mkdir()
                    sentinel = output_dir / "operator-note.txt"
                    sentinel.write_text("preserve me\n", encoding="utf-8")
                    result = self.run_setup(
                        "--output-dir", str(output_dir),
                        "--platform", "cloud",
                        "--phase", "apply",
                        "--operation", operation,
                    )
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 2, msg=output)
                    self.assertIn("not customer-managed on Splunk Cloud", output)
                    self.assertFalse((output_dir / "kvstore").exists())
                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    def test_auto_platform_resolves_cloud_before_lifecycle_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            env = os.environ.copy()
            env["SPLUNK_PLATFORM"] = "cloud"
            result = subprocess.run(
                [
                    "bash", str(SETUP),
                    "--output-dir", str(output_dir),
                    "--phase", "apply",
                    "--operation", "backup",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
            self.assertFalse(output_dir.exists())

    def test_cloud_rendered_host_script_is_a_non_mutating_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            splunk_home = Path(tmpdir) / "managed-cloud-must-not-exist"
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--platform", "cloud",
                "--splunk-home", str(splunk_home),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "kvstore"
            for name in ("backup.sh", "restore.sh", "clean.sh", "migrate.sh", "upgrade.sh"):
                with self.subTest(script=name):
                    script = render_dir / name
                    applied = subprocess.run(
                        ["bash", str(script)],
                        cwd=script.parent,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )
                    self.assertEqual(applied.returncode, 2, msg=applied.stdout + applied.stderr)
                    self.assertIn("Managed Splunk Cloud owns KV Store host lifecycle", applied.stderr)
            self.assertFalse(splunk_home.exists())

    def test_cloud_collection_governance_dry_run_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "cloud",
                "--dry-run",
                "--phase", "apply",
                "--operation", "collections",
                "--collection-name", "asset_inventory",
                "--collection-fields", "ip:string,risk:number",
                "--lookup-definition-name", "asset_inventory_lookup",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("via REST", result.stdout + result.stderr)
            self.assertIn("on cloud", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
