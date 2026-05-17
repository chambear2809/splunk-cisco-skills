#!/usr/bin/env python3
"""Regression tests for Splunk Observability deep native workflow rendering."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.regression_helpers import REPO_ROOT


SCRIPT_DIR = REPO_ROOT / "skills/splunk-observability-deep-native-workflows/scripts"
TEMPLATE = REPO_ROOT / "skills/splunk-observability-deep-native-workflows/template.example"


def test_deep_native_template_renders_coverage_packet(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "render_workflows.py"),
            "--spec",
            str(TEMPLATE),
            "--output-dir",
            str(tmp_path),
            "--realm",
            "us0",
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["coverage_report"]["summary"]["api_apply"] >= 1
    assert payload["coverage_report"]["summary"]["api_validate"] >= 1
    assert payload["coverage_report"]["summary"]["handoff"] >= 1

    surfaces = {
        item["surface"]
        for item in payload["coverage_report"]["objects"]
    }
    assert "modern_dashboard" in surfaces
    assert "slo_creation" in surfaces
    assert "rum_session_replay" in surfaces

    for rel_path in (
        "coverage-report.json",
        "deeplinks.json",
        "apply-plan.json",
        "workflow-handoff.md",
        "payloads/slo/checkout-request-success-slo.json",
    ):
        assert (tmp_path / rel_path).is_file()


def test_deep_native_setup_rejects_inline_secret_flags() -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_DIR / "setup.sh"),
            "--render",
            "--spec",
            str(TEMPLATE),
            "--token",
            "secret-value",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "would expose a secret in process listings" in result.stdout + result.stderr
