#!/usr/bin/env python3
"""Regression tests for the splunk-ddaa-archive-setup renderer and wrapper."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-ddaa-archive-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-ddaa-archive-setup/scripts/setup.sh"


class DdaaArchiveTests(unittest.TestCase):
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

    def test_render_payload_and_runbooks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--index", "netfw",
                "--searchable-days", "90",
                "--archival-retention-days", "365",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "ddaa"
            payload = json.loads((render_dir / "acs-payload.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["splunkArchivalRetentionDays"], 365)
            self.assertEqual(payload["searchableDays"], 90)
            self.assertTrue((render_dir / "restore-runbook.md").exists())
            self.assertTrue((render_dir / "disable-runbook.md").exists())

    def test_rejects_archival_not_greater_than_searchable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--index", "netfw",
                "--searchable-days", "90",
                "--archival-retention-days", "90",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be greater than", result.stderr)

    def test_rejects_archival_over_max(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--index", "netfw",
                "--searchable-days", "90",
                "--archival-retention-days", "4000",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("<= 3650", result.stderr)

    def test_apply_refused_without_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--phase", "apply",
                "--index", "netfw",
                "--searchable-days", "90",
                "--archival-retention-days", "365",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-archive-retention", result.stdout + result.stderr)

    def test_dry_run_apply_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--dry-run", "--phase", "apply",
                "--index", "netfw",
                "--searchable-days", "90",
                "--archival-retention-days", "365",
                "--accept-archive-retention",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
