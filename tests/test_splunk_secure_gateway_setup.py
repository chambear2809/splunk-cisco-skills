#!/usr/bin/env python3
"""Regression tests for the splunk-secure-gateway-setup renderer and wrapper."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-secure-gateway-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-secure-gateway-setup/scripts/setup.sh"
VALIDATE = REPO_ROOT / "skills/splunk-secure-gateway-setup/scripts/validate.sh"


class SecureGatewayTests(unittest.TestCase):
    def run_renderer(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(RENDERER), *args],
            cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
        )

    def run_setup(
        self, *args: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SETUP), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env=env,
        )

    def cloud_guard_env(self, root: Path, *, auto: bool) -> tuple[dict[str, str], Path]:
        env = os.environ.copy()
        for key in list(env):
            if key.startswith(("SPLUNK_", "STACK_", "ACS_")):
                env.pop(key)
        marker = root / "unexpected-live-io.log"
        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        for tool in ("curl", "nc"):
            path = fake_bin / tool
            path.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s\\n" "$0 $*" >> "${LIVE_IO_MARKER}"\n'
                "exit 99\n",
                encoding="utf-8",
            )
            path.chmod(0o755)
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["LIVE_IO_MARKER"] = str(marker)
        env["HOME"] = str(root / "empty-home")
        credentials = root / "platform-settings"
        if auto:
            credentials.write_text(
                "SPLUNK_PLATFORM=cloud\nSPLUNK_URI=https://example.splunkcloud.com:8089\n",
                encoding="utf-8",
            )
        else:
            # An explicit platform must not even try to parse the credential source.
            credentials.mkdir()
        env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
        return env, marker

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

    def test_cloud_operational_modes_fail_before_render_or_live_io(self) -> None:
        cases = (
            ("preflight", []),
            ("apply", ["--action", "enable", "--accept-spacebridge-egress"]),
            ("status", []),
            ("all", ["--action", "enable", "--accept-spacebridge-egress"]),
            ("render-apply", ["--phase", "render", "--apply"]),
        )
        for platform in ("cloud", "auto"):
            for label, extra in cases:
                with self.subTest(platform=platform, mode=label), tempfile.TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    env, marker = self.cloud_guard_env(root, auto=platform == "auto")
                    output_dir = root / "rendered"
                    phase_args = extra if label == "render-apply" else ["--phase", label, *extra]
                    result = self.run_setup(
                        "--output-dir",
                        str(output_dir),
                        "--platform",
                        platform,
                        *phase_args,
                        env=env,
                    )
                    output = result.stdout + result.stderr
                    self.assertEqual(result.returncode, 2, msg=output)
                    self.assertIn("No artifacts were rendered", output)
                    self.assertIn("--platform cloud --phase render", output)
                    self.assertFalse(output_dir.exists())
                    self.assertFalse(marker.exists())

    def test_cloud_plain_render_emits_non_network_handoff_for_explicit_and_auto(self) -> None:
        for platform in ("cloud", "auto"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                env, marker = self.cloud_guard_env(root, auto=platform == "auto")
                output_dir = root / "rendered"
                result = self.run_setup(
                    "--output-dir",
                    str(output_dir),
                    "--platform",
                    platform,
                    "--phase",
                    "render",
                    env=env,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
                render_dir = output_dir / "secure-gateway"
                metadata = json.loads((render_dir / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(metadata["platform"], "cloud")
                egress = render_dir / "egress-preflight.sh"
                text = egress.read_text(encoding="utf-8")
                self.assertIn("HANDOFF", text)
                self.assertNotIn("nc -z", text)
                self.assertNotIn("curl -", text)
                handoff = subprocess.run(
                    ["bash", str(egress)],
                    cwd=render_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                self.assertEqual(handoff.returncode, 2)
                self.assertIn("Splunk Cloud Support", handoff.stderr)
                self.assertFalse(marker.exists())
                validation = subprocess.run(
                    [
                        "bash",
                        str(VALIDATE),
                        "--live",
                        "--output-dir",
                        str(output_dir),
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                    env=env,
                )
                validation_output = validation.stdout + validation.stderr
                self.assertEqual(validation.returncode, 2, msg=validation_output)
                self.assertIn("HANDOFF", validation_output)
                self.assertFalse(marker.exists())

if __name__ == "__main__":
    unittest.main()
