#!/usr/bin/env python3
"""Render Splunk Platform Dashboard Studio (version=2) dashboards from a panel spec."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import stat
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

VIZ_TYPE_MAP = {
    "table": "splunk.table",
    "single": "splunk.singlevalue",
    "line": "splunk.line",
    "area": "splunk.area",
    "column": "splunk.column",
    "bar": "splunk.bar",
    "pie": "splunk.pie",
    "markdown": "splunk.markdown",
}

GENERATED_FILES = {
    "README.md",
    "metadata.json",
    "dashboard.json",
    "dashboard.xml",
    "apply.sh",
    "status.sh",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk Dashboard Studio assets.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--splunk-home", default="/opt/splunk")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--dashboard-id", default="")
    parser.add_argument("--app", default="search")
    parser.add_argument("--owner", default="nobody")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--layout", choices=("grid", "absolute"), default="grid")
    parser.add_argument("--default-earliest", default="-24h@h")
    parser.add_argument("--default-latest", default="now")
    parser.add_argument("--panel", action="append", default=[], help="Title::type::content (repeatable)")
    parser.add_argument("--panels-file", default="")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def die(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def shell_quote(value: object) -> str:
    return shlex.quote(str(value))


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def make_script(body: str) -> str:
    return "#!/usr/bin/env bash\nset -euo pipefail\n\n" + body.lstrip()


def clean_render_dir(render_dir: Path) -> None:
    for rel in GENERATED_FILES:
        candidate = render_dir / rel
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "dashboard"


def load_panels(args: argparse.Namespace) -> list[dict]:
    panels: list[dict] = []
    if args.panels_file:
        path = Path(args.panels_file).expanduser()
        if not path.is_file():
            die(f"--panels-file not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            die(f"--panels-file is not valid JSON: {exc}")
        if not isinstance(data, list):
            die("--panels-file must contain a JSON list of panel objects.")
        for index, entry in enumerate(data):
            if not isinstance(entry, dict):
                die(f"--panels-file entry {index} must be an object.")
            ptype = str(entry.get("type", "table"))
            content = entry.get("markdown") if ptype == "markdown" else entry.get("query", "")
            panels.append(
                {"title": str(entry.get("title", f"Panel {index + 1}")), "type": ptype, "content": str(content or "")}
            )
    for raw in args.panel:
        parts = raw.split("::", 2)
        if len(parts) != 3:
            die(f"--panel must be 'Title::type::content': {raw!r}")
        panels.append({"title": parts[0].strip(), "type": parts[1].strip(), "content": parts[2]})
    if not panels:
        panels.append(
            {"title": "Event count", "type": "single", "content": "index=_internal | stats count"}
        )
    return panels


def validate(args: argparse.Namespace, panels: list[dict]) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", args.app or ""):
        die("--app must be a valid app namespace.")
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", args.owner or ""):
        die("--owner must be a valid Splunk username or 'nobody'.")
    if "\n" in (args.splunk_home or "") or "\r" in (args.splunk_home or ""):
        die("--splunk-home must not contain newlines.")
    if args.dashboard_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.dashboard_id):
        die("--dashboard-id must be a valid view name (letters, numbers, underscore, hyphen).")
    for index, panel in enumerate(panels):
        if panel["type"] not in VIZ_TYPE_MAP:
            die(
                f"Panel {index + 1} has unknown type {panel['type']!r}. Valid: "
                + ", ".join(sorted(VIZ_TYPE_MAP))
            )
        if panel["type"] != "markdown" and not panel["content"].strip():
            die(f"Panel {index + 1} ({panel['title']}) needs a non-empty SPL query.")
        if "]]>" in panel["content"]:
            die(f"Panel {index + 1} content must not contain ']]>' (breaks the XML CDATA).")


def build_definition(args: argparse.Namespace, panels: list[dict]) -> dict:
    data_sources: dict = {}
    visualizations: dict = {}
    structure: list[dict] = []
    columns = 2
    cell_w = 600
    cell_h = 316
    gutter = 20
    max_y = 0
    for index, panel in enumerate(panels):
        viz_id = f"viz_{index + 1}"
        viz_type = VIZ_TYPE_MAP[panel["type"]]
        col = index % columns
        row = index // columns
        x = col * (cell_w + gutter)
        y = row * (cell_h + gutter)
        max_y = max(max_y, y + cell_h)
        if panel["type"] == "markdown":
            visualizations[viz_id] = {
                "type": viz_type,
                "options": {"markdown": panel["content"]},
            }
        else:
            ds_id = f"ds_{index + 1}"
            data_sources[ds_id] = {
                "type": "ds.search",
                "options": {"query": panel["content"]},
                "name": panel["title"],
            }
            visualizations[viz_id] = {
                "type": viz_type,
                "title": panel["title"],
                "dataSources": {"primary": ds_id},
            }
        structure.append(
            {
                "item": viz_id,
                "type": "block",
                "position": {"x": x, "y": y, "w": cell_w, "h": cell_h},
            }
        )

    definition = {
        "title": args.title,
        "description": args.description,
        "dataSources": data_sources,
        "visualizations": visualizations,
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
                    "options": {"width": 1240, "height": max(max_y, cell_h)},
                    "structure": structure,
                }
            },
            "tabs": {"items": [{"label": "New tab", "layoutId": "layout_1"}]},
        },
    }
    return definition


def hidden_elements_meta() -> str:
    return json.dumps(
        {
            "hideEdit": False,
            "hideOpenInSearch": False,
            "hideExport": False,
        },
        indent=2,
    )


def build_xml(args: argparse.Namespace, definition: dict) -> str:
    definition_json = json.dumps(definition, indent=2)
    label = xml_escape(args.title)
    description = xml_escape(args.description)
    description_block = f"  <description>{description}</description>\n" if args.description else ""
    return (
        f'<dashboard version="2" theme="{args.theme}">\n'
        f"  <label>{label}</label>\n"
        f"{description_block}"
        "  <definition><![CDATA[\n"
        f"{definition_json}\n"
        "  ]]></definition>\n"
        '  <meta type="hiddenElements"><![CDATA[\n'
        f"{hidden_elements_meta()}\n"
        "  ]]></meta>\n"
        "</dashboard>\n"
    )


def render_apply(args: argparse.Namespace, dashboard_id: str) -> str:
    owner = shell_quote(args.owner)
    app = shell_quote(args.app)
    did = shell_quote(dashboard_id)
    return make_script(
        f"""owner={owner}
app={app}
dashboard_id={did}
mgmt_uri="${{SPLUNK_MGMT_URI:-https://localhost:8089}}"
base="${{mgmt_uri}}/servicesNS/${{owner}}/${{app}}/data/ui/views"

# Authenticate without putting secrets on the command line:
#   SPLUNK_CURL_CONFIG=/path/to/curl.cfg  # chmod 600; e.g. a line: user = "admin:<password>"
# or SPLUNK_USERNAME=<user>               # curl prompts for the password interactively
auth=()
if [[ -n "${{SPLUNK_CURL_CONFIG:-}}" ]]; then
  auth=(--config "${{SPLUNK_CURL_CONFIG}}")
elif [[ -n "${{SPLUNK_USERNAME:-}}" ]]; then
  auth=(--user "${{SPLUNK_USERNAME}}")
else
  echo "Set SPLUNK_CURL_CONFIG=/path/to/curl.cfg (chmod 600) or SPLUNK_USERNAME=<user> first." >&2
  exit 1
fi

echo "Publishing Dashboard Studio view '${{dashboard_id}}' to app '${{app}}' (owner ${{owner}})."
read -r -p "Type APPLY to continue: " confirm
[[ "${{confirm}}" == "APPLY" ]] || {{ echo "Aborted."; exit 1; }}

# eai:data is read from dashboard.xml; the definition is never passed on the command line.
if curl -ks -f "${{auth[@]}}" "${{base}}/${{dashboard_id}}" -o /dev/null; then
  echo "View exists; updating definition."
  curl -ks -f "${{auth[@]}}" "${{base}}/${{dashboard_id}}" \\
    --data-urlencode "eai:data@dashboard.xml" -o /dev/null
else
  echo "Creating new view."
  curl -ks -f "${{auth[@]}}" "${{base}}" \\
    --data-urlencode "name=${{dashboard_id}}" \\
    --data-urlencode "eai:data@dashboard.xml" -o /dev/null
fi
echo "Done. Open Apps > ${{app}} to view '${{dashboard_id}}'."
"""
    )


def render_status(args: argparse.Namespace) -> str:
    splunk = shell_quote(f"{args.splunk_home}/bin/splunk")
    app = shell_quote(args.app)
    return make_script(
        f"""splunk={splunk}
app={app}
echo "== Dashboard Studio (version=2) views in app ${{app}} =="
"${{splunk}}" search "| rest splunk_server=local /servicesNS/-/${{app}}/data/ui/views | search eai:data=\\"*version=\\\\\\"2\\\\\\"*\\" | table title eai:acl.owner eai:acl.sharing" -maxout 0 \\
  || echo "Could not list views; verify app and REST access."
"""
    )


def render_readme(args: argparse.Namespace, dashboard_id: str, panels: list[dict]) -> str:
    rows = "\n".join(f"- `{p['title']}` ({p['type']})" for p in panels)
    return f"""# Splunk Dashboard Studio Rendered Assets

Title: `{args.title}`
View id: `{dashboard_id}`
App: `{args.app}` (owner `{args.owner}`)
Theme: `{args.theme}` | Layout: `{args.layout}`

Panels:

{rows}

Files:

- `dashboard.json` — the Dashboard Studio version=2 definition
- `dashboard.xml` — the data/ui/views source XML wrapper (CDATA definition)
- `apply.sh` — create/update the view via the data/ui/views REST endpoint (gated)
- `status.sh` — list version=2 views in the app

Review `dashboard.json` before publishing. On Splunk Cloud, publishing uses the
search-tier REST API (ensure the search-api allow list permits your IP).
"""


def render(args: argparse.Namespace, panels: list[dict]) -> dict:
    dashboard_id = args.dashboard_id or slugify(args.title)
    output_dir = Path(args.output_dir).expanduser().resolve()
    render_dir = output_dir / "dashboard-studio"
    definition = build_definition(args, panels)
    assets: list[str] = []
    if not args.dry_run:
        clean_render_dir(render_dir)
        files = {
            "README.md": render_readme(args, dashboard_id, panels),
            "metadata.json": json.dumps(
                {
                    "title": args.title,
                    "dashboard_id": dashboard_id,
                    "app": args.app,
                    "owner": args.owner,
                    "theme": args.theme,
                    "layout": args.layout,
                    "panels": [{"title": p["title"], "type": p["type"]} for p in panels],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            "dashboard.json": json.dumps(definition, indent=2) + "\n",
            "dashboard.xml": build_xml(args, definition),
            "apply.sh": render_apply(args, dashboard_id),
            "status.sh": render_status(args),
        }
        for rel, content in files.items():
            write_file(render_dir / rel, content, executable=rel.endswith(".sh"))
            assets.append(rel)
    return {
        "target": "dashboard-studio",
        "title": args.title,
        "dashboard_id": dashboard_id,
        "app": args.app,
        "panel_count": len(panels),
        "output_dir": str(output_dir),
        "render_dir": str(render_dir),
        "assets": assets,
        "dry_run": args.dry_run,
        "commands": {
            "apply": [["./apply.sh"]],
            "status": [["./status.sh"]],
        },
    }


def main() -> int:
    args = parse_args()
    panels = load_panels(args)
    validate(args, panels)
    payload = render(args, panels)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif args.dry_run:
        print(f"Would render Dashboard Studio assets under {payload['render_dir']}")
    else:
        print(f"Rendered Dashboard Studio assets under {payload['render_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
