#!/usr/bin/env python3
"""Regression coverage for splunk-spl2-pipeline-kit."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "splunk-spl2-pipeline-kit"
SCRIPT = SKILL_DIR / "scripts" / "spl2_pipeline_kit.py"


def load_kit():
    spec = importlib.util.spec_from_file_location("spl2_pipeline_kit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ingest_command_catalog_covers_current_pipeline_surface() -> None:
    kit = load_kit()
    commands = kit.PROFILE_COMMANDS["ingestProcessor"]

    for command in (
        "branch",
        "decrypt",
        "eval",
        "expand",
        "fields",
        "flatten",
        "from",
        "into",
        "lookup",
        "mvexpand",
        "ocsf",
        "rename",
        "replace",
        "rex",
        "route",
        "stats",
        "thru",
        "where",
        "logs_to_metrics",
    ):
        assert command in commands


def test_edge_command_catalog_includes_stats() -> None:
    kit = load_kit()
    commands = kit.PROFILE_COMMANDS["edgeProcessor"]

    assert "stats" in commands


def test_logs_to_metrics_requires_import() -> None:
    kit = load_kit()
    text = """
$pipeline = | from $source
            | thru [ | logs_to_metrics metric_name="x" metric_value=1 | into $destination_metrics ]
            | into $destination;
"""
    findings = kit.lint_text(text, "ingestProcessor")

    assert any(finding.code == "SPL2-METRICS-IMPORT" for finding in findings)


def test_edge_profile_rejects_ingest_only_commands() -> None:
    kit = load_kit()
    text = """
import logs_to_metrics from /splunk.ingest.commands;
$pipeline = | from $source
            | decrypt encrypted AS clear WITH private_key
            | thru [ | logs_to_metrics metric_name="x" metric_value=1 | into $destination_metrics ]
            | into $destination;
"""
    findings = kit.lint_text(text, "edgeProcessor")
    messages = [finding.message for finding in findings]

    assert any("decrypt" in message for message in messages)
    assert any("logs_to_metrics" in message for message in messages)


def test_edge_profile_accepts_stats() -> None:
    kit = load_kit()
    text = """
$pipeline = | from $source
            | stats count() as event_count, sum(bytes) as bytes_sum by sourcetype
            | into $destination;
"""
    findings = kit.lint_text(text, "edgeProcessor")

    assert not any(finding.severity == "error" for finding in findings)


def test_stats_avg_and_pcre2_warnings_are_reported() -> None:
    kit = load_kit()
    text = """
$pipeline = | from $source
            | rex field=_raw "(?<user>user=[^ ]+)"
            | stats avg(bytes) as avg_bytes by sourcetype
            | into $destination;
"""
    findings = kit.lint_text(text, "ingestProcessor")
    codes = {finding.code for finding in findings}

    assert "SPL2-STATS-AVG" in codes
    assert "SPL2-PCRE2-NAMED-CAPTURE" in codes


def test_object_to_array_deprecation_warning_is_reported() -> None:
    kit = load_kit()
    text = """
$pipeline = | from $source
            | eval entries = object_to_array(payload)
            | into $destination;
"""
    findings = kit.lint_text(text, "ingestProcessor")
    codes = {finding.code for finding in findings}

    assert "SPL2-DEPRECATED-FUNCTION" in codes


def test_render_outputs_templates_and_clean_lint_report(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--phase",
            "all",
            "--profile",
            "both",
            "--output-dir",
            str(out),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (out / "templates/ingestProcessor/metrics.spl2").is_file()
    assert (out / "templates/ingestProcessor/decrypt.spl2").is_file()
    assert (out / "templates/edgeProcessor/route.spl2").is_file()
    assert (out / "templates/edgeProcessor/stats.spl2").is_file()
    assert (out / "custom-template-app/default/data/spl2/ip_route_redact_template.spl2").is_file()
    reports = json.loads((out / "lint-report.json").read_text())
    assert all(report["status"] != "FAIL" for report in reports)
