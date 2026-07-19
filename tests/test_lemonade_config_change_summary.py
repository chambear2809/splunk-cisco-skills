from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from tests.regression_helpers import REPO_ROOT


SCRIPT = REPO_ROOT / "skills/lemonade-splunk-otel/scripts/config_change_summary.py"


def run(before: Path, after: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--before", str(before), "--after", str(after)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_summary_reports_paths_without_values(tmp_path: Path) -> None:
    before = tmp_path / "before.yaml"
    after = tmp_path / "after.yaml"
    before.write_text(
        yaml.safe_dump(
            {
                "exporters": {"otlp": {"headers": {"token": "secret-before"}}},
                "service": {"pipelines": {"traces": {"processors": ["batch"]}}},
            }
        ),
        encoding="utf-8",
    )
    after.write_text(
        yaml.safe_dump(
            {
                "exporters": {"otlp": {"headers": {"token": "secret-after"}}},
                "service": {
                    "pipelines": {
                        "traces": {"processors": ["privacy", "batch"]},
                        "logs": {"processors": ["batch"]},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    result = run(before, after)
    assert result.returncode == 0, result.stderr
    assert "secret-before" not in result.stdout
    assert "secret-after" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["added"] == ["/service/pipelines/logs"]
    assert payload["changed"] == [
        "/exporters/otlp/headers/token",
        "/service/pipelines/traces/processors",
    ]


def test_summary_rejects_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real.yaml"
    link = tmp_path / "link.yaml"
    real.write_text("service: {}\n", encoding="utf-8")
    link.symlink_to(real)
    result = run(link, real)
    assert result.returncode != 0
    assert "regular file" in result.stderr
