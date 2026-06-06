#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Salesforce assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-salesforce-ta-rendered"

APP_NAME = "Splunk_TA_salesforce"
SPLUNKBASE_ID = "3549"
LATEST_VERIFIED_VERSION = "6.0.2"
OBJECTS = ["user", "loginhistory", "account", "opportunity", "dashboard", "report", "contentversion"]
SOURCETYPES = [
    "sfdc:object",
    "sfdc:logfile",
    "sfdc:user",
    "sfdc:loginhistory",
    "sfdc:account",
    "sfdc:opportunity",
    "sfdc:dashboard",
    "sfdc:report",
    "sfdc:contentversion",
]
REST_HANDLERS = [
    "Splunk_TA_salesforce_account",
    "Splunk_TA_salesforce_oauth",
    "Splunk_TA_salesforce_sfdc_object",
    "Splunk_TA_salesforce_sfdc_event_log",
    "Splunk_TA_salesforce_settings",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_salesforce assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="salesforce", help="Target Salesforce event index.")
    parser.add_argument("--account-name", default="salesforce_prod", help="Salesforce account stanza name.")
    parser.add_argument("--objects", default=",".join(OBJECTS), help="Comma-separated Salesforce object input selectors.")
    parser.add_argument("--no-event-log", action="store_true", help="Do not render the sfdc_event_log input stanza.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_list(raw: str, allowed: list[str], label: str) -> list[str]:
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if not values:
        raise SystemExit(f"ERROR: at least one {label} is required. Choose from {', '.join(allowed)}.")
    unknown = [item for item in values if item not in allowed]
    if unknown:
        raise SystemExit(f"ERROR: unknown {label}: {', '.join(unknown)}. Choose from {', '.join(allowed)}.")
    return values


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, objects: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.",
        f"# Account '{args.account_name}' is created through the add-on account handler.",
        "",
    ]
    for object_name in objects:
        lines += [
            f"[sfdc_object://{object_name}]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"object = {object_name}",
            "fields = *",
            "order_by = SystemModstamp",
            "interval = 300",
            f"index = {args.index}",
            "",
        ]
    if not args.no_event_log:
        lines += [
            "[sfdc_event_log://event_log]",
            "disabled = 0",
            f"account = {args.account_name}",
            "monitoring_interval = daily",
            "start_date = 2026-01-01T00:00:00Z",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Account Runbook

Create account `{args.account_name}` in the add-on Configuration tab or through
`/servicesNS/nobody/{APP_NAME}/Splunk_TA_salesforce_account`.

Use a Salesforce connected app or OAuth account with the minimum API and event
log permissions required for the selected objects. Put any client secret,
refresh token, or private key material into a protected local file first:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/salesforce_secret
```

Then paste or upload the value into the Splunk add-on account flow so Splunk
stores it encrypted in `storage/passwords`. Do not add secret values to
`inputs.conf`, rendered assets, environment variables, or command-line flags.

REST handlers verified in the package: {', '.join(REST_HANDLERS)}.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}
bash skills/splunk-salesforce-ta-setup/scripts/setup.sh --create-index --index {args.index}

# Configure account {args.account_name}, then enable the rendered inputs.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack salesforce
"""


def render_validation_spl(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{item}"' for item in SOURCETYPES)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype IN ("sfdc:loginhistory","sfdc:logfile")
| stats count dc(USER_ID) as users values(EVENT_TYPE) as event_types by LOGIN_STATUS CLIENT_IP

index=_internal source=*splunkd.log* ({APP_NAME} OR sfdc_object OR sfdc_event_log)
| stats count values(log_level) as levels by sourcetype component
"""


def render_plan_md(args: argparse.Namespace, objects: list[str]) -> str:
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`
Objects: `{', '.join(objects)}`
Event log input: `{'no' if args.no_event_log else 'yes'}`

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

- Store Salesforce secrets only in the add-on account.
- Run each org/input set on one collection node.
- Do not match generic `_json`, `httpevent`, or `sfdc` lookalike data without the exact package source type.
"""


def render_assets(args: argparse.Namespace, objects: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-salesforce-ta"
    files = ["account-setup.md", "inputs.local.conf.template", "install-commands.sh", "metadata.json", "profile-plan.md", "validation-searches.spl"]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}
    metadata = {
        "app_name": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_VERSION,
        "index": args.index,
        "account_name": args.account_name,
        "objects": objects,
        "include_event_log": not args.no_event_log,
        "rest_handlers": REST_HANDLERS,
        "source_package": f"splunk-ta/_unpacked/{APP_NAME}-{LATEST_VERIFIED_VERSION}/{APP_NAME}",
        "sourcetypes": SOURCETYPES,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, objects))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, objects))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args))
    return {"ok": True, "dry_run": False, "output_dir": str(profile_dir), "files": sorted(path.name for path in profile_dir.iterdir() if path.is_file())}


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
    objects = parse_list(args.objects, OBJECTS, "object selector")
    if args.phase == "list":
        emit({"ok": True, "app_name": APP_NAME, "splunkbase_id": SPLUNKBASE_ID, "objects": OBJECTS, "sourcetypes": SOURCETYPES}, args.json)
        return 0
    emit(render_assets(args, objects), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
