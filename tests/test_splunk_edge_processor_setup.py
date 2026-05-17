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
