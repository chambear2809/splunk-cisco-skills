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
from lib.common import SkillError, load_json
from lib.native import NativeWorkflow


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the native ITSI workflow.")
    parser.add_argument("--spec-json", required=True, help="Path to a JSON spec file.")
    parser.add_argument("--mode", choices=["preview", "apply", "validate"], required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        spec = load_json(args.spec_json)
        client = SplunkRestClient.from_spec(spec)
        result = NativeWorkflow(client).run(spec, args.mode)
        payload = {
            "mode": result.mode,
            "summary": result.summary(),
            "changes": [change.__dict__ for change in result.changes],
            "validations": result.validations,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1 if result.failed else 0
    except SkillError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

