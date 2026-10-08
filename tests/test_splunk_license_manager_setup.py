"""Regression tests for the license manager renderer."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
import json
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-license-manager-setup/scripts/render_assets.py"
LICENSE_HELPERS = REPO_ROOT / "skills/shared/lib/license_helpers.sh"


class LicenseManagerRendererTests(unittest.TestCase):
    def render(self, output_dir: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(RENDERER),
                "--output-dir",
                output_dir,
                "--license-manager-uri",
                "https://127.0.0.1:18089",
                "--license-files",
                "/tmp/enterprise-license.lic",
                "--license-group",
                "Enterprise",
                "--peer-hosts",
                "127.0.0.1",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_upload_preserves_license_filename_for_rest_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.render(tmpdir)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (
                Path(tmpdir) / "license" / "manager" / "install-licenses.sh"
            )
            text = script.read_text(encoding="utf-8")
            self.assertIn('license_install_files "${MANAGER_URI}" "${SK}" "$f"', text)
            self.assertNotIn('curl -q -sS -k', text)
            shell = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(shell.returncode, 0, msg=shell.stderr)

    def test_validate_accepts_four_component_enterprise_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.render(tmpdir)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (Path(tmpdir) / "license" / "validate.sh").read_text(
                encoding="utf-8"
            )
            self.assertIn(r"(\d+)\.(\d+)(?:\.(\d+))?(?:\.(\d+))?", script)

    def test_peer_update_targets_localpeer_license_resource(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.render(tmpdir)
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            script = (
                Path(tmpdir) / "license" / "peers" / "127.0.0.1" / "configure-peer.sh"
            )
            text = script.read_text(encoding="utf-8")
            self.assertIn("/services/licenser/localpeer/license?output_mode=json", text)
            self.assertIn('http_code="$(splunk_curl', text)
            shell = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(shell.returncode, 0, msg=shell.stderr)

    def test_pool_apply_propagates_mocked_create_and_update_failures(self) -> None:
        harness = """
set -u
source {helpers}
log() {{ echo "LOG:$*"; }}
splunk_curl() {{
  if [[ "$*" == *"-X POST"* ]]; then
    return "${{FAKE_POST_RC}}"
  fi
  printf '%s\\n' "${{FAKE_EXISTS}}"
  return 0
}}
license_pool_apply https://example.invalid sk "$1"
""".format(helpers=LICENSE_HELPERS)
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = Path(tmpdir) / "pool.json"
            spec.write_text(
                json.dumps({"name": "p", "stack_id": "enterprise", "quota": "1", "slaves": "*"}),
                encoding="utf-8",
            )
            script = Path(tmpdir) / "harness.sh"
            script.write_text(harness, encoding="utf-8")
            for exists in ("404", "200"):
                failed = subprocess.run(
                    ["bash", str(script), str(spec)],
                    env={**__import__("os").environ, "FAKE_EXISTS": exists, "FAKE_POST_RC": "1"},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(failed.returncode, 0, msg=failed.stdout + failed.stderr)
                passed = subprocess.run(
                    ["bash", str(script), str(spec)],
                    env={**__import__("os").environ, "FAKE_EXISTS": exists, "FAKE_POST_RC": "0"},
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(passed.returncode, 0, msg=passed.stdout + passed.stderr)

    def test_shared_license_transport_preserves_upload_and_legacy_peer_fallback(self) -> None:
        text = LICENSE_HELPERS.read_text(encoding="utf-8")
        self.assertIn("credential_curl_stream_file", text)
        self.assertIn("urlencode", text)
        self.assertIn("-d @-", text)
        self.assertNotIn("curl -q -sS -k", text)
        self.assertGreaterEqual(text.count("/services/licenser/localpeer/license?output_mode=json"), 2)
        self.assertIn('master_uri=${manager_uri}', text)


if __name__ == "__main__":
    unittest.main()
