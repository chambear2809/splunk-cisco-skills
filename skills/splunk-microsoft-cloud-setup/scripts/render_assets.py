#!/usr/bin/env python3
"""Render reviewable Microsoft cloud add-on assets for Splunk.

Covers two real packages:
  - Splunk Add-on for Microsoft Cloud Services (Splunk_TA_microsoft-cloudservices, 3110)
  - Splunk Add-on for Microsoft Office 365 (splunk_ta_o365, 4055)

Offline and render-first: emits inputs.conf stanzas, an Entra ID app-registration
account-setup runbook, a placement/CIM plan, and validation SPL grounded in the
real package models (Entra/Azure AD via MSCS, Office 365 + Graph + Entra metadata
via the O365 add-on).
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-microsoft-cloud-rendered"

# Real package facts.
MSCS_APP = "Splunk_TA_microsoft-cloudservices"
MSCS_ID = "3110"
MSCS_VERSION = "6.1.3"
O365_APP = "splunk_ta_o365"
O365_ID = "4055"
O365_VERSION = "6.0.2"

# Office 365 Management Activity content types (real values from the spec).
O365_MGMT_CONTENT_TYPES = [
    "Audit.AzureActiveDirectory",
    "Audit.Exchange",
    "Audit.SharePoint",
    "Audit.General",
    "DLP.All",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Microsoft cloud add-on assets for Splunk.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--o365-index", default="o365", help="Index for Office 365 / Entra audit data.")
    parser.add_argument("--azure-index", default="azure", help="Index for MSCS Azure (Entra) audit data.")
    parser.add_argument("--account-name", default="msentra", help="Azure app-registration account/tenant stanza name.")
    parser.add_argument("--tenant-name", default="contoso", help="O365 tenant stanza name.")
    parser.add_argument(
        "--products",
        default="o365,mscs",
        help="Comma-separated add-ons to render: o365 (Office 365 + Graph + Entra) and mscs (Azure/Entra audit).",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def selected_products(raw: str) -> list[str]:
    valid = {"o365", "mscs"}
    products = [item.strip().lower() for item in raw.split(",") if item.strip()]
    unknown = [p for p in products if p not in valid]
    if unknown:
        raise SystemExit(f"ERROR: unknown product(s): {', '.join(unknown)}. Choose from o365, mscs.")
    return products or ["o365", "mscs"]


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_o365_inputs(args: argparse.Namespace) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {O365_APP} (Splunkbase {O365_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{O365_APP}/local/inputs.conf.",
        f"# Reference the tenant '{args.tenant_name}' configured in the add-on (see account-setup.md).",
        "",
        "# Office 365 Management Activity API (audit logs). One stanza per content type.",
    ]
    for content_type in O365_MGMT_CONTENT_TYPES:
        suffix = content_type.split(".")[-1].lower()
        lines += [
            f"[splunk_ta_o365_management_activity://{args.tenant_name}_{suffix}]",
            "disabled = 0",
            f"tenant_name = {args.tenant_name}",
            f"content_type = {content_type}",
            "interval = 300",
            f"index = {args.o365_index}",
            "sourcetype = o365:management:activity",
            "",
        ]
    lines += [
        "# Microsoft Entra ID metadata via Microsoft Graph.",
        "# entra_id_type accepts: users, groups, applications, devices (multi-select).",
        f"[splunk_ta_o365_microsoft_entra_id_metadata://{args.tenant_name}_entra]",
        "disabled = 0",
        f"tenant_name = {args.tenant_name}",
        "entra_id_type = users,groups",
        "interval = 86400",
        f"index = {args.o365_index}",
        "sourcetype = o365:metadata",
        "",
        "# Office 365 service status / health.",
        f"[splunk_ta_o365_service_status://{args.tenant_name}_status]",
        "disabled = 0",
        f"tenant_name = {args.tenant_name}",
        "interval = 300",
        f"index = {args.o365_index}",
        "sourcetype = o365:service:status",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_mscs_inputs(args: argparse.Namespace) -> str:
    return f"""# Starter local/inputs.conf overlay for {MSCS_APP} (Splunkbase {MSCS_ID}).
# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{MSCS_APP}/local/inputs.conf.
# Reference the Azure app-registration account '{args.account_name}' (see account-setup.md).

# Azure AD / Entra ID management (audit) events.
[mscs_azure_audit://{args.account_name}_audit]
disabled = 0
account = {args.account_name}
subscription_id = __AZURE_SUBSCRIPTION_ID__
interval = 300
index = {args.azure_index}
sourcetype = mscs:azure:audit
"""


def render_account_setup(args: argparse.Namespace) -> str:
    return f"""# Microsoft Cloud Add-ons Account Setup Runbook

Both add-ons authenticate to Microsoft Entra ID (Azure AD) with an **app
registration** (service principal). Create it once in the Azure portal, grant
API permissions, then register it in each add-on.

## 1. Azure app registration (Entra ID)

1. Azure portal > Entra ID > App registrations > New registration.
2. Record the **Directory (tenant) ID** and **Application (client) ID**.
3. Certificates & secrets > New client secret. Copy the secret value.
4. Grant API permissions:
   - Office 365 Management APIs: `ActivityFeed.Read`, `ActivityFeed.ReadDlp`.
   - Microsoft Graph (Entra metadata): `Directory.Read.All`, `AuditLog.Read.All`
     (application permissions, admin-consented).

## 2. Store the client secret locally (never in chat/argv)

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/msentra_client_secret
```

## 3. Register the account in each add-on

- **Office 365 add-on ({O365_APP})**: Configuration > Tenants. Create tenant
  `{args.tenant_name}` with endpoint (WorldWide / USGovGCCHigh), `tenant_id`,
  `client_id`, and the `client_secret` value.
  REST endpoint: `/servicesNS/nobody/{O365_APP}/splunk_ta_o365_tenants`.
- **Microsoft Cloud Services add-on ({MSCS_APP})**: Configuration > Azure App
  Account. Create account `{args.account_name}` with `tenant_id`, `client_id`,
  and the `client_secret` value.
  REST endpoint: `/servicesNS/nobody/{MSCS_APP}/splunk_ta_mscs_azureaccount`.

The add-ons store secrets encrypted in `storage/passwords`; they are never
written to a plaintext conf file. This skill renders inputs and indexes only and
does not transmit the client secret.

## Choosing the Entra/Azure AD path

- Modern audit + sign-in: prefer the **Office 365 add-on** Management Activity
  `Audit.AzureActiveDirectory` content type and the Entra ID metadata Graph input.
- Azure subscription management events: use the **MSCS add-on** `mscs_azure_audit`
  input.
"""


def render_install_commands(args: argparse.Namespace, products: list[str]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "# Review before running. No secrets are embedded in this file.",
        "# Microsoft cloud add-on install + indexes.",
        "",
    ]
    if "o365" in products:
        lines += [
            f"# Office 365 add-on ({O365_APP}, Splunkbase {O365_ID}).",
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {O365_ID}",
            "",
        ]
    if "mscs" in products:
        lines += [
            f"# Microsoft Cloud Services add-on ({MSCS_APP}, Splunkbase {MSCS_ID}).",
            f"bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {MSCS_ID}",
            "",
        ]
    lines += [
        "# Create indexes through the Splunk control plane.",
        f"bash skills/splunk-microsoft-cloud-setup/scripts/setup.sh --create-index --o365-index {args.o365_index} --azure-index {args.azure_index}",
        "",
        "# Configure the Entra app registration (account-setup.md), then enable inputs.",
        "",
        "# Score post-ingest readiness once data flows.",
        "bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack microsoft_o365_management_activity",
        "bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack microsoft_entra_id",
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_validation_spl(args: argparse.Namespace, products: list[str]) -> str:
    blocks = ["# Microsoft cloud add-on validation searches"]
    if "o365" in products:
        blocks.append(
            f"""
index={args.o365_index} sourcetype IN ("o365:management:activity","o365:service:status","o365:metadata")
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.o365_index} sourcetype=o365:management:activity Workload=AzureActiveDirectory
| stats count by Operation"""
        )
    if "mscs" in products:
        blocks.append(
            f"""
index={args.azure_index} sourcetype="mscs:azure:audit"
| stats count min(_time) as first_seen max(_time) as last_seen
| convert ctime(first_seen) ctime(last_seen)"""
        )
    apps = " OR ".join(filter(None, [O365_APP if "o365" in products else "", MSCS_APP if "mscs" in products else ""]))
    blocks.append(
        f"""
index=_internal source=*splunkd.log* ({apps})
| stats count values(log_level) as levels by sourcetype"""
    )
    return "\n".join(blocks).strip() + "\n"


def render_plan_md(args: argparse.Namespace, products: list[str]) -> str:
    rows = []
    if "o365" in products:
        rows.append(
            f"| Office 365 audit | `{O365_APP}` (`{O365_ID}`) | `splunk_ta_o365_management_activity` | `o365:management:activity` | Authentication, Change |"
        )
        rows.append(
            f"| Entra ID metadata | `{O365_APP}` (`{O365_ID}`) | `splunk_ta_o365_microsoft_entra_id_metadata` | `o365:metadata` | Identity |"
        )
        rows.append(
            f"| O365 service status | `{O365_APP}` (`{O365_ID}`) | `splunk_ta_o365_service_status` | `o365:service:status` | - |"
        )
    if "mscs" in products:
        rows.append(
            f"| Azure/Entra audit | `{MSCS_APP}` (`{MSCS_ID}`) | `mscs_azure_audit` | `mscs:azure:audit` | Change |"
        )
    feed_rows = "\n".join(rows)
    content_types = ", ".join(f"`{ct}`" for ct in O365_MGMT_CONTENT_TYPES)
    return f"""# Microsoft Cloud Add-ons Setup Plan

Office 365 add-on: `{O365_APP}` (Splunkbase `{O365_ID}`, verified `{O365_VERSION}`)
MSCS add-on: `{MSCS_APP}` (Splunkbase `{MSCS_ID}`, verified `{MSCS_VERSION}`)
O365 index: `{args.o365_index}`
Azure index: `{args.azure_index}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | supported (can run the inputs directly) |
| `heavy-forwarder` | supported (preferred dedicated collector) |
| `indexer` | none |
| `universal-forwarder` | none (modular inputs need the Splunk Python runtime) |
| `external-collector` | none |

## Feeds, Inputs, Source Types, And CIM

| Feed | Add-on | Modular input | Source type | CIM data models |
| --- | --- | --- | --- | --- |
{feed_rows}

Office 365 Management Activity content types: {content_types}.

## Account Model

Both add-ons use an Entra ID app registration (tenant_id + client_id +
client_secret, or certificate auth). Configure it in each add-on's Configuration
tab. See `account-setup.md`.

## Guardrails

- Run on the search tier or a dedicated heavy forwarder; the add-ons need the
  full Splunk Python runtime and are not Universal-Forwarder safe.
- Store the Entra client secret only via the add-on account (encrypted); never
  in conf files or argv.
- Grant least-privilege Graph / Office 365 Management API permissions and
  admin-consent application permissions.
- Pick one Entra/Azure AD audit path (O365 Management Activity vs MSCS audit) to
  avoid duplicate ingestion.

## Sources

- https://splunkbase.splunk.com/app/{O365_ID}
- https://splunkbase.splunk.com/app/{MSCS_ID}
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/microsoft-office-365
- https://help.splunk.com/en/splunk-cloud-platform/get-data-in/splunk-supported-add-ons/microsoft-cloud-services
"""


def render_assets(args: argparse.Namespace, products: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-microsoft-cloud"
    if args.dry_run:
        files = ["account-setup.md", "install-commands.sh", "metadata.json", "profile-plan.md", "validation-searches.spl"]
        if "o365" in products:
            files.append("inputs.o365.local.conf.template")
        if "mscs" in products:
            files.append("inputs.mscs.local.conf.template")
        return {"ok": True, "dry_run": True, "output_dir": str(profile_dir), "files": sorted(files)}

    metadata = {
        "office365": {"app_name": O365_APP, "splunkbase_id": O365_ID, "latest_verified_version": O365_VERSION},
        "mscs": {"app_name": MSCS_APP, "splunkbase_id": MSCS_ID, "latest_verified_version": MSCS_VERSION},
        "o365_index": args.o365_index,
        "azure_index": args.azure_index,
        "products": products,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, products))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args, products), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args, products))
    if "o365" in products:
        write_file(profile_dir / "inputs.o365.local.conf.template", render_o365_inputs(args))
    if "mscs" in products:
        write_file(profile_dir / "inputs.mscs.local.conf.template", render_mscs_inputs(args))
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
        print(f"Apps: {O365_APP} ({O365_ID}), {MSCS_APP} ({MSCS_ID})")
        print(f"Output: {payload['output_dir']}")
        print("Files: " + ", ".join(payload["files"]))
        return
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    products = selected_products(args.products)
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "office365": {"app_name": O365_APP, "splunkbase_id": O365_ID},
                "mscs": {"app_name": MSCS_APP, "splunkbase_id": MSCS_ID},
                "o365_management_content_types": O365_MGMT_CONTENT_TYPES,
            },
            args.json,
        )
        return 0
    emit(render_assets(args, products), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
