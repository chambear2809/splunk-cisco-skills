#!/usr/bin/env python3
"""Regression tests for the splunk-knowledge-objects-setup renderer and wrapper."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-knowledge-objects-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-knowledge-objects-setup/scripts/setup.sh"


class KnowledgeObjectsTests(unittest.TestCase):
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

    def test_macro_with_args_renders_arity_stanza(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--object-kind", "macro",
                "--name", "net_idx",
                "--args", "a,b",
                "--definition", "index IN ($a$,$b$)",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            macros = (Path(tmpdir) / "knowledge-objects" / "macros.conf").read_text(encoding="utf-8")
            self.assertIn("[net_idx(2)]", macros)
            self.assertIn("args = a, b", macros)

    def test_csv_lookup_emits_transform_props_and_stub(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--object-kind", "lookup",
                "--name", "asset_lookup",
                "--lookup-type", "csv",
                "--lookup-filename", "assets.csv",
                "--fields-list", "ip,risk",
                "--auto-lookup-sourcetype", "cisco:ise",
                "--lookup-output-fields", "risk",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "knowledge-objects"
            transforms = (render_dir / "transforms.conf").read_text(encoding="utf-8")
            props = (render_dir / "props.conf").read_text(encoding="utf-8")
            self.assertIn("filename = assets.csv", transforms)
            self.assertIn("LOOKUP-asset_lookup = asset_lookup OUTPUT risk", props)
            self.assertTrue((render_dir / "lookup-stub.csv").exists())

    def test_savedsearch_requires_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir, "--object-kind", "savedsearch", "--name", "S1",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--search is required", result.stderr)

    def test_global_sharing_refused_without_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--phase", "apply",
                "--object-kind", "macro",
                "--name", "net_idx",
                "--definition", "index IN (a)",
                "--sharing", "global",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-global-sharing", result.stdout + result.stderr)

    def test_dry_run_apply_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--dry-run", "--phase", "apply",
                "--object-kind", "macro",
                "--name", "net_idx",
                "--definition", "index IN (a)",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
