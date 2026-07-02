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
CANONICAL_RENDERER = REPO_ROOT / "skills/splunk-secure-gateway/scripts/render_assets.py"
CANONICAL_SETUP = REPO_ROOT / "skills/splunk-secure-gateway/scripts/setup.sh"


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
                "--output-dir", tmpdir, "--platform", "enterprise",
                "--phase", "apply", "--action", "enable",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-spacebridge-egress", result.stdout + result.stderr)

    def test_dry_run_enable_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir, "--platform", "enterprise",
                "--dry-run", "--phase", "apply",
                "--action", "enable", "--accept-spacebridge-egress",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)

    def test_cloud_apply_is_blocked_and_routed_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir, "--platform", "cloud",
                "--phase", "apply", "--action", "enable",
                "--accept-spacebridge-egress",
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 2, msg=output)
            self.assertIn("will not enable, disable, or configure", output)
            self.assertIn("splunk-secure-gateway/scripts/setup.sh --platform cloud", output)
            metadata = json.loads(
                (Path(tmpdir) / "secure-gateway" / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["platform"], "cloud")

    def test_canonical_cloud_local_phases_exit_before_rendering(self) -> None:
        for phase in ("preflight", "enable", "status"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmpdir:
                output_dir = Path(tmpdir) / "rendered"
                result = subprocess.run(
                    [
                        "bash",
                        str(CANONICAL_SETUP),
                        "--platform",
                        "cloud",
                        "--phase",
                        phase,
                        "--output-dir",
                        str(output_dir),
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 2, msg=result.stdout + result.stderr)
                self.assertIn("managed Splunk Cloud search tier", result.stdout + result.stderr)
                self.assertFalse(output_dir.exists())

    def test_canonical_cloud_rendered_local_checks_are_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "python3",
                    str(CANONICAL_RENDERER),
                    "--platform",
                    "cloud",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "secure-gateway"
            for script_name in ("connectivity-preflight.sh", "status.sh"):
                run = subprocess.run(
                    ["bash", str(render_dir / script_name)],
                    cwd=render_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                self.assertEqual(run.returncode, 2, msg=run.stdout + run.stderr)
                self.assertIn("HANDOFF", run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
