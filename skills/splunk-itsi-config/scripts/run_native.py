#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.client import SplunkRestClient
from lib.common import SkillError, load_json, write_json, write_yaml
from lib.native import NativeWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the native ITSI workflow.")
    parser.add_argument("--spec-json", required=True, help="Path to a JSON spec file.")
    parser.add_argument("--mode", choices=["preview", "apply", "validate", "export", "inventory", "prune-plan", "cleanup-apply"], required=True)
    parser.add_argument("--output", help="Optional output path for export, inventory, or prune-plan payloads.")
    parser.add_argument("--output-format", choices=["json", "yaml"], default="json")
    parser.add_argument("--backup-output", help="Required backup output path before cleanup-apply.")
    parser.add_argument("--backup-format", choices=["json", "yaml"], default="yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        spec = load_json(args.spec_json)
        client = SplunkRestClient.from_spec(spec)
        workflow = NativeWorkflow(client)
        if args.mode == "cleanup-apply":
            if not args.backup_output:
                raise SkillError("cleanup-apply requires --backup-output so the live ITSI export is written before deletion.")
            backup_result = workflow.run(spec, "export")
            backup_payload = backup_result.exports.get("native_spec", {})
            if args.backup_format == "yaml":
                write_yaml(args.backup_output, backup_payload)
            else:
                write_json(args.backup_output, backup_payload)
        result = workflow.run(spec, args.mode)
        payload = {
            "mode": result.mode,
            "summary": result.summary(),
            "changes": [change.__dict__ for change in result.changes],
            "validations": result.validations,
            "diagnostics": result.diagnostics,
        }
        if result.exports:
            payload["exports"] = result.exports
        if result.inventory:
            payload["inventory"] = result.inventory
        if result.prune_plan:
            payload["prune_plan"] = result.prune_plan
        if args.output:
            output_payload: object = payload
            if args.mode == "export":
                output_payload = result.exports.get("native_spec", {})
            elif args.mode == "inventory":
                output_payload = result.inventory
            elif args.mode == "prune-plan":
                output_payload = result.prune_plan
            if args.output_format == "yaml":
                write_yaml(args.output, output_payload)
            else:
                write_json(args.output, output_payload)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1 if result.failed else 0
    except SkillError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
