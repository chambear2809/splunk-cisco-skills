#!/usr/bin/env python3
"""Regression tests for the splunk-ddaa-archive-setup renderer and wrapper."""

from __future__ import annotations

import json
import os
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

    def test_apply_refuses_create_when_index_observation_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            credentials = root / "credentials"
            credentials.write_text(
                "\n".join(
                    [
                        "SPLUNK_PLATFORM=cloud",
                        "SPLUNK_CLOUD_STACK=reviewed-stack",
                        "STACK_TOKEN=synthetic-token",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            credentials.chmod(0o600)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            marker = root / "mutation-ran"
            acs = fake_bin / "acs"
            acs.write_text(
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  *'config current-stack'*) printf '%s\\n' 'Stack: reviewed-stack' ;;\n"
                "  *'indexes describe'*) printf '%s' '{\"statusCode\":500}' >&2; exit 1 ;;\n"
                f"  *'indexes create'*|*'indexes update'*) touch {str(marker)!r} ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            acs.chmod(0o700)
            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            for key in (
                "ACS_SERVER",
                "SPLUNK_CLOUD_SEARCH_HEAD",
                "SPLUNK_CLOUD_STACK",
                "SPLUNK_PLATFORM",
                "SPLUNK_PROFILE",
                "SPLUNK_SEARCH_PROFILE",
                "STACK_TOKEN",
            ):
                env.pop(key, None)

            result = subprocess.run(
                [
                    "bash",
                    str(SETUP),
                    "--output-dir",
                    str(root / "render"),
                    "--phase",
                    "apply",
                    "--index",
                    "netfw",
                    "--searchable-days",
                    "90",
                    "--archival-retention-days",
                    "365",
                    "--accept-archive-retention",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing mutation", result.stdout + result.stderr)
            self.assertFalse(marker.exists())

    def test_apply_does_not_claim_success_after_mismatching_post_readback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            credentials = root / "credentials"
            credentials.write_text(
                "\n".join(
                    [
                        "SPLUNK_PLATFORM=cloud",
                        "SPLUNK_CLOUD_STACK=reviewed-stack",
                        "STACK_TOKEN=synthetic-token",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            credentials.chmod(0o600)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            marker = root / "mutation-ran"
            acs = fake_bin / "acs"
            acs.write_text(
                "#!/usr/bin/env bash\n"
                "case \"$*\" in\n"
                "  *'config current-stack'*) printf '%s\\n' 'Stack: reviewed-stack' ;;\n"
                "  *'indexes describe'*)\n"
                f"    if [[ -e {str(marker)!r} ]]; then\n"
                "      printf '%s' '{\"name\":\"netfw\",\"datatype\":\"event\",\"searchableDays\":91,\"splunkArchivalRetentionDays\":365}'\n"
                "    else\n"
                "      printf '%s' '{\"statusCode\":404}' >&2\n"
                "      exit 1\n"
                "    fi\n"
                "    ;;\n"
                f"  *'indexes create'*) touch {str(marker)!r} ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            acs.chmod(0o700)
            env = os.environ.copy()
            env["SPLUNK_CREDENTIALS_FILE"] = str(credentials)
            env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
            for key in (
                "ACS_SERVER",
                "SPLUNK_CLOUD_SEARCH_HEAD",
                "SPLUNK_CLOUD_STACK",
                "SPLUNK_PLATFORM",
                "SPLUNK_PROFILE",
                "SPLUNK_SEARCH_PROFILE",
                "STACK_TOKEN",
            ):
                env.pop(key, None)

            result = subprocess.run(
                [
                    "bash",
                    str(SETUP),
                    "--output-dir",
                    str(root / "render"),
                    "--phase",
                    "apply",
                    "--index",
                    "netfw",
                    "--searchable-days",
                    "90",
                    "--archival-retention-days",
                    "365",
                    "--accept-archive-retention",
                ],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("status is incomplete", result.stdout + result.stderr)
            self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
