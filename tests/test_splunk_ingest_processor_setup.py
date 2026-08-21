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
        "AI-powered data management readiness",
        "Automated Field Extraction",
        "Automated Field Extraction region allowlist",
        "Guided Onboarding with Auto-Schematization",
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
        "control-plane-handoffs/ai-powered-data-management.md",
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


def test_ai_powered_data_management_lifecycle_is_explicit_and_ui_only(tmp_path: Path) -> None:
    out = run_renderer(tmp_path)
    coverage = json.loads((out / "coverage-report.json").read_text())
    by_feature = {row["feature"]: row for row in coverage}

    afe = by_feature["Automated Field Extraction"]
    assert afe["availability"] == "controlled_availability"
    assert afe["source_date"] == "2026-03-11"
    assert afe["coverage_status"] == "ui_handoff"
    assert afe["automation"] == "ui_suggestion_and_human_review_only"
    assert afe["rechecked"] == "2026-08-20"
    assert afe["release_notes_updated"] == "2026-06-16"
    assert "no release-stage label" in afe["recheck_evidence"]
    assert "never states that AFE is generally available" in afe["recheck_evidence"]

    guided = by_feature["Guided Onboarding with Auto-Schematization"]
    assert guided["availability"] == "alpha"
    assert guided["source_date"] == "2026-03-11"
    assert guided["coverage_status"] == "ui_handoff"
    assert guided["automation"] == "ui_handoff_and_human_review_only"
    assert guided["rechecked"] == "2026-08-20"
    assert guided["release_notes_updated"] == "2026-06-16"
    assert "zero occurrences" in guided["recheck_evidence"]

    plan = json.loads((out / "apply-plan.json").read_text())
    ai_plan = plan["ai_powered_data_management"]
    assert ai_plan["api_crud"] == "not_claimed"
    assert {item["capability"] for item in ai_plan["capabilities"]} == {
        "Automated Field Extraction",
        "Guided Onboarding with Auto-Schematization",
    }
    assert {item["availability"] for item in ai_plan["capabilities"]} == {
        "alpha",
        "controlled_availability",
    }
    assert all(action["type"] != "api" for action in plan["actions"])

    handoff = (out / "control-plane-handoffs/ai-powered-data-management.md").read_text()
    normalized_handoff = " ".join(handoff.split())
    for phrase in (
        "Controlled Availability",
        "Alpha",
        "does not generate, download, install, or apply",
        "explicit human apply decision",
        "not evidence that the tenant configuration changed",
        "does not infer a third",
    ):
        assert phrase in normalized_handoff


def test_ai_powered_data_management_records_dated_negative_evidence(tmp_path: Path) -> None:
    out = run_renderer(tmp_path)
    handoff = " ".join(
        (out / "control-plane-handoffs/ai-powered-data-management.md").read_text().split()
    )
    readiness = " ".join((out / "readiness-report.md").read_text().split())
    ui_handoff = " ".join(
        (out / "control-plane-handoffs/ingest-processor-ui.md").read_text().split()
    )

    for phrase in (
        "re-checked 2026-08-20",
        "release notes updated 2026-06-16",
        "Neither stage moved",
        "negative evidence rather than a new claim",
        "list AFE under February 18, 2026 with no release-stage label",
        '"(Controlled Availability release)" on May 18, 2026',
        '"(General Availability release)" on June 29, 2026',
        "never states that AFE is generally available",
        "zero occurrences of Auto-Schematization or Guided Onboarding",
        "equally consistent with still-Alpha and with quiet withdrawal",
    ):
        assert phrase in handoff

    assert (
        "https://help.splunk.com/en/data-management/process-data-at-ingest-time"
        "/use-ingest-processor/introduction/release-notes-for-ingest-processor" in handoff
    )

    for surface in (readiness, ui_handoff):
        assert "re-checked 2026-08-20" in surface
        assert "release notes updated 2026-06-16" in surface


def test_ai_powered_data_management_stages_stay_conservative() -> None:
    module = load_renderer()
    lifecycle = module.AI_POWERED_DATA_MANAGEMENT_LIFECYCLE

    assert lifecycle["Automated Field Extraction"]["availability"] == "controlled_availability"
    assert lifecycle["Guided Onboarding with Auto-Schematization"]["availability"] == "alpha"
    assert module.AI_LIFECYCLE_RECHECKED == "2026-08-20"
    assert module.RELEASE_NOTES_UPDATED == "2026-06-16"

    ledger = (SKILL_DIR / "references" / "research-ledger.md").read_text()
    reference = (SKILL_DIR / "reference.md").read_text()
    skill_doc = (SKILL_DIR / "SKILL.md").read_text()

    for text in (ledger, reference, skill_doc):
        assert "2026-08-20" in text
        assert "2026-06-16" in text
    assert "Negative evidence re-check" in ledger
    assert "Announced `2026-03-11`, re-checked `2026-08-20`" in reference


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
        "POST /services/data-management/guided-onboarding",
        "terraform resource splunk_guided_onboarding",
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
    out = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER),
            "--phase",
            "all",
            "--output-dir",
            str(out),
            "--subscription-tier",
            "premier",
            "--destinations",
            "enterprise=type=splunk_enterprise;host=idx.example.com",
            "--pipelines",
            "",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "IP-DESTINATION-REFUSED" in result.stderr
    findings = json.loads((out / "findings.json").read_text())
    assert any(finding["code"] == "IP-DESTINATION-REFUSED" for finding in findings)
    destination = json.loads((out / "destinations/enterprise.json").read_text())
    assert destination["status"] == "refused_handoff"
