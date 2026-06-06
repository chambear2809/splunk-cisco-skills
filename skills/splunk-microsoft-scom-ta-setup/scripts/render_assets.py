#!/usr/bin/env python3
"""Render package-verified Microsoft SCOM supported add-on assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-microsoft-scom-ta-rendered"

APP_NAME = "Splunk_TA_microsoft-scom"
APP_ID = "2729"
APP_VERSION = "4.5.0"
SOURCE_PACK = "microsoft_scom"

INPUTS: list[tuple[str, str]] = [
    ("powershell://scom_Events", "microsoft:scom:events"),
    ("powershell://scom_Internal", "microsoft:scom:internal"),
    ("powershell://scom_Management_Network", "microsoft:scom:mgmt_network"),
    ("powershell://scom_alert", "microsoft:scom:alert"),
    ("powershell://scom_commands", "microsoft:scom:cmd"),
    ("powershell://scom_event", "microsoft:scom:event"),
    ("powershell://scom_mgmt", "microsoft:scom:mgmt"),
    ("powershell://scom_perf_command", "microsoft:scom:performance"),
]

SOURCETYPES = [
    "microsoft:scom",
    "microsoft:scom:alert",
    "microsoft:scom:events",
    "microsoft:scom:performance",
    "microsoft:scom:cmd",
]

EVENTTYPES = [
    "ms_scom_alert",
    "ms_scom_event",
    "ms_scom_inventory",
    "ms_scom_perf",
    "ms_scom_task",
]

LOOKUPS = [
    "ms_scom_countername_to_datamodel_lookup",
    "ms_scom_monitor_to_datamodel_lookup",
    "ms_scom_type_lookup",
    "ms_scom_vendor_severity_lookup",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Microsoft SCOM add-on assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--products", default="scom", help="Product selector; only scom is supported.")
    parser.add_argument("--index", default="scom", help="Target SCOM event index.")
    parser.add_argument("--account-name", default="scom_prod", help="SCOM account stanza name.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def validate_products(raw: str) -> None:
    values = [item.strip().lower() for item in raw.split(",") if item.strip()]
    if values != ["scom"]:
        raise SystemExit("ERROR: Microsoft SCOM renderer supports --products scom")


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME}.",
        "# Stanzas come from the package inputs template and are disabled for review.",
        f"# Configure account {args.account_name} in the add-on before enabling.",
        "",
    ]
    for stanza, sourcetype in INPUTS:
        lines += [
            f"[{stanza}]",
            "disabled = 1",
            f"account = {args.account_name}",
            f"sourcetype = {sourcetype}",
            f"index = {args.index}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_account(args: argparse.Namespace) -> str:
    return f"""# SCOM Account Setup

Create add-on account `{args.account_name}` in `{APP_NAME}` for the approved
SCOM management server/API endpoint. Put any password into a protected local
file before entering it into the add-on UI so Splunk stores it encrypted:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/scom_password
```

Run the selected PowerShell inputs on one approved search tier or heavy
forwarder for each SCOM environment. Do not place SCOM credentials in argv,
rendered files, or environment variables.
"""


def render_plan(args: argparse.Namespace) -> str:
    input_rows = [f"| `{stanza}` | `{sourcetype}` |" for stanza, sourcetype in INPUTS]
    return f"""# Microsoft SCOM Add-on Setup Plan

App: `{APP_NAME}` (Splunkbase `{APP_ID}`, verified `{APP_VERSION}`)
Index: `{args.index}`
Account: `{args.account_name}`

| Package Input | Source Type |
| --- | --- |
{chr(10).join(input_rows)}

Eventtypes: {', '.join(f'`{item}`' for item in EVENTTYPES)}
Lookups: {', '.join(f'`{item}`' for item in LOOKUPS)}
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {APP_ID} --app-version {APP_VERSION} --no-update
bash skills/splunk-microsoft-scom-ta-setup/scripts/setup.sh --create-index --index {args.index}
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack {SOURCE_PACK}
"""


def render_validation(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{item}"' for item in SOURCETYPES)
    return f"""# Microsoft SCOM validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype host source
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=microsoft:scom:alert
| stats count by severity state priority

index=_internal source=*splunkd.log* ({APP_NAME} OR scom_)
| stats count values(log_level) as levels by component
"""


def render_assets(args: argparse.Namespace) -> dict[str, Any]:
    output = Path(args.output_dir).expanduser().resolve() / "splunk-microsoft-scom-ta"
    files = [
        "account-setup.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "metadata.json",
        "profile-plan.md",
        "validation-searches.spl",
    ]
    if args.dry_run:
        return {"ok": True, "dry_run": True, "output_dir": str(output), "files": files}
    metadata = {
        "app": APP_NAME,
        "splunkbase_id": APP_ID,
        "version": APP_VERSION,
        "index": args.index,
        "source_pack": SOURCE_PACK,
        "sourcetypes": SOURCETYPES,
        "eventtypes": EVENTTYPES,
        "lookups": LOOKUPS,
    }
    write_file(output / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True))
    write_file(output / "profile-plan.md", render_plan(args))
    write_file(output / "inputs.local.conf.template", render_inputs(args))
    write_file(output / "account-setup.md", render_account(args))
    write_file(output / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(output / "validation-searches.spl", render_validation(args))
    return {"ok": True, "dry_run": False, "output_dir": str(output), "files": sorted(files)}


def emit(payload: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Output: {payload.get('output_dir', '')}")
        if payload.get("files"):
            print("Files: " + ", ".join(payload["files"]))


def main() -> int:
    args = parse_args()
    validate_products(args.products)
    if args.phase == "list":
        emit({"ok": True, "products": ["scom"], "app": APP_NAME, "sourcetypes": SOURCETYPES}, args.json)
        return 0
    emit(render_assets(args), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
