#!/usr/bin/env python3
"""Regression coverage for splunk-cloud-data-manager-setup."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "splunk-cloud-data-manager-setup"
RENDERER_PATH = SKILL_DIR / "scripts" / "render_assets.py"


def load_renderer():
    spec = importlib.util.spec_from_file_location("data_manager_renderer", RENDERER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_renderer(tmp_path: Path) -> Path:
    out = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER_PATH),
            "--spec",
            str(SKILL_DIR / "template.example"),
            "--output-dir",
            str(out),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out


def test_source_catalog_covers_documented_provider_families() -> None:
    renderer = load_renderer()
    catalog = renderer.SOURCE_CATALOG

    assert "aws:cloudtrail" in catalog["aws"]
    assert "aws:securityhub:finding" in catalog["aws"]
    assert "aws:accessanalyzer:finding" in catalog["aws"]
    assert "aws:metadata" in catalog["aws"]
    assert "aws:cloudwatchlogs" in catalog["aws"]
    assert "azure:monitor:activity" in catalog["azure"]
    assert "mscs:azure:eventhub" in catalog["azure"]
    assert "google:gcp:pubsub:access_transparency" in catalog["gcp"]
    assert "google:gcp:pubsub:audit:data_access" in catalog["gcp"]
    assert "google:gcp:pubsub:audit:system_event" in catalog["gcp"]
    assert "crowdstrike:events:sensor" in catalog["crowdstrike"]
    assert "crowdstrike:inventory:managedassets" in catalog["crowdstrike"]
    assert "aws:asl:shfindings" not in catalog["aws"]
    assert "google:gcp:pubsub:monitoring:system_event" not in catalog["gcp"]


def test_hec_ack_mapping_is_source_specific() -> None:
    renderer = load_renderer()

    assert renderer.HEC_ACK_REQUIRED_SOURCES == [
        "CloudTrail",
        "GuardDuty",
        "SecurityHub",
        "IAM Access Analyzer",
        "CloudWatch Logs",
    ]
    assert renderer.HEC_SPECIAL_TOKENS == {
        "aws_s3": "scdm-scs-hec-token",
        "aws_s3_promote": "scdm-scs-promote-hec-token",
        "azure_event_hub": "scdm-scs-hec-token",
        "crowdstrike_fdr": "scdm-scs-hec-token",
    }
    assert renderer.HEC_TOKEN_NAMES["aws_security_hub"] == "data-manager-security_<input_id>"
    assert renderer.HEC_TOKEN_NAMES["gcp"] == "data-manager-gcp-cloud-logging_<input_id>"


def test_render_outputs_required_artifacts_and_allowed_coverage(tmp_path: Path) -> None:
    out = run_renderer(tmp_path)
    coverage = json.loads((out / "coverage-report.json").read_text())
    statuses = {row["coverage_status"] for row in coverage}
    renderer = load_renderer()

    assert statuses <= renderer.ALLOWED_COVERAGE_STATUSES
    assert any(
        row["feature"] == "Data Manager input creation"
        and row["coverage_status"] == "ui_handoff"
        for row in coverage
    )
    assert (out / "apply-plan.json").is_file()
    assert (out / "provider-runbooks" / "source-catalog.json").is_file()
    assert (out / "scripts" / "aws-cloudformation.sh").is_file()
    assert (out / "scripts" / "azure-arm.sh").is_file()
    assert (out / "scripts" / "gcp-terraform.sh").is_file()


def test_rendered_artifacts_do_not_claim_private_crud(tmp_path: Path) -> None:
    out = run_renderer(tmp_path)
    combined = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in out.rglob("*")
        if path.is_file() and path.suffix in {".md", ".sh", ".json"}
    )

    forbidden = [
        "POST /services/data-manager/input",
        "PUT /services/data-manager/input",
        "terraform resource splunk_cloud_data_manager_input",
        "global HEC ACK",
    ]
    for phrase in forbidden:
        assert phrase not in combined
    assert "Data Manager input creation" in combined
    assert "ui_handoff" in combined


def test_secret_like_spec_values_are_rejected(tmp_path: Path) -> None:
    bad_spec = tmp_path / "bad.json"
    bad_spec.write_text(
        json.dumps(
            {
                "api_version": "splunk-cloud-data-manager-setup/v1",
                "splunk_cloud": {"primary_search_head": True, "roles": ["sc_admin"]},
                "hec": {"enabled": True},
                "crowdstrike": {
                    "enabled": True,
                    "aws_access_key_id": "do-not-render-this-either",
                    "aws_secret_access_key": "do-not-render-this",
                    "event_types": ["sensor"],
                    "single_account_confirmed": True,
                },
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER_PATH),
            "--spec",
            str(bad_spec),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Raw secret-like values are not allowed" in result.stderr


def test_overlap_and_migration_guardrails_are_reported() -> None:
    renderer = load_renderer()
    spec = {
        "splunk_cloud": {"primary_search_head": True, "roles": ["sc_admin"]},
        "hec": {"enabled": True},
        "aws": {
            "enabled": True,
            "source_families": ["cloudtrail", "cloudwatch_logs", "s3"],
            "organizations": {"enabled": True, "checked_for_overlap": False},
        },
        "azure": {
            "enabled": True,
            "mscs_migration": {
                "enabled": True,
                "inputs_inactive": False,
                "health_ready": False,
                "duplicate_migration_checked": False,
            },
        },
        "gcp": {"enabled": True, "overlap_checked": False},
        "crowdstrike": {
            "enabled": True,
            "event_types": ["external"],
            "single_account_confirmed": False,
        },
        "iac": {"splunk_scp_provider_adjacent_only": True},
    }

    messages = [finding["message"] for finding in renderer.collect_findings(spec)]
    assert any(
        "AWS Organizations/OUs are not documented for: cloudwatch_logs, s3" in msg
        for msg in messages
    )
    assert any("Duplicate Azure Event Hub migration check is required" in msg for msg in messages)
    assert any("GCP project/folder/org overlap" in msg for msg in messages)
    assert any("single-account only" in msg for msg in messages)
    assert any("sensor events are mandatory" in msg for msg in messages)


def test_supported_region_guardrails_are_reported() -> None:
    renderer = load_renderer()
    spec = {
        "splunk_cloud": {"primary_search_head": True, "roles": ["sc_admin"]},
        "hec": {"enabled": True},
        "aws": {"enabled": True, "regions": ["moon-east-1"]},
        "azure": {"enabled": True, "event_hub_region": "usgovvirginia"},
        "gcp": {"enabled": True, "dataflow_region": "antarctica1", "overlap_checked": True},
        "crowdstrike": {
            "enabled": True,
            "region": "US-2",
            "sqs_queue_url": "https://sqs.us-west-1.amazonaws.com/123456789012/example-fdr",
            "event_types": ["sensor"],
            "single_account_confirmed": True,
            "aws_access_key_id_file": "/tmp/key-id",
            "aws_secret_access_key_file": "/tmp/key-secret",
        },
        "iac": {"splunk_scp_provider_adjacent_only": True},
    }

    messages = [finding["message"] for finding in renderer.collect_findings(spec)]
    assert any("AWS ingestion region" in msg for msg in messages)
    assert any("Azure Event Hub region" in msg for msg in messages)
    assert any("GCP Dataflow region" in msg for msg in messages)
    assert any("maps to AWS region us-west-2" in msg for msg in messages)


def test_apply_refuses_enabled_provider_without_artifact_path(tmp_path: Path) -> None:
    spec_path = tmp_path / "bad-apply.json"
    spec_path.write_text(
        json.dumps(
            {
                "api_version": "splunk-cloud-data-manager-setup/v1",
                "splunk_cloud": {"primary_search_head": True, "roles": ["sc_admin"]},
                "hec": {"enabled": True},
                "aws": {"enabled": True, "regions": ["us-east-1"]},
                "iac": {
                    "apply_enabled": True,
                    "aws_cloudformation_apply_enabled": True,
                    "splunk_scp_provider_adjacent_only": True,
                },
            }
        )
    )
    result = subprocess.run(
        [
            "bash",
            str(SKILL_DIR / "scripts" / "setup.sh"),
            "--phase",
            "apply",
            "--spec",
            str(spec_path),
            "--output-dir",
            str(tmp_path / "rendered"),
            "--accept-apply",
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "missing Data Manager-generated artifacts" in result.stdout + result.stderr


def test_global_apply_gate_disables_provider_apply_without_top_level_opt_in(tmp_path: Path) -> None:
    spec_path = tmp_path / "gated-apply.json"
    spec_path.write_text(
        json.dumps(
            {
                "api_version": "splunk-cloud-data-manager-setup/v1",
                "splunk_cloud": {"primary_search_head": True, "roles": ["sc_admin"]},
                "hec": {"enabled": True},
                "aws": {
                    "enabled": True,
                    "regions": ["us-east-1"],
                    "cloudformation_template_path": "/tmp/dm-template.yaml",
                },
                "iac": {
                    "apply_enabled": False,
                    "aws_cloudformation_apply_enabled": True,
                    "splunk_scp_provider_adjacent_only": True,
                },
            }
        )
    )
    out = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(RENDERER_PATH),
            "--spec",
            str(spec_path),
            "--output-dir",
            str(out),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    plan = json.loads((out / "apply-plan.json").read_text())
    aws_apply = next(op for op in plan["operations"] if op["id"] == "aws-cloudformation-apply")
    assert aws_apply["enabled"] is False
    doctor = (out / "doctor-report.md").read_text()
    assert "Provider apply flags are ignored" in doctor
