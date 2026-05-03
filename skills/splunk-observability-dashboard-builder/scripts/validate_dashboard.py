#!/usr/bin/env python3
"""Validate Splunk Observability dashboard specs and rendered payloads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from render_dashboard import SpecError, load_structured, validate_spec  # noqa: E402


def validate_rendered(output_dir: Path) -> list[str]:
    errors: list[str] = []
    for rel in ("apply-plan.json", "dashboard.json", "metadata.json"):
        path = output_dir / rel
        if not path.is_file():
            errors.append(f"Missing rendered file: {path}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
    charts_dir = output_dir / "charts"
    if not charts_dir.is_dir():
        errors.append(f"Missing rendered charts directory: {charts_dir}")
    else:
        chart_files = sorted(charts_dir.glob("*.json"))
        if not chart_files:
            errors.append(f"No rendered chart payloads in {charts_dir}")
        for path in chart_files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"{path}: invalid JSON: {exc}")
                continue
            if "name" not in payload or "options" not in payload:
                errors.append(f"{path}: chart payload requires name and options")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args()

    if not args.spec and not args.output_dir:
        parser.error("provide --spec, --output-dir, or both")

    errors: list[str] = []
    warnings: list[str] = []
    try:
        if args.spec:
            spec = load_structured(args.spec)
            spec_errors, spec_warnings = validate_spec(spec)
            errors.extend(spec_errors)
            warnings.extend(spec_warnings)
        if args.output_dir:
            errors.extend(validate_rendered(args.output_dir))
    except (OSError, json.JSONDecodeError, SpecError) as exc:
        errors.append(str(exc))

    result = {"ok": not errors, "errors": errors, "warnings": warnings}
    if args.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for warning in warnings:
            print(f"WARNING: {warning}")
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if not errors:
            print("Splunk Observability dashboard validation passed.")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
