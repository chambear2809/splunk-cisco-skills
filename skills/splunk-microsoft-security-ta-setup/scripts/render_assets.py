#!/usr/bin/env python3
"""Render reviewable Splunk Add-on for Microsoft Security assets."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPO_ROOT / "splunk-microsoft-security-ta-rendered"

APP_NAME = "Splunk_TA_MS_Security"
SPLUNKBASE_ID = "6207"
LATEST_VERIFIED_VERSION = "3.0.0"

STREAMING_EVENT_TYPES = (
    "AlertInfo,AlertEvidence,DeviceInfo,DeviceNetworkInfo,DeviceProcessEvents,"
    "DeviceNetworkEvents,DeviceFileEvents,DeviceRegistryEvents,DeviceLogonEvents,"
    "DeviceImageLoadEvents,DeviceEvents,DeviceFileCertificateInfo,EmailAttachmentInfo,"
    "EmailEvents,EmailPostDeliveryEvents,EmailUrlInfo,UrlClickEvents,IdentityLogonEvents,"
    "IdentityQueryEvents,IdentityDirectoryEvents,CloudAppEvents"
)

FEEDS = {
    "incidents",
    "atp_alerts",
    "machines",
    "simulations",
    "event_hub",
    "threat_intel",
}

SOURCETYPES = [
    "ms365:defender:incident",
    "ms:defender:atp:alerts",
    "ms:defender:machines",
    "ms:defender:simulations",
    "ms:defender:eventhub",
    "ms:defender:ti:articles",
    "m365:defender:incident:advanced_hunting",
    "ms365:defender:incident:alerts",
]

ALERT_ACTIONS = [
    "defender_advanced_hunting",
    "defender_update_incident",
    "defender_update_incident_graph",
    "defender_dismiss_azure_alert",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render Splunk_TA_MS_Security assets.")
    parser.add_argument("--phase", choices=("render", "list"), default="render")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--index", default="microsoft_security", help="Target event index.")
    parser.add_argument("--account-name", default="ms_security_prod", help="Add-on account stanza name.")
    parser.add_argument("--tenant-id", default="00000000-0000-0000-0000-000000000000", help="Entra tenant ID placeholder.")
    parser.add_argument("--environment", default="commercial", help="Package environment value.")
    parser.add_argument("--location", default="api.securitycenter.windows.com", help="Defender endpoint API location.")
    parser.add_argument("--event-hub-namespace", default="defender-events.servicebus.windows.net")
    parser.add_argument("--event-hub-name", default="defender-events")
    parser.add_argument("--consumer-group", default="$Default")
    parser.add_argument(
        "--feeds",
        default="incidents,atp_alerts,machines,simulations,event_hub,threat_intel",
        help="Comma-separated feeds: incidents,atp_alerts,machines,simulations,event_hub,threat_intel.",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def parse_feeds(raw: str) -> list[str]:
    feeds = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = [item for item in feeds if item not in FEEDS]
    if unknown:
        raise SystemExit(f"ERROR: unknown feed(s): {', '.join(unknown)}. Choose from {', '.join(sorted(FEEDS))}.")
    return feeds


def write_file(path: Path, content: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render_inputs(args: argparse.Namespace, feeds: list[str]) -> str:
    lines = [
        f"# Starter local/inputs.conf overlay for {APP_NAME} (Splunkbase {SPLUNKBASE_ID}).",
        f"# Copy reviewed stanzas into $SPLUNK_HOME/etc/apps/{APP_NAME}/local/inputs.conf.",
        f"# Reference account '{args.account_name}' configured in the add-on Configuration tab.",
        "",
    ]
    if "incidents" in feeds:
        lines += [
            "[microsoft_365_defender_endpoint_incidents://defender_incidents]",
            "disabled = 0",
            f"azure_app_account = {args.account_name}",
            f"tenant_id = {args.tenant_id}",
            f"environment = {args.environment}",
            "request_timeout = 60",
            "lookback = 0",
            "interval = 300",
            f"index = {args.index}",
            "sourcetype = ms365:defender:incident",
            "",
        ]
    if "atp_alerts" in feeds:
        lines += [
            "[microsoft_defender_endpoint_atp_alerts://defender_atp_alerts]",
            "disabled = 0",
            f"azure_app_account = {args.account_name}",
            f"tenant_id = {args.tenant_id}",
            f"location = {args.location}",
            "request_timeout = 60",
            "lookback = 0",
            "interval = 300",
            f"index = {args.index}",
            "sourcetype = ms:defender:atp:alerts",
            "",
        ]
    if "machines" in feeds:
        lines += [
            "[microsoft_defender_endpoint_machines://defender_machines]",
            "disabled = 0",
            f"azure_app_account = {args.account_name}",
            f"tenant_id = {args.tenant_id}",
            f"location = {args.location}",
            "request_timeout = 60",
            "interval = 300",
            f"index = {args.index}",
            "sourcetype = ms:defender:machines",
            "",
        ]
    if "simulations" in feeds:
        lines += [
            "[microsoft_defender_endpoint_simulations://defender_simulations]",
            "disabled = 0",
            f"azure_app_account = {args.account_name}",
            f"tenant_id = {args.tenant_id}",
            "environment = commercial-graph-api",
            "request_timeout = 60",
            "lookback = 0",
            "interval = 2629800",
            f"index = {args.index}",
            "sourcetype = ms:defender:simulations",
            "",
        ]
    if "event_hub" in feeds:
        lines += [
            "[microsoft_defender_event_hub://defender_event_hub]",
            "disabled = 0",
            f"azure_app_account = {args.account_name}",
            f"event_hub_namespace = {args.event_hub_namespace}",
            f"event_hub_name = {args.event_hub_name}",
            f"consumer_group = {args.consumer_group}",
            f"streaming_event_types = {STREAMING_EVENT_TYPES}",
            "interval = 0",
            f"index = {args.index}",
            "sourcetype = ms:defender:eventhub",
            "",
        ]
    if "threat_intel" in feeds:
        lines += [
            "[microsoft_defender_threat_intelligence_datasets://defender_threat_intel]",
            "disabled = 0",
            f"azure_app_account = {args.account_name}",
            f"tenant_id = {args.tenant_id}",
            "environment = commercial-graph-api",
            "datasets = articles,indicators,passivedns,components,cookies,trackers,hostpairs,certificates,whois,subdomains",
            "identifiers = *",
            "interval = 86400",
            f"index = {args.index}",
            "sourcetype = ms:defender:ti:articles",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def render_macros(args: argparse.Namespace) -> str:
    return f"""# local/macros.conf overlay for package-shipped Microsoft Security dashboards/searches.
[defender_index]
definition = index={args.index}
iseval = 0

[defender_atp_index]
definition = index={args.index}
iseval = 0
"""


def render_settings() -> str:
    return """# Optional local/Splunk_TA_MS_Security_settings.conf overlay.
[proxy]
proxy_enabled = 0

[logging]
loglevel = INFO
"""


def render_account_setup(args: argparse.Namespace) -> str:
    actions = ", ".join(f"`{action}`" for action in ALERT_ACTIONS)
    return f"""# {APP_NAME} Account And Microsoft Setup Runbook

Create an Entra app registration for Microsoft Defender / Microsoft 365
Defender API collection. Configure account `{args.account_name}` in the add-on
Configuration tab with:

| Field | Value |
| --- | --- |
| `username` | Application/client ID |
| `password` | Client secret value |
| `tenant_id` | `{args.tenant_id}` |

Write the client secret to a protected file before opening Splunk Web:

```bash
bash skills/shared/scripts/write_secret_file.sh /tmp/ms_security_client_secret
```

REST handler: `/servicesNS/nobody/{APP_NAME}/Splunk_TA_MS_Security_account`.
Secrets are stored encrypted in `storage/passwords`; this skill never places
client secrets in argv or rendered conf.

## Permissions

Grant least-privilege Microsoft Graph / Defender permissions for selected
inputs: incidents, alerts, machines, simulations, Advanced Hunting/Event Hub,
and threat intelligence datasets. Use admin consent where required.

## Splunk Cloud Caveats

- Splunk Cloud customers normally configure accounts and inputs in Splunk Web
  or through supported REST endpoints; do not edit cloud filesystem paths.
- Event Hub streaming requires Azure egress from the Splunk collection node. For
  Splunk Cloud, coordinate network allowlists or ACS egress handoff before
  enabling `[microsoft_defender_event_hub://...]`.

## Alert Actions And Migration

The package ships alert actions: {actions}. Configure them only after validating
the account and role permissions.

If migrating from older Microsoft Defender add-ons, disable duplicate legacy
inputs before enabling the rendered stanzas. For dashboard content, use the
package-shipped knowledge objects and the documented Microsoft 365 App for
Splunk handoff; this skill only renders macro/input configuration.
"""


def render_install_commands(args: argparse.Namespace) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Review before running. No secrets are embedded in this file.
bash skills/splunk-app-install/scripts/install_app.sh --source splunkbase --app-id {SPLUNKBASE_ID}
bash skills/splunk-microsoft-security-ta-setup/scripts/setup.sh --create-index --index {args.index}

# Configure account {args.account_name}, apply macros.local.conf.template if needed, then enable inputs.
bash skills/splunk-data-source-readiness-doctor/scripts/setup.sh --phase collect --source-pack microsoft_security
"""


def render_validation_spl(args: argparse.Namespace) -> str:
    sourcetypes = ",".join(f'"{s}"' for s in SOURCETYPES)
    return f"""# {APP_NAME} validation searches

index={args.index} sourcetype IN ({sourcetypes})
| stats count min(_time) as first_seen max(_time) as last_seen by sourcetype
| convert ctime(first_seen) ctime(last_seen)

index={args.index} sourcetype=ms:defender:eventhub
| stats count by category ActionType DeviceName AccountName

`defender_index` sourcetype=ms365:defender:incident
| stats count by status severity classification

index=_internal source=*splunkd.log* ({APP_NAME} OR microsoft_defender OR MS_Security)
| stats count values(log_level) as levels by sourcetype
"""


def render_plan_md(args: argparse.Namespace, feeds: list[str]) -> str:
    rows = [
        "| `microsoft_365_defender_endpoint_incidents` | `ms365:defender:incident` | Defender incidents |",
        "| `microsoft_defender_endpoint_atp_alerts` | `ms:defender:atp:alerts` | Defender endpoint alerts |",
        "| `microsoft_defender_endpoint_machines` | `ms:defender:machines` | Defender machines |",
        "| `microsoft_defender_endpoint_simulations` | `ms:defender:simulations` | Attack simulations |",
        "| `microsoft_defender_event_hub` | `ms:defender:eventhub` | Advanced Hunting / streaming events |",
        "| `microsoft_defender_threat_intelligence_datasets` | `ms:defender:ti:articles` | Threat intelligence datasets |",
    ]
    return f"""# {APP_NAME} Setup Plan

Add-on: `{APP_NAME}` (Splunkbase `{SPLUNKBASE_ID}`, verified `{LATEST_VERIFIED_VERSION}`)
Event index: `{args.index}`
Account: `{args.account_name}`
Rendered feeds: `{", ".join(feeds)}`

## Role Placement

| Role | Support |
| --- | --- |
| `search-tier` | required for setup, searches, macros, alert actions |
| `heavy-forwarder` | supported for collection |
| `indexer` | none |
| `universal-forwarder` | none |
| `external-collector` | none |

Run API/Event Hub inputs on one collection node.

## Package-Backed Inputs

| Input | Source type | Notes |
| --- | --- | --- |
{chr(10).join(rows)}

## Package-Backed Alert Actions

{", ".join(f"`{action}`" for action in ALERT_ACTIONS)}

## Dashboard Handoff

Apply the rendered `macros.local.conf.template` so package-shipped searches and
documented Microsoft 365 App for Splunk dashboards resolve to index
`{args.index}`. No custom dashboards are generated.
"""


def render_assets(args: argparse.Namespace, feeds: list[str]) -> dict[str, Any]:
    output_root = Path(args.output_dir).expanduser().resolve()
    profile_dir = output_root / "splunk-microsoft-security-ta"
    files = [
        "account-setup.md",
        "inputs.local.conf.template",
        "install-commands.sh",
        "macros.local.conf.template",
        "metadata.json",
        "profile-plan.md",
        "settings.local.conf.template",
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
        "feeds": feeds,
        "source_package": f"splunk-ta/_unpacked/{APP_NAME}-{LATEST_VERIFIED_VERSION}/{APP_NAME}",
        "sourcetypes": SOURCETYPES,
        "alert_actions": ALERT_ACTIONS,
    }
    write_file(profile_dir / "metadata.json", json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    write_file(profile_dir / "profile-plan.md", render_plan_md(args, feeds))
    write_file(profile_dir / "inputs.local.conf.template", render_inputs(args, feeds))
    write_file(profile_dir / "settings.local.conf.template", render_settings())
    write_file(profile_dir / "macros.local.conf.template", render_macros(args))
    write_file(profile_dir / "account-setup.md", render_account_setup(args))
    write_file(profile_dir / "install-commands.sh", render_install_commands(args), executable=True)
    write_file(profile_dir / "validation-searches.spl", render_validation_spl(args))
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
    feeds = parse_feeds(args.feeds)
    if args.phase == "list":
        emit(
            {
                "ok": True,
                "app_name": APP_NAME,
                "splunkbase_id": SPLUNKBASE_ID,
                "feeds": sorted(FEEDS),
                "sourcetypes": SOURCETYPES,
                "alert_actions": ALERT_ACTIONS,
            },
            args.json,
        )
        return 0
    emit(render_assets(args, feeds), args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
