#!/usr/bin/env python3
"""Regression coverage for splunk-ingest-processor-setup."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "splunk-ingest-processor-setup"
RENDERER = SKILL_DIR / "scripts" / "render_assets.py"


def load_renderer():
    spec = importlib.util.spec_from_file_location("ingest_processor_renderer", RENDERER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_renderer(tmp_path: Path, *extra: str) -> Path:
    out = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--phase",
            "all",
            "--output-dir",
            str(out),
            *extra,
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_feature_coverage_includes_current_ip_surface() -> None:
    renderer = load_renderer()
    features = {feature for feature, _status in renderer.FEATURE_COVERAGE}

    expected = {
        "Provisioning and entitlement",
        "Source types and sample data",
        "Amazon S3 JSON Parquet destination",
        "Route branch thru copy templates",
        "Logs to metrics",
        "OCSF conversion",
        "Decrypt private-key lookup",
        "Stats aggregation",
        "Custom pipeline templates",
        "Automated Field Extraction",
        "Automated Field Extraction region allowlist",
        "SPL to SPL2 conversion review",
        "PCRE2 compatibility lint",
        "Queue DLQ Usage Summary monitoring",
        "Known issue guardrails",
        "Splunk Enterprise destination",
    }
    assert expected <= features


def test_render_outputs_required_artifacts(tmp_path: Path) -> None:
    out = run_renderer(tmp_path)

    for rel in (
        "readiness-report.md",
        "coverage-report.json",
        "apply-plan.json",
        "control-plane-handoffs/ingest-processor-ui.md",
        "control-plane-handoffs/known-issues.md",
        "monitoring/searches.spl",
        "monitoring/usage-summary-handoff.md",
        "spl2-pipeline-kit/templates/ingestProcessor/metrics.spl2",
        "pipelines/http_metrics.spl2",
        "handoffs/splunk-data-source-readiness-doctor.md",
    ):
        assert (out / rel).is_file(), rel

    coverage = json.loads((out / "coverage-report.json").read_text())
    statuses = {row["coverage_status"] for row in coverage}
    assert {"rendered", "ui_handoff", "delegated_handoff", "refused_handoff", "lint"} <= statuses


def test_known_issue_guardrails_and_afe_regions_are_rendered(tmp_path: Path) -> None:
    out = run_renderer(tmp_path)
    known_issues = (out / "control-plane-handoffs/known-issues.md").read_text()
    readiness = (out / "readiness-report.md").read_text()

    for region in (
        "us-east-1",
        "eu-west-1",
        "eu-west-2",
        "ap-southeast-1",
        "ap-southeast-2",
        "eu-central-1",
        "us-west-2",
        "eu-west-3",
    ):
        assert region in known_issues
        assert region in readiness
    for phrase in (
        "no data delivery guarantees",
        "tenant administrators",
        "Multiple browser sessions",
        "useACK=false",
        "indexer acknowledgement disabled",
        "CIDR matching is not supported",
    ):
        assert phrase in known_issues


def test_rendered_artifacts_do_not_claim_private_crud_or_render_secrets(tmp_path: Path) -> None:
    out = run_renderer(tmp_path)
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in out.rglob("*")
        if path.is_file() and path.suffix in {".md", ".json", ".spl", ".spl2", ".sh"}
    )

    forbidden = [
        "POST /services/data-manager/input",
        "PUT /services/data-manager/input",
        "terraform resource splunk_cloud_data_manager_input",
        "global HEC ACK",
        "BEGIN PRIVATE KEY",
    ]
    for phrase in forbidden:
        assert phrase not in combined
    assert "api_crud" in combined
    assert "not_claimed" in combined


def test_secret_like_destination_fields_are_rejected(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--phase",
            "all",
            "--output-dir",
            str(tmp_path / "out"),
            "--destinations",
            "bad=type=s3;secret_access_key=do-not-render-this",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Raw secret-like field" in result.stderr


def test_splunk_enterprise_destination_is_refused_handoff(tmp_path: Path) -> None:
    out = run_renderer(
        tmp_path,
        "--destinations",
        "enterprise=type=splunk_enterprise;host=idx.example.com",
    )
    findings = json.loads((out / "findings.json").read_text())
    assert any(finding["code"] == "IP-DESTINATION-REFUSED" for finding in findings)
    destination = json.loads((out / "destinations/enterprise.json").read_text())
    assert destination["status"] == "refused_handoff"
