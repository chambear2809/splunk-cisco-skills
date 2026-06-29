#!/usr/bin/env python3
"""Render Splunk Platform Dashboard Studio assets (data/ui/views version 2 JSON + XML wrapper)."""

from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "dashboard.json",
    "view.xml",
}

VIZ_TYPES = {
    "splunk.singlevalue",
    "splunk.table",
    "splunk.line",
    "splunk.column",
    "splunk.bar",
    "splunk.area",
    "splunk.pie",
    "splunk.markergauge",
    "splunk.events",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Dashboard Studio assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--app-name", default="search")
    parser.add_argument("--dashboard-name", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--search", default="")
    parser.add_argument("--viz-type", choices=sorted(VIZ_TYPES), default="splunk.table")
    parser.add_argument("--datasource-name", default="Search_1")
    parser.add_argument("--layout", choices=("grid", "absolute", "freeform"), default="grid")
    parser.add_argument("--default-earliest", default="-24h@h")
    parser.add_argument("--default-latest", default="now")
    parser.add_argument("--definition-file", default="")
    parser.add_argument("--owner", default="nobody")
    parser.add_argument("--sharing", choices=("user", "app", "global"), default="app")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def no_newline(value: str, option: str) -> None:
    if "\n" in value or "\r" in value:
        die(f"{option} must not contain newlines.")


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


def xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def validate(args: argparse.Namespace) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app_name or ""):
        die("--app-name must contain only letters, numbers, underscore, dot, colon, or hyphen.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,253}", args.dashboard_name or ""):
        die("--dashboard-name must be a safe view id (letters, numbers, underscore, hyphen).")
    for value, option in ((args.title, "--title"), (args.description, "--description")):
        no_newline(value, option)
    if args.definition_file:
        path = Path(args.definition_file).expanduser()
        if not path.is_file():
            die(f"--definition-file not found: {args.definition_file}")
        try:
            definition = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            die(f"--definition-file is not valid JSON: {exc}")
        if not isinstance(definition, dict):
            die("--definition-file must contain a JSON object.")
        return definition
    if not args.search:
        die("Provide --search to build a dashboard, or --definition-file with a full Dashboard Studio JSON definition.")
    return build_definition(args)


def build_definition(args: argparse.Namespace) -> dict:
    title = args.title or args.dashboard_name
    viz_id = "viz_primary"
    ds_id = "ds_primary"
    layout_options = {"width": 1440, "height": 960} if args.layout == "absolute" else {}
    structure_item: dict = {
        "item": viz_id,
        "type": "block",
        "position": {"x": 0, "y": 0, "w": 1200, "h": 400},
    }
    return {
        "title": title,
        "description": args.description,
        "visualizations": {
            viz_id: {
                "type": args.viz_type,
                "dataSources": {"primary": ds_id},
                "options": {},
            }
        },
        "dataSources": {
            ds_id: {
                "type": "ds.search",
                "name": args.datasource_name,
                "options": {"query": args.search},
            }
        },
        "inputs": {
            "input_global_trp": {
                "type": "input.timerange",
                "title": "Time",
                "options": {
                    "token": "global_time",
                    "defaultValue": f"{args.default_earliest},{args.default_latest}",
                },
            }
        },
        "defaults": {
            "dataSources": {
                "ds.search": {
                    "options": {
                        "queryParameters": {
                            "earliest": "$global_time.earliest$",
                            "latest": "$global_time.latest$",
                        }
                    }
                }
            }
        },
        "layout": {
            "globalInputs": ["input_global_trp"],
            "layoutDefinitions": {
                "layout_1": {
                    "type": args.layout,
                    "options": layout_options,
                    "structure": [structure_item],
                }
            },
            "tabs": {"items": [{"label": "New tab", "layoutId": "layout_1"}]},
        },
    }


def render_view_xml(args: argparse.Namespace, definition: dict) -> str:
    definition_json = json.dumps(definition, indent=4, sort_keys=True)
    if "]]>" in definition_json:
        die("Dashboard definition must not contain ']]>' (CDATA terminator).")
    title = args.title or args.dashboard_name
    return (
        f'<dashboard version="2" theme="{args.theme}">\n'
        f"  <label>{xml_escape(title)}</label>\n"
        f"  <description>{xml_escape(args.description)}</description>\n"
        "  <definition><![CDATA[\n"
        f"{definition_json}\n"
        "  ]]></definition>\n"
        "</dashboard>\n"
    )


def render_readme(args: argparse.Namespace) -> str:
    return f"""# Splunk Dashboard Studio Rendered Assets

Dashboard: `{args.dashboard_name}`
App: `{args.app_name}`
Theme: `{args.theme}`
Layout: `{args.layout}`
Sharing: `{args.sharing}` (owner `{args.owner}`)

Files:

- `dashboard.json` - the Dashboard Studio (version 2) JSON definition
- `view.xml` - the `eai:data` XML wrapper posted to `data/ui/views`

Apply posts `name=<dashboard>` and `eai:data=<view.xml>` to
`/servicesNS/<owner>/<app>/data/ui/views`. Updating an existing dashboard
requires `--accept-overwrite`. This is Splunk Platform Dashboard Studio and is
distinct from the Splunk Observability Cloud dashboard builder.
"""


def render(args: argparse.Namespace, definition: dict) -> dict:
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "dashboard-studio"
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args),
            "metadata.json": json.dumps(
                {
                    "dashboard_name": args.dashboard_name,
                    "app_name": args.app_name,
                    "theme": args.theme,
                    "layout": args.layout,
                    "owner": args.owner,
                    "sharing": args.sharing,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "dashboard.json": json.dumps(definition, indent=2, sort_keys=True) + "\n",
            "view.xml": render_view_xml(args, definition),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content)
            assets.append(rel)
    return {
        "target": "dashboard-studio",
        "dashboard_name": args.dashboard_name,
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
    }


def main() -> int:
    args = parse_args()
    definition = validate(args)
    payload = render(args, definition)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render Dashboard Studio assets under {payload['render_dir']}")
    else:
        print(f"Rendered Dashboard Studio assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
