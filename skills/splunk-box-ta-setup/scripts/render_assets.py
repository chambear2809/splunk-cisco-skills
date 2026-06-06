#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Box assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-box-ta-rendered"

APP_NAME = "Splunk_TA_box"
SPLUNKBASE_ID = "2679"
LATEST_VERIFIED_VERSION = "4.0.0"
INPUTS = ["historical", "live", "file"]
SOURCETYPES = [
    "box:events",
    "box:users",
    "box:groups",
    "box:folder",
    "box:file",
    "box:fileComment",
    "box:fileTask",
    "box:folderCollaboration",
    "box:filecontent",
    "box:filecontent:csv",
    "box:filecontent:json",
    "box:filecontent:xml",
]
REST_HANDLERS = [
    "Splunk_TA_box_account",
    "Splunk_TA_box_oauth",
    "Splunk_TA_box_box_service",
    "Splunk_TA_box_box_live_monitoring_service",
    "Splunk_TA_box_box_file_ingestion_service",
    "Splunk_TA_box_settings",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_box assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="box", help="Target Box event index.")
    parser.add_argument("--account-name", default="box_prod", help="Box account stanza name.")
    parser.add_argument("--inputs", default=",".join(INPUTS), help="Comma-separated inputs: historical,live,file.")
    parser.add_argument("--rest-endpoint", default="api.box.com", help="Box API endpoint host.")
    parser.add_argument("--file-or-folder-id", default="0", help="Starter folder ID for file ingestion templates.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_inputs(raw: str) -> list[str]:
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not values:
        raise SystemExit(f"ERROR: at least one input selector is required. Choose from {', '.join(INPUTS)}.")
    unknown = [item for item in values if item not in INPUTS]
    if unknown:
        raise SystemExit(f"ERROR: unknown input(s): {', '.join(unknown)}. Choose from {', '.join(INPUTS)}.")
    return values


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, selected: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.",
        f"# Account '{args.account_name}' is created through the add-on account handler.",
        "",
    ]
    if "historical" in selected:
        lines += [
            "[box_service://box_historical]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"rest_endpoint = {args.rest_endpoint}",
            "input_name = box_historical",
            "collect_events = 1",
            "collect_users = 1",
            "collect_groups = 1",
            "interval = 300",
            f"index = {args.index}",
            "",
        ]
    if "live" in selected:
        lines += [
            "[box_live_monitoring_service://box_live]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"rest_endpoint = {args.rest_endpoint}",
            "input_name = box_live",
            "interval = 60",
            f"index = {args.index}",
            "",
        ]
    if "file" in selected:
        lines += [
            "[box_file_ingestion_service://box_file]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"rest_endpoint = {args.rest_endpoint}",
            f"file_or_folder_id = {args.file_or_folder_id}",
            "include_subfolders = 0",
            "interval = 3600",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Account Runbook

Create account `{args.account_name}` with the Box add-on OAuth workflow or
`/servicesNS/nobody/{APP_NAME}/Splunk_TA_box_account`.

Write any Box client secret or private-key material to a protected local file
first:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/box_secret
```

Then paste or upload the value into the Splunk add-on account flow so Splunk
stores it encrypted in `storage/passwords`. Do not put secret values in argv,
environment variables, or rendered files.

REST endpoint: `{args.rest_endpoint}`
REST handlers verified in the package: {', '.join(REST_HANDLERS)}.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}
bash skills/splunk-box-ta-setup/scripts/setup.sh --create-index --index {args.index}

# Configure account {args.account_name}, then enable the rendered inputs.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack box
"""


def render_validation_spl(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{item}"' for item in SOURCETYPES)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=box:events
| stats count dc(created_by.login) as users values(event_type) as event_types by source

index=_internal source=*splunkd.log* ({APP_NAME} OR box_service OR box_live_monitoring_service OR box_file_ingestion_service)
| stats count values(log_level) as levels by sourcetype component
"""


def render_plan_md(args: argparse.Namespace, selected: list[str]) -> str:
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`
Rendered inputs: `{', '.join(selected)}`
REST endpoint: `{args.rest_endpoint}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required for setup and knowledge objects |
| `heavy-forwarder` | supported for API collection |
| `indexer` | none |
| `universal-forwarder` | none |
| `external-collector` | none |

## Package-Backed Source Types

`{', '.join(SOURCETYPES)}`

## Guardrails

- Store Box OAuth material only in the add-on account.
- Run each Box enterprise collection path on one collection node.
- Review file-ingestion folder scope before enabling content collection.
"""


def render_assets(args: argparse.Namespace, selected: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-box-ta"
    files = ["account-setup.md", "inputs.local.conf.template", "install-commands.sh", "metadata.json", "profile-plan.md", "validation-searches.spl"]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}
    metadata = {
        "app_name": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_VERSION,
        "index": args.index,
        "account_name": args.account_name,
        "inputs": selected,
        "rest_endpoint": args.rest_endpoint,
        "rest_handlers": REST_HANDLERS,
        "source_package": f"splunk-ta/_unpacked/{APP_NAME}-{LATEST_VERIFIED_VERSION}/{APP_NAME}",
        "sourcetypes": SOURCETYPES,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, selected))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, selected))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args))
    return {"ok": True, "dry_run": False, "output_dir": str(profile_dir), "files": sorted(path.name for path in profile_dir.iterdir() if path.is_file())}


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif "files" in payload:
        print(f"App: {APP_NAME} (Splunkbase {SPLUNKBASE_ID})")
        print(f"Output: {payload['output_dir']}")
        print("Files: " + ", ".join(payload["files"]))
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    selected = parse_inputs(args.inputs)
    if args.phase == "list":
        emit({"ok": True, "app_name": APP_NAME, "splunkbase_id": SPLUNKBASE_ID, "inputs": INPUTS, "sourcetypes": SOURCETYPES}, args.json)
        return 0
    emit(render_assets(args, selected), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
