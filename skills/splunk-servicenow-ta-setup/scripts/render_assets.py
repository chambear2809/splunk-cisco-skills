#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for ServiceNow (Splunk_TA_snow) assets.

Offline and render-first: emits per-table snow:// inputs.conf stanzas, an
account-setup runbook (basic auth or OAuth), a placement/CIM plan, and
validation SPL grounded in the real Splunk_TA_snow package model.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-servicenow-ta-rendered"

APP_NAME = "Splunk_TA_snow"
SPLUNKBASE_ID = "1928"
LATEST_VERIFIED_VERSION = "10.0.1"

# Common ServiceNow tables. Each snow://<table> input emits sourcetype snow:<table>.
TABLES: dict[str, dict[str, str]] = {
    "incident": {"sourcetype": "snow:incident", "desc": "Incident records.", "timefield": "sys_updated_on"},
    "change_request": {"sourcetype": "snow:change_request", "desc": "Change requests.", "timefield": "sys_updated_on"},
    "problem": {"sourcetype": "snow:problem", "desc": "Problem records.", "timefield": "sys_updated_on"},
    "em_event": {"sourcetype": "snow:em_event", "desc": "Event Management events.", "timefield": "sys_updated_on"},
    "sys_user": {"sourcetype": "snow:sys_user", "desc": "Users (identity).", "timefield": "sys_updated_on"},
    "sys_user_group": {"sourcetype": "snow:sys_user_group", "desc": "User groups.", "timefield": "sys_updated_on"},
    "cmdb_ci": {"sourcetype": "snow:cmdb_ci", "desc": "Configuration items (CMDB).", "timefield": "sys_updated_on"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_snow assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="snow", help="Target event index for ServiceNow data.")
    parser.add_argument("--account-name", default="snow_prod", help="Account stanza name referenced by inputs.")
    parser.add_argument(
        "--tables",
        default="incident,change_request,problem,em_event",
        help="Comma-separated tables to render (see --phase list for the catalog).",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def selected_tables(raw: str) -> list[str]:
    tables = [t.strip() for t in raw.split(",") if t.strip()]
    unknown = [t for t in tables if t not in TABLES]
    if unknown:
        raise SystemExit(f"ERROR: unknown table(s): {', '.join(unknown)}. Choose from {', '.join(TABLES)}.")
    return tables or list(TABLES)


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, tables: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.",
        f"# Reference the configured account '{args.account_name}' (see account-setup.md).",
        "",
    ]
    for table in tables:
        meta = TABLES[table]
        lines += [
            f"[snow://{table}]",
            "disabled = 0",
            f"account = {args.account_name}",
            f"table = {table}",
            f"timefield = {meta['timefield']}",
            "id_field = sys_id",
            "interval = 300",
            "# since_when = 2024-01-01 00:00:00   # optional backfill start (default ~1 week ago)",
            f"sourcetype = {meta['sourcetype']}",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# {APP_NAME} Account Setup Runbook

The ServiceNow add-on connects to a ServiceNow instance REST API. Configure an
account named `{args.account_name}` in the add-on Configuration tab. Two
supported `auth_type` values:

## Option A - Basic auth

1. Create a dedicated ServiceNow integration user with read access (`rest_api_explorer`
   / table read ACLs) to the tables you collect.
2. Write the password to a local protected file (never paste it in chat):

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/snow_password
```

3. In the add-on Configuration tab, create account `{args.account_name}` with
   `url` (`https://yourinstance.service-now.com`), `username`, and the password
   value.

## Option B - OAuth

1. In ServiceNow, register an OAuth application (Application Registry) and note
   the client ID and client secret.
2. Write the client secret to a local file:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/snow_client_secret
```

3. In the add-on Configuration tab, create account `{args.account_name}` with
   `auth_type = OAuth`, `url`, `client_id`, and the client secret value; the
   add-on stores access/refresh tokens encrypted.

The account REST endpoint is
`/servicesNS/nobody/{APP_NAME}/splunk_ta_snow_account`; the OAuth endpoint is
`splunk_ta_snow_oauth`. Secrets are stored encrypted in `storage/passwords`;
this skill never transmits them.

## Notes

- Use a read-only integration user scoped to the tables you collect.
- The add-on checkpoints on `timefield` (default `sys_updated_on`) and dedups
  on `id_field` (default `sys_id`).
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
# {APP_NAME} (Splunkbase {SPLUNKBASE_ID}) install + index.

# 1. Install the add-on on the search tier (and any heavy-forwarder collector).
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}

# 2. Create the ServiceNow event index.
bash skills/splunk-servicenow-ta-setup/scripts/setup.sh --create-index --index {args.index}

# 3. Configure the account (see account-setup.md), then enable the rendered inputs.
"""


def render_validation_spl(args: argparse.Namespace, tables: list[str]) -> str:
    sourcetypes = ",".join(f'"{TABLES[t]["sourcetype"]}"' for t in tables)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=snow:incident
| stats count by priority state

index=_internal source=*splunkd.log* ({APP_NAME} OR snow OR ServiceNow)
| stats count values(log_level) as levels by sourcetype
"""


def render_plan_md(args: argparse.Namespace, tables: list[str]) -> str:
    rows = "\n".join(f"| `snow://{t}` | `{TABLES[t]['sourcetype']}` | {TABLES[t]['desc']} |" for t in tables)
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required (setup, auth, knowledge objects) |
| `heavy-forwarder` | supported (preferred data-collection node) |
| `indexer` | none |
| `universal-forwarder` | none |
| `external-collector` | none |

Run a given table input on a single node to avoid duplicate collection.

## Inputs, Source Types

| Input | Source type | Description |
| --- | --- | --- |
{rows}

## Account Model

Configure an `account` (Basic auth or OAuth) in the add-on Configuration tab
before enabling inputs. See `account-setup.md`.

## Guardrails

- Run each `snow://<table>` input on a single node (search tier or one heavy
  forwarder) to avoid duplicate ingestion.
- Use a read-only ServiceNow integration user scoped to the collected tables.
- The add-on checkpoints on `timefield` (default `sys_updated_on`) and dedups on
  `id_field` (default `sys_id`); keep those defaults unless the table differs.
- Store the ServiceNow password / OAuth secret only via the add-on account
  (encrypted); never in conf files or argv.
- ServiceNow incident/change data is commonly consumed by Splunk ITSI; hand off
  service/KPI modeling to `splunk-itsi-config`.

## Sources

- https://splunkbase.splunk.com/app/{SPLUNKBASE_ID}
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/servicenow
"""


def render_assets(args: argparse.Namespace, tables: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-servicenow-ta"
    files = [
        "account-setup.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": files}

    metadata = {
        "app_name": APP_NAME,
        "splunkbase_id": SPLUNKBASE_ID,
        "latest_verified_version": LATEST_VERIFIED_VERSION,
        "index": args.index,
        "account_name": args.account_name,
        "tables": tables,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, tables))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, tables))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args, tables))
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
    tables = selected_tables(args.tables)
    if args.phase == "list":
        emit({"ok": True, "app_name": APP_NAME, "splunkbase_id": SPLUNKBASE_ID, "tables": list(TABLES)}, args.json)
        return 0
    emit(render_assets(args, tables), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
