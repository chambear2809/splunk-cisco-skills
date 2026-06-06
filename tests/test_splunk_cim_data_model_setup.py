#!/usr/bin/env python3
"""Regression tests for the splunk-cim-data-model-setup renderer and wrapper."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-cim-data-model-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-cim-data-model-setup/scripts/setup.sh"


class CimDataModelTests(unittest.TestCase):
    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(RENDERER), *args],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
        )

    def run_setup(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SETUP), *args],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
        )

    def test_render_acceleration_and_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--datamodel", "Network_Traffic",
                "--acceleration", "true",
                "--earliest-time", "-7d",
                "--constrain-indexes", "netfw,proxy",
                "--eventtype-name", "cisco_auth",
                "--eventtype-search", "sourcetype=cisco:ise",
                "--tags", "authentication",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "cim"
            datamodels = (render_dir / "datamodels.conf").read_text(encoding="utf-8")
            macros = (render_dir / "macros.conf").read_text(encoding="utf-8")
            tags = (render_dir / "tags.conf").read_text(encoding="utf-8")
            self.assertIn("[Network_Traffic]", datamodels)
            self.assertIn("acceleration = 1", datamodels)
            self.assertIn("[cim_Network_Traffic_indexes]", macros)
            self.assertIn("(index=netfw OR index=proxy)", macros)
            self.assertIn("[eventtype=cisco_auth]", tags)
            self.assertIn("authentication = enabled", tags)

    def test_rejects_unknown_cim_model_without_custom_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer("--output-dir", tmpdir, "--datamodel", "My_Custom_Model")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not a known CIM model", result.stderr)

    def test_allows_custom_model_with_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir, "--datamodel", "My_Custom_Model",
                "--allow-custom-datamodel", "true",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)

    def test_acceleration_apply_refused_without_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--phase", "apply",
                "--datamodel", "Network_Traffic",
                "--acceleration", "true",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-acceleration", result.stdout + result.stderr)

    def test_dry_run_apply_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--dry-run", "--phase", "apply",
                "--datamodel", "Network_Traffic",
                "--acceleration", "true",
                "--accept-acceleration",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
