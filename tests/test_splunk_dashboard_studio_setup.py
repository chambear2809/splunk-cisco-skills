#!/usr/bin/env python3
"""Regression tests for the splunk-dashboard-studio-setup renderer and wrapper."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-dashboard-studio-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-dashboard-studio-setup/scripts/setup.sh"


class DashboardStudioTests(unittest.TestCase):
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

    def test_build_from_search_emits_version2_xml_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--dashboard-name", "net_overview",
                "--title", "Network Overview",
                "--search", "index=netfw | stats count by action",
                "--viz-type", "splunk.column",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "dashboard-studio"
            view = (render_dir / "view.xml").read_text(encoding="utf-8")
            definition = json.loads((render_dir / "dashboard.json").read_text(encoding="utf-8"))
            self.assertIn('<dashboard version="2"', view)
            self.assertIn("<![CDATA[", view)
            self.assertEqual(definition["visualizations"]["viz_primary"]["type"], "splunk.column")
            self.assertEqual(
                definition["dataSources"]["ds_primary"]["options"]["query"],
                "index=netfw | stats count by action",
            )

    def test_definition_file_used_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            defn = Path(tmpdir) / "def.json"
            defn.write_text(json.dumps({"title": "Custom", "visualizations": {}, "dataSources": {}, "layout": {}}), encoding="utf-8")
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--dashboard-name", "custom_dash",
                "--definition-file", str(defn),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            dashboard = json.loads((Path(tmpdir) / "dashboard-studio" / "dashboard.json").read_text(encoding="utf-8"))
            self.assertEqual(dashboard["title"], "Custom")

    def test_requires_search_or_definition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer("--output-dir", tmpdir, "--dashboard-name", "empty_dash")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Provide --search", result.stderr)

    def test_rejects_invalid_definition_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            result = self.run_renderer(
                "--output-dir", tmpdir, "--dashboard-name", "d", "--definition-file", str(bad),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not valid JSON", result.stderr)

    def test_dry_run_apply_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir, "--dry-run", "--phase", "apply",
                "--dashboard-name", "net_overview",
                "--search", "index=netfw | stats count",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
