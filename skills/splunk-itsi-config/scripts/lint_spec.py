#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.common import SkillError, load_json  # noqa: E402
from lib.spec_validation import SCHEMA_VERSION, validate_spec  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline lint for an ITSI configuration spec.")
    parser.add_argument("--workflow", choices=["native", "content-packs", "topology"], required=True)
    parser.add_argument("--spec-json", required=True)
    parser.add_argument("--source-path")
    parser.add_argument("--for-apply", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        spec = load_json(args.spec_json)
        warnings = validate_spec(
            spec,
            args.workflow,
            for_apply=args.for_apply,
            source_path=args.source_path,
        )
        if not args.quiet:
            print(
                json.dumps(
                    {
                        "status": "pass",
                        "workflow": args.workflow,
                        "schema_version": SCHEMA_VERSION,
                        "network_requests": 0,
                        "warnings": warnings,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    except (SkillError, json.JSONDecodeError, OSError) as exc:
        print(f"Spec lint failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
