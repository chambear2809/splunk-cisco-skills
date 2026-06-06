#!/usr/bin/env python3
"""Regression tests for the splunk-kvstore-admin-setup renderer and wrapper."""

from __future__ import annotations

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
                "--phase", "apply",
                "--operation", "clean",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-kvstore-clean", result.stdout + result.stderr)

    def test_dry_run_collections_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--dry-run",
                "--phase", "apply",
                "--operation", "collections",
                "--collection-name", "asset_inventory",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
