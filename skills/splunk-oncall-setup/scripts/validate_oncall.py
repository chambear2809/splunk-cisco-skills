#!/usr/bin/env python3
"""Validate Splunk On-Call specs and rendered output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from render_oncall import (
    ALLOWED_COVERAGE,
    API_VERSION,
    SECTIONS,
    SpecError,
    load_structured,
    validate_spec,
)


REQUIRED_RENDERED_FILES = (
    "coverage-report.json",
    "apply-plan.json",
    "deeplinks.json",
    "handoff.md",
    "metadata.json",
)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{path} must contain a JSON object.")
    return data


def validate_rendered_output(output_dir: Path) -> dict[str, Any]:
    if not output_dir.exists():
        raise SpecError(f"Rendered output directory does not exist: {output_dir}")
    missing = [name for name in REQUIRED_RENDERED_FILES if not (output_dir / name).exists()]
    if missing:
        raise SpecError(f"Rendered output is missing required files: {', '.join(missing)}")

    metadata = load_json(output_dir / "metadata.json")
    if metadata.get("mode") != "splunk-oncall":
        raise SpecError("metadata.json mode must be splunk-oncall.")
    if metadata.get("api_version") != API_VERSION:
        raise SpecError(f"metadata.json api_version must be {API_VERSION!r}.")

    coverage = load_json(output_dir / "coverage-report.json")
    if coverage.get("api_version") != API_VERSION:
        raise SpecError(f"coverage-report.json api_version must be {API_VERSION!r}.")
    objects = coverage.get("objects")
    if not isinstance(objects, list):
        raise SpecError("coverage-report.json objects must be a list.")
    for index, item in enumerate(objects):
        if not isinstance(item, dict):
            raise SpecError(f"coverage-report.json objects[{index}] must be an object.")
        if item.get("coverage") not in ALLOWED_COVERAGE:
            raise SpecError(
                f"coverage-report.json objects[{index}] has invalid coverage {item.get('coverage')!r}."
            )

    apply_plan = load_json(output_dir / "apply-plan.json")
    if apply_plan.get("mode") != "splunk-oncall":
        raise SpecError("apply-plan.json mode must be splunk-oncall.")
    actions = apply_plan.get("actions")
    if not isinstance(actions, list):
        raise SpecError("apply-plan.json actions must be a list.")
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise SpecError(f"apply-plan.json actions[{index}] must be an object.")
        coverage_tag = action.get("coverage")
        if coverage_tag not in {"api_apply", "api_validate"}:
            raise SpecError(
                f"apply-plan.json actions[{index}] cannot use coverage {coverage_tag!r}."
            )
        path = str(action.get("path", ""))
        if not path.startswith("/"):
            raise SpecError(
                f"apply-plan.json actions[{index}] path must start with '/': {path}"
            )
        if any(marker in path for marker in ("{", "}", "<", ">")):
            raise SpecError(
                f"apply-plan.json actions[{index}] path contains an unresolved placeholder: {path}"
            )
        if any(ch in path for ch in ("\n", "\r", "\x00")):
            raise SpecError(
                f"apply-plan.json actions[{index}] path contains forbidden control characters."
            )
        service = str(action.get("service", "on_call"))
        if service != "on_call":
            raise SpecError(
                f"apply-plan.json actions[{index}] service must be 'on_call' (got {service!r})."
            )
        payload_file = action.get("payload_file")
        if payload_file:
            payload_path = output_dir / str(payload_file)
            if not payload_path.is_file():
                raise SpecError(
                    f"apply-plan.json actions[{index}] references missing payload_file {payload_file!r}."
                )
            # Defense in depth: payload_file must be inside output_dir.
            try:
                payload_path.resolve().relative_to(output_dir.resolve())
            except ValueError as exc:
                raise SpecError(
                    f"apply-plan.json actions[{index}] payload_file escapes output dir."
                ) from exc

    return {
        "actions": len(actions),
        "coverage_objects": len(objects),
        "ok": True,
        "output_dir": str(output_dir),
    }


def validate_spec_file(spec_path: Path) -> dict[str, Any]:
    spec = load_structured(spec_path)
    validate_spec(spec)
    counts: dict[str, int] = {}
    for section in SECTIONS:
        value = spec.get(section)
        if isinstance(value, list):
            counts[section] = len(value)
        elif isinstance(value, dict):
            counts[section] = sum(
                len(value.get(sub, []) or []) if isinstance(value.get(sub), list) else 1
                for sub in value
            )
        else:
            counts[section] = 0
    return {"ok": True, "api_version": API_VERSION, "sections": counts, "spec": str(spec_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.spec and not args.output_dir:
        parser.error("at least one of --spec or --output-dir is required")
    results: dict[str, Any] = {"ok": True}
    try:
        if args.spec:
            results["spec"] = validate_spec_file(args.spec)
        if args.output_dir:
            results["rendered"] = validate_rendered_output(args.output_dir)
    except (OSError, SpecError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        if args.spec:
            print(f"Validated Splunk On-Call spec: {args.spec}")
        if args.output_dir:
            print(f"Validated Splunk On-Call rendered output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
