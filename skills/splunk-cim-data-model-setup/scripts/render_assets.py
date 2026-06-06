#!/usr/bin/env python3
"""Render Splunk CIM data model governance assets (acceleration, mapping, index constraints)."""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from pathlib import Path

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "datamodels.conf",
    "macros.conf",
    "eventtypes.conf",
    "tags.conf",
    "validate-tstats.sh",
}

CIM_MODELS = {
    "Alerts",
    "Authentication",
    "Certificates",
    "Change",
    "Compute_Inventory",
    "Data_Access",
    "Databases",
    "Data_Loss_Prevention",
    "Email",
    "Endpoint",
    "Event_Signatures",
    "Interprocess_Messaging",
    "Intrusion_Detection",
    "Inventory",
    "JVM",
    "Malware",
    "Network_Resolution",
    "Network_Sessions",
    "Network_Traffic",
    "Performance",
    "Splunk_Audit",
    "Ticket_Management",
    "Updates",
    "Vulnerabilities",
    "Web",
}

SPLUNK_TIME_OPTIONS = {"--earliest-time", "--backfill-time"}


def normalize_splunk_time_args(argv: list[str]) -> list[str]:
    normalized: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in SPLUNK_TIME_OPTIONS and i + 1 < len(argv):
            value = argv[i + 1]
            if value.startswith("-") and not value.startswith("--"):
                normalized.append(f"{arg}={value}")
                i += 2
                continue
        normalized.append(arg)
        i += 1
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk CIM data model governance assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--app-name", default="Splunk_SA_CIM")
    parser.add_argument("--datamodel", required=True)
    parser.add_argument("--allow-custom-datamodel", choices=("true", "false"), default="false")
    parser.add_argument("--acceleration", choices=("true", "false"), default="false")
    parser.add_argument("--earliest-time", default="-7d")
    parser.add_argument("--backfill-time", default="")
    parser.add_argument("--max-concurrent", default="")
    parser.add_argument("--manual-rebuilds", choices=("true", "false", "unset"), default="unset")
    parser.add_argument("--cron-schedule", default="")
    parser.add_argument("--constrain-indexes", default="")
    parser.add_argument("--eventtype-name", default="")
    parser.add_argument("--eventtype-search", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    raw_argv = sys.argv[1:] if argv is None else list(argv)
    return parser.parse_args(normalize_splunk_time_args(raw_argv))


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


def csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def validate_index_name(value: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        die(f"Invalid index name {value!r}; use letters, numbers, underscore, hyphen (1-80 chars).")


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.datamodel or ""):
        die("--datamodel must contain only letters, numbers, and underscores.")
    if args.datamodel not in CIM_MODELS and args.allow_custom_datamodel != "true":
        die(
            f"--datamodel {args.datamodel!r} is not a known CIM model. Pass "
            "--allow-custom-datamodel true to govern a custom data model."
        )
    for value, option in (
        (args.earliest_time, "--earliest-time"),
        (args.backfill_time, "--backfill-time"),
        (args.cron_schedule, "--cron-schedule"),
        (args.eventtype_search, "--eventtype-search"),
    ):
        no_newline(value, option)
    if args.max_concurrent and not re.fullmatch(r"[0-9]+", args.max_concurrent):
        die("--max-concurrent must be a nonnegative integer.")
    for index in csv_list(args.constrain_indexes):
        validate_index_name(index)
    if args.eventtype_name and not re.fullmatch(r"[A-Za-z0-9_:-]+", args.eventtype_name):
        die("--eventtype-name must contain only letters, numbers, underscore, colon, or hyphen.")
    if args.eventtype_name and not args.eventtype_search:
        die("--eventtype-name requires --eventtype-search.")
    if args.tags and not args.eventtype_name:
        die("--tags requires --eventtype-name (CIM tags attach to an eventtype).")
    for tag in csv_list(args.tags):
        if not re.fullmatch(r"[A-Za-z0-9_]+", tag):
            die(f"Tag {tag!r} must contain only letters, numbers, and underscores.")


def render_datamodels(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-cim-data-model-setup. Review before applying."]
    if args.acceleration != "true":
        lines.append(f"# Acceleration not requested for data model {args.datamodel}.")
        return "\n".join(lines) + "\n"
    lines.append(f"[{args.datamodel}]")
    lines.append("acceleration = 1")
    lines.append(f"acceleration.earliest_time = {args.earliest_time}")
    if args.backfill_time:
        lines.append(f"acceleration.backfill_time = {args.backfill_time}")
    if args.max_concurrent:
        lines.append(f"acceleration.max_concurrent = {args.max_concurrent}")
    if args.manual_rebuilds != "unset":
        lines.append(f"acceleration.manual_rebuilds = {args.manual_rebuilds}")
    if args.cron_schedule:
        lines.append(f"acceleration.cron_schedule = {args.cron_schedule}")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_macros(args: argparse.Namespace) -> str:
    indexes = csv_list(args.constrain_indexes)
    lines = ["# Rendered by splunk-cim-data-model-setup. Review before applying."]
    if not indexes:
        lines.append("# No CIM index constraint macro requested.")
        return "\n".join(lines) + "\n"
    definition = "(" + " OR ".join(f"index={index}" for index in indexes) + ")"
    lines.extend(
        [
            f"[cim_{args.datamodel}_indexes]",
            f"definition = {definition}",
            f"description = Allowed indexes for the {args.datamodel} CIM data model",
            "iseval = 0",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def render_eventtypes(args: argparse.Namespace) -> str:
    lines = ["# Rendered by splunk-cim-data-model-setup. Review before applying."]
    if not args.eventtype_name:
        lines.append("# No CIM eventtype requested.")
        return "\n".join(lines) + "\n"
    lines.extend([f"[{args.eventtype_name}]", f"search = {args.eventtype_search}", ""])
    return "\n".join(lines).rstrip() + "\n"


def render_tags(args: argparse.Namespace) -> str:
    tags = csv_list(args.tags)
    lines = ["# Rendered by splunk-cim-data-model-setup. Review before applying."]
    if not (args.eventtype_name and tags):
        lines.append("# No CIM tags requested.")
        return "\n".join(lines) + "\n"
    lines.append(f"[eventtype={args.eventtype_name}]")
    for tag in tags:
        lines.append(f"{tag} = enabled")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_validate(args: argparse.Namespace) -> str:
    splunk = '"${SPLUNK_HOME:-/opt/splunk}/bin/splunk"'
    return (
        "#!/usr/bin/env bash\nset -euo pipefail\n\n"
        f"# Validate that the {args.datamodel} CIM data model returns tstats results.\n"
        "# Authenticate first with: splunk login\n"
        f'{splunk} search "| tstats count from datamodel={args.datamodel} | head 5" '
        '-maxout 5 -auth "" 2>/dev/null || '
        f'echo "Run: | tstats count from datamodel={args.datamodel} in Search to confirm acceleration/mapping."\n'
    )


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk CIM Data Model Rendered Assets

Data model: `{args.datamodel}`
App: `{args.app_name}`
Acceleration: `{args.acceleration}`

Files:

- `datamodels.conf` - acceleration override for the data model
- `macros.conf` - `cim_{args.datamodel}_indexes` allowed-index constraint
- `eventtypes.conf` - CIM eventtype mapping
- `tags.conf` - CIM tags attached to the eventtype
- `validate-tstats.sh` - `| tstats ... from datamodel={args.datamodel}` check

Requires the Splunk Common Information Model add-on (`Splunk_SA_CIM`,
Splunkbase 1621). If it is missing, install it with `splunk-app-install` first.
Acceleration consumes indexer/storage resources; size the earliest_time window
and summary range deliberately.
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "cim"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "datamodel": args.datamodel,
                    "app_name": args.app_name,
                    "acceleration": args.acceleration,
                    "earliest_time": args.earliest_time,
                    "constrain_indexes": csv_list(args.constrain_indexes),
                    "eventtype_name": args.eventtype_name,
                    "tags": csv_list(args.tags),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "datamodels.conf": render_datamodels(args),
            "macros.conf": render_macros(args),
            "eventtypes.conf": render_eventtypes(args),
            "tags.conf": render_tags(args),
            "validate-tstats.sh": render_validate(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "cim",
        "datamodel": args.datamodel,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
    }


def main() -> int:
    args = parse_args()
    validate(args)
    payload = render(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render CIM data model assets under {payload['render_dir']}")
    else:
        print(f"Rendered CIM data model assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
