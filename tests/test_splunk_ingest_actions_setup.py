#!/usr/bin/env python3
"""Regression tests for the splunk-ingest-actions-setup renderer and wrapper."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

RENDERER = REPO_ROOT / "skills/splunk-ingest-actions-setup/scripts/render_assets.py"
SETUP = REPO_ROOT / "skills/splunk-ingest-actions-setup/scripts/setup.sh"
CANONICAL_RENDERER = REPO_ROOT / "skills/splunk-ingest-actions/scripts/render_assets.py"
CANONICAL_SETUP = REPO_ROOT / "skills/splunk-ingest-actions/scripts/setup.sh"


class IngestActionsTests(unittest.TestCase):
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

    def test_drop_rule_renders_props_and_transforms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "drop_debug",
                "--rule-type", "drop",
                "--drop-regex", "level=DEBUG",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "ingest-actions"
            props = (render_dir / "props.conf").read_text(encoding="utf-8")
            transforms = (render_dir / "transforms.conf").read_text(encoding="utf-8")
            self.assertIn("RULESET-drop_debug = drop_debug_drop", props)
            self.assertIn('queue=if(match(_raw, "level=DEBUG"), "nullQueue", queue)', transforms)

    def test_route_s3_keeps_keys_out_of_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            access = Path(tmpdir) / "access.key"
            secret = Path(tmpdir) / "secret.key"
            access.write_text("AKIA_TEST_INGEST\n", encoding="utf-8")
            secret.write_text("VERY_SECRET_INGEST_KEY\n", encoding="utf-8")
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "arch",
                "--rule-type", "route-s3",
                "--s3-destination-name", "asa_arch",
                "--s3-path", "s3://bucket/asa",
                "--s3-access-key-file", str(access),
                "--s3-secret-key-file", str(secret),
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            render_dir = Path(tmpdir) / "ingest-actions"
            all_assets = "\n".join(
                p.read_text(encoding="utf-8") for p in render_dir.iterdir() if p.is_file()
            )
            transforms = (render_dir / "transforms.conf").read_text(encoding="utf-8")
            props = (render_dir / "props.conf").read_text(encoding="utf-8")
            self.assertIn("[rfs:asa_arch]", (render_dir / "outputs.conf").read_text(encoding="utf-8"))
            self.assertNotIn("AKIA_TEST_INGEST", all_assets)
            self.assertNotIn("VERY_SECRET_INGEST_KEY", all_assets)
            # route-s3 must NOT fabricate an S2S/tcpout routing transform; the
            # routing rule is authored in the Ingest Actions UI / rulesets endpoint.
            self.assertNotIn("_TCP_ROUTING", transforms)
            self.assertNotIn("RULESET-arch", props)

    def test_route_s3_render_passes_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            render = self.run_renderer(
                "--output-dir", tmpdir,
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "arch",
                "--rule-type", "route-s3",
                "--s3-destination-name", "asa_arch",
                "--s3-path", "s3://bucket/asa",
            )
            self.assertEqual(render.returncode, 0, msg=render.stdout + render.stderr)
            validate = subprocess.run(
                ["bash", str(REPO_ROOT / "skills/splunk-ingest-actions-setup/scripts/validate.sh"),
                 "--output-dir", tmpdir],
                cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=60,
            )
            self.assertEqual(validate.returncode, 0, msg=validate.stdout + validate.stderr)

    def test_rule_type_requires_its_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_renderer(
                "--output-dir", tmpdir,
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "m1",
                "--rule-type", "mask",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--mask-regex is required", result.stderr)

    def test_apply_refused_without_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--phase", "apply",
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "drop_debug",
                "--rule-type", "drop",
                "--drop-regex", "level=DEBUG",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--accept-irreversible-ingest", result.stdout + result.stderr)

    def test_dry_run_apply_does_not_execute(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "enterprise",
                "--dry-run", "--phase", "apply",
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "drop_debug",
                "--rule-type", "drop",
                "--drop-regex", "level=DEBUG",
                "--accept-irreversible-ingest",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            self.assertIn("DRY RUN", result.stdout + result.stderr)

    def test_cloud_apply_is_blocked_and_routed_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "existing-output"
            output_dir.mkdir()
            sentinel = output_dir / "operator-note.txt"
            sentinel.write_text("preserve me\n", encoding="utf-8")
            result = self.run_setup(
                "--output-dir", str(output_dir),
                "--platform", "cloud",
                "--phase", "apply",
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "drop_debug",
                "--rule-type", "drop",
                "--drop-regex", "level=DEBUG",
                "--accept-irreversible-ingest",
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 2, msg=output)
            self.assertIn("will not write", output)
            self.assertIn("splunk-ingest-actions-setup/scripts/setup.sh --platform cloud", output)
            self.assertFalse((output_dir / "ingest-actions").exists())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve me\n")

    def test_cloud_render_only_emits_review_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self.run_setup(
                "--output-dir", tmpdir,
                "--platform", "cloud",
                "--phase", "render",
                "--ruleset-sourcetype", "cisco:asa",
                "--ruleset-name", "drop_debug",
                "--rule-type", "drop",
                "--drop-regex", "level=DEBUG",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            metadata = json.loads(
                (Path(tmpdir) / "ingest-actions" / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["platform"], "cloud")

    def test_canonical_cloud_apply_exits_before_rendering_or_local_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            splunk_home = Path(tmpdir) / "managed-cloud-must-not-exist"
            result = subprocess.run(
                [
                    "bash",
                    str(CANONICAL_SETUP),
                    "--phase",
                    "apply",
                    "--platform",
                    "cloud",
                    "--output-dir",
                    str(output_dir),
                    "--splunk-home",
                    str(splunk_home),
                    "--destination-type",
                    "s3",
                    "--destination-name",
                    "archive",
                    "--s3-path",
                    "s3://example/archive",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 2, msg=output)
            self.assertIn("managed Splunk Cloud", output)
            self.assertFalse(output_dir.exists())
            self.assertFalse(splunk_home.exists())

    def test_canonical_cloud_rendered_apply_is_also_non_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "rendered"
            splunk_home = Path(tmpdir) / "managed-cloud-must-not-exist"
            render = subprocess.run(
                [
                    "python3",
                    str(CANONICAL_RENDERER),
                    "--output-dir",
                    str(output_dir),
                    "--platform",
                    "cloud",
                    "--splunk-home",
                    str(splunk_home),
                    "--destination-type",
                    "s3",
                    "--destination-name",
                    "archive",
                    "--s3-path",
                    "s3://example/archive",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(render.returncode, 0, msg=render.stdout + render.stderr)
            apply = subprocess.run(
                ["bash", str(output_dir / "ingest-actions" / "apply.sh")],
                cwd=output_dir / "ingest-actions",
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            self.assertEqual(apply.returncode, 2, msg=apply.stdout + apply.stderr)
            self.assertFalse(splunk_home.exists())


if __name__ == "__main__":
    unittest.main()
