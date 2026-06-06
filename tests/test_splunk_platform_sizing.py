#!/usr/bin/env python3
"""Regression tests for the Splunk platform sizing engine."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.regression_helpers import REPO_ROOT

ENGINE = REPO_ROOT / "skills/splunk-platform-sizing/scripts/size_engine.py"


class SplunkPlatformSizingTests(unittest.TestCase):
    def run_engine(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["python3", str(ENGINE), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def size(self, *args: str) -> dict:
        result = self.run_engine("--json", "--dry-run", *args)
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_small_use_case_recommends_all_in_one(self) -> None:
        data = self.size("--daily-ingest-gb", "80", "--retention-days", "30")
        rec = data["recommendation"]
        self.assertEqual(rec["resolved_target"], "standalone")
        self.assertTrue(data["computed"]["aio_eligible"])
        self.assertEqual(data["computed"]["indexer_count"], 1)

    def test_es_ha_use_case_sizes_cluster(self) -> None:
        data = self.size(
            "--daily-ingest-gb", "500",
            "--workload-profile", "es",
            "--ha",
            "--growth-pct", "0",
            "--concurrent-searches", "20",
        )
        computed = data["computed"]
        # es ceiling 100 GB/day, medium density -> 5 indexers for 500 GB/day.
        self.assertEqual(computed["per_indexer_ceiling_gb"], 100.0)
        self.assertEqual(computed["indexer_count"], 5)
        self.assertTrue(computed["search_head_cluster"])
        self.assertEqual(computed["replication_factor"], 3)
        self.assertIn("Enterprise Security", computed["dedicated_premium_search_heads"])
        self.assertIn("C3", data["recommendation"]["sva_category"])

    def test_storage_math(self) -> None:
        data = self.size(
            "--daily-ingest-gb", "100",
            "--retention-days", "30",
            "--growth-pct", "0",
        )
        computed = data["computed"]
        # 100 GB/day * 0.5 compression * 30 days * RF1 = 1500 GB.
        self.assertEqual(computed["indexed_per_day_gb"], 50.0)
        self.assertEqual(computed["cluster_storage_gb"], 1500.0)

    def test_aio_gate_rejects_explicit_standalone(self) -> None:
        result = self.run_engine(
            "--daily-ingest-gb", "500",
            "--deployment-target", "standalone",
            "--dry-run",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("not viable", result.stderr)

    def test_json_schema_keys(self) -> None:
        data = self.size("--daily-ingest-gb", "200")
        for key in ("schema_version", "inputs", "computed", "recommendation",
                    "targets", "handoffs"):
            self.assertIn(key, data)
        for target in ("standalone", "distributed", "sok", "pod", "cloud"):
            self.assertIn(target, data["targets"])

    def test_sok_multisite_architecture(self) -> None:
        data = self.size(
            "--daily-ingest-gb", "900",
            "--workload-profile", "es",
            "--multisite", "--sites", "3",
            "--deployment-target", "sok",
        )
        self.assertEqual(data["recommendation"]["sok_architecture"], "m4")
        self.assertEqual(data["targets"]["sok"]["site_count"], 3)

    def test_writes_report_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "rendered"
            result = self.run_engine(
                "--daily-ingest-gb", "120",
                "--output-dir", str(out),
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue((out / "sizing.json").is_file())
            self.assertTrue((out / "sizing-report.md").is_file())
            payload = json.loads((out / "sizing.json").read_text())
            self.assertEqual(payload["schema_version"], "1.0")

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "rendered"
            result = self.run_engine(
                "--daily-ingest-gb", "120",
                "--output-dir", str(out),
                "--dry-run",
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertFalse(out.exists())

    def test_invalid_ingest_rejected(self) -> None:
        result = self.run_engine("--daily-ingest-gb", "0", "--dry-run")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
