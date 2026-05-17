#!/usr/bin/env python3
"""Generate and validate manifest-backed MCP tool artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parents[1] / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from mcp_tooling import (  # noqa: E402
    GENERATED_FILENAME,
    ManifestError,
    coverage_report,
    find_legacy_json,
    find_source_manifests,
    generated_json_text,
    legacy_doc_from_manifest,
    load_manifest,
    read_json,
    rest_batch_payload,
    validate_legacy_doc,
    validate_manifest_payload,
)


def cmd_validate(args: argparse.Namespace) -> int:
    errors: list[str] = []
    manifests = find_source_manifests(args.paths if not args.all else None)
    json_paths = find_legacy_json(args.paths if args.paths and not args.all else None)

    if args.sources_only:
        json_paths = []
    if args.json_only:
        manifests = []

    for manifest_path in manifests:
        if not manifest_path.exists():
            errors.append(f"{manifest_path}: source manifest not found")
            continue
        try:
            payload = load_manifest(manifest_path)
            errors.extend(validate_manifest_payload(payload, source=str(manifest_path)))
        except Exception as exc:  # noqa: BLE001 - CLI should collect all failures
            errors.append(f"{manifest_path}: {exc}")

    for json_path in json_paths:
        if not json_path.exists():
            errors.append(f"{json_path}: {GENERATED_FILENAME} not found")
            continue
        try:
            payload = read_json(json_path)
            enforce_generated = (json_path.with_name("mcp_tools.source.yaml")).exists()
            errors.extend(
                validate_legacy_doc(
                    payload,
                    source=str(json_path),
                    enforce_generated_rules=enforce_generated,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{json_path}: {exc}")

    if errors:
        print("MCP tool validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"Validated {len(manifests)} source manifests and {len(json_paths)} MCP JSON files.")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    manifests = find_source_manifests(args.paths if not args.all else None)
    if not manifests:
        print("No MCP source manifests found.", file=sys.stderr)
        return 1

    for manifest_path in manifests:
        payload = load_manifest(manifest_path)
        doc = legacy_doc_from_manifest(payload, source=str(manifest_path))
        output_path = manifest_path.with_name(GENERATED_FILENAME)
        output_path.write_text(generated_json_text(doc), encoding="utf-8")
        print(output_path.relative_to(Path.cwd()) if output_path.is_relative_to(Path.cwd()) else output_path)
    return 0


def cmd_check_generated(args: argparse.Namespace) -> int:
    errors: list[str] = []
    manifests = find_source_manifests(args.paths if not args.all else None)
    if not manifests:
        print("No MCP source manifests found.", file=sys.stderr)
        return 1

    for manifest_path in manifests:
        generated_path = manifest_path.with_name(GENERATED_FILENAME)
        try:
            expected = generated_json_text(legacy_doc_from_manifest(load_manifest(manifest_path), source=str(manifest_path)))
        except ManifestError as exc:
            errors.append(str(exc))
            continue
        if not generated_path.exists():
            errors.append(f"{generated_path}: generated file missing")
            continue
        actual = generated_path.read_text(encoding="utf-8")
        if actual != expected:
            errors.append(f"{generated_path}: generated file is out of date")

    if errors:
        print("MCP generated artifact check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"Checked {len(manifests)} generated MCP JSON files.")
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    report = coverage_report()
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    totals = report["totals"]
    print(
        "MCP coverage: "
        f"{totals['with_manifest']} manifest-backed skills, "
        f"{totals['legacy_mcp_json']} legacy MCP JSON skills, "
        f"{totals['uncovered']} uncovered skills, "
        f"{totals['checks']} classified checks"
    )
    for status in (
        "mcp_tool",
        "covered_by_builtin_mcp",
        "live_lab_only",
        "excluded_with_reason",
    ):
        print(f"  {status}: {totals[status]}")
    return 0


def cmd_rest_batch_payload(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_absolute():
        path = Path.cwd() / path
    payload = rest_batch_payload(read_json(path), external_app_id=args.external_app_id)
    text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    if args.output:
        output = Path(args.output)
        output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate source manifests and generated JSON")
    validate.add_argument("paths", nargs="*", help="manifest, skill directory, or mcp_tools.json paths")
    validate.add_argument("--all", action="store_true", help="validate all repo MCP sources and JSON files")
    validate.add_argument("--sources-only", action="store_true", help="skip mcp_tools.json validation")
    validate.add_argument("--json-only", action="store_true", help="skip source manifest validation")
    validate.set_defaults(func=cmd_validate)

    generate = subparsers.add_parser("generate", help="generate mcp_tools.json from source manifests")
    generate.add_argument("paths", nargs="*", help="manifest or skill directory paths")
    generate.add_argument("--all", action="store_true", help="generate all repo MCP source manifests")
    generate.set_defaults(func=cmd_generate)

    check = subparsers.add_parser("check-generated", help="verify generated JSON is current")
    check.add_argument("paths", nargs="*", help="manifest or skill directory paths")
    check.add_argument("--all", action="store_true", help="check all repo MCP source manifests")
    check.set_defaults(func=cmd_check_generated)

    coverage = subparsers.add_parser("coverage", help="emit MCP coverage ledger")
    coverage.add_argument("--format", choices=("text", "json"), default="text")
    coverage.set_defaults(func=cmd_coverage)

    rest = subparsers.add_parser("rest-batch-payload", help="convert legacy mcp_tools.json to /mcp_tools batch payload")
    rest.add_argument("path", help="mcp_tools.json path")
    rest.add_argument("--external-app-id", help="override inferred external_app_id")
    rest.add_argument("--output", help="write payload to this path instead of stdout")
    rest.set_defaults(func=cmd_rest_batch_payload)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
