#!/usr/bin/env python3
"""Read-only AWS Lambda + Splunk Observability Cloud APM probes.

This module is used by doctor.sh / validate.sh for live checks only.
It never mutates Lambda functions; all writes go through the rendered
aws-cli/apply-plan.sh artifacts that the operator reviews first.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _aws(args: list[str]) -> dict[str, Any] | list[Any]:
    result = subprocess.run(
        ["aws"] + args + ["--output", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"aws CLI error: {result.stderr.strip()}")
    return json.loads(result.stdout)


def describe_function(function_name: str, region: str) -> dict[str, Any]:
    return _aws([  # type: ignore[return-value]
        "lambda", "get-function-configuration",
        "--function-name", function_name,
        "--region", region,
    ])


def list_functions(region: str) -> list[dict[str, Any]]:
    result = _aws([
        "lambda", "list-functions",
        "--region", region,
        "--query", "Functions[].{Name:FunctionName,Runtime:Runtime,Arch:Architectures[0]}",
    ])
    return result if isinstance(result, list) else []


def check_vendor_conflicts(
    config: dict[str, Any],
    allow_vendor_coexistence: bool = False,
) -> list[dict[str, str]]:
    env = (config.get("Environment") or {}).get("Variables") or {}
    layers = [layer.get("Arn", "") for layer in (config.get("Layers") or [])]

    conflicts: list[dict[str, str]] = []

    def _add(vendor: str, reason: str) -> None:
        level = "WARN" if allow_vendor_coexistence else "FAIL"
        conflicts.append({"vendor": vendor, "reason": reason, "level": level})

    for key in env:
        if key.startswith("DD_"):
            _add("Datadog", f"env var {key}")
            break
    for key in env:
        if key.startswith("APPDYNAMICS_"):
            _add("AppDynamics", f"env var {key}")
            break
    if "NEW_RELIC_LAMBDA_HANDLER" in env:
        _add("New Relic", "env var NEW_RELIC_LAMBDA_HANDLER")
    if "DT_TENANT" in env:
        _add("Dynatrace", "env var DT_TENANT")

    for arn in layers:
        if "datadog" in arn.lower():
            if not any(c["vendor"] == "Datadog" for c in conflicts):
                _add("Datadog", f"layer {arn}")
        if "NewRelicLambdaExtension" in arn:
            if not any(c["vendor"] == "New Relic" for c in conflicts):
                _add("New Relic", f"layer {arn}")
        if "Dynatrace_" in arn:
            if not any(c["vendor"] == "Dynatrace" for c in conflicts):
                _add("Dynatrace", f"layer {arn}")
        if "aws-otel" in arn or "901920570463" in arn:
            conflicts.append({"vendor": "ADOT", "reason": f"ADOT layer {arn}", "level": "FAIL"})

    return conflicts


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Read-only Lambda APM probes")
    p.add_argument("--function-name", required=False)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--list-functions", action="store_true")
    p.add_argument("--check-conflicts", action="store_true")
    p.add_argument("--allow-vendor-coexistence", action="store_true")
    p.add_argument("--json", action="store_true", dest="json_output")
    args = p.parse_args(argv)

    if args.list_functions:
        functions = list_functions(args.region)
        if args.json_output:
            print(json.dumps(functions, indent=2))
        else:
            for f in functions:
                print(f"  {f.get('Name')}  runtime={f.get('Runtime')}  arch={f.get('Arch')}")
        return

    if args.check_conflicts and args.function_name:
        config = describe_function(args.function_name, args.region)
        conflicts = check_vendor_conflicts(config, args.allow_vendor_coexistence)
        if args.json_output:
            print(json.dumps(conflicts, indent=2))
        else:
            if not conflicts:
                print(f"No vendor conflicts detected for {args.function_name}.")
            for c in conflicts:
                print(f"{c['level']}: {c['vendor']} conflict — {c['reason']}")
        return

    p.print_help()


if __name__ == "__main__":
    main()
