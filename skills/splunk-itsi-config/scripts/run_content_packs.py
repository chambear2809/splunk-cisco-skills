#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib.client import SplunkRestClient  # noqa: E402
from lib.common import SkillError, load_json  # noqa: E402
from lib.content_packs import ContentPackWorkflow  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ITSI content-pack workflow.")
    parser.add_argument("--spec-json", required=True, help="Path to a JSON spec file.")
    parser.add_argument("--mode", choices=["preview", "apply", "validate"], required=True)
    parser.add_argument(
        "--report-root",
        default=str(SCRIPT_DIR.parent / "reports"),
        help="Directory where content-pack reports should be written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        spec = load_json(args.spec_json)
        client = SplunkRestClient.from_spec(spec)
        result = ContentPackWorkflow(client, args.report_root).run(spec, args.mode)
        print(json.dumps(result, indent=2, sort_keys=True))
        prerequisite_failed = any(
            check["status"] == "error"
            for state_key in ("itsi", "content_library")
            for check in result.get(state_key, {}).get("checks", [])
        )
        failed = any(
            finding["status"] == "error"
            for run in result["runs"]
            for finding in run.get("findings", [])
        )
        return 1 if (prerequisite_failed or failed) else 0
    except SkillError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
