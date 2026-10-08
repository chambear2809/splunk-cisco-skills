"""Regression tests for Enterprise HEC file ownership."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-hec-service-setup/scripts/render_assets.py"


class HecServiceOwnershipTests(unittest.TestCase):
    def test_enterprise_apply_derives_service_owner_and_protects_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "python3",
                    str(RENDERER),
                    "--platform",
                    "enterprise",
                    "--output-dir",
                    tmpdir,
                    "--splunk-home",
                    "/opt/splunk-fresh106",
                    "--token-file",
                    "/tmp/hec-token",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (
                Path(tmpdir) / "hec-service" / "apply-enterprise-files.sh"
            ).read_text(encoding="utf-8")
            self.assertIn('os.environ.get("SPLUNK_SERVICE_USER"', script)
            self.assertIn("pwd.getpwuid(home_owner)", script)
            self.assertIn("os.chown(path, account.pw_uid, account.pw_gid)", script)
            self.assertNotIn("secure_owner(token_path, 0o600)", script)
            self.assertIn("source token ownership preserved", script)
            self.assertIn("secure_owner(target_path, 0o640)", script)
            self.assertIn("refusing to assign HEC files to root", script)

    def test_generated_apply_script_has_valid_shell_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    "python3",
                    str(RENDERER),
                    "--platform",
                    "enterprise",
                    "--output-dir",
                    tmpdir,
                    "--token-file",
                    "/tmp/hec-token",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = Path(tmpdir) / "hec-service" / "apply-enterprise-files.sh"
            check = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(check.returncode, 0, msg=check.stdout + check.stderr)


if __name__ == "__main__":
    unittest.main()
