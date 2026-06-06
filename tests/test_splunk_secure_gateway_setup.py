#!/usr/bin/env python3
"""Regression tests for the splunk-secure-gateway-setup renderer and wrapper."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-secure-gateway-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-secure-gateway-setup/scripts/setup.sh"


class SecureGatewayTests(unittest.TestCase):
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

    def test_render_private_spacebridge_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--deployment-name", "prod-sh",
                "--visible-apps", "search,cisco-catalyst-app",
                "--private-spacebridge", "true",
                "--custom-endpoint-id", "pvt1",
                "--custom-endpoint-hostname", "sb.example.com",
                "--custom-endpoint-grpc-hostname", "grpc.example.com",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "secure-gateway"
            cfg = json.loads((render_dir / "instance-id-config.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["endpoint_config"][0]["custom_endpoint_id"], "pvt1")
            egress = (render_dir / "egress-preflight.sh").read_text(encoding="utf-8")
            self.assertIn("sb.example.com", egress)
            self.assertTrue((render_dir / "registration-runbook.md").exists())

    def test_private_spacebridge_requires_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir, "--private-spacebridge", "true",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires --custom-endpoint-id", result.stderr)

    def test_default_egress_targets_public_spacebridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            self.run_renderer("--output-dir", tmpdir)
            egress = (Path(tmpdir) / "secure-gateway" / "egress-preflight.sh").read_text(encoding="utf-8")
            self.assertIn("prod.spacebridge.spl.mobi", egress)

    def test_enable_refused_without_egress_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir, "--phase", "apply", "--action", "enable",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-spacebridge-egress", result.stdout + result.stderr)

    def test_dry_run_enable_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir, "--dry-run", "--phase", "apply",
                "--action", "enable", "--accept-spacebridge-egress",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
