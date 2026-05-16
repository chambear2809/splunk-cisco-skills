#!/usr/bin/env python3
"""Validate the checked-in Splunk AppDynamics coverage taxonomy."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TAXONOMY = REPO_ROOT / "skills/splunk-appdynamics-setup/references/appdynamics-taxonomy.yaml"

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - local convenience path
    venv_python = REPO_ROOT / ".venv/bin/python"
    if venv_python.exists() and Path(sys.executable) != venv_python:
        os.execv(str(venv_python), [str(venv_python), *sys.argv])
    raise

REQUIRED_FIELDS = {
    "id",
    "family",
    "feature",
    "owner",
    "source_url",
    "status",
    "validation_method",
    "apply_boundary",
}

ALLOWED_STATUSES = {
    "api_apply",
    "cli_apply",
    "k8s_apply",
    "delegated_apply",
    "render_runbook",
    "validate_only",
    "not_applicable",
}


def load_rows(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = data.get("features")
    if not isinstance(rows, list):
        raise ValueError("taxonomy must contain a top-level features list")
    return rows


def validate_rows(rows: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"features[{index}] must be a mapping")
            continue
        missing = sorted(field for field in REQUIRED_FIELDS if not row.get(field))
        if missing:
            errors.append(f"{row.get('id', f'features[{index}]')}: missing {', '.join(missing)}")
        row_id = str(row.get("id", ""))
        if row_id in seen:
            errors.append(f"{row_id}: duplicate feature id")
        seen.add(row_id)
        status = row.get("status")
        if status and status not in ALLOWED_STATUSES:
            errors.append(f"{row_id}: unsupported status {status!r}")
        source_url = str(row.get("source_url", ""))
        if source_url and not source_url.startswith("https://help.splunk.com/"):
            errors.append(f"{row_id}: source_url must use official help.splunk.com docs")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check AppDynamics taxonomy coverage.")
    parser.add_argument("--taxonomy", default=str(DEFAULT_TAXONOMY), help="Taxonomy YAML path.")
    args = parser.parse_args()

    path = Path(args.taxonomy)
    errors = validate_rows(load_rows(path))
    if errors:
        print("AppDynamics coverage taxonomy errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"AppDynamics coverage taxonomy OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
