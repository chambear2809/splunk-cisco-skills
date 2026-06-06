#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Microsoft Windows (Splunk_TA_windows) assets.

Offline and render-first: this engine never touches a Splunk instance or a
Windows host. It emits an inputs.local.conf overlay, a placement/CIM plan, and
validation SPL grounded in the real Splunk_TA_windows package model.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-windows-ta-rendered"

APP_NAME = "Splunk_TA_windows"
SPLUNKBASE_ID = "742"
LATEST_VERIFIED_VERSION = "10.0.1"

# WinEventLog channels shipped by Splunk_TA_windows default/inputs.conf, with
# the source type the add-on assigns and the CIM data model it maps to.
WINEVENTLOG_CHANNELS: list[dict[str, str]] = [
    {"channel": "Security", "sourcetype": "WinEventLog:Security", "cim": "Authentication, Change"},
    {"channel": "System", "sourcetype": "WinEventLog:System", "cim": "Change, Inventory"},
    {"channel": "Application", "sourcetype": "WinEventLog:Application", "cim": "Change"},
    {
        "channel": "Microsoft-Windows-Windows Defender/Operational",
        "sourcetype": "WinEventLog:Microsoft-Windows-Windows Defender/Operational",
        "cim": "Malware",
    },
    {
        "channel": "Microsoft-Windows-PowerShell/Operational",
        "sourcetype": "WinEventLog:Microsoft-Windows-PowerShell/Operational",
        "cim": "Endpoint",
    },
    {
        "channel": "Microsoft-Windows-TaskScheduler/Operational",
        "sourcetype": "WinEventLog:Microsoft-Windows-TaskScheduler/Operational",
        "cim": "Change",
    },
]

# Perfmon stanzas shipped by the add-on. Source types are Perfmon:<name>.
PERFMON_OBJECTS: list[dict[str, str]] = [
    {"object": "CPU", "sourcetype": "Perfmon:CPU"},
    {"object": "Memory", "sourcetype": "Perfmon:Memory"},
    {"object": "LogicalDisk", "sourcetype": "Perfmon:LogicalDisk"},
    {"object": "PhysicalDisk", "sourcetype": "Perfmon:PhysicalDisk"},
    {"object": "Network", "sourcetype": "Perfmon:Network"},
    {"object": "System", "sourcetype": "Perfmon:System"},
]

# WinHostMon stanzas shipped by the add-on (Endpoint / Inventory CIM coverage).
WINHOSTMON_TYPES = ["Computer", "Process", "Service", "OperatingSystem", "Disk", "NetworkAdapter"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_windows assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--event-index", default="wineventlog", help="Index for WinEventLog/WinHostMon events.")
    parser.add_argument("--perfmon-index", default="perfmon", help="Index for Perfmon events.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(event_index: str, perfmon_index: str) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into %SPLUNK_HOME%\\etc\\apps\\{APP_NAME}\\local\\inputs.conf",
        "# on Windows Universal Forwarders. Stanza names match the add-on default model.",
        "# Enable inputs with local files, never the Splunk Web setup page.",
        "",
    ]
    for entry in WINEVENTLOG_CHANNELS:
        lines += [
            f"[WinEventLog://{entry['channel']}]",
            "disabled = 0",
            "current_only = 0",
            "checkpointInterval = 5",
            "# renderXml = true   # uncomment to collect XmlWinEventLog:* instead",
            f"index = {event_index}",
            "",
        ]
    for obj in PERFMON_OBJECTS:
        lines += [
            f"[perfmon://{obj['object']}]",
            "disabled = 0",
            "interval = 60",
            f"index = {perfmon_index}",
            "",
        ]
    for host_type in WINHOSTMON_TYPES:
        lines += [
            f"[WinHostMon://{host_type}]",
            "disabled = 0",
            "interval = 600",
            f"index = {event_index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_install_commands(event_index: str, perfmon_index: str) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review before running. No secrets are embedded in this file.",
        f"# {APP_NAME} (Splunkbase {SPLUNKBASE_ID}) install + index + forwarder rollout.",
        "",
        "# 1. Install the add-on on the search tier (and indexers for parsing).",
        f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}",
        "",
        "# 2. Create the event and Perfmon indexes through the Splunk control plane.",
        f"bash skills/splunk-windows-ta-setup/scripts/setup.sh --create-index --event-index {event_index} --perfmon-index {perfmon_index}",
        "",
        "# 3. Roll the forwarder app out to Windows hosts through Agent Management.",
        f"bash skills/splunk-agent-management-setup/scripts/setup.sh --mode agent-manager --deployment-app-name {APP_NAME}",
        "",
        "# 4. Score post-ingest CIM/data readiness after data starts flowing.",
        "bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack windows_security",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_validation_spl(event_index: str, perfmon_index: str) -> str:
    return f"""# {APP_NAME} validation searches

index={event_index} sourcetype IN ("WinEventLog:Security","WinEventLog:System","WinEventLog:Application")
| stats count min(_time) as first_seen max(_time) as last_seen dc(host) as hosts by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={perfmon_index} sourcetype IN ("Perfmon:CPU","Perfmon:Memory","Perfmon:LogicalDisk","Perfmon:Network")
| stats count dc(host) as hosts by sourcetype

| datamodel Authentication Authentication search
| search tag=authentication sourcetype="WinEventLog:Security"
| stats count by action

index=_internal source=*splunkd.log* ({APP_NAME} OR WinEventLog OR perfmon OR "permission denied")
| stats count values(log_level) as levels by host
"""


def render_plan_md(event_index: str, perfmon_index: str) -> str:
    we_rows = "\n".join(
        f"| `WinEventLog://{e['channel']}` | `{e['sourcetype']}` | {e['cim']} |" for e in WINEVENTLOG_CHANNELS
    )
    pf_rows = "\n".join(f"| `perfmon://{p['object']}` | `{p['sourcetype']}` | Performance |" for p in PERFMON_OBJECTS)
    hm_rows = "\n".join(f"| `WinHostMon://{t}` | `WinHostMon` | Endpoint, Inventory |" for t in WINHOSTMON_TYPES)
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{event_index}`
Perfmon index: `{perfmon_index}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required (search-time knowledge objects, CIM) |
| `indexer` | supported (index-time parsing) |
| `heavy-forwarder` | supported (when an HF collects Windows data) |
| `universal-forwarder` | required on Windows hosts for inputs |
| `external-collector` | none |

## Inputs, Source Types, And CIM

| Input stanza | Source type | CIM data models |
| --- | --- | --- |
{we_rows}
{pf_rows}
{hm_rows}

## Guardrails

- Inputs run on Windows Universal Forwarders. Enable with local files, not the
  Splunk Web setup page.
- Keep the add-on visible off on search heads (the package ships
  `[ui] is_visible = false`).
- Copy only reviewed stanzas into `local/inputs.conf`; do not copy the entire
  default file because broad local overrides survive upgrades.
- Create the Perfmon metrics index before routing Perfmon data to it.
- Sysmon is collected by a separate add-on (Splunk Add-on for Sysmon); it is
  not bundled in `{APP_NAME}`.

## Sources

- https://splunkbase.splunk.com/app/{SPLUNKBASE_ID}
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/microsoft-windows
"""


def render_assets(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-windows-ta"
    files = [
        "metadata.json",
        "profile-plan.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}

    metadata = {
        "app_name": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_VERSION,
        "event_index": args.event_index,
        "perfmon_index": args.perfmon_index,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args.event_index, args.perfmon_index))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args.event_index, args.perfmon_index))
    write_file(
        profile_dir / "install-commands.sh",
        render_install_commands(args.event_index, args.perfmon_index),
        executable=True,
    )
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args.event_index, args.perfmon_index))
    return {
        "ok": True,
        "dry_run": False,
        "output_dir": str(profile_dir),
        "files": sorted(path.name for path in profile_dir.iterdir() if path.is_file()),
    }


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if "files" in payload:
        print(f"App: {APP_NAME} (Splunkbase {SPLUNKBASE_ID})")
        print(f"Output: {payload['output_dir']}")
        print("Files: " + ", ".join(payload["files"]))
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "app_name": APP_NAME,
                "splunkbase_id": SPLUNKBASE_ID,
                "wineventlog_channels": [e["channel"] for e in WINEVENTLOG_CHANNELS],
                "perfmon_objects": [p["object"] for p in PERFMON_OBJECTS],
                "winhostmon_types": WINHOSTMON_TYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
