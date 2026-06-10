#!/usr/bin/env python3
"""Regression coverage for splunk-edge-processor-setup release guardrails."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RENDERER = REPO_ROOT / "skills/splunk-edge-processor-setup/scripts/render_assets.py"


def base_args(out: Path) -> list[str]:
    return [
        sys.executable,
        str(RENDERER),
        "--output-dir",
        str(out),
        "--ep-tenant-url",
        "https://example.scs.splunk.com",
        "--ep-name",
        "prod-ep",
        "--ep-instances",
        "ep01.example.com=systemd",
        "--ep-source-types",
        "syslog_router",
        "--ep-destinations",
        "primary=type=s2s;host=idx.example.com;port=9997",
        "--ep-default-destination",
        "primary",
    ]


def test_edge_processor_fips_and_release_guardrails_render(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    result = subprocess.run(
        [*base_args(out), "--ep-fips-mode", "enabled"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    metadata = json.loads((out / "metadata.json").read_text())
    ep_object = json.loads((out / "control-plane/edge-processors/prod-ep.json").read_text())
    readme = (out / "README.md").read_text()

    assert metadata["ep_fips_mode"] == "enabled"
    assert ep_object["fips"]["mode"] == "enabled"
    assert "FIPS-compliant mode requires non-containerized" in readme
    assert "export_destination_errors_total" in readme
    assert "4000 source types" in readme
    assert "bulk indexer" in readme
    assert "Parquet and gzip" in readme


def test_edge_processor_fips_refuses_docker(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    args = base_args(out)
    idx = args.index("--ep-instances") + 1
    args[idx] = "ep01.example.com=docker"
    result = subprocess.run(
        [*args, "--ep-fips-mode", "enabled"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "FIPS" in result.stderr
    assert "Docker" in result.stderr


def test_edge_processor_shared_templates_include_stats(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    result = subprocess.run(
        base_args(out),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (out / "pipelines/templates/stats.spl2").is_file()


def test_cloud_s3_destination_defaults_to_data_management_dataset_handoff(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    args = base_args(out)
    idx = args.index("--ep-destinations") + 1
    args[idx] = "archive=type=s3;bucket=splunk-archive;prefix=ep/;region=us-west-2"
    idx = args.index("--ep-default-destination") + 1
    args[idx] = "archive"
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    destination = json.loads((out / "control-plane/destinations/archive.json").read_text())
    metadata = json.loads((out / "metadata.json").read_text())
    apply_objects = (out / "control-plane/apply-objects.sh").read_text()

    assert destination["type"] == "s3_dataset"
    assert destination["original_type"] == "s3"
    assert destination["status"] == "data_management_handoff"
    assert destination["dataset_family"] == "amazon_s3"
    assert destination["cloud_version"] == "10.4.2604"
    assert destination["api_crud"] == "not_claimed"
    assert metadata["destination_types"]["archive"] == "s3_dataset"
    assert "Data Management dataset handoff" in apply_objects


def test_cloud_azure_destination_renders_data_management_dataset_handoff(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    args = base_args(out)
    idx = args.index("--ep-destinations") + 1
    args[idx] = "archive=type=azure_dataset;storage_account=acct;container=logs;path=prod/"
    idx = args.index("--ep-default-destination") + 1
    args[idx] = "archive"
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    destination = json.loads((out / "control-plane/destinations/archive.json").read_text())

    assert destination["type"] == "azure_dataset"
    assert destination["status"] == "data_management_handoff"
    assert destination["dataset_family"] == "microsoft_azure"
    assert destination["connection_handoff"]["storage_account"] == "acct"


def test_enterprise_s3_destination_remains_direct_payload(tmp_path: Path) -> None:
    out = tmp_path / "rendered"
    args = base_args(out)
    args.extend(["--ep-control-plane", "enterprise"])
    idx = args.index("--ep-destinations") + 1
    args[idx] = "archive=type=s3;bucket=splunk-archive;prefix=ep/;region=us-west-2"
    idx = args.index("--ep-default-destination") + 1
    args[idx] = "archive"
    result = subprocess.run(
        args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    destination = json.loads((out / "control-plane/destinations/archive.json").read_text())
    metadata = json.loads((out / "metadata.json").read_text())

    assert destination["type"] == "s3"
    assert "status" not in destination
    assert metadata["destination_types"]["archive"] == "s3"


def test_edge_processor_docs_and_smoke_default_to_cloud_10_4_datasets() -> None:
    skill_root = REPO_ROOT / "skills/splunk-edge-processor-setup"
    reference = (skill_root / "reference.md").read_text(encoding="utf-8")
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    template = (skill_root / "template.example").read_text(encoding="utf-8")
    smoke = (skill_root / "scripts/smoke_offline.sh").read_text(encoding="utf-8")
    setup = (skill_root / "scripts/setup.sh").read_text(encoding="utf-8")

    for text in (reference, skill, template, smoke, setup):
        assert "s3_dataset" in text
    assert "azure_dataset" in reference
    assert "Data Management app" in reference
    assert "10.4.2604" in reference
    assert "9.2.2406" not in reference
    assert "9.3.2408" not in reference
    assert "archive=type=s3;bucket=splunk-archive" not in template
    assert "archive=type=s3;bucket=splunk-archive" not in smoke
    assert "type=s2s|hec|s3_dataset|azure_dataset|s3|syslog" in setup
