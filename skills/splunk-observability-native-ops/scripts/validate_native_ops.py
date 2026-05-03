#!/usr/bin/env python3
"""Validate native Splunk Observability Cloud operations specs and rendered output."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from render_native_ops import ALLOWED_COVERAGE, API_VERSION, SECTIONS, SpecError, load_structured, validate_spec


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
    if metadata.get("mode") != "native-ops":
        raise SpecError("metadata.json mode must be native-ops.")
    if metadata.get("api_version") != API_VERSION:
        raise SpecError(f"metadata.json api_version must be {API_VERSION!r}.")

    coverage_report = load_json(output_dir / "coverage-report.json")
    if coverage_report.get("api_version") != API_VERSION:
        raise SpecError(f"coverage-report.json api_version must be {API_VERSION!r}.")
    objects = coverage_report.get("objects", [])
    if not isinstance(objects, list):
        raise SpecError("coverage-report.json objects must be a list.")
    for index, item in enumerate(objects):
        if not isinstance(item, dict):
            raise SpecError(f"coverage-report.json objects[{index}] must be an object.")
        coverage = item.get("coverage")
        if coverage not in ALLOWED_COVERAGE:
            raise SpecError(f"coverage-report.json objects[{index}] has invalid coverage {coverage!r}.")
        object_type = item.get("object_type")
        if object_type in {"rum_session", "logs_chart"} and coverage == "api_apply":
            raise SpecError(f"{object_type} must not be marked api_apply.")

    apply_plan = load_json(output_dir / "apply-plan.json")
    if apply_plan.get("mode") != "native-ops":
        raise SpecError("apply-plan.json mode must be native-ops.")
    actions = apply_plan.get("actions", [])
    if not isinstance(actions, list):
        raise SpecError("apply-plan.json actions must be a list.")
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise SpecError(f"apply-plan.json actions[{index}] must be an object.")
        coverage = action.get("coverage")
        if coverage not in {"api_apply", "api_validate"}:
            raise SpecError(f"apply-plan.json actions[{index}] cannot use coverage {coverage!r}.")
        path = str(action.get("path", ""))
        service = str(action.get("service", "o11y"))
        if service not in {"o11y", "synthetics", "on_call"}:
            raise SpecError(f"apply-plan.json actions[{index}] uses unsupported service {service!r}.")
        if not path.startswith("/"):
            raise SpecError(f"apply-plan.json actions[{index}] path must start with '/': {path}")
        if "{" in path or "}" in path:
            raise SpecError(f"apply-plan.json actions[{index}] path contains an unresolved placeholder: {path}")
        if path.startswith("/synthetics/tests"):
            raise SpecError(
                f"apply-plan.json actions[{index}] uses the old Synthetics path prefix; use service=synthetics and /tests/..."
            )
        if action.get("object_type", "").startswith("synthetic") and service != "synthetics":
            raise SpecError(f"apply-plan.json actions[{index}] synthetic action must use service=synthetics.")
        if action.get("object_type") in {"rum_session", "logs_chart"} and coverage == "api_apply":
            raise SpecError(f"apply-plan.json actions[{index}] falsely marks UI-only workflow api_apply.")
        payload_file = action.get("payload_file")
        if payload_file and not (output_dir / str(payload_file)).exists():
            raise SpecError(f"apply-plan.json actions[{index}] references missing payload_file {payload_file!r}.")

    return {
        "actions": len(actions),
        "coverage_objects": len(objects),
        "ok": True,
        "output_dir": str(output_dir),
    }


def validate_spec_file(spec_path: Path) -> dict[str, Any]:
    spec = load_structured(spec_path)
    validate_spec(spec)
    counts = {section: len(spec.get(section, []) or []) for section in SECTIONS}
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
            print(f"Validated native Observability spec: {args.spec}")
        if args.output_dir:
            print(f"Validated native Observability rendered output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
