#!/usr/bin/env python3
"""Regression coverage for VMware and focused Observability wrapper skills."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


def run_cmd(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


class SplunkVmwareAndO11yWrapperTests(unittest.TestCase):
    def test_vmware_render_and_validate_assets(self) -> None:
        setup = REPO_ROOT / "skills/splunk-vmware-ta-setup/scripts/setup.sh"
        validate = REPO_ROOT / "skills/splunk-vmware-ta-setup/scripts/validate.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd(
                "bash",
                str(setup),
                "--render",
                "--json",
                "--output-dir",
                tmpdir,
                "--event-index",
                "vmware",
                "--esxi-index",
                "vmware_esxi",
                "--metrics-index",
                "vmware_metrics",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("indexes.conf.template", payload["files"])
            self.assertIn("vmware-readiness-evidence.template.json", payload["files"])
            indexes = Path(tmpdir, "indexes.conf.template").read_text(encoding="utf-8")
            self.assertIn("[vmware_metrics]", indexes)
            self.assertIn("datatype = metric", indexes)
            itsi = Path(tmpdir, "itsi-readiness.md").read_text(encoding="utf-8")
            self.assertIn("--phase source-packs", itsi)
            self.assertIn("--phase synthesize --targets itsi", itsi)
            self.assertIn("VMWARE_RENDERED_DIR", itsi)
            self.assertIn("DSRD_RENDERED_DIR", itsi)
            self.assertIn("live-evidence.synthesized.json", itsi)
            self.assertNotIn("--phase render", itsi)
            self.assertNotIn("--source-pack vmware", itsi)
            evidence = json.loads(Path(tmpdir, "vmware-readiness-evidence.template.json").read_text(encoding="utf-8"))
            self.assertEqual(evidence["targets"], ["itsi"])
            self.assertEqual(len(evidence["data_sources"]), 3)
            self.assertEqual(evidence["data_sources"][0]["sample_events"]["count"], 0)
            self.assertIn("vmware_metrics", evidence["data_sources"][2]["expected_indexes"])
            self.assertTrue(evidence["data_sources"][2]["metrics"]["mstats_zero_results"])

            validation = run_cmd("bash", str(validate), "--rendered-dir", tmpdir)
            self.assertEqual(validation.returncode, 0, msg=validation.stdout + validation.stderr)
            self.assertIn("PASS", validation.stdout + validation.stderr)

    def test_browser_rum_render_and_validate_assets(self) -> None:
        setup = REPO_ROOT / "skills/splunk-observability-browser-rum-setup/scripts/setup.sh"
        validate = REPO_ROOT / "skills/splunk-observability-browser-rum-setup/scripts/validate.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd(
                "bash",
                str(setup),
                "--render",
                "--json",
                "--output-dir",
                tmpdir,
                "--application-name",
                "checkout-web",
                "--framework",
                "vite",
                "--enable-session-replay",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertIn("cdn-snippet.html", payload["files"])
            snippet = Path(tmpdir, "cdn-snippet.html").read_text(encoding="utf-8")
            self.assertIn("SplunkRum.init", snippet)
            self.assertIn("splunk-otel-web-session-recorder.js", snippet)
            upload = Path(tmpdir, "source-map-upload.sh").read_text(encoding="utf-8")
            self.assertIn("splunk-rum sourcemaps inject --path", upload)
            self.assertIn("splunk-rum sourcemaps upload", upload)
            self.assertIn("SPLUNK_ACCESS_TOKEN", upload)
            self.assertNotIn("--token-file", upload)
            webpack = Path(tmpdir, "webpack-sourcemap-plugin.js").read_text(encoding="utf-8")
            self.assertIn("applicationName: 'checkout-web'", webpack)
            self.assertIn("version: '1.0.0'", webpack)
            self.assertIn("sourceMaps:", webpack)
            self.assertIn("disableUpload:", webpack)
            self.assertNotIn("tokenFile", webpack)

            validation = run_cmd("bash", str(validate), "--rendered-dir", tmpdir)
            self.assertEqual(validation.returncode, 0, msg=validation.stdout + validation.stderr)

    def test_synthetics_wrapper_emits_native_ops_spec(self) -> None:
        setup = REPO_ROOT / "skills/splunk-observability-synthetics-setup/scripts/setup.sh"
        validate = REPO_ROOT / "skills/splunk-observability-synthetics-setup/scripts/validate.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd(
                "bash",
                str(setup),
                "--render",
                "--json",
                "--output-dir",
                tmpdir,
                "--name",
                "Checkout browser",
                "--url",
                "https://shop.example.com",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            spec = json.loads(Path(tmpdir, "native-ops-spec.json").read_text(encoding="utf-8"))
            self.assertIn("synthetics", spec)
            self.assertEqual(spec["synthetics"][0]["kind"], "browser")

            validation = run_cmd("bash", str(validate), "--rendered-dir", tmpdir)
            self.assertEqual(validation.returncode, 0, msg=validation.stdout + validation.stderr)

    def test_slo_wrapper_emits_deep_native_spec(self) -> None:
        setup = REPO_ROOT / "skills/splunk-observability-slo-setup/scripts/setup.sh"
        validate = REPO_ROOT / "skills/splunk-observability-slo-setup/scripts/validate.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd(
                "bash",
                str(setup),
                "--render",
                "--json",
                "--output-dir",
                tmpdir,
                "--name",
                "Checkout SLO",
                "--service",
                "checkoutservice",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            spec = json.loads(Path(tmpdir, "deep-native-workflow-spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["workflows"][0]["surface"], "slo_creation")

            validation = run_cmd("bash", str(validate), "--rendered-dir", tmpdir)
            self.assertEqual(validation.returncode, 0, msg=validation.stdout + validation.stderr)

    def test_metrics_pipeline_wrapper_emits_deep_native_spec(self) -> None:
        setup = REPO_ROOT / "skills/splunk-observability-metrics-pipeline-setup/scripts/setup.sh"
        validate = REPO_ROOT / "skills/splunk-observability-metrics-pipeline-setup/scripts/validate.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_cmd(
                "bash",
                str(setup),
                "--render",
                "--json",
                "--output-dir",
                tmpdir,
                "--metric",
                "service.request.duration",
                "--action",
                "aggregate",
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            spec = json.loads(Path(tmpdir, "deep-native-workflow-spec.json").read_text(encoding="utf-8"))
            self.assertEqual(spec["workflows"][0]["surface"], "metrics_pipeline_management")

            validation = run_cmd("bash", str(validate), "--rendered-dir", tmpdir)
            self.assertEqual(validation.returncode, 0, msg=validation.stdout + validation.stderr)


if __name__ == "__main__":
    unittest.main()
