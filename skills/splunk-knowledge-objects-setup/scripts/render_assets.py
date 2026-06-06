#!/usr/bin/env python3
"""Render Splunk knowledge object governance assets (saved searches, macros, lookups, eventtypes, tags, ACLs)."""

from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "savedsearches.conf",
    "macros.conf",
    "transforms.conf",
    "props.conf",
    "eventtypes.conf",
    "tags.conf",
    "acl-plan.json",
    "lookup-stub.csv",
}

OBJECT_KINDS = ("savedsearch", "macro", "lookup", "eventtype", "tag")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk knowledge object governance assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--app-name", default="search")
    parser.add_argument("--object-kind", choices=OBJECT_KINDS, required=True)
    parser.add_argument("--name", default="")
    # saved search
    parser.add_argument("--search", default="")
    parser.add_argument("--is-scheduled", choices=("true", "false"), default="false")
    parser.add_argument("--cron-schedule", default="")
    parser.add_argument("--dispatch-earliest-time", default="")
    parser.add_argument("--dispatch-latest-time", default="")
    parser.add_argument("--alert-type", default="")
    parser.add_argument("--alert-condition", default="")
    parser.add_argument("--actions", default="")
    # macro
    parser.add_argument("--definition", default="")
    parser.add_argument("--args", default="")
    parser.add_argument("--iseval", choices=("0", "1"), default="0")
    # lookup
    parser.add_argument("--lookup-type", choices=("csv", "kvstore"), default="csv")
    parser.add_argument("--lookup-filename", default="")
    parser.add_argument("--collection", default="")
    parser.add_argument("--fields-list", default="")
    parser.add_argument("--csv-headers", default="")
    parser.add_argument("--auto-lookup-sourcetype", default="")
    parser.add_argument("--lookup-input-fields", default="")
    parser.add_argument("--lookup-output-fields", default="")
    # eventtype / tag
    parser.add_argument("--eventtype-search", default="")
    parser.add_argument("--tags", default="")
    # ACL
    parser.add_argument("--sharing", choices=("user", "app", "global"), default="app")
    parser.add_argument("--owner", default="nobody")
    parser.add_argument("--read-roles", default="")
    parser.add_argument("--write-roles", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


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


def validate(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not args.name and args.object_kind != "tag":
        die(f"--name is required for object-kind {args.object_kind}.")
    no_newline(args.name, "--name")
    if args.object_kind == "savedsearch":
        if not args.search:
            die("--search is required for a savedsearch.")
    elif args.object_kind == "macro":
        if not args.definition:
            die("--definition is required for a macro.")
    elif args.object_kind == "lookup":
        if not re.fullmatch(r"[A-Za-z0-9_]+", args.name):
            die("lookup --name (transforms stanza) must be letters, numbers, and underscores.")
        if args.lookup_type == "csv" and not args.lookup_filename:
            die("--lookup-filename is required for a csv lookup.")
        if args.lookup_type == "kvstore" and not args.collection:
            die("--collection is required for a kvstore lookup.")
        if args.lookup_filename and not re.fullmatch(r"[A-Za-z0-9._-]+\.csv", args.lookup_filename):
            die("--lookup-filename must be a *.csv name with safe characters.")
    elif args.object_kind == "eventtype":
        if not args.eventtype_search:
            die("--eventtype-search is required for an eventtype.")
    elif args.object_kind == "tag":
        if not args.name:
            die("--name (the eventtype name) is required for tags.")
        if not args.tags:
            die("--tags is required for object-kind tag.")
    for tag in csv_list(args.tags):
        if not re.fullmatch(r"[A-Za-z0-9_]+", tag):
            die(f"Tag {tag!r} must contain only letters, numbers, and underscores.")
    for role in csv_list(args.read_roles) + csv_list(args.write_roles):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", role):
            die(f"Role {role!r} must contain only letters, numbers, underscore, and hyphen.")


def render_savedsearches(args: argparse.Namespace) -> str:
    if args.object_kind != "savedsearch":
        return "# No saved search requested.\n"
    lines = [f"[{args.name}]", f"search = {args.search}"]
    if args.is_scheduled == "true":
        lines.append("enableSched = 1")
    if args.cron_schedule:
        lines.append(f"cron_schedule = {args.cron_schedule}")
    if args.dispatch_earliest_time:
        lines.append(f"dispatch.earliest_time = {args.dispatch_earliest_time}")
    if args.dispatch_latest_time:
        lines.append(f"dispatch.latest_time = {args.dispatch_latest_time}")
    if args.alert_type:
        lines.append(f"alert_type = {args.alert_type}")
    if args.alert_condition:
        lines.append(f"alert_condition = {args.alert_condition}")
    for action in csv_list(args.actions):
        lines.append(f"action.{action} = 1")
    if args.actions:
        lines.append(f"actions = {', '.join(csv_list(args.actions))}")
    lines.append("")
    return "# Rendered by splunk-knowledge-objects-setup.\n" + "\n".join(lines)


def render_macros(args: argparse.Namespace) -> str:
    if args.object_kind != "macro":
        return "# No macro requested.\n"
    stanza = args.name
    if args.args and "(" not in stanza:
        arg_count = len(csv_list(args.args))
        stanza = f"{args.name}({arg_count})"
    lines = [f"[{stanza}]", f"definition = {args.definition}"]
    if args.args:
        lines.append(f"args = {', '.join(csv_list(args.args))}")
    lines.append(f"iseval = {args.iseval}")
    lines.append("")
    return "# Rendered by splunk-knowledge-objects-setup.\n" + "\n".join(lines)


def render_transforms(args: argparse.Namespace) -> str:
    if args.object_kind != "lookup":
        return "# No lookup definition requested.\n"
    lines = [f"[{args.name}]"]
    if args.lookup_type == "csv":
        lines.append(f"filename = {args.lookup_filename}")
    else:
        lines.append("external_type = kvstore")
        lines.append(f"collection = {args.collection}")
    if args.fields_list:
        lines.append(f"fields_list = {', '.join(csv_list(args.fields_list))}")
    lines.append("")
    return "# Rendered by splunk-knowledge-objects-setup.\n" + "\n".join(lines)


def render_props(args: argparse.Namespace) -> str:
    if args.object_kind != "lookup" or not args.auto_lookup_sourcetype:
        return "# No automatic lookup binding requested.\n"
    inputs = csv_list(args.lookup_input_fields)
    outputs = csv_list(args.lookup_output_fields)
    spec = args.name
    if inputs:
        spec += " " + " ".join(inputs)
    if outputs:
        spec += " OUTPUT " + " ".join(outputs)
    return (
        "# Rendered by splunk-knowledge-objects-setup.\n"
        f"[{args.auto_lookup_sourcetype}]\n"
        f"LOOKUP-{args.name} = {spec}\n"
    )


def render_eventtypes(args: argparse.Namespace) -> str:
    if args.object_kind != "eventtype":
        return "# No eventtype requested.\n"
    return (
        "# Rendered by splunk-knowledge-objects-setup.\n"
        f"[{args.name}]\nsearch = {args.eventtype_search}\n"
    )


def render_tags(args: argparse.Namespace) -> str:
    tags = csv_list(args.tags)
    if args.object_kind != "tag" or not tags:
        return "# No tags requested.\n"
    lines = [f"[eventtype={args.name}]"]
    lines.extend(f"{tag} = enabled" for tag in tags)
    lines.append("")
    return "# Rendered by splunk-knowledge-objects-setup.\n" + "\n".join(lines)


def render_csv_stub(args: argparse.Namespace) -> str:
    if args.object_kind != "lookup" or args.lookup_type != "csv":
        return ""
    headers = csv_list(args.csv_headers) or csv_list(args.fields_list)
    if not headers:
        headers = ["key", "value"]
    return ",".join(headers) + "\n"


def endpoint_for(kind: str) -> str:
    return {
        "savedsearch": "saved/searches",
        "macro": "configs/conf-macros",
        "lookup": "data/transforms/lookups",
        "eventtype": "saved/eventtypes",
        "tag": "configs/conf-tags",
    }[kind]


def render_acl_plan(args: argparse.Namespace) -> str:
    return json.dumps(
        {
            "app_name": args.app_name,
            "object_kind": args.object_kind,
            "name": args.name,
            "endpoint": endpoint_for(args.object_kind),
            "sharing": args.sharing,
            "owner": args.owner,
            "read_roles": csv_list(args.read_roles) or ["*"],
            "write_roles": csv_list(args.write_roles),
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Knowledge Object Rendered Assets

Object kind: `{args.object_kind}`
Name: `{args.name}`
App: `{args.app_name}`
Sharing: `{args.sharing}` (owner `{args.owner}`)

Files map to the conf the object lives in:

- savedsearch -> `savedsearches.conf`
- macro -> `macros.conf`
- lookup -> `transforms.conf` (+ optional `props.conf` automatic lookup, `lookup-stub.csv`)
- eventtype -> `eventtypes.conf`
- tag -> `tags.conf`
- `acl-plan.json` -> sharing/ownership applied to the object's `/acl` endpoint

For CSV lookups, place `lookup-stub.csv` (renamed to your filename) in the app's
`lookups/` directory or upload it through the lookup editor; the apply step
writes the lookup definition via REST. Global sharing requires
`--accept-global-sharing` at apply time.
"""


def render(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "knowledge-objects"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "object_kind": args.object_kind,
                    "name": args.name,
                    "app_name": args.app_name,
                    "sharing": args.sharing,
                    "owner": args.owner,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "savedsearches.conf": render_savedsearches(args),
            "macros.conf": render_macros(args),
            "transforms.conf": render_transforms(args),
            "props.conf": render_props(args),
            "eventtypes.conf": render_eventtypes(args),
            "tags.conf": render_tags(args),
            "acl-plan.json": render_acl_plan(args),
        }
        csv_stub = render_csv_stub(args)
        if csv_stub:
            files["lookup-stub.csv"] = csv_stub
        for rel, content in files.items():
            write_file(render_dir / rel, content)
            assets.append(rel)
    return {
        "target": "knowledge-objects",
        "object_kind": args.object_kind,
        "name": args.name,
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
        print(f"Would render knowledge object assets under {payload['render_dir']}")
    else:
        print(f"Rendered knowledge object assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
